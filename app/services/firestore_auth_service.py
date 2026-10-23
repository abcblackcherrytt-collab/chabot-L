"""Firestoreを使用するLINE Login認証サービス（セッション基盤版）。

- 発行したAccess/Refresh Tokenは共通のセッションID（sid）と認証世代
  （auth_version）を持つ。セッション失効・世代更新はAccess Tokenにも
  即時に反映される。
- Refresh Tokenの更新はFirestore Transactionで単回消費を原子的に確定する。
  同じトークンから成功する更新は1件のみ。
- 通常のCookie認証はトークンを消費しない検証（authenticate_refresh）で、
  残存期間が閾値を下回ったときだけローテーションする。これにより並行
  アクセスでも不必要な再ログインを発生させない。
- 旧形式（sid無し）のRefresh Tokenは有効期限内の受付で一度だけ新
  セッションへ移行する。既存利用者に再ログインを要求しない。
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore

from app.core.config import settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_token_hash,
)
from app.repositories.firestore_auth_session_repository import (
    FirestoreAuthSessionRepository,
)
from app.repositories.firestore_refresh_token_repository import (
    FirestoreRefreshTokenRepository,
)
from app.repositories.firestore_user_repository import FirestoreUserRepository

logger = logging.getLogger(__name__)


class FirestoreAuthService:
    """LINE LoginのJWT発行・検証・更新・失効をFirestoreで管理する。"""

    def __init__(
        self,
        user_repository: Optional[FirestoreUserRepository] = None,
        token_repository: Optional[FirestoreRefreshTokenRepository] = None,
        session_repository: Optional[FirestoreAuthSessionRepository] = None,
    ) -> None:
        self.user_repository = user_repository or FirestoreUserRepository()
        self.token_repository = token_repository or FirestoreRefreshTokenRepository()
        self.session_repository = (
            session_repository or FirestoreAuthSessionRepository()
        )

    # ---- 内部ヘルパー ----

    @staticmethod
    def _as_utc(value: Any) -> Optional[datetime]:
        """Firestore値・ISO文字列をtz-awareなUTC時刻へ正規化する。"""
        if isinstance(value, str):
            try:
                value = datetime.fromisoformat(value)
            except ValueError:
                return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value
        return None

    @staticmethod
    def _decode_refresh(refresh_token: str) -> Optional[Dict[str, Any]]:
        """Refresh Tokenとして署名・形式を検証してpayloadを返す。"""
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None
        if payload.get("provider") != "line":
            return None
        if not payload.get("jti") or not payload.get("sub"):
            return None
        return payload

    @staticmethod
    def _is_expired(expires_at: Optional[datetime]) -> bool:
        return expires_at is None or expires_at <= datetime.now(timezone.utc)

    async def _load_active_user(
        self, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """有効なユーザー文書を取得する。無効・欠損時はNone。"""
        user = await self.user_repository.find_by_id(user_id)
        if not user or not user.get("is_active", False):
            return None
        if not user.get("line_user_id"):
            return None
        return user

    def _token_document(
        self,
        *,
        refresh_jti: str,
        user_id: str,
        token_hash: str,
        expires_at: datetime,
        session_id: str,
        created_at: datetime,
    ) -> Dict[str, Any]:
        return {
            "id": refresh_jti,
            "user_id": user_id,
            "token_hash": token_hash,
            "expires_at": expires_at,
            "is_revoked": False,
            "revoked_at": None,
            "consumed_at": None,
            "provider": "line",
            "session_id": session_id,
            "created_at": created_at,
        }

    def _token_response(
        self,
        *,
        access_token: str,
        access_expires_at: datetime,
        refresh_token: str,
    ) -> Dict[str, Any]:
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(
                max(
                    0,
                    (
                        access_expires_at - datetime.now(timezone.utc)
                    ).total_seconds(),
                )
            ),
        }

    # ---- 発行 ----

    async def issue_tokens(
        self,
        user: Dict[str, Any],
        line_user_id: str,
    ) -> Dict[str, Any]:
        """LINEユーザーへセッション付きAccess/Refresh Tokenを発行する。"""
        session_id = str(uuid.uuid4())
        access_jti = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())
        email = user.get("email") or f"line_{line_user_id}@chabot.local"
        auth_version = int(user.get("auth_version") or 0)
        now = datetime.now(timezone.utc)

        access_token, access_expires_at = create_access_token(
            user_id=user["id"],
            email=email,
            jti=access_jti,
            additional_claims={
                "provider": "line",
                "role": user.get("role", "user"),
            },
            session_id=session_id,
            auth_version=auth_version,
        )
        refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user["id"],
            email=email,
            jti=refresh_jti,
            additional_claims={
                "provider": "line",
            },
            session_id=session_id,
            auth_version=auth_version,
        )
        token_hash = await asyncio.to_thread(hash_token, refresh_token)

        await self.session_repository.create(
            {
                "id": session_id,
                "user_id": user["id"],
                "auth_version": auth_version,
                "current_refresh_jti": refresh_jti,
                "expires_at": refresh_expires_at,
                "revoked_at": None,
                "created_at": now,
            }
        )
        await self.token_repository.create(
            self._token_document(
                refresh_jti=refresh_jti,
                user_id=user["id"],
                token_hash=token_hash,
                expires_at=refresh_expires_at,
                session_id=session_id,
                created_at=now,
            )
        )
        return self._token_response(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=refresh_token,
        )

    # ---- 検証・更新 ----

    async def authenticate_refresh(
        self, refresh_token: str
    ) -> Optional[Dict[str, Any]]:
        """Cookie認証用の検証。トークン消費は必要時のみ。

        - 旧形式（sid無し）は一度だけ新セッションへ移行する。
        - 残存期間が settings.jwt_refresh_rotate_days 未満のときだけ
          ローテーションする。
        - それ以外は同一セッションで新しいAccess Tokenだけを発行し、
          Refresh Tokenは消費しない（並行アクセスでも競合しない）。
        """
        payload = self._decode_refresh(refresh_token)
        if not payload:
            return None

        session_id = payload.get("sid")
        if not session_id:
            # 旧形式のRefresh Tokenは新セッションへの移行が初回アクセス。
            return await self._migrate_legacy_refresh(refresh_token, payload)

        token_id = payload["jti"]
        user_id = payload["sub"]
        token_version = int(payload.get("auth_version") or 0)

        stored = await self._validate_stored_refresh(refresh_token, token_id)
        if not stored:
            return None
        expires_at = self._as_utc(stored.get("expires_at"))

        session = await self.session_repository.get(session_id)
        if not session or session.get("user_id") != user_id:
            return None
        if session.get("revoked_at"):
            return None
        if int(session.get("auth_version") or 0) != token_version:
            return None
        if self._is_expired(self._as_utc(session.get("expires_at"))):
            return None

        user = await self._load_active_user(user_id)
        if not user:
            return None
        if int(user.get("auth_version") or 0) != token_version:
            return None

        remaining = expires_at - datetime.now(timezone.utc)
        if remaining < timedelta(days=settings.jwt_refresh_rotate_days):
            return await self._rotate_with_session(refresh_token, payload)

        # 検証のみ。Refresh Tokenは消費せず同一値を返す（Cookie再設定は冪等）。
        line_user_id = user.get("line_user_id")
        email = user.get("email") or f"line_{line_user_id}@chabot.local"
        access_token, access_expires_at = create_access_token(
            user_id=user_id,
            email=email,
            jti=str(uuid.uuid4()),
            additional_claims={
                "provider": "line",
                "role": user.get("role", "user"),
            },
            session_id=session_id,
            auth_version=token_version,
        )
        return self._token_response(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=refresh_token,
        )

    async def refresh(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """保存済みRefresh Tokenを検証し、ローテーションまたは移行する。"""
        payload = self._decode_refresh(refresh_token)
        if not payload:
            return None
        if payload.get("sid"):
            return await self._rotate_with_session(refresh_token, payload)
        return await self._migrate_legacy_refresh(refresh_token, payload)

    async def _validate_stored_refresh(
        self,
        refresh_token: str,
        token_id: str,
    ) -> Optional[Dict[str, Any]]:
        """保存済みトークンの存在・失効状態・期限・hashを確認する。"""
        stored = await self.token_repository.get_by_id(token_id)
        if not stored or stored.get("is_revoked", False):
            return None
        if stored.get("consumed_at"):
            return None
        expires_at = self._as_utc(stored.get("expires_at"))
        if self._is_expired(expires_at):
            return None
        if not await asyncio.to_thread(
            verify_token_hash,
            refresh_token,
            stored.get("token_hash", ""),
        ):
            return None
        return stored

    async def _rotate_with_session(
        self,
        refresh_token: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """セッション内でRefresh Tokenを原子的にローテーションする。"""
        token_id = payload["jti"]
        user_id = payload["sub"]
        session_id = payload["sid"]
        token_version = int(payload.get("auth_version") or 0)

        stored = await self._validate_stored_refresh(refresh_token, token_id)
        if not stored:
            return None

        session = await self.session_repository.get(session_id)
        if not session or session.get("user_id") != user_id:
            return None
        if session.get("revoked_at"):
            return None
        if int(session.get("auth_version") or 0) != token_version:
            return None
        if self._is_expired(self._as_utc(session.get("expires_at"))):
            return None
        if session.get("current_refresh_jti") != token_id:
            return None

        user = await self._load_active_user(user_id)
        if not user:
            return None
        if int(user.get("auth_version") or 0) != token_version:
            return None

        # 新トークンはTransaction外で準備する（Transaction再試行内で
        # 外部処理を起こさない）。
        new_access_jti = str(uuid.uuid4())
        new_refresh_jti = str(uuid.uuid4())
        line_user_id = user.get("line_user_id")
        email = user.get("email") or f"line_{line_user_id}@chabot.local"
        access_token, access_expires_at = create_access_token(
            user_id=user_id,
            email=email,
            jti=new_access_jti,
            additional_claims={
                "provider": "line",
                "role": user.get("role", "user"),
            },
            session_id=session_id,
            auth_version=token_version,
        )
        new_refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user_id,
            email=email,
            jti=new_refresh_jti,
            additional_claims={
                "provider": "line",
            },
            session_id=session_id,
            auth_version=token_version,
        )
        new_hash = await asyncio.to_thread(hash_token, new_refresh_token)
        now = datetime.now(timezone.utc)

        db = self.token_repository.db
        token_collection = db.collection(self.token_repository.collection_name)
        old_token_ref = token_collection.document(token_id)
        new_token_ref = token_collection.document(new_refresh_jti)
        session_ref = db.collection(
            self.session_repository.collection_name
        ).document(session_id)

        new_token_document = self._token_document(
            refresh_jti=new_refresh_jti,
            user_id=user_id,
            token_hash=new_hash,
            expires_at=refresh_expires_at,
            session_id=session_id,
            created_at=now,
        )

        transaction = db.transaction()

        @firestore.async_transactional
        async def rotate_in_transaction(tx):
            current = await old_token_ref.get(transaction=tx)
            if not current.exists:
                return False
            current_data = current.to_dict() or {}
            if current_data.get("is_revoked", False):
                return False
            if current_data.get("consumed_at"):
                return False
            # 旧トークン消費・新トークン作成・セッション指し替えを
            # 1つのTransactionで確定し、単回消費を保証する。
            tx.update(
                old_token_ref,
                {"is_revoked": True, "revoked_at": now, "consumed_at": now},
            )
            tx.set(new_token_ref, new_token_document)
            tx.update(
                session_ref,
                {
                    "current_refresh_jti": new_refresh_jti,
                    "expires_at": refresh_expires_at,
                },
            )
            return True

        committed = await rotate_in_transaction(transaction)
        if not committed:
            logger.info("Refresh rotation lost race or token already consumed")
            return None

        return self._token_response(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=new_refresh_token,
        )

    async def _migrate_legacy_refresh(
        self,
        refresh_token: str,
        payload: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """旧形式（sid無し）Refresh Tokenを新セッションへ一度だけ移行する。"""
        token_id = payload["jti"]
        user_id = payload["sub"]

        stored = await self._validate_stored_refresh(refresh_token, token_id)
        if not stored:
            return None
        user = await self._load_active_user(user_id)
        if not user:
            return None
        line_user_id = user.get("line_user_id")

        session_id = str(uuid.uuid4())
        new_refresh_jti = str(uuid.uuid4())
        auth_version = int(user.get("auth_version") or 0)
        email = user.get("email") or f"line_{line_user_id}@chabot.local"
        access_token, access_expires_at = create_access_token(
            user_id=user_id,
            email=email,
            jti=str(uuid.uuid4()),
            additional_claims={
                "provider": "line",
                "role": user.get("role", "user"),
            },
            session_id=session_id,
            auth_version=auth_version,
        )
        new_refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user_id,
            email=email,
            jti=new_refresh_jti,
            additional_claims={
                "provider": "line",
            },
            session_id=session_id,
            auth_version=auth_version,
        )
        new_hash = await asyncio.to_thread(hash_token, new_refresh_token)
        now = datetime.now(timezone.utc)

        db = self.token_repository.db
        token_collection = db.collection(self.token_repository.collection_name)
        old_token_ref = token_collection.document(token_id)
        new_token_ref = token_collection.document(new_refresh_jti)
        session_ref = db.collection(
            self.session_repository.collection_name
        ).document(session_id)

        session_document = {
            "id": session_id,
            "user_id": user_id,
            "auth_version": auth_version,
            "current_refresh_jti": new_refresh_jti,
            "expires_at": refresh_expires_at,
            "revoked_at": None,
            "created_at": now,
        }
        new_token_document = self._token_document(
            refresh_jti=new_refresh_jti,
            user_id=user_id,
            token_hash=new_hash,
            expires_at=refresh_expires_at,
            session_id=session_id,
            created_at=now,
        )

        transaction = db.transaction()

        @firestore.async_transactional
        async def migrate_in_transaction(tx):
            current = await old_token_ref.get(transaction=tx)
            if not current.exists:
                return False
            current_data = current.to_dict() or {}
            if current_data.get("is_revoked", False):
                return False
            if current_data.get("consumed_at"):
                return False
            tx.update(
                old_token_ref,
                {"is_revoked": True, "revoked_at": now, "consumed_at": now},
            )
            tx.set(new_token_ref, new_token_document)
            tx.set(session_ref, session_document)
            return True

        committed = await migrate_in_transaction(transaction)
        if not committed:
            logger.info("Legacy refresh migration lost race or already consumed")
            return None

        return self._token_response(
            access_token=access_token,
            access_expires_at=access_expires_at,
            refresh_token=new_refresh_token,
        )

    # ---- 失効 ----

    async def logout(self, refresh_token: str) -> bool:
        """LINE Refresh Tokenとそのセッションを失効させる。"""
        payload = self._decode_refresh(refresh_token)
        if not payload:
            return False
        token_id = payload["jti"]
        session_id = payload.get("sid")
        if session_id:
            try:
                await self.session_repository.revoke(session_id)
            except Exception as exc:
                logger.warning(
                    "Session revoke during logout failed: error_type=%s",
                    type(exc).__name__,
                )
        return bool(token_id) and await self.token_repository.revoke_token(token_id)

    async def revoke_all_user_tokens(self, user_id: str) -> int:
        """ユーザーの全セッションを即時失効させる（Access Tokenを含む）。

        認証世代を原子的に更新するため、失効処理に漏れがあっても
        世代不一致により旧トークンは無効になる。
        """
        await self.user_repository.increment_auth_version(user_id)
        revoked_count = await self.token_repository.revoke_all_user_tokens(user_id)
        try:
            await self.session_repository.revoke_all_for_user(user_id)
        except Exception as exc:
            logger.warning(
                "Session batch revoke failed: error_type=%s",
                type(exc).__name__,
            )
        return revoked_count

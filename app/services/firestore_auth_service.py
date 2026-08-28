"""Firestoreを使用するLINE Login認証サービス。"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_token,
    verify_token_hash,
)
from app.repositories.firestore_refresh_token_repository import (
    FirestoreRefreshTokenRepository,
)
from app.repositories.firestore_user_repository import FirestoreUserRepository


class FirestoreAuthService:
    """LINE LoginのJWT発行・更新・失効をFirestoreで管理する。"""

    def __init__(
        self,
        user_repository: Optional[FirestoreUserRepository] = None,
        token_repository: Optional[FirestoreRefreshTokenRepository] = None,
    ) -> None:
        self.user_repository = user_repository or FirestoreUserRepository()
        self.token_repository = token_repository or FirestoreRefreshTokenRepository()

    async def issue_tokens(
        self,
        user: Dict[str, Any],
        line_user_id: str,
    ) -> Dict[str, Any]:
        """LINEユーザーへAccess/Refresh Tokenを発行し、Refresh Tokenを保存する。"""
        access_jti = str(uuid.uuid4())
        refresh_jti = str(uuid.uuid4())
        email = user.get("email") or f"line_{line_user_id}@chabot.local"

        access_token, access_expires_at = create_access_token(
            user_id=user["id"],
            email=email,
            jti=access_jti,
            additional_claims={
                "provider": "line",
                "line_user_id": line_user_id,
                "role": user.get("role", "user"),
            },
        )
        refresh_token, refresh_expires_at = create_refresh_token(
            user_id=user["id"],
            email=email,
            jti=refresh_jti,
            additional_claims={
                "provider": "line",
                "line_user_id": line_user_id,
            },
        )
        token_hash = await asyncio.to_thread(hash_token, refresh_token)
        await self.token_repository.create(
            {
                "id": refresh_jti,
                "user_id": user["id"],
                "token_hash": token_hash,
                "expires_at": refresh_expires_at,
                "is_revoked": False,
                "revoked_at": None,
                "provider": "line",
                "created_at": datetime.now(timezone.utc),
            }
        )
        return {
            "access_token": access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer",
            "expires_in": int(
                (access_expires_at - datetime.now(timezone.utc)).total_seconds()
            ),
        }

    async def refresh(self, refresh_token: str) -> Optional[Dict[str, Any]]:
        """保存済みLINE Refresh Tokenを検証し、ローテーションする。"""
        payload = decode_token(refresh_token)
        if not payload or payload.get("type") != "refresh":
            return None
        if payload.get("provider") != "line":
            return None

        token_id = payload.get("jti")
        user_id = payload.get("sub")
        line_user_id = payload.get("line_user_id")
        if not token_id or not user_id or not line_user_id:
            return None

        stored = await self.token_repository.get_by_id(token_id)
        if not stored or stored.get("is_revoked", False):
            return None
        expires_at = stored.get("expires_at")
        if isinstance(expires_at, str):
            expires_at = datetime.fromisoformat(expires_at)
        if expires_at and expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if not expires_at or expires_at <= datetime.now(timezone.utc):
            return None
        if not await asyncio.to_thread(
            verify_token_hash,
            refresh_token,
            stored.get("token_hash", ""),
        ):
            return None

        user = await self.user_repository.find_by_id(user_id)
        if not user or not user.get("is_active", False):
            return None

        tokens = await self.issue_tokens(user, line_user_id)
        await self.token_repository.revoke_token(token_id)
        return tokens

    async def logout(self, refresh_token: str) -> bool:
        """LINE Refresh Tokenを失効させる。"""
        payload = decode_token(refresh_token)
        if not payload or payload.get("provider") != "line":
            return False
        token_id = payload.get("jti")
        return bool(token_id) and await self.token_repository.revoke_token(token_id)

    async def revoke_all_user_tokens(self, user_id: str) -> int:
        """ユーザーに属する全Refresh Tokenを失効させる。"""
        return await self.token_repository.revoke_all_user_tokens(user_id)

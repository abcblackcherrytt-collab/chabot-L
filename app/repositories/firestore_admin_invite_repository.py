"""Firestore無料登録URLリポジトリ（admin_invites）。

1回限りの無料登録URLの発行・一覧・失効と、公開Bot側からの
トークン照合・単回消費（Transaction）を担う。トークン平文は保存しない。
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


ADMIN_INVITES_COLLECTION = "admin_invites"
INVITE_STATUS_UNUSED = "unused"
INVITE_STATUS_CONSUMED = "consumed"
INVITE_STATUS_REVOKED = "revoked"
INVITE_TYPES = ("free", "service")


def _parse_iso(value: Any) -> Optional[datetime]:
    """ISO日時文字列をパースする。不正時はNone。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _with_effective_status(data: Dict[str, Any]) -> Dict[str, Any]:
    """未使用だが期限切れの招待を期限切れとして表示する。"""
    result = dict(data)
    if result.get("status") == INVITE_STATUS_UNUSED:
        expires_at = _parse_iso(result.get("expires_at"))
        if expires_at is None or expires_at <= datetime.now(timezone.utc):
            result["effective_status"] = "expired"
        else:
            result["effective_status"] = INVITE_STATUS_UNUSED
    else:
        result["effective_status"] = result.get("status")
    return result


class FirestoreAdminInviteRepository:
    """admin_invites コレクションの読み書きを提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    async def issue(
        self,
        *,
        token_sha256: str,
        expires_at: datetime,
        created_by: str,
        invite_type: str = "free",
    ) -> Dict[str, Any]:
        """新しい招待を作成し、ハッシュのみ保存する。"""
        if invite_type not in INVITE_TYPES:
            raise ValueError("invalid_invite_type")
        now = datetime.now(timezone.utc)
        invite_id = f"inv_{uuid.uuid4().hex[:12]}"
        data = {
            "id": invite_id,
            "token_sha256": token_sha256,
            "status": INVITE_STATUS_UNUSED,
            "invite_type": invite_type,
            "expires_at": expires_at.astimezone(timezone.utc).isoformat(),
            "created_by": created_by,
            "created_at": now.isoformat(),
            "consumed_by": None,
            "consumed_at": None,
        }
        await self.db.collection(ADMIN_INVITES_COLLECTION).document(invite_id).set(data)
        logger.info("Admin invite issued")
        return dict(data)

    async def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """新しい順に一覧を返す（トークンハッシュは除外）。"""
        docs = await (
            self.db.collection(ADMIN_INVITES_COLLECTION)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data.pop("token_sha256", None)
            results.append(_with_effective_status(data))
        return results

    async def revoke(self, invite_id: str) -> bool:
        """未使用の招待を失効する。"""
        ref = self.db.collection(ADMIN_INVITES_COLLECTION).document(invite_id)
        doc = await ref.get()
        if not doc.exists or doc.to_dict().get("status") != INVITE_STATUS_UNUSED:
            return False
        await ref.update(
            {
                "status": INVITE_STATUS_REVOKED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return True

    async def find_active_by_token_hash(self, token_sha256: str) -> Optional[Dict[str, Any]]:
        """トークンハッシュで未使用かつ期限内の招待を探す。"""
        docs = await (
            self.db.collection(ADMIN_INVITES_COLLECTION)
            .where("token_sha256", "==", token_sha256)
            .where("status", "==", INVITE_STATUS_UNUSED)
            .limit(1)
            .get()
        )
        for doc in docs:
            data = doc.to_dict()
            expires_at = _parse_iso(data.get("expires_at"))
            if expires_at is None or expires_at <= datetime.now(timezone.utc):
                continue
            data["id"] = doc.id
            return data
        return None

    async def consume(self, *, invite_id: str, user_id: str) -> bool:
        """招待消費とservice権限付与を同一Transactionで確定する。"""
        ref = self.db.collection(ADMIN_INVITES_COLLECTION).document(invite_id)
        transaction = self.db.transaction()

        @firestore.async_transactional
        async def _consume(tx: firestore.AsyncTransaction) -> bool:
            doc = await ref.get(transaction=tx)
            if not doc.exists:
                return False
            data = doc.to_dict()
            if data.get("status") != INVITE_STATUS_UNUSED:
                return False
            expires_at = _parse_iso(data.get("expires_at"))
            if expires_at is None or expires_at <= datetime.now(timezone.utc):
                return False
            tx.update(
                ref,
                {
                    "status": INVITE_STATUS_CONSUMED,
                    "consumed_by": user_id,
                    "consumed_at": datetime.now(timezone.utc).isoformat(),
                },
            )
            if data.get("invite_type", "free") == "service":
                tx.set(
                    self.db.collection("users").document(user_id),
                    {
                        "plan_override": {
                            "plan": "service",
                            "source": "service_invite",
                            "expires_at": None,
                        },
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    },
                    merge=True,
                )
            return True

        return await _consume(transaction)

    async def mark_user_registration(
        self,
        *,
        invite_id: str,
        user_id: str,
    ) -> None:
        """ユーザー文書へ招待経由登録を記録する。"""
        await self.db.collection("users").document(user_id).update(
            {
                "registration_source": "admin_invite",
                "admin_invite_id": invite_id,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

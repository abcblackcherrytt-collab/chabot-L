"""Firestore版Refresh Tokenリポジトリ。"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync


class FirestoreRefreshTokenRepository:
    """LINE Login用Refresh Tokenの保存・失効を管理する。"""

    collection_name = "refresh_tokens"

    def __init__(self, client: Optional[firestore.AsyncClient] = None) -> None:
        self.db = client or get_firestore_client_sync()

    async def create(self, token_data: Dict[str, Any]) -> None:
        """Refresh TokenメタデータをJTI単位で保存する。"""
        await (
            self.db.collection(self.collection_name)
            .document(token_data["id"])
            .set(token_data)
        )

    async def get_by_id(self, token_id: str) -> Optional[Dict[str, Any]]:
        """JTIに一致するRefresh Tokenを取得する。"""
        document = await (
            self.db.collection(self.collection_name).document(token_id).get()
        )
        if not document.exists:
            return None
        data = document.to_dict()
        data["id"] = document.id
        return data

    async def revoke_token(self, token_id: str) -> bool:
        """Refresh Tokenを失効状態へ更新する。"""
        document = self.db.collection(self.collection_name).document(token_id)
        snapshot = await document.get()
        if not snapshot.exists:
            return False
        await document.update(
            {
                "is_revoked": True,
                "revoked_at": datetime.now(timezone.utc),
            }
        )
        return True

    async def revoke_all_user_tokens(self, user_id: str) -> int:
        """ユーザーに属する有効なRefresh Tokenをすべて失効させる。"""
        documents = await (
            self.db.collection(self.collection_name)
            .where("user_id", "==", user_id)
            .get()
        )
        active_documents = [
            document
            for document in documents
            if not document.to_dict().get("is_revoked", False)
        ]
        if not active_documents:
            return 0

        batch = self.db.batch()
        revoked_at = datetime.now(timezone.utc)
        for document in active_documents:
            batch.update(
                document.reference,
                {"is_revoked": True, "revoked_at": revoked_at},
            )
        await batch.commit()
        return len(active_documents)

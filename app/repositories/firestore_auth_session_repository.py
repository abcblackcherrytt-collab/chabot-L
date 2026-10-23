"""Firestore認証セッションリポジトリ（auth_sessions）。

Access Tokenを含む即時失効とRefresh Tokenの原子的更新のための
セッション状態を管理する。文書ID（sid）はランダムUUIDで、
ユーザー識別子を含まない。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync


class FirestoreAuthSessionRepository:
    """auth_sessionsコレクションの読み書き・失効を提供する。"""

    collection_name = "auth_sessions"

    def __init__(self, client: Optional[firestore.AsyncClient] = None) -> None:
        self.db = client or get_firestore_client_sync()

    async def create(self, session_data: Dict[str, Any]) -> None:
        """セッション文書を作成する（id=sid）。"""
        await (
            self.db.collection(self.collection_name)
            .document(session_data["id"])
            .set(session_data)
        )

    async def get(self, session_id: str) -> Optional[Dict[str, Any]]:
        """sidに一致するセッションを取得する。存在しない場合はNone。"""
        document = await (
            self.db.collection(self.collection_name).document(session_id).get()
        )
        if not document.exists:
            return None
        data = document.to_dict() or {}
        data["id"] = document.id
        return data

    async def revoke(self, session_id: str) -> bool:
        """単一セッションを失効させる。"""
        document = self.db.collection(self.collection_name).document(session_id)
        snapshot = await document.get()
        if not snapshot.exists:
            return False
        await document.update({"revoked_at": datetime.now(timezone.utc)})
        return True

    async def revoke_all_for_user(self, user_id: str) -> int:
        """ユーザーに属する未失効セッションをすべて失効させる。"""
        documents = await (
            self.db.collection(self.collection_name)
            .where("user_id", "==", user_id)
            .get()
        )
        active_documents = [
            document
            for document in documents
            if not document.to_dict().get("revoked_at")
        ]
        if not active_documents:
            return 0
        batch = self.db.batch()
        revoked_at = datetime.now(timezone.utc)
        for document in active_documents:
            batch.update(document.reference, {"revoked_at": revoked_at})
        await batch.commit()
        return len(active_documents)

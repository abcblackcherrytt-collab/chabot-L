"""Stripe WebhookイベントのFirestore冪等性管理。"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Literal, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync


ClaimResult = Literal["claimed", "completed", "in_progress"]


class FirestoreStripeEventRepository:
    """WebhookイベントをCloud Runインスタンス間で一意に処理する。"""

    collection_name = "stripe_events"
    processing_timeout = timedelta(minutes=5)

    def __init__(self, client: Optional[firestore.AsyncClient] = None) -> None:
        self.db = client or get_firestore_client_sync()

    async def claim(
        self,
        event_id: str,
        event_type: str,
        event_created: Any,
    ) -> ClaimResult:
        """イベントを原子的に確保し、重複または処理中なら状態を返す。"""
        document = self.db.collection(self.collection_name).document(event_id)
        transaction = self.db.transaction()

        @firestore.async_transactional
        async def claim_in_transaction(tx) -> ClaimResult:
            snapshot = await document.get(transaction=tx)
            now = datetime.now(timezone.utc)
            attempts = 0

            if snapshot.exists:
                stored = snapshot.to_dict()
                attempts = int(stored.get("attempts", 0))
                if stored.get("status") == "completed":
                    return "completed"

                updated_at = stored.get("updated_at")
                if isinstance(updated_at, str):
                    updated_at = datetime.fromisoformat(updated_at)
                if updated_at and updated_at.tzinfo is None:
                    updated_at = updated_at.replace(tzinfo=timezone.utc)
                if (
                    stored.get("status") == "processing"
                    and updated_at
                    and now - updated_at < self.processing_timeout
                ):
                    return "in_progress"

            tx.set(
                document,
                {
                    "event_id": event_id,
                    "event_type": event_type,
                    "event_created": event_created,
                    "status": "processing",
                    "attempts": attempts + 1,
                    "updated_at": now,
                    "last_error": None,
                },
                merge=True,
            )
            return "claimed"

        return await claim_in_transaction(transaction)

    async def mark_completed(self, event_id: str) -> None:
        """正常処理したイベントを完了状態にする。"""
        await self.db.collection(self.collection_name).document(event_id).update(
            {
                "status": "completed",
                "completed_at": datetime.now(timezone.utc),
                "updated_at": datetime.now(timezone.utc),
                "last_error": None,
            }
        )

    async def mark_failed(self, event_id: str, error: str) -> None:
        """失敗イベントを再確保可能な状態にする。"""
        await self.db.collection(self.collection_name).document(event_id).update(
            {
                "status": "failed",
                "updated_at": datetime.now(timezone.utc),
                "last_error": error[:500],
            }
        )

    async def get(self, event_id: str) -> Optional[Dict[str, Any]]:
        """監査・テスト用にイベント状態を取得する。"""
        snapshot = await (
            self.db.collection(self.collection_name).document(event_id).get()
        )
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        data["id"] = snapshot.id
        return data

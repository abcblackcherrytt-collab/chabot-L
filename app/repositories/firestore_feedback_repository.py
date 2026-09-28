"""Firestore要望リポジトリ（feedback / feedback_pending）。

LINEでの要望受付（受付モード・日次上限）と、管理画面での要望一覧・対応管理を担う。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


FEEDBACK_COLLECTION = "feedback"
FEEDBACK_PENDING_COLLECTION = "feedback_pending"
FEEDBACK_STATUS_OPEN = "open"
FEEDBACK_STATUS_HANDLED = "handled"
FEEDBACK_DAILY_LIMIT = 5
FEEDBACK_CONTENT_MAX_LENGTH = 2000
ADMIN_NOTE_MAX_LENGTH = 500
JST = ZoneInfo("Asia/Tokyo")


def _now_jst() -> datetime:
    """現在のJST時刻を返す。"""
    return datetime.now(JST)


class FirestoreFeedbackRepository:
    """要望の受付と管理を提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    async def start_pending(self, *, user_id: str, ttl_seconds: int = 600) -> datetime:
        """要望受付モードを開始する。"""
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        await self.db.collection(FEEDBACK_PENDING_COLLECTION).document(user_id).set(
            {"user_id": user_id, "expires_at": expires_at.isoformat()}
        )
        return expires_at

    async def get_pending(self, user_id: str) -> Optional[Dict[str, Any]]:
        """有効な受付モードを返す。期限切れはNone扱いとする（lazy expiry）。"""
        doc = await self.db.collection(FEEDBACK_PENDING_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        expires_at = data.get("expires_at")
        if isinstance(expires_at, str):
            try:
                if datetime.fromisoformat(expires_at) <= datetime.now(timezone.utc):
                    return None
            except ValueError:
                return None
        elif expires_at is not None:
            if expires_at <= datetime.now(timezone.utc):
                return None
        data["id"] = doc.id
        return data

    async def cancel_pending(self, user_id: str) -> bool:
        """受付モードを取り消す。"""
        await self.db.collection(FEEDBACK_PENDING_COLLECTION).document(user_id).delete()
        return True

    async def count_today_feedback(self, user_id: str) -> int:
        """本日（JST）の要望件数を数える。"""
        today_start = _now_jst().replace(hour=0, minute=0, second=0, microsecond=0)
        docs = await (
            self.db.collection(FEEDBACK_COLLECTION)
            .where("user_id", "==", user_id)
            .where("created_at", ">=", today_start.isoformat())
            .get()
        )
        return len(docs)

    async def save(self, *, user_id: str, display_name: str, content: str) -> str:
        """要望を1件保存する。"""
        document = {
            "user_id": user_id,
            "display_name": display_name or "",
            "content": content[:FEEDBACK_CONTENT_MAX_LENGTH],
            "status": FEEDBACK_STATUS_OPEN,
            "admin_note": None,
            "handled_by": None,
            "handled_at": None,
            "created_at": datetime.now(JST).isoformat(),
        }
        _, ref = await self.db.collection(FEEDBACK_COLLECTION).add(document)
        logger.info("Feedback saved")
        return ref.id

    async def list(self, status: Optional[str] = None, limit: int = 100) -> List[Dict[str, Any]]:
        """新しい順に要望一覧を返す。本文は管理UIの表示用に含める。"""
        query = self.db.collection(FEEDBACK_COLLECTION).order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        if status in (FEEDBACK_STATUS_OPEN, FEEDBACK_STATUS_HANDLED):
            query = query.where("status", "==", status)
        docs = await query.limit(limit).get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    async def update_status(
        self,
        feedback_id: str,
        *,
        status: str,
        admin_note: Optional[str],
        handled_by: str,
    ) -> Optional[Dict[str, Any]]:
        """対応ステータスと管理メモを更新する。"""
        if status not in (FEEDBACK_STATUS_OPEN, FEEDBACK_STATUS_HANDLED):
            raise ValueError("invalid_status")
        ref = self.db.collection(FEEDBACK_COLLECTION).document(feedback_id)
        doc = await ref.get()
        if not doc.exists:
            return None
        update = {
            "status": status,
            "handled_by": handled_by if status == FEEDBACK_STATUS_HANDLED else None,
            "handled_at": datetime.now(JST).isoformat()
            if status == FEEDBACK_STATUS_HANDLED
            else None,
            "updated_at": datetime.now(JST).isoformat(),
        }
        if admin_note is not None:
            update["admin_note"] = admin_note[:ADMIN_NOTE_MAX_LENGTH]
        await ref.update(update)
        data = doc.to_dict()
        data.update(update)
        data["id"] = feedback_id
        return data

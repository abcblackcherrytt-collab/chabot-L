"""Firestore管理用日次統計リポジトリ（admin_daily_stats）。

Bot側の使用カウント更新と同じタイミングで指標を加算し、
管理UIの「集計」項目は既存ドキュメントの範囲集計で表示する。
"""

import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


ADMIN_STATS_COLLECTION = "admin_daily_stats"
ACTIVE_USERS_SUBCOLLECTION = "active_users"
JST = ZoneInfo("Asia/Tokyo")


class FirestoreAdminStatsRepository:
    """admin_daily_stats コレクションの加算と範囲集計を提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    def _doc_ref(self, date: Optional[datetime] = None):
        """当日（JST）の統計ドキュメント参照を返す。"""
        date_str = (date or datetime.now(JST)).strftime("%Y-%m-%d")
        return self.db.collection(ADMIN_STATS_COLLECTION).document(date_str)

    def _date_str(self, date: datetime) -> str:
        """日付文字列を返す。"""
        return date.strftime("%Y-%m-%d")

    async def _increment(self, field: str, date: Optional[datetime] = None) -> None:
        """指定フィールドを原子的に1加算する。"""
        ref = self._doc_ref(date)
        await ref.set(
            {
                "date": self._date_str(date or datetime.now(JST)),
                field: firestore.Increment(1),
                "updated_at": datetime.now(JST).isoformat(),
            },
            merge=True,
        )

    async def increment_message_count(self) -> None:
        """メッセージ数を加算する。"""
        await self._increment("message_count")

    async def increment_denied_by_limit(self) -> None:
        """上限拒否数を加算する。"""
        await self._increment("denied_by_limit")

    async def increment_coupon_redemption(self) -> None:
        """クーポン引き換れ数を加算する。"""
        await self._increment("coupon_redemptions")

    async def increment_coupon_failure(self) -> None:
        """クーポン引き換れ失敗試行を加算する。"""
        await self._increment("coupon_failed_attempts")

    async def increment_feedback(self) -> None:
        """要望件数を加算する。"""
        await self._increment("feedback_count")

    async def record_active_user(self, user_id: str) -> None:
        """当日のアクティブユーザーを記録する。初出現時だけカウンタを加算する。"""
        ref = self._doc_ref()
        user_ref = ref.collection(ACTIVE_USERS_SUBCOLLECTION).document(user_id)
        try:
            await user_ref.create({"user_id": user_id, "created_at": datetime.now(JST).isoformat()})
        except Exception as exc:
            # 既に存在する（=本日既にアクティブ）場合はカウントしない。
            if "already exists" not in str(exc).lower():
                raise
            return
        await ref.set(
            {
                "date": self._date_str(datetime.now(JST)),
                "active_user_count": firestore.Increment(1),
                "updated_at": datetime.now(JST).isoformat(),
            },
            merge=True,
        )

    async def get_range(self, days: int) -> List[Dict]:
        """過去N日分（当日含む・JST）の統計を返す。"""
        today = datetime.now(JST)
        start = (today - timedelta(days=days - 1)).strftime("%Y-%m-%d")
        end = today.strftime("%Y-%m-%d")
        docs = await (
            self.db.collection(ADMIN_STATS_COLLECTION)
            .where("date", ">=", start)
            .where("date", "<=", end)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return sorted(results, key=lambda item: item.get("date", ""))

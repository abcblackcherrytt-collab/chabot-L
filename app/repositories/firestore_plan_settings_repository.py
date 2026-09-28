"""Firestore日次回数上限設定リポジトリ（plan_settings）。

管理UIが公開する日次回数上限の下書き保存・反映・ロールバックと、
Bot側からの公開済み値読み取り（60秒キャッシュ・安全なフォールバック）を担う。
"""

import logging
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


PLAN_SETTINGS_COLLECTION = "plan_settings"
MIN_DAILY_LIMIT = 1
MAX_DAILY_LIMIT = 999
PLAN_SETTINGS_CACHE_TTL_SECONDS = 60.0
PLAN_HISTORY_KEEP = 20
VALID_PLANS = ("free", "basic", "pro")


class FirestorePlanSettingsRepository:
    """plan_settings コレクションの読み書きを提供する。"""

    # Bot側キャッシュ。管理サービスは別プロセスのため反映は最大60秒で伝搬する。
    _limit_cache: Dict[str, tuple[float, Optional[int]]] = {}

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    @classmethod
    def invalidate_limit_cache(cls, plan: Optional[str] = None) -> None:
        """公開後にBot側キャッシュを破棄する（同一プロセス内のみ）。"""
        if plan is None:
            cls._limit_cache.clear()
        else:
            cls._limit_cache.pop(plan, None)

    async def get_published_daily_limit(self, plan: str) -> Optional[int]:
        """公開済み日次上限を返す。欠損・不正・読取失敗時はNone（呼び出し側は既定値へフォールバック）。"""
        cached = self._limit_cache.get(plan)
        if cached and time.monotonic() - cached[0] < PLAN_SETTINGS_CACHE_TTL_SECONDS:
            return cached[1]
        try:
            doc = await self.db.collection(PLAN_SETTINGS_COLLECTION).document(plan).get()
        except Exception as exc:
            logger.warning(
                "Plan settings read failed: plan=%s error_type=%s",
                plan,
                type(exc).__name__,
            )
            self._limit_cache[plan] = (time.monotonic(), None)
            return None
        limit = self._validated_limit(doc.to_dict()) if doc.exists else None
        self._limit_cache[plan] = (time.monotonic(), limit)
        return limit

    async def get_settings(self, plan: str) -> Optional[Dict[str, Any]]:
        """管理UI表示用に1プラン分の設定を返す。"""
        if plan not in VALID_PLANS:
            raise ValueError(f"Invalid plan: {plan}")
        doc = await self.db.collection(PLAN_SETTINGS_COLLECTION).document(plan).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    async def list_settings(self) -> List[Dict[str, Any]]:
        """全プラン分の設定を返す（未設定分は含めない）。"""
        docs = await self.db.collection(PLAN_SETTINGS_COLLECTION).get()
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

    async def save_draft(
        self,
        *,
        plan: str,
        daily_message_limit: int,
        base_revision: int,
        updated_by: str,
    ) -> Dict[str, Any]:
        """下書きを保存する。既定値（未設定）状態からも保存できる。"""
        if plan not in VALID_PLANS:
            raise ValueError(f"Invalid plan: {plan}")
        limit = self._require_valid_limit(daily_message_limit)
        now = datetime.now(timezone.utc).isoformat()
        ref = self.db.collection(PLAN_SETTINGS_COLLECTION).document(plan)
        doc = await ref.get()
        data = doc.to_dict() if doc.exists else {}
        if int(data.get("published_revision", 0)) != int(base_revision):
            raise ValueError("revision_conflict")
        update = {
            "plan": plan,
            "daily_message_limit": self._validated_limit(data) if data else None,
            "published_revision": int(base_revision),
            "draft_daily_message_limit": limit,
            "draft_updated_by": updated_by,
            "draft_updated_at": now,
            "updated_at": now,
        }
        if not doc.exists:
            update["created_at"] = now
        await ref.set(update, merge=True)
        return {**update, "id": plan}

    async def publish(self, *, plan: str, revision: int, published_by: str) -> Dict[str, Any]:
        """下書きを公開へ反映する。Transactionでrevisionを検証して切替える。"""
        if plan not in VALID_PLANS:
            raise ValueError(f"Invalid plan: {plan}")
        ref = self.db.collection(PLAN_SETTINGS_COLLECTION).document(plan)
        transaction = self.db.transaction()

        @firestore.async_transactional
        async def _publish(tx: firestore.AsyncTransaction) -> Dict[str, Any]:
            doc = await ref.get(transaction=tx)
            data = doc.to_dict() if doc.exists else {}
            current_revision = int(data.get("published_revision", 0))
            if not doc.exists or current_revision != int(revision):
                raise ValueError("revision_conflict")
            limit = self._require_valid_limit(data.get("draft_daily_message_limit"))
            now = datetime.now(timezone.utc).isoformat()
            new_revision = current_revision + 1
            history = list(data.get("history") or [])
            history.append(
                {
                    "revision": new_revision,
                    "daily_message_limit": limit,
                    "published_by": published_by,
                    "published_at": now,
                }
            )
            update = {
                "plan": plan,
                "daily_message_limit": limit,
                "published_revision": new_revision,
                "draft_daily_message_limit": limit,
                "draft_updated_by": published_by,
                "draft_updated_at": now,
                "updated_at": now,
                "history": history[-PLAN_HISTORY_KEEP:],
            }
            tx.set(ref, update, merge=True)
            return {**update, "id": plan}

        return await _publish(transaction)

    async def rollback(self, *, plan: str, performed_by: str) -> Dict[str, Any]:
        """直前の公開履歴へ戻す。戻した値も新しいrevisionとして履歴に記録する。"""
        if plan not in VALID_PLANS:
            raise ValueError(f"Invalid plan: {plan}")
        ref = self.db.collection(PLAN_SETTINGS_COLLECTION).document(plan)
        transaction = self.db.transaction()

        @firestore.async_transactional
        async def _rollback(tx: firestore.AsyncTransaction) -> Dict[str, Any]:
            doc = await ref.get(transaction=tx)
            data = doc.to_dict() if doc.exists else {}
            history = list(data.get("history") or [])
            if not doc.exists or len(history) < 2:
                raise ValueError("no_rollback_target")
            previous = history[-2]
            limit = self._require_valid_limit(previous.get("daily_message_limit"))
            now = datetime.now(timezone.utc).isoformat()
            new_revision = int(data.get("published_revision", 0)) + 1
            history.append(
                {
                    "revision": new_revision,
                    "daily_message_limit": limit,
                    "published_by": performed_by,
                    "published_at": now,
                    "rollback_of": previous.get("revision"),
                }
            )
            update = {
                "plan": plan,
                "daily_message_limit": limit,
                "published_revision": new_revision,
                "draft_daily_message_limit": limit,
                "draft_updated_by": performed_by,
                "draft_updated_at": now,
                "updated_at": now,
                "history": history[-PLAN_HISTORY_KEEP:],
            }
            tx.set(ref, update, merge=True)
            return {**update, "id": plan}

        return await _rollback(transaction)

    @staticmethod
    def _validated_limit(data: Optional[Dict[str, Any]]) -> Optional[int]:
        """保存値として妥当な上限だけを通す。"""
        if not data:
            return None
        raw = data.get("daily_message_limit")
        if isinstance(raw, bool) or not isinstance(raw, int):
            return None
        if not MIN_DAILY_LIMIT <= raw <= MAX_DAILY_LIMIT:
            return None
        return raw

    @staticmethod
    def _require_valid_limit(raw: Any) -> int:
        """入力値を検証し、不正なら例外を投げる。"""
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise ValueError("invalid_limit")
        if not MIN_DAILY_LIMIT <= raw <= MAX_DAILY_LIMIT:
            raise ValueError("invalid_limit")
        return raw

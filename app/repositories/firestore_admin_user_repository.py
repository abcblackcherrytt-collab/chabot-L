"""Firestore管理用ユーザー参照リポジトリ。

管理UIのためのユーザー一覧（ページネーション・検索・絞込み）と詳細参照、
プラン変更（plan_override）・無効化を担う。公開Botのユーザーリポジトリとは責務を分ける。
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync
from app.core.pricing import resolve_effective_plan

logger = logging.getLogger(__name__)


USERS_COLLECTION = "users"
USAGE_DAILY_COLLECTION = "usage_daily"
JST = ZoneInfo("Asia/Tokyo")


class FirestoreAdminUserRepository:
    """users コレクションの管理向け読み書きを提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    @staticmethod
    def _mask_line_user_id(line_user_id: Optional[str]) -> Optional[str]:
        """一覧表示用にLINE user IDをマスクする。"""
        if not line_user_id:
            return None
        if len(line_user_id) <= 8:
            return line_user_id[:2] + "…"
        return f"{line_user_id[:4]}…{line_user_id[-4:]}"

    @staticmethod
    def _summary(data: Dict[str, Any], doc_id: str) -> Dict[str, Any]:
        """一覧表示用の非PII要約へ絞り込む。"""
        override = data.get("plan_override") if isinstance(data.get("plan_override"), dict) else None
        return {
            "id": doc_id,
            "display_name": data.get("display_name"),
            "subscription_plan": data.get("subscription_plan") or "free",
            "effective_plan": resolve_effective_plan(data),
            "plan_override": override,
            "is_active": bool(data.get("is_active", True)),
            "created_at": data.get("created_at"),
            "updated_at": data.get("updated_at"),
            "line_user_id_masked": FirestoreAdminUserRepository._mask_line_user_id(
                data.get("line_user_id")
            ),
        }

    async def list_users(
        self,
        *,
        page_size: int = 20,
        q: Optional[str] = None,
        plan: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """ユーザー一覧を返す。Firestoreの順序取得のみ使い、絞込みは適用後に行う。

        複合インデックスを要求しない構成にするため、where句は使わない。
        """
        query = self.db.collection(USERS_COLLECTION).order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        docs = await query.limit(500).get()
        users: List[Dict[str, Any]] = []
        prefix = (q or "").strip()
        for doc in docs:
            data = doc.to_dict()
            if prefix:
                name = data.get("display_name") or ""
                if not name.startswith(prefix):
                    continue
            if plan in ("free", "basic", "pro", "service"):
                if resolve_effective_plan(data) != plan:
                    continue
            if status == "active" and not data.get("is_active", True):
                continue
            if status == "inactive" and data.get("is_active", True):
                continue
            users.append(self._summary(data, doc.id))
            if len(users) >= page_size:
                break
        await self._attach_today_usage(users)
        return {"users": users, "count": len(users)}

    async def _attach_today_usage(self, users: List[Dict[str, Any]]) -> None:
        """当日利用回数を並行取得して一覧へ付与する。"""
        if not users:
            return
        today = datetime.now(JST).strftime("%Y-%m-%d")

        async def _usage(user: Dict[str, Any]) -> None:
            doc = await (
                self.db.collection(USAGE_DAILY_COLLECTION)
                .document(f"{user['id']}_{today}")
                .get()
            )
            data = doc.to_dict() if doc.exists else {}
            user["today_message_count"] = int(data.get("message_count", 0) or 0)

        await asyncio.gather(*[_usage(user) for user in users])

    async def get_user_detail(self, user_id: str) -> Optional[Dict[str, Any]]:
        """詳細（LINE user ID・email等のPIIを含む）を返す。呼び出し側は監査を記録する。"""
        doc = await self.db.collection(USERS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        data["id"] = doc.id
        return data

    async def set_plan_override(
        self,
        *,
        user_id: str,
        plan: Optional[str],
        expires_at: Optional[datetime],
        source: str,
    ) -> None:
        """プラン変更（plan_override）を書き込む。plan=Noneで解除。"""
        override = None
        if plan is not None:
            override = {
                "plan": plan,
                "expires_at": expires_at.astimezone(timezone.utc).isoformat()
                if expires_at
                else None,
                "source": source,
            }
        await self.db.collection(USERS_COLLECTION).document(user_id).update(
            {
                "plan_override": override,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    async def deactivate(self, *, user_id: str) -> None:
        """ユーザーを無効化する（unfollowと同じ扱い）。"""
        await self.db.collection(USERS_COLLECTION).document(user_id).update(
            {
                "is_active": False,
                "deactivated_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

"""Firestore管理用ユーザー参照リポジトリ。

管理UIのための明示的なユーザー検索・絞込みと詳細参照、
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

    # 管理UI詳細応答へ含めるフィールド。連携ID（stripe_customer_id等）は
    # 応答へ返さず、漏洩面を最小化する。
    _DETAIL_FIELDS = (
        "display_name",
        "line_user_id",
        "email",
        "subscription_plan",
        "subscription_status",
        "plan_override",
        "is_active",
        "created_at",
        "updated_at",
    )

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
        q: str,
        search_field: str = "display_name",
        plan: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """検索条件に一致するユーザーだけを返す。

        全件一覧は提供しない。内部IDは1文書、LINE IDは完全一致、表示名は
        前方一致で最大20文書だけ読み、プラン・状態はその候補へ適用する。
        """
        query_text = q.strip()
        if not query_text:
            raise ValueError("search_query_required")
        if search_field not in {"display_name", "line_user_id", "user_id"}:
            raise ValueError("invalid_search_field")

        collection = self.db.collection(USERS_COLLECTION)
        if search_field == "user_id":
            document = await collection.document(query_text).get()
            docs = [document] if document.exists else []
        elif search_field == "line_user_id":
            docs = await (
                collection.where("line_user_id", "==", query_text)
                .limit(page_size)
                .get()
            )
        else:
            docs = await (
                collection.order_by("display_name")
                .start_at({"display_name": query_text})
                .end_at({"display_name": f"{query_text}\uf8ff"})
                .limit(page_size)
                .get()
            )

        users: List[Dict[str, Any]] = []
        for doc in docs:
            data = doc.to_dict()
            if search_field == "display_name":
                name = data.get("display_name") or ""
                if not name.startswith(query_text):
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
        """詳細を管理UI表示用フィールドへ絞り込んで返す。呼び出し側は監査を記録する。"""
        doc = await self.db.collection(USERS_COLLECTION).document(user_id).get()
        if not doc.exists:
            return None
        data = doc.to_dict()
        detail = {field: data.get(field) for field in self._DETAIL_FIELDS}
        detail["id"] = doc.id
        detail["effective_plan"] = resolve_effective_plan(data)
        return detail

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

"""Firestoreクーポンリポジトリ（coupons / coupon_redemptions）。

クーポン定義の発行・一覧・失効と、公開Bot側の引き換え（Transaction）を担う。
コード平文は保存せず、SHA-256ハッシュでのみ照合する。
"""

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


COUPONS_COLLECTION = "coupons"
COUPON_REDEMPTIONS_COLLECTION = "coupon_redemptions"
USAGE_DAILY_COLLECTION = "usage_daily"
USERS_COLLECTION = "users"
COUPON_KIND_PLAN_GRANT = "plan_grant"
COUPON_KIND_BONUS_MESSAGES = "bonus_messages"
COUPON_STATUS_ACTIVE = "active"
COUPON_STATUS_REVOKED = "revoked"
JST = ZoneInfo("Asia/Tokyo")


def _parse_iso(value: Any) -> Optional[datetime]:
    """ISO日時文字列をパースする。不正時はNone。"""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _today_str(now: datetime) -> str:
    """JST基準の今日日付を返す。"""
    return now.astimezone(JST).strftime("%Y-%m-%d")


class FirestoreCouponRepository:
    """クーポンの定義と引き換えを管理する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    async def create(
        self,
        *,
        code_sha256: str,
        kind: str,
        plan: Optional[str],
        duration_days: Optional[int],
        bonus_free_messages: Optional[int],
        max_redemptions: int,
        expires_at: Optional[datetime],
        created_by: str,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """クーポン定義を作成する。"""
        now = datetime.now(timezone.utc)
        coupon_id = f"cpn_{uuid.uuid4().hex[:12]}"
        data = {
            "id": coupon_id,
            "code_sha256": code_sha256,
            "kind": kind,
            "plan": plan,
            "duration_days": duration_days,
            "bonus_free_messages": bonus_free_messages,
            "max_redemptions": int(max_redemptions),
            "redeemed_count": 0,
            "expires_at": expires_at.astimezone(timezone.utc).isoformat() if expires_at else None,
            "status": COUPON_STATUS_ACTIVE,
            "created_by": created_by,
            "note": note,
            "created_at": now.isoformat(),
        }
        await self.db.collection(COUPONS_COLLECTION).document(coupon_id).set(data)
        logger.info("Coupon created: kind=%s", kind)
        return {k: v for k, v in data.items() if k != "code_sha256"}

    async def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """新しい順に一覧を返す（コードハッシュは除外）。"""
        docs = await (
            self.db.collection(COUPONS_COLLECTION)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data.pop("code_sha256", None)
            results.append(data)
        return results

    async def revoke(self, coupon_id: str) -> bool:
        """有効なクーポンを失効する（新規引き換え停止のみ）。"""
        ref = self.db.collection(COUPONS_COLLECTION).document(coupon_id)
        doc = await ref.get()
        if not doc.exists or doc.to_dict().get("status") != COUPON_STATUS_ACTIVE:
            return False
        await ref.update(
            {
                "status": COUPON_STATUS_REVOKED,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        return True

    async def redeem(
        self,
        *,
        code_sha256: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """クーポン引き換えをTransactionで実行する。

        Returns:
            辞書:
            - status: granted / not_found / expired / exhausted /
              already_redeemed / revoked
            - kind / plan / duration_days / bonus_free_messages: 付与内容
        """
        transaction = self.db.transaction()

        @firestore.async_transactional
        async def _redeem(tx: firestore.AsyncTransaction) -> Dict[str, Any]:
            now = datetime.now(timezone.utc)
            docs = await (
                self.db.collection(COUPONS_COLLECTION)
                .where("code_sha256", "==", code_sha256)
                .limit(1)
                .get(transaction=tx)
            )
            coupon = None
            coupon_ref = None
            for doc in docs:
                coupon = doc.to_dict()
                coupon_ref = self.db.collection(COUPONS_COLLECTION).document(doc.id)
            if coupon is None or coupon_ref is None:
                return {"status": "not_found"}
            if coupon.get("status") != COUPON_STATUS_ACTIVE:
                return {"status": "revoked"}
            expires_at = _parse_iso(coupon.get("expires_at"))
            if expires_at is not None and expires_at <= now:
                return {"status": "expired"}
            redeemed_count = int(coupon.get("redeemed_count", 0))
            if redeemed_count >= int(coupon.get("max_redemptions", 0)):
                return {"status": "exhausted"}

            redemption_id = f"{coupon.get('id')}_{user_id}"
            redemption_ref = self.db.collection(COUPON_REDEMPTIONS_COLLECTION).document(redemption_id)
            redemption_doc = await redemption_ref.get(transaction=tx)
            if redemption_doc.exists:
                return {"status": "already_redeemed"}

            kind = coupon.get("kind")
            result = {
                "status": "granted",
                "kind": kind,
                "plan": coupon.get("plan"),
                "duration_days": coupon.get("duration_days"),
                "bonus_free_messages": coupon.get("bonus_free_messages"),
            }

            # 引き換え記録とカウンタ更新を同じTransactionへ入れる。
            tx.set(
                redemption_ref,
                {
                    "coupon_id": coupon.get("id"),
                    "user_id": user_id,
                    "kind": kind,
                    "granted_plan": coupon.get("plan") if kind == COUPON_KIND_PLAN_GRANT else None,
                    "granted_bonus": coupon.get("bonus_free_messages")
                    if kind == COUPON_KIND_BONUS_MESSAGES
                    else None,
                    "redeemed_at": now.isoformat(),
                },
            )
            tx.update(coupon_ref, {"redeemed_count": redeemed_count + 1})

            if kind == COUPON_KIND_PLAN_GRANT:
                # plan_override付与。Stripe契約（basic/pro）とは競合時にStripeを優先するため、
                # Bot側のプラン解決が subscription_plan を優先して本フィールドを参照する。
                duration_days = int(coupon.get("duration_days") or 0)
                expires = now + timedelta(days=duration_days) if duration_days > 0 else None
                user_ref = self.db.collection(USERS_COLLECTION).document(user_id)
                tx.update(
                    user_ref,
                    {
                        "plan_override": {
                            "plan": coupon.get("plan"),
                            "expires_at": expires.isoformat() if expires else None,
                            "source": "coupon",
                        },
                        "updated_at": now.isoformat(),
                    },
                )
            elif kind == COUPON_KIND_BONUS_MESSAGES:
                usage_ref = self.db.collection(USAGE_DAILY_COLLECTION).document(
                    f"{user_id}_{_today_str(now)}"
                )
                usage_doc = await usage_ref.get(transaction=tx)
                usage_data = usage_doc.to_dict() if usage_doc.exists else {}
                bonus = int(usage_data.get("bonus_messages", 0) or 0) + int(
                    coupon.get("bonus_free_messages", 0) or 0
                )
                tx.set(
                    usage_ref,
                    {
                        "user_id": user_id,
                        "date": _today_str(now),
                        "bonus_messages": bonus,
                        "updated_at": now.isoformat(),
                    },
                    merge=True,
                )
            return result

        return await _redeem(transaction)

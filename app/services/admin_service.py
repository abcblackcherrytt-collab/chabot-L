"""管理コンソール操作サービス。

Firestoreリポジトリへの操作を組み立て、全書込み操作に監査記録を付与する。
HTTPの関心事（ステータスコード等）は持たない。
"""

import hashlib
import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.core.pricing import DAILY_MESSAGE_LIMITS
from app.repositories.firestore_admin_invite_repository import (
    FirestoreAdminInviteRepository,
)
from app.repositories.firestore_admin_stats_repository import (
    FirestoreAdminStatsRepository,
)
from app.repositories.firestore_admin_user_repository import (
    FirestoreAdminUserRepository,
)
from app.repositories.firestore_audit_log_repository import (
    FirestoreAuditLogRepository,
)
from app.repositories.firestore_conversation_repository import (
    FirestoreConversationRepository,
)
from app.repositories.firestore_coupon_repository import FirestoreCouponRepository
from app.repositories.firestore_feedback_repository import (
    FirestoreFeedbackRepository,
)
from app.repositories.firestore_plan_settings_repository import (
    FirestorePlanSettingsRepository,
    VALID_PLANS,
)
from app.repositories.firestore_user_repository import FirestoreUserRepository
from app.services.coupon_service import CouponService

logger = logging.getLogger(__name__)


class AdminService:
    """管理UIの操作を担うサービス。"""

    def __init__(
        self,
        *,
        plan_settings_repository: Optional[FirestorePlanSettingsRepository] = None,
        invite_repository: Optional[FirestoreAdminInviteRepository] = None,
        coupon_repository: Optional[FirestoreCouponRepository] = None,
        audit_repository: Optional[FirestoreAuditLogRepository] = None,
        feedback_repository: Optional[FirestoreFeedbackRepository] = None,
        stats_repository: Optional[FirestoreAdminStatsRepository] = None,
        admin_user_repository: Optional[FirestoreAdminUserRepository] = None,
        user_repository: Optional[FirestoreUserRepository] = None,
        conversation_repository: Optional[FirestoreConversationRepository] = None,
        line_client: Optional[Any] = None,
    ):
        """依存リポジトリを注入する。未指定時は既定実装を使う。"""
        self.plan_settings_repository = (
            plan_settings_repository or FirestorePlanSettingsRepository()
        )
        self.invite_repository = invite_repository or FirestoreAdminInviteRepository()
        self.coupon_service = CouponService(coupon_repository)
        self.audit_repository = audit_repository or FirestoreAuditLogRepository()
        self.feedback_repository = feedback_repository or FirestoreFeedbackRepository()
        self.stats_repository = stats_repository or FirestoreAdminStatsRepository()
        self.admin_user_repository = admin_user_repository or FirestoreAdminUserRepository()
        self.user_repository = user_repository or FirestoreUserRepository()
        self.conversation_repository = (
            conversation_repository or FirestoreConversationRepository()
        )
        self._line_client = line_client

    async def _line_client(self):
        """Messaging APIクライアントを遅延生成する。"""
        if self._line_client is None:
            from app.clients.line import LINEClient

            self._line_client = LINEClient(
                channel_access_token=settings.line_channel_access_token,
                channel_secret=settings.line_channel_secret,
                base_url=settings.line_api_base_url,
            )
        return self._line_client

    async def _audit(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        revision: Optional[int] = None,
        result: str = "success",
        detail: Optional[str] = None,
    ) -> None:
        """監査ログを記録する。"""
        await self.audit_repository.record(
            actor=actor,
            action=action,
            target_type=target_type,
            target_id=target_id,
            revision=revision,
            result=result,
            detail=detail,
        )

    # ---- プラン設定 ----

    async def get_plan_settings(self) -> List[Dict[str, Any]]:
        """free/basic/proの実効設定を返す。未設定分はコード既定値を示す。"""
        stored = {item.get("plan"): item for item in await self.plan_settings_repository.list_settings()}
        results = []
        for plan in VALID_PLANS:
            data = stored.get(plan) or {}
            fallback = DAILY_MESSAGE_LIMITS.get(plan)
            results.append(
                {
                    "plan": plan,
                    "configured": plan in stored,
                    "daily_message_limit": data.get("daily_message_limit", fallback),
                    "draft_daily_message_limit": data.get(
                        "draft_daily_message_limit", fallback
                    ),
                    "published_revision": int(data.get("published_revision", 0)),
                    "updated_at": data.get("updated_at"),
                    "history": list(data.get("history") or []),
                }
            )
        return results

    async def save_plan_draft(
        self,
        *,
        plan: str,
        daily_message_limit: int,
        base_revision: int,
        actor: str,
    ) -> Dict[str, Any]:
        """下書きを保存し、監査へ記録する。"""
        result = await self.plan_settings_repository.save_draft(
            plan=plan,
            daily_message_limit=daily_message_limit,
            base_revision=base_revision,
            updated_by=actor,
        )
        await self._audit(
            actor=actor,
            action="plan_settings.draft",
            target_type="plan_settings",
            target_id=plan,
            revision=base_revision,
            detail=f"draft={daily_message_limit}",
        )
        return result

    async def publish_plan(
        self, *, plan: str, revision: int, actor: str
    ) -> Dict[str, Any]:
        """下書きを反映し、監査へ記録してBot側キャッシュを破棄する。"""
        result = await self.plan_settings_repository.publish(
            plan=plan,
            revision=revision,
            published_by=actor,
        )
        FirestorePlanSettingsRepository.invalidate_limit_cache(plan)
        await self._audit(
            actor=actor,
            action="plan_settings.publish",
            target_type="plan_settings",
            target_id=plan,
            revision=result.get("published_revision"),
            detail=f"limit={result.get('daily_message_limit')}",
        )
        return result

    async def rollback_plan(self, *, plan: str, actor: str) -> Dict[str, Any]:
        """直前revisionへ戻し、監査へ記録する。"""
        result = await self.plan_settings_repository.rollback(
            plan=plan,
            performed_by=actor,
        )
        FirestorePlanSettingsRepository.invalidate_limit_cache(plan)
        await self._audit(
            actor=actor,
            action="plan_settings.rollback",
            target_type="plan_settings",
            target_id=plan,
            revision=result.get("published_revision"),
        )
        return result

    # ---- 無料登録URL ----

    async def issue_invite(self, *, actor: str, ttl_hours: Optional[int] = None) -> Dict[str, Any]:
        """1回限りの無料登録URLを発行する。平文トークンは応答にのみ載せる。"""
        if not settings.public_base_url:
            raise ValueError("public_base_url_not_configured")
        hours = int(ttl_hours or settings.admin_invite_default_ttl_hours)
        if not 1 <= hours <= 24 * 30:
            raise ValueError("invalid_ttl")
        token = secrets.token_urlsafe(32)
        token_sha256 = hashlib.sha256(token.encode("utf-8")).hexdigest()
        expires_at = datetime.now(timezone.utc) + timedelta(hours=hours)
        invite = await self.invite_repository.issue(
            token_sha256=token_sha256,
            expires_at=expires_at,
            created_by=actor,
        )
        # 保存用ハッシュは応答へ含めない（平文トークンはURLfragmentでのみ返す）。
        invite.pop("token_sha256", None)
        await self._audit(
            actor=actor,
            action="invite.issue",
            target_type="admin_invites",
            target_id=invite["id"],
        )
        url = f"{settings.public_base_url.rstrip('/')}/api/{settings.api_version}/invite#t={token}"
        return {"invite": invite, "url": url}

    async def list_invites(self) -> List[Dict[str, Any]]:
        """招待一覧を返す。"""
        return await self.invite_repository.list()

    async def revoke_invite(self, *, invite_id: str, actor: str) -> bool:
        """未使用の招待を失効する。"""
        result = await self.invite_repository.revoke(invite_id)
        if result:
            await self._audit(
                actor=actor,
                action="invite.revoke",
                target_type="admin_invites",
                target_id=invite_id,
            )
        return result

    # ---- ユーザー ----

    async def list_users(
        self,
        *,
        q: Optional[str] = None,
        plan: Optional[str] = None,
        status: Optional[str] = None,
    ) -> Dict[str, Any]:
        """ユーザー一覧（非PII要約＋当日利用回数）を返す。"""
        return await self.admin_user_repository.list_users(
            q=q,
            plan=plan,
            status=status,
        )

    async def get_user_detail(self, *, user_id: str, actor: str) -> Optional[Dict[str, Any]]:
        """ユーザー詳細（PII含む）を返し、閲覧を監査する。"""
        detail = await self.admin_user_repository.get_user_detail(user_id)
        if detail is not None:
            await self._audit(
                actor=actor,
                action="user.view",
                target_type="users",
                target_id=user_id,
            )
        return detail

    async def change_user_plan(
        self,
        *,
        user_id: str,
        plan: str,
        actor: str,
    ) -> None:
        """プラン変更（plan_override）を行い、監査へ記録する。

        freeを選択した場合はplan_overrideを解除する（Stripe契約は常に優先）。
        """
        if plan not in VALID_PLANS:
            raise ValueError("invalid_plan")
        detail = await self.admin_user_repository.get_user_detail(user_id)
        if detail is None:
            raise LookupError("user_not_found")
        before = (detail.get("plan_override") or {}).get("plan") or "free"
        await self.admin_user_repository.set_plan_override(
            user_id=user_id,
            plan=None if plan == "free" else plan,
            expires_at=None,
            source="admin",
        )
        await self._audit(
            actor=actor,
            action="user.plan_change",
            target_type="users",
            target_id=user_id,
            detail=f"before={before} after={plan}",
        )

    async def deactivate_user(self, *, user_id: str, reason: str, actor: str) -> None:
        """ユーザーを無効化し、監査へ記録する。"""
        if not reason or not reason.strip():
            raise ValueError("reason_required")
        detail = await self.admin_user_repository.get_user_detail(user_id)
        if detail is None:
            raise LookupError("user_not_found")
        await self.admin_user_repository.deactivate(user_id=user_id)
        await self._audit(
            actor=actor,
            action="user.deactivate",
            target_type="users",
            target_id=user_id,
            detail=f"reason={reason.strip()}",
        )

    async def create_free_user(
        self, *, line_user_id: str, actor: str
    ) -> Dict[str, Any]:
        """LINE user ID直指定でfreeユーザーを作成する（実在確認付き）。"""
        if not line_user_id.startswith("U") or len(line_user_id) < 10:
            raise ValueError("invalid_line_user_id")
        existing = await self.user_repository.find_by_line_user_id(line_user_id)
        if existing:
            raise ValueError("user_already_exists")
        try:
            profile = await (await self._line_client()).get_profile(line_user_id)
            display_name = profile.get("displayName", "")
        except Exception as exc:
            logger.warning(
                "LINE profile check failed: error_type=%s",
                type(exc).__name__,
            )
            raise ValueError("line_profile_not_found") from exc
        user = await self.user_repository.create_line_user(
            line_user_id=line_user_id,
            display_name=display_name,
        )
        await self._audit(
            actor=actor,
            action="user.create_free",
            target_type="users",
            target_id=user.get("id"),
        )
        return {"id": user.get("id"), "display_name": display_name, "plan": "free"}

    # ---- クーポン ----

    async def issue_coupon(
        self,
        *,
        actor: str,
        kind: str,
        plan: Optional[str] = None,
        duration_days: Optional[int] = None,
        bonus_free_messages: Optional[int] = None,
        max_redemptions: int = 1,
        expires_at: Optional[datetime] = None,
        note: Optional[str] = None,
    ) -> Dict[str, Any]:
        """クーポンを発行する。平文コードは応答にのみ載せる。"""
        result = await self.coupon_service.issue(
            kind=kind,
            plan=plan,
            duration_days=duration_days,
            bonus_free_messages=bonus_free_messages,
            max_redemptions=max_redemptions,
            expires_at=expires_at,
            created_by=actor,
            note=note,
        )
        await self._audit(
            actor=actor,
            action="coupon.issue",
            target_type="coupons",
            target_id=result["coupon"]["id"],
            detail=f"kind={kind}",
        )
        return result

    async def list_coupons(self) -> List[Dict[str, Any]]:
        """クーポン一覧を返す。"""
        return await self.coupon_service.coupon_repository.list()

    async def revoke_coupon(self, *, coupon_id: str, actor: str) -> bool:
        """クーポンを失効する。"""
        result = await self.coupon_service.coupon_repository.revoke(coupon_id)
        if result:
            await self._audit(
                actor=actor,
                action="coupon.revoke",
                target_type="coupons",
                target_id=coupon_id,
            )
        return result

    # ---- 会話・要望・監査・集計 ----

    async def list_conversations(self, *, limit: int = 100) -> Dict[str, Any]:
        """会話メタデータ（本文なし）を返す。"""
        return await self.conversation_repository.list_metadata(limit=limit)

    async def list_feedback(
        self, *, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """要望一覧を返す。"""
        return await self.feedback_repository.list(status=status)

    async def update_feedback_status(
        self,
        *,
        feedback_id: str,
        status: str,
        admin_note: Optional[str],
        actor: str,
    ) -> Optional[Dict[str, Any]]:
        """要望の対応ステータスを更新し、監査へ記録する。"""
        result = await self.feedback_repository.update_status(
            feedback_id,
            status=status,
            admin_note=admin_note,
            handled_by=actor,
        )
        if result is not None:
            await self._audit(
                actor=actor,
                action="feedback.status",
                target_type="feedback",
                target_id=feedback_id,
                detail=f"status={status}",
            )
        return result

    async def list_audit_logs(self, *, limit: int = 100) -> List[Dict[str, Any]]:
        """監査ログ一覧を返す。"""
        return await self.audit_repository.list(limit=limit)

    async def get_stats(self, *, days: int = 30) -> Dict[str, Any]:
        """日次統計の範囲集計を返す。"""
        if not 1 <= days <= 365:
            raise ValueError("invalid_days")
        daily = await self.stats_repository.get_range(days)
        totals: Dict[str, int] = {}
        for item in daily:
            for key in (
                "message_count",
                "active_user_count",
                "denied_by_limit",
                "coupon_redemptions",
                "coupon_failed_attempts",
                "feedback_count",
            ):
                totals[key] = totals.get(key, 0) + int(item.get(key, 0) or 0)
        return {"daily": daily, "totals": totals, "days": days}

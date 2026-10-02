"""LINE経路のクーポン・要望・プラン上書き・動的上限のテスト。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services.coupon_service import generate_coupon_code
from app.services.feedback_service import FeedbackService
from app.services.line_service import LineService


@pytest.fixture
def flow_service(monkeypatch) -> LineService:
    """新経路の依存をモックしたLineServiceを返す。"""
    line_client = MagicMock()
    line_client.reply_message = AsyncMock(return_value={})
    line_client.get_profile = AsyncMock(
        return_value={"displayName": "テストユーザー", "userId": "U_test123"}
    )

    user_repo = MagicMock()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "display_name": "テストユーザー",
        "is_active": True,
        "subscription_plan": "free",
    })
    user_repo.create_line_user = AsyncMock()

    rag_permission_repo = MagicMock()
    rag_permission_repo.get_by_plan = AsyncMock(return_value=None)

    usage_repo = MagicMock()
    usage_repo.increment_with_limit_check = AsyncMock(return_value={
        "success": True,
        "current_count": 1,
        "remaining": 2,
        "message": "ok",
    })

    plan_settings_repo = MagicMock()
    plan_settings_repo.get_published_daily_limit = AsyncMock(return_value=None)

    feedback_service = MagicMock()
    feedback_service.handle_pending_message = AsyncMock(return_value=None)

    stats_repo = MagicMock()
    stats_repo.increment_message_count = AsyncMock()
    stats_repo.increment_denied_by_limit = AsyncMock()
    stats_repo.increment_coupon_redemption = AsyncMock()
    stats_repo.increment_coupon_failure = AsyncMock()
    stats_repo.increment_feedback = AsyncMock()
    stats_repo.record_active_user = AsyncMock()

    service = LineService(line_client=line_client)
    monkeypatch.setattr(service, "_get_user_repository", lambda db=None: user_repo)
    monkeypatch.setattr(
        service,
        "_get_rag_permission_repository",
        lambda: rag_permission_repo,
    )
    monkeypatch.setattr(
        "app.repositories.firestore_usage_repository.FirestoreUsageRepository",
        lambda: usage_repo,
    )
    monkeypatch.setattr(
        "app.repositories.firestore_plan_settings_repository.FirestorePlanSettingsRepository",
        lambda: plan_settings_repo,
    )
    monkeypatch.setattr(
        "app.services.feedback_service.FeedstoreService_placeholder",
        lambda: feedback_service,
        raising=False,
    )
    monkeypatch.setattr(
        "app.services.feedback_service.FeedbackService",
        lambda: feedback_service,
    )
    monkeypatch.setattr(
        "app.repositories.firestore_admin_stats_repository.FirestoreAdminStatsRepository",
        lambda: stats_repo,
    )
    service._test_plan_settings_repo = plan_settings_repo
    service._test_usage_repo = usage_repo
    service._test_feedback_service = feedback_service
    return service


def _message_event(text: str) -> dict:
    """テキストメッセージイベントを返す。"""
    return {
        "type": "message",
        "replyToken": "reply-token",
        "source": {"userId": "U_test123"},
        "message": {"type": "text", "text": text},
    }


@pytest.mark.asyncio
async def test_coupon_message_redeems_without_usage(flow_service) -> None:
    """クーポンメッセージは回数を消費せず引き換え結果を返すこと。"""
    from app.services import coupon_service as coupon_module

    coupon_service = MagicMock()
    coupon_service.redeem = AsyncMock(
        return_value={
            "status": "granted",
            "kind": "plan_grant",
            "message": "クーポンを適用しました。",
        }
    )
    original = coupon_module.CouponService
    coupon_module.CouponService = lambda: coupon_service
    try:
        result = await flow_service.process_webhook_event(_message_event("クーポン ABC123"))
    finally:
        coupon_module.CouponService = original

    assert result["status"] == "processed"
    assert result["action"] == "coupon_redeem"
    flow_service._test_usage_repo.increment_with_limit_check.assert_not_awaited()
    flow_service.client.reply_message.assert_awaited_once()


@pytest.mark.asyncio
async def test_feedback_pending_message_is_recorded(flow_service) -> None:
    """受付モード中のメッセージを要望として処理すること。"""
    flow_service._test_feedback_service.handle_pending_message = AsyncMock(
        return_value={"reply": "要望を受け付けました。", "saved": True}
    )

    result = await flow_service.process_webhook_event(_message_event("もっと短くしてほしい"))

    assert result["action"] == "feedback_saved"
    flow_service._test_feedback_service.handle_pending_message.assert_awaited_once()
    flow_service._test_usage_repo.increment_with_limit_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_feedback_entry_text_starts_pending(flow_service) -> None:
    """「要望を送る」入力で受付モードを開始すること。"""
    flow_service._test_feedback_service.start_pending = AsyncMock(
        return_value="この後のメッセージ1通を要望として受け付けます。"
    )

    result = await flow_service.process_webhook_event(_message_event("要望を送る"))

    assert result["action"] == "feedback_start"
    flow_service._test_feedback_service.start_pending.assert_awaited_once_with(
        user_id="user-123"
    )


@pytest.mark.asyncio
async def test_plan_override_upgrades_free_user(flow_service, monkeypatch) -> None:
    """期限内有効なplan_overrideでbasicのコーパスと上限を使うこと。"""
    user_repo = flow_service._get_user_repository()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "display_name": "テストユーザー",
        "is_active": True,
        "subscription_plan": "free",
        "plan_override": {
            "plan": "basic",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(days=5)
            ).isoformat(),
            "source": "coupon",
        },
    })
    rag_repo = flow_service._get_rag_permission_repository()
    flow_service._test_plan_settings_repo.get_published_daily_limit = AsyncMock(
        return_value=120
    )

    result = await flow_service.process_webhook_event(_message_event("通常の質問"))

    assert result["status"] == "processed"
    assert result["plan"] == "basic"
    assert result["daily_limit"] == 120
    rag_repo.get_by_plan.assert_awaited_once_with("basic")
    flow_service._test_usage_repo.increment_with_limit_check.assert_awaited_once_with(
        "user-123", "basic", 120
    )


@pytest.mark.asyncio
async def test_service_override_resolves_to_pro(flow_service) -> None:
    """無期限serviceのplan_overrideをpro相当（コーパス・上限）で解決すること。"""
    user_repo = flow_service._get_user_repository()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "is_active": True,
        "subscription_plan": "free",
        "plan_override": {
            "plan": "service",
            "expires_at": None,
            "source": "service_invite",
        },
    })
    rag_repo = flow_service._get_rag_permission_repository()
    flow_service._test_plan_settings_repo.get_published_daily_limit = AsyncMock(
        return_value=500
    )

    result = await flow_service.process_webhook_event(_message_event("通常の質問"))

    assert result["status"] == "processed"
    assert result["plan"] == "pro"
    rag_repo.get_by_plan.assert_awaited_once_with("pro")
    flow_service._test_usage_repo.increment_with_limit_check.assert_awaited_once_with(
        "user-123", "pro", 500
    )


@pytest.mark.asyncio
async def test_stripe_plan_wins_over_override(flow_service) -> None:
    """Stripe契約中のプランをplan_overrideより優先すること。"""
    user_repo = flow_service._get_user_repository()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "is_active": True,
        "subscription_plan": "pro",
        "plan_override": {
            "plan": "basic",
            "expires_at": (
                datetime.now(timezone.utc) + timedelta(days=5)
            ).isoformat(),
        },
    })

    result = await flow_service.process_webhook_event(_message_event("通常の質問"))

    assert result["plan"] == "pro"


@pytest.mark.asyncio
async def test_expired_override_is_ignored(flow_service) -> None:
    """期限切れのplan_overrideを無視すること。"""
    user_repo = flow_service._get_user_repository()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "is_active": True,
        "subscription_plan": "free",
        "plan_override": {
            "plan": "pro",
            "expires_at": (
                datetime.now(timezone.utc) - timedelta(days=1)
            ).isoformat(),
        },
    })

    result = await flow_service.process_webhook_event(_message_event("通常の質問"))

    assert result["plan"] == "free"


@pytest.mark.asyncio
async def test_plan_settings_failure_falls_back_to_default(flow_service) -> None:
    """plan_settings読取失敗時は3/100/500の既定値へ戻すこと。"""
    flow_service._test_plan_settings_repo.get_published_daily_limit = AsyncMock(
        side_effect=RuntimeError("firestore down")
    )

    result = await flow_service.process_webhook_event(_message_event("通常の質問"))

    assert result["status"] == "processed"
    assert result["daily_limit"] == 3


@pytest.mark.asyncio
async def test_postback_feedback_start(flow_service) -> None:
    """postbackのfeedback_startで受付モードを開始すること。"""
    flow_service._test_feedback_service.start_pending = AsyncMock(
        return_value="この後のメッセージ1通を要望として受け付けます。"
    )
    event = {
        "type": "postback",
        "replyToken": "reply-token",
        "source": {"userId": "U_test123"},
        "postback": {"data": "action=feedback_start"},
    }

    result = await flow_service.process_webhook_event(event)

    assert result["status"] == "processed"
    flow_service._test_feedback_service.start_pending.assert_awaited_once_with(
        user_id="user-123"
    )

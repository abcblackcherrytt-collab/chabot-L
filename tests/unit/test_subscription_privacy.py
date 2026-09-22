"""Stripeへ送信するユーザー情報の最小化を検証する。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.services import subscription_service as subscription_module
from app.services.subscription_service import SubscriptionService


@pytest.mark.asyncio
async def test_checkout_does_not_send_line_user_id_to_stripe(monkeypatch) -> None:
    """Stripe metadataへLINE固有識別子を複製しないこと。"""
    monkeypatch.setattr(
        subscription_module,
        "get_plan_config",
        lambda plan: {"price_id": "price-test"},
    )
    monkeypatch.setattr(
        subscription_module,
        "get_checkout_urls",
        lambda: {"success_url": "https://example.com/s", "cancel_url": "https://example.com/c"},
    )
    stripe_client = MagicMock()
    stripe_client.create_customer = AsyncMock(return_value={"id": "cus-test"})
    stripe_client.create_checkout_session = AsyncMock(
        return_value={"url": "https://checkout.stripe.com/c/pay/test"}
    )
    user_repository = MagicMock()
    user_repository.find_by_id = AsyncMock(
        return_value={
            "id": "internal-user",
            "line_user_id": "U-sensitive",
            "email": "user@example.com",
            "display_name": "利用者",
        }
    )
    user_repository.update_stripe_customer_id = AsyncMock()
    service = SubscriptionService.__new__(SubscriptionService)
    service.stripe_client = stripe_client
    service.user_repo = user_repository

    await service.create_checkout_session("internal-user", "basic")

    customer_metadata = stripe_client.create_customer.call_args.kwargs["metadata"]
    checkout_metadata = stripe_client.create_checkout_session.call_args.kwargs["metadata"]
    assert customer_metadata == {"user_id": "internal-user"}
    assert checkout_metadata == {"user_id": "internal-user", "plan": "basic"}
    assert "U-sensitive" not in str(stripe_client.mock_calls)

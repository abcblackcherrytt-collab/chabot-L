"""LINE登録リンクからStripe Checkoutへ遷移する導線のテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import subscription as subscription_api
from app.core.auth_cookies import REFRESH_TOKEN_COOKIE_NAME
from app.server import app


@pytest.fixture
def checkout_service() -> MagicMock:
    """Checkout URLを返すSubscriptionServiceモック。"""
    service = MagicMock()
    service.create_checkout_session = AsyncMock(
        return_value="https://checkout.stripe.com/c/pay/test-session"
    )
    return service


@pytest.mark.asyncio
async def test_checkout_link_shows_preparing_page_without_price_id(
    monkeypatch,
    checkout_service,
) -> None:
    """Price ID未設定中は外部APIを呼ばず準備中画面を返すこと。"""
    monkeypatch.setattr(
        subscription_api,
        "get_plan_config",
        lambda plan: {"price_id": None},
    )
    app.dependency_overrides[subscription_api.get_subscription_service] = (
        lambda: checkout_service
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/subscription/checkout/basic")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "決済ページを準備中" in response.text
    checkout_service.create_checkout_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_checkout_link_starts_line_login_when_session_is_missing(
    monkeypatch,
    checkout_service,
) -> None:
    """Price設定後にセッションがなければCheckout復帰先付きでLINE Loginへ進むこと。"""
    monkeypatch.setattr(
        subscription_api,
        "get_plan_config",
        lambda plan: {"price_id": "price_later"},
    )
    app.dependency_overrides[subscription_api.get_subscription_service] = (
        lambda: checkout_service
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get(
                "/api/v1/subscription/checkout/basic",
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    assert response.headers["location"].startswith("/api/v1/auth/line?")
    assert "subscription%2Fcheckout%2Fbasic" in response.headers["location"]


@pytest.mark.asyncio
async def test_authenticated_checkout_link_redirects_to_stripe(
    monkeypatch,
    checkout_service,
) -> None:
    """保存済みセッションを更新し、実ユーザーIDでStripeへ遷移すること。"""
    monkeypatch.setattr(
        subscription_api,
        "get_plan_config",
        lambda plan: {"price_id": "price_later"},
    )
    auth_service = MagicMock()
    auth_service.refresh = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
    )
    monkeypatch.setattr(
        subscription_api,
        "FirestoreAuthService",
        lambda: auth_service,
    )
    monkeypatch.setattr(
        subscription_api,
        "decode_token",
        lambda token: {"sub": "real-user-id"},
    )
    app.dependency_overrides[subscription_api.get_subscription_service] = (
        lambda: checkout_service
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            client.cookies.set(
                REFRESH_TOKEN_COOKIE_NAME,
                "saved-refresh",
                path="/api/v1",
            )
            response = await client.get(
                "/api/v1/subscription/checkout/pro",
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 303
    assert response.headers["location"].startswith("https://checkout.stripe.com/")
    auth_service.refresh.assert_awaited_once_with("saved-refresh")
    checkout_service.create_checkout_session.assert_awaited_once_with(
        user_id="real-user-id",
        plan="pro",
    )
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=new-refresh" in response.headers["set-cookie"]

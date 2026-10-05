"""LINE登録リンクからStripe Checkoutへ遷移する導線のテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import subscription as subscription_api
from app.clients.stripe import StripeError
from app.core.auth_cookies import REFRESH_TOKEN_COOKIE_NAME
from app.server import app


@pytest.mark.asyncio
async def test_plan_selection_page_has_clear_basic_and_pro_cards() -> None:
    """プラン選択画面に両プランとStripe導線が表示されること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "あなたに合うプランを選ぶ" in response.text
    assert "ベーシック" in response.text
    assert "プロ" in response.text
    assert "/api/v1/subscription/checkout/basic" in response.text
    assert "/api/v1/subscription/checkout/pro" in response.text
    assert "499円" in response.text
    assert "999円" in response.text
    assert "/api/v1/subscription/select.css" in response.text
    assert "<style>" not in response.text


@pytest.mark.asyncio
async def test_plan_selection_stylesheet_is_served_same_origin() -> None:
    """CSPのdefault-src 'self'制約下でもスタイルが読み込めること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/subscription/select.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert ".plan" in response.text
    assert "prefers-reduced-motion" in response.text


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


@pytest.mark.asyncio
async def test_authenticated_checkout_link_shows_preparing_page_on_stripe_error(
    monkeypatch,
    checkout_service,
) -> None:
    """Stripe側でCheckout作成が失敗した場合も生の500ではなく案内画面を返すこと。"""
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
    checkout_service.create_checkout_session = AsyncMock(
        side_effect=StripeError("checkout failed")
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
                "/api/v1/subscription/checkout/basic",
                follow_redirects=False,
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 503
    assert "決済ページを準備中" in response.text


@pytest.mark.asyncio
async def test_legacy_checkout_api_requires_line_session(
    monkeypatch,
    checkout_service,
) -> None:
    """旧POST Checkout APIが固定ユーザーではなく認証を必須にすること。"""
    monkeypatch.setattr(subscription_api, "validate_plan_availability", lambda plan: True)
    app.dependency_overrides[subscription_api.get_subscription_service] = (
        lambda: checkout_service
    )
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.post(
                "/api/v1/subscription/checkout/create",
                json={"plan": "basic"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 401
    checkout_service.create_checkout_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_legacy_checkout_api_uses_authenticated_user(
    monkeypatch,
    checkout_service,
) -> None:
    """旧POST Checkout APIも実認証ユーザーIDを使用すること。"""
    monkeypatch.setattr(subscription_api, "validate_plan_availability", lambda plan: True)
    auth_service = MagicMock()
    auth_service.refresh = AsyncMock(return_value={
        "access_token": "new-access",
        "refresh_token": "new-refresh",
    })
    monkeypatch.setattr(subscription_api, "FirestoreAuthService", lambda: auth_service)
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
            response = await client.post(
                "/api/v1/subscription/checkout/create",
                json={"plan": "basic"},
            )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    checkout_service.create_checkout_session.assert_awaited_once_with(
        user_id="real-user-id",
        plan="basic",
    )
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=new-refresh" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_plan_selection_page_lists_both_checkout_links() -> None:
    """選択画面がbasic/pro両方の登録導線と注意書きを表示すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "/api/v1/subscription/checkout/basic" in response.text
    assert "/api/v1/subscription/checkout/pro" in response.text
    assert "ベーシックプラン" in response.text
    assert "プロプラン" in response.text
    assert "499" in response.text
    assert "999" in response.text
    assert "Stripe" in response.text
    assert response.headers["cache-control"] == "no-store"


def _plan_selection_auth_mocks(
    monkeypatch,
    user: dict,
) -> None:
    """選択画面の現在プラン解決に必要な認証・ユーザー取得をモックする。"""
    auth_service = MagicMock()
    auth_service.refresh = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
        }
    )
    user_repo = MagicMock()
    user_repo.find_by_id = AsyncMock(return_value=user)
    monkeypatch.setattr(subscription_api, "FirestoreAuthService", lambda: auth_service)
    monkeypatch.setattr(
        subscription_api, "FirestoreUserRepository", lambda: user_repo
    )
    monkeypatch.setattr(
        subscription_api,
        "decode_token",
        lambda token: {"sub": "real-user-id"},
    )


@pytest.mark.asyncio
async def test_plan_selection_page_keeps_both_plans_without_session() -> None:
    """未ログインでも選択画面は壊れず、現在プラン表示を出さないこと。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "現在のプラン" not in response.text
    assert "href='/api/v1/subscription/checkout/basic'" in response.text
    assert "href='/api/v1/subscription/checkout/pro'" in response.text
    assert "aria-disabled" not in response.text


@pytest.mark.asyncio
async def test_plan_selection_page_disables_registered_basic_plan(
    monkeypatch,
) -> None:
    """basic登録済みユーザーには現在プランを表示し、同一プランを選択不可にすること。"""
    _plan_selection_auth_mocks(
        monkeypatch,
        {"id": "real-user-id", "subscription_plan": "basic", "is_active": True},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(
            REFRESH_TOKEN_COOKIE_NAME,
            "saved-refresh",
            path="/api/v1",
        )
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "現在のプラン：<strong>ベーシックプラン</strong>" in response.text
    assert "ご利用中のプラン" in response.text
    assert "aria-disabled='true'" in response.text
    assert "href='/api/v1/subscription/checkout/basic'" not in response.text
    assert "href='/api/v1/subscription/checkout/pro'" in response.text
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=new-refresh" in response.headers["set-cookie"]


@pytest.mark.asyncio
async def test_plan_selection_page_disables_registered_pro_plan(
    monkeypatch,
) -> None:
    """pro登録済みユーザーはproを選択不可にし、basicへの変更導線を残すこと。"""
    _plan_selection_auth_mocks(
        monkeypatch,
        {"id": "real-user-id", "subscription_plan": "pro", "is_active": True},
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(
            REFRESH_TOKEN_COOKIE_NAME,
            "saved-refresh",
            path="/api/v1",
        )
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "現在のプラン：<strong>プロプラン</strong>" in response.text
    assert "href='/api/v1/subscription/checkout/pro'" not in response.text
    assert "href='/api/v1/subscription/checkout/basic'" in response.text


@pytest.mark.asyncio
async def test_plan_selection_page_treats_service_override_as_pro(
    monkeypatch,
) -> None:
    """service権限ユーザーはpro相当として扱い、proの再選択をさせないこと。"""
    _plan_selection_auth_mocks(
        monkeypatch,
        {
            "id": "real-user-id",
            "subscription_plan": "free",
            "plan_override": {"plan": "service"},
            "is_active": True,
        },
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(
            REFRESH_TOKEN_COOKIE_NAME,
            "saved-refresh",
            path="/api/v1",
        )
        response = await client.get("/api/v1/subscription/select")

    assert response.status_code == 200
    assert "現在のプラン：<strong>プロプラン</strong>" in response.text
    assert "href='/api/v1/subscription/checkout/pro'" not in response.text
    assert "href='/api/v1/subscription/checkout/basic'" in response.text

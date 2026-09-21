"""HttpOnly Cookieを使用する認証セッションAPIのテスト。"""

from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import ValidationError

from app.api.v1 import auth as auth_api
from app.api.v1 import auth_line as auth_line_api
from app.core.auth_cookies import REFRESH_TOKEN_COOKIE_NAME
from app.core.config import Settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_token,
    verify_token_hash,
)
from app.server import app


def test_long_refresh_token_hash_avoids_bcrypt_limit() -> None:
    """72バイト超のRefresh Tokenを保存・検証できること。"""
    token = "header.payload.signature" * 20

    hashed = hash_token(token)

    assert hashed.startswith("sha256$")
    assert token not in hashed
    assert verify_token_hash(token, hashed) is True
    assert verify_token_hash(f"{token}x", hashed) is False


@pytest.mark.parametrize("token_factory", [create_access_token, create_refresh_token])
def test_jwt_rejects_pii_and_reserved_additional_claims(token_factory) -> None:
    """追加クレームからPIIや署名済み予約クレームを再注入できないこと。"""
    for protected_claim in ("email", "line_user_id", "sub", "exp", "type"):
        with pytest.raises(ValueError, match="Protected JWT claims"):
            token_factory(
                user_id="user-1",
                email="user@example.com",
                jti="token-1",
                additional_claims={protected_claim: "attacker-controlled"},
            )


def test_access_token_expiry_cannot_exceed_logout_window() -> None:
    """環境設定でもAccess Tokenを15分超へ延長できないこと。"""
    with pytest.raises(ValidationError, match="between 1 and 15 minutes"):
        Settings(_env_file=None, jwt_access_token_expire_minutes=16)


@pytest.mark.asyncio
async def test_line_login_uses_s256_pkce_and_temporary_cookies() -> None:
    """LINE Login開始時にS256 PKCEとcallback検証Cookieを設定すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/auth/line", follow_redirects=False)

    assert response.status_code == 303
    params = parse_qs(urlparse(response.headers["location"]).query)
    assert params["code_challenge_method"] == ["S256"]
    assert params["code_challenge"][0]
    assert "code_verifier" not in params
    set_cookies = "\n".join(response.headers.get_list("set-cookie")).lower()
    assert "line_login_state=" in set_cookies
    assert "line_code_verifier=" in set_cookies
    assert "line_login_nonce=" in set_cookies
    assert set_cookies.count("httponly") == 3


@pytest.mark.asyncio
async def test_line_login_preserves_safe_checkout_return_path() -> None:
    """Checkoutからログインした場合に安全な復帰先を短期Cookieへ保存すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/auth/line",
            params={"return_to": "/api/v1/subscription/checkout/basic"},
            follow_redirects=False,
        )

    set_cookies = "\n".join(response.headers.get_list("set-cookie")).lower()
    assert "line_login_return_to=" in set_cookies
    assert "/api/v1/auth" in set_cookies


@pytest.mark.asyncio
async def test_refresh_uses_cookie_rotates_it_and_hides_token(monkeypatch) -> None:
    """Cookieだけで更新でき、新Refresh TokenをJSONへ露出しないこと。"""
    service = MagicMock()
    service.refresh = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "token_type": "bearer",
            "expires_in": 900,
        }
    )
    monkeypatch.setattr(auth_api, "FirestoreAuthService", lambda: service)
    monkeypatch.setattr(
        auth_api,
        "decode_token",
        lambda token: {"provider": "line", "type": "refresh"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(
            REFRESH_TOKEN_COOKIE_NAME,
            "old-refresh",
            path="/api/v1",
        )
        response = await client.post("/api/v1/auth/refresh")

    assert response.status_code == 200
    assert response.json() == {
        "access_token": "new-access",
        "token_type": "bearer",
        "expires_in": 900,
    }
    service.refresh.assert_awaited_once_with("old-refresh")
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=new-refresh" in set_cookie
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "path=/api/v1" in set_cookie
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_refresh_keeps_legacy_body_client_compatible(monkeypatch) -> None:
    """既存APIクライアントはbodyトークンでも更新できること。"""
    service = MagicMock()
    service.refresh = AsyncMock(
        return_value={
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "token_type": "bearer",
            "expires_in": 900,
        }
    )
    monkeypatch.setattr(auth_api, "FirestoreAuthService", lambda: service)
    monkeypatch.setattr(
        auth_api,
        "decode_token",
        lambda token: {"provider": "line", "type": "refresh"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "legacy-refresh"},
        )

    assert response.status_code == 200
    assert response.json()["refresh_token"] == "new-refresh"
    service.refresh.assert_awaited_once_with("legacy-refresh")


@pytest.mark.asyncio
async def test_logout_uses_cookie_revokes_and_clears_it(monkeypatch) -> None:
    """ログアウトがCookieトークンを失効し、ブラウザCookieも削除すること。"""
    service = MagicMock()
    service.logout = AsyncMock(return_value=True)
    monkeypatch.setattr(auth_api, "FirestoreAuthService", lambda: service)
    monkeypatch.setattr(
        auth_api,
        "decode_token",
        lambda token: {"provider": "line", "type": "refresh"},
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set(
            REFRESH_TOKEN_COOKIE_NAME,
            "saved-refresh",
            path="/api/v1",
        )
        response = await client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    service.logout.assert_awaited_once_with("saved-refresh")
    set_cookie = response.headers["set-cookie"].lower()
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=" in set_cookie
    assert "max-age=0" in set_cookie


@pytest.mark.asyncio
async def test_line_login_callback_without_return_path_returns_html_not_tokens(
    monkeypatch,
) -> None:
    """復帰先Cookieを失った場合、トークンJSONではなく再案内HTMLを返すこと。"""
    import httpx

    class _TokenResponse:
        status_code = 200

        def json(self) -> dict:
            return {"id_token": "signed-id-token"}

    class _FakeAsyncClient:
        def __init__(self, *args, **kwargs) -> None:
            pass

        async def __aenter__(self) -> "_FakeAsyncClient":
            return self

        async def __aexit__(self, *exc_info) -> None:
            return None

        async def post(self, *args, **kwargs) -> _TokenResponse:
            return _TokenResponse()

    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    monkeypatch.setattr(
        auth_line_api,
        "verify_line_id_token",
        AsyncMock(
            return_value={
                "sub": "line-user-id",
                "name": "表示名",
                "nonce": "nonce",
            }
        ),
    )
    auth_service = MagicMock()
    auth_service.user_repository.find_by_line_user_id = AsyncMock(
        return_value={
            "id": "user-1",
            "is_active": True,
            "display_name": "表示名",
        }
    )
    auth_service.issue_tokens = AsyncMock(
        return_value={
            "access_token": "access",
            "refresh_token": "rotated-refresh",
            "token_type": "bearer",
            "expires_in": 900,
        }
    )
    monkeypatch.setattr(
        auth_line_api,
        "FirestoreAuthService",
        lambda: auth_service,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        client.cookies.set("line_login_state", "state123")
        client.cookies.set("line_code_verifier", "verifier")
        client.cookies.set("line_login_nonce", "nonce")
        response = await client.get(
            "/api/v1/auth/line/callback",
            params={"code": "auth-code", "state": "state123"},
        )

    assert response.status_code == 200
    assert "access_token" not in response.text
    assert "rotated-refresh" not in response.text
    assert "プラン登録リンク" in response.text
    assert f"{REFRESH_TOKEN_COOKIE_NAME}=rotated-refresh" in response.headers["set-cookie"]

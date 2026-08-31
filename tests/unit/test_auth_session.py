"""HttpOnly Cookieを使用する認証セッションAPIのテスト。"""

from urllib.parse import parse_qs, urlparse
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import auth as auth_api
from app.core.auth_cookies import REFRESH_TOKEN_COOKIE_NAME
from app.core.security import hash_token, verify_token_hash
from app.server import app


def test_long_refresh_token_hash_avoids_bcrypt_limit() -> None:
    """72バイト超のRefresh Tokenを保存・検証できること。"""
    token = "header.payload.signature" * 20

    hashed = hash_token(token)

    assert hashed.startswith("sha256$")
    assert token not in hashed
    assert verify_token_hash(token, hashed) is True
    assert verify_token_hash(f"{token}x", hashed) is False


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

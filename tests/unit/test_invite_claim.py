"""無料登録URL（招待）引き換え導線のテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.v1 import invite as invite_api
from app.server import app


class TestClaimToken:
    """クレームトークンのテスト。"""

    def test_roundtrip(self) -> None:
        """作成したトークンから招待IDを復元できること。"""
        token = invite_api._create_claim_token("inv-123")

        assert invite_api._verify_claim_token(token) == "inv-123"

    def test_rejects_tampering(self) -> None:
        """改ざんトークンを拒否すること。"""
        token = invite_api._create_claim_token("inv-123")
        tampered = token[:-1] + ("0" if token[-1] != "0" else "1")

        assert invite_api._verify_claim_token(tampered) is None

    def test_rejects_garbage(self) -> None:
        """不正形式を拒否すること。"""
        assert invite_api._verify_claim_token("not-a-token") is None


@pytest.mark.asyncio
async def test_invite_landing_and_script_are_served() -> None:
    """landingページとクレーム用スクリプトを配信すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        landing = await client.get("/api/v1/invite")
        script = await client.get("/api/v1/invite/claim.js")

    assert landing.status_code == 200
    assert "claim.js" in landing.text
    assert landing.headers["cache-control"] == "no-store"
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "replaceState" in script.text


@pytest.mark.asyncio
async def test_invite_session_sets_claim_cookie(monkeypatch) -> None:
    """有効トークンでクレームCookieを設定しLINE Login URLを返すこと。"""
    repository = MagicMock()
    repository.find_active_by_token_hash = AsyncMock(
        return_value={"id": "inv-1", "status": "unused"}
    )
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAdminInviteRepository",
        lambda: repository,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/invite/session",
            json={"token": "a" * 43},
        )

    assert response.status_code == 200
    assert response.json()["login_url"].startswith("/api/v1/auth/line")
    assert "return_to=/api/v1/invite/complete" in response.json()["login_url"]
    assert invite_api.CLAIM_COOKIE_NAME in response.cookies


@pytest.mark.asyncio
async def test_invite_session_rejects_unknown_token(monkeypatch) -> None:
    """未知・失効トークンを410で拒否すること。"""
    repository = MagicMock()
    repository.find_active_by_token_hash = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAdminInviteRepository",
        lambda: repository,
    )
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/invite/session",
            json={"token": "a" * 43},
        )

    assert response.status_code == 410


@pytest.mark.asyncio
async def test_invite_complete_requires_cookies() -> None:
    """Cookieなしの完了アクセスを案内ページで拒否すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/invite/complete")

    assert response.status_code == 200
    assert "完了できませんでした" in response.text


@pytest.mark.asyncio
async def test_invite_complete_consumes_invite(monkeypatch) -> None:
    """消費成功時に登録完了ページを返すこと。"""
    invite_repository = MagicMock()
    invite_repository.consume = AsyncMock(return_value=True)
    invite_repository.mark_user_registration = AsyncMock()
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAdminInviteRepository",
        lambda: invite_repository,
    )
    auth_service = MagicMock()
    auth_service.refresh = AsyncMock(
        return_value={
            "access_token": "access",
            "refresh_token": "rotated-refresh",
        }
    )
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAuthService",
        lambda: auth_service,
    )
    monkeypatch.setattr(
        "app.api.v1.invite.decode_token",
        lambda token: {"sub": "user-9"},
    )
    claim_token = invite_api._create_claim_token("inv-1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/invite/complete",
            cookies={
                invite_api.CLAIM_COOKIE_NAME: claim_token,
                "chabot_refresh_token": "valid-refresh",
            },
        )

    assert response.status_code == 200
    assert "登録が完了しました" in response.text
    invite_repository.consume.assert_awaited_once_with(
        invite_id="inv-1",
        user_id="user-9",
    )
    invite_repository.mark_user_registration.assert_awaited_once_with(
        invite_id="inv-1",
        user_id="user-9",
    )


@pytest.mark.asyncio
async def test_invite_complete_rejects_used_invite(monkeypatch) -> None:
    """使用済み招待の完了アクセスを拒否すること。"""
    invite_repository = MagicMock()
    invite_repository.consume = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAdminInviteRepository",
        lambda: invite_repository,
    )
    auth_service = MagicMock()
    auth_service.refresh = AsyncMock(
        return_value={"access_token": "access", "refresh_token": "rotated"}
    )
    monkeypatch.setattr(
        "app.api.v1.invite.FirestoreAuthService",
        lambda: auth_service,
    )
    monkeypatch.setattr(
        "app.api.v1.invite.decode_token",
        lambda token: {"sub": "user-9"},
    )
    claim_token = invite_api._create_claim_token("inv-1")
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/invite/complete",
            cookies={
                invite_api.CLAIM_COOKIE_NAME: claim_token,
                "chabot_refresh_token": "valid-refresh",
            },
        )

    assert response.status_code == 200
    assert "利用できません" in response.text

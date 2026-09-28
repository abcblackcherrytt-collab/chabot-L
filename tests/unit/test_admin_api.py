"""管理APIの認証・CSRF・ルート分離テスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

import app.admin_api as admin_api_module
from app.admin_server import create_admin_app
from app.core.config import settings
from app.server import app as public_app


DEV_EMAIL = "admin@example.com"


@pytest.fixture
def dev_admin_app(monkeypatch) -> MagicMock:
    """devモードで認証を通す管理アプリを返す。"""
    monkeypatch.setattr(settings, "admin_auth_mode", "dev")
    monkeypatch.setattr(settings, "debug", True)
    monkeypatch.setattr(settings, "admin_dev_emails", DEV_EMAIL)
    monkeypatch.setattr(admin_api_module, "is_admin_allowed", AsyncMock(return_value=True))
    return create_admin_app(enabled=True)


@pytest.mark.asyncio
async def test_public_bot_does_not_expose_admin_api() -> None:
    """公開Botに管理APIパスが存在しないこと。"""
    paths = set(public_app.openapi()["paths"])

    assert not any(path.startswith("/api/v1/admin") for path in paths)


@pytest.mark.asyncio
async def test_admin_api_rejects_missing_identity(dev_admin_app) -> None:
    """未認証のセッション確立を401で拒否すること。"""
    transport = ASGITransport(app=dev_admin_app)
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/api/v1/admin/session")

    assert response.status_code == 401
    assert response.json()["detail"]["mode"] == "dev"


@pytest.mark.asyncio
async def test_admin_session_flow_and_csrf(dev_admin_app) -> None:
    """devモードでセッション確立し、CSRF必須の書込みを検証する。"""
    transport = ASGITransport(app=dev_admin_app)
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        session = await client.get(
            "/api/v1/admin/session",
            headers={"X-Admin-Dev-Email": DEV_EMAIL},
        )
        assert session.status_code == 200
        csrf_token = session.json()["csrf_token"]

        service = MagicMock()
        service.list_users = AsyncMock(return_value={"users": [], "count": 0})
        service.save_plan_draft = AsyncMock(return_value={"plan": "free"})
        original_service = admin_api_module._admin_service
        admin_api_module._admin_service = lambda: service
        try:
            listed = await client.get("/api/v1/admin/users")
            assert listed.status_code == 200

            no_csrf = await client.put(
                "/api/v1/admin/plan-settings/free",
                json={"daily_message_limit": 5, "base_revision": 0},
            )
            assert no_csrf.status_code == 403

            with_csrf = await client.put(
                "/api/v1/admin/plan-settings/free",
                headers={"X-CSRF-Token": csrf_token},
                json={"daily_message_limit": 5, "base_revision": 0},
            )
            assert with_csrf.status_code == 200
            service.save_plan_draft.assert_awaited_once_with(
                plan="free",
                daily_message_limit=5,
                base_revision=0,
                actor=DEV_EMAIL,
            )
        finally:
            admin_api_module._admin_service = original_service


@pytest.mark.asyncio
async def test_admin_api_returns_503_when_disabled() -> None:
    """無効な管理アプリはAPIも503で拒否すること。"""
    disabled_app = create_admin_app(enabled=False)
    transport = ASGITransport(app=disabled_app)
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/api/v1/admin/users")

    assert response.status_code == 503


@pytest.mark.asyncio
async def test_admin_api_rejects_csrf_mismatch(dev_admin_app) -> None:
    """CSRFトークン不一致の書込みを拒否すること。"""
    transport = ASGITransport(app=dev_admin_app)
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        session = await client.get(
            "/api/v1/admin/session",
            headers={"X-Admin-Dev-Email": DEV_EMAIL},
        )
        assert session.status_code == 200

        response = await client.put(
            "/api/v1/admin/plan-settings/free",
            headers={"X-CSRF-Token": "wrong-token"},
            json={"daily_message_limit": 5, "base_revision": 0},
        )

    assert response.status_code == 403

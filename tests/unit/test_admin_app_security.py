"""公開Botと管理アプリの分離・HTTP安全設定テスト。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin_server import create_admin_app
from app.server import app as public_app


def _paths(app) -> set[str]:
    """アプリに登録されたルートパスを返す。"""
    return {
        path
        for route in app.routes
        if (path := getattr(route, "path", None)) is not None
    }


def test_public_bot_does_not_contain_admin_routes() -> None:
    """公開Botへ管理画面・管理APIが混入していないこと。"""
    paths = set(public_app.openapi()["paths"])

    assert "/admin" not in paths
    assert not any(path.startswith("/api/v1/admin") for path in paths)
    assert "/api/v1/webhooks/line" in paths


def test_admin_app_does_not_contain_public_bot_routes_or_docs() -> None:
    """管理アプリへWebhook・一般認証・APIドキュメントを登録しないこと。"""
    admin_app = create_admin_app(enabled=True)
    paths = _paths(admin_app)

    assert "/admin" in paths
    assert "/health" in paths
    assert not any(path.startswith("/api/v1/webhooks") for path in paths)
    assert not any(path.startswith("/api/v1/auth") for path in paths)
    assert "/docs" not in paths
    assert "/redoc" not in paths
    assert "/openapi.json" not in paths


@pytest.mark.asyncio
async def test_admin_ui_is_disabled_by_default() -> None:
    """明示的に有効化しない限り管理画面を返さないこと。"""
    admin_app = create_admin_app(enabled=False)
    transport = ASGITransport(app=admin_app)

    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/admin")

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_admin_responses_prevent_cache_referrer_and_framing() -> None:
    """管理画面にキャッシュ・Referer・埋込み防止ヘッダーが付くこと。"""
    admin_app = create_admin_app(enabled=True)
    transport = ASGITransport(app=admin_app)

    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/admin")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["content-security-policy"] == "default-src 'self'"

"""管理UIの構成・CSP準拠・既定無効のテスト。"""

import pytest
from httpx import ASGITransport, AsyncClient

from app.admin_server import create_admin_app


@pytest.mark.asyncio
async def test_admin_shell_contains_all_sections_and_external_assets() -> None:
    """全管理セクションのHTMLが外部CSS/JSだけを読み込むこと。"""
    transport = ASGITransport(app=create_admin_app(enabled=True))
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/admin")

    assert response.status_code == 200
    for label in (
        "集計",
        "ユーザー",
        "回数上限設定",
        "クーポン",
        "無料登録URL",
        "会話保管",
        "要望",
        "監査ログ",
    ):
        assert label in response.text
    assert "/admin.css" in response.text
    assert "/admin.js" in response.text
    assert "<style>" not in response.text
    assert "style=" not in response.text
    assert "onload=" not in response.text


@pytest.mark.asyncio
async def test_admin_assets_are_served_same_origin() -> None:
    """CSPのdefault-src self制約下でCSS/JSが配信されること。"""
    transport = ASGITransport(app=create_admin_app(enabled=True))
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        css = await client.get("/admin.css")
        js = await client.get("/admin.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert "prefers-reduced-motion" in css.text
    assert "#536bd0" in css.text
    assert "44px" in css.text
    assert js.status_code == 200
    assert js.headers["content-type"].startswith("text/javascript")
    assert "/api/v1/admin" in js.text
    assert "refreshSection" in js.text
    # 保存型XSS対策と外部originへの通信なしを固定する（同一originのfetchのみ許可）。
    assert "innerHTML" not in js.text
    assert "http://" not in js.text
    assert "https://" not in js.text
    assert "XMLHttpRequest" not in js.text
    assert "eval(" not in js.text


@pytest.mark.asyncio
async def test_admin_ui_and_assets_are_disabled_by_default() -> None:
    """明示的に有効化しない限りUI資産も503になること。"""
    transport = ASGITransport(app=create_admin_app(enabled=False))
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        for path in ("/admin", "/admin.css", "/admin.js"):
            response = await client.get(path)
            assert response.status_code == 503
        health = await client.get("/health")
        assert health.status_code == 200


@pytest.mark.asyncio
async def test_admin_shell_does_not_embed_user_data() -> None:
    """初期HTMLへ実データ相当の全件埋め込みをしないこと。"""
    transport = ASGITransport(app=create_admin_app(enabled=True))
    async with AsyncClient(transport=transport, base_url="https://admin.test") as client:
        response = await client.get("/admin")

    assert "env-badge" not in response.text
    assert "u-00" not in response.text
    assert "lineId" not in response.text

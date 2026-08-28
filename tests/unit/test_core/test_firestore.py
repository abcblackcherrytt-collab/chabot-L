"""共有Firestoreクライアントのライフサイクルテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import firestore as firestore_module


@pytest.mark.asyncio
async def test_firestore_client_is_reused_and_closed(monkeypatch) -> None:
    """同一プロセスではADC解決とクライアント生成を1回に限定すること。"""
    client = MagicMock()
    client.close = AsyncMock()
    client_factory = MagicMock(return_value=client)
    monkeypatch.setattr(firestore_module, "_client", None)
    monkeypatch.setattr(firestore_module.firestore, "AsyncClient", client_factory)

    first = firestore_module.get_firestore_client_sync()
    second = await firestore_module.get_firestore_client()

    assert first is client
    assert second is client
    client_factory.assert_called_once()

    await firestore_module.close_firestore_client()
    client.close.assert_awaited_once()
    assert firestore_module._client is None


@pytest.mark.asyncio
async def test_app_lifespan_initializes_and_closes_shared_firestore(monkeypatch) -> None:
    """Firestore-only起動で共有クライアントをライフサイクル管理すること。"""
    from app import server

    get_client = AsyncMock(return_value=MagicMock())
    close_client = AsyncMock()
    line_service = MagicMock()
    line_service.client.close = AsyncMock()
    monkeypatch.setattr(server.settings, "database_backend", "firestore")
    monkeypatch.setattr(server, "get_firestore_client", get_client)
    monkeypatch.setattr(server, "close_firestore_client", close_client)
    monkeypatch.setattr(server, "RAGService", MagicMock(return_value=MagicMock()))
    monkeypatch.setattr(server, "LineService", MagicMock(return_value=line_service))

    async with server.app.router.lifespan_context(server.app):
        get_client.assert_awaited_once()

    line_service.client.close.assert_awaited_once()
    close_client.assert_awaited_once()

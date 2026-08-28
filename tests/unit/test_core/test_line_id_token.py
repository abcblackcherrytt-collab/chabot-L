"""LINE公式APIを使用するID Token検証のテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core import security


class _AsyncClientContext:
    """httpx.AsyncClientの最小非同期コンテキストモック。"""

    def __init__(self, client: MagicMock) -> None:
        self.client = client

    async def __aenter__(self) -> MagicMock:
        return self.client

    async def __aexit__(self, *args) -> None:
        return None


@pytest.mark.asyncio
async def test_verify_line_id_token_uses_official_verify_endpoint(monkeypatch) -> None:
    """署名検証をLINE公式endpointへ委譲し、nonce等を照合すること。"""
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "iss": "https://access.line.me",
        "aud": "channel-1",
        "sub": "U123",
        "nonce": "nonce-1",
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    monkeypatch.setattr(
        security.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientContext(client),
    )

    payload = await security.verify_line_id_token(
        "signed-token",
        "channel-1",
        "nonce-1",
    )

    assert payload is not None
    assert payload["sub"] == "U123"
    client.post.assert_awaited_once()
    assert client.post.await_args.args[0].endswith("/oauth2/v2.1/verify")
    assert client.post.await_args.kwargs["data"] == {
        "id_token": "signed-token",
        "client_id": "channel-1",
        "nonce": "nonce-1",
    }


@pytest.mark.asyncio
async def test_verify_line_id_token_rejects_nonce_mismatch(monkeypatch) -> None:
    """公式API応答でもnonceが一致しなければ拒否すること。"""
    response = MagicMock(status_code=200)
    response.json.return_value = {
        "iss": "https://access.line.me",
        "aud": "channel-1",
        "sub": "U123",
        "nonce": "different",
    }
    client = MagicMock()
    client.post = AsyncMock(return_value=response)
    monkeypatch.setattr(
        security.httpx,
        "AsyncClient",
        lambda **kwargs: _AsyncClientContext(client),
    )

    payload = await security.verify_line_id_token(
        "signed-token",
        "channel-1",
        "nonce-1",
    )

    assert payload is None

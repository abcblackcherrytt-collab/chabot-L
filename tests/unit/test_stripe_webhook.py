"""Stripe Webhook APIの再送・サイズ制限テスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from app.server import app


@pytest.mark.asyncio
async def test_stripe_webhook_returns_500_when_business_processing_fails(
    monkeypatch,
) -> None:
    """業務処理失敗時にStripeが再送できるHTTP 500を返すこと。"""
    stripe_client = MagicMock()
    stripe_client.verify_webhook_signature = MagicMock(return_value=True)
    stripe_service = MagicMock()
    stripe_service.process_webhook_event = AsyncMock(return_value=False)
    monkeypatch.setattr(
        "app.clients.stripe.StripeClient",
        lambda: stripe_client,
    )
    monkeypatch.setattr(
        "app.services.stripe_service.StripeService",
        lambda stripe_client: stripe_service,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/webhooks/stripe",
            content=b'{"id":"evt_1","type":"invoice.paid"}',
            headers={"stripe-signature": "test-signature"},
        )

    assert response.status_code == 500
    stripe_service.process_webhook_event.assert_awaited_once()


@pytest.mark.asyncio
async def test_stripe_webhook_returns_200_only_after_success(monkeypatch) -> None:
    """正常処理したイベントだけHTTP 200を返すこと。"""
    stripe_client = MagicMock()
    stripe_client.verify_webhook_signature = MagicMock(return_value=True)
    stripe_service = MagicMock()
    stripe_service.process_webhook_event = AsyncMock(return_value=True)
    monkeypatch.setattr(
        "app.clients.stripe.StripeClient",
        lambda: stripe_client,
    )
    monkeypatch.setattr(
        "app.services.stripe_service.StripeService",
        lambda stripe_client: stripe_service,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/webhooks/stripe",
            content=b'{"id":"evt_1","type":"invoice.paid"}',
            headers={"stripe-signature": "test-signature"},
        )

    assert response.status_code == 200
    assert response.json()["status"] == "processed"


@pytest.mark.asyncio
async def test_stripe_webhook_rejects_oversized_payload() -> None:
    """1MiBを超えるWebhook本文を署名検証前に拒否すること。"""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/v1/webhooks/stripe",
            content=b"x" * (1024 * 1024 + 1),
            headers={"stripe-signature": "test-signature"},
        )

    assert response.status_code == 413

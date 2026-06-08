"""
Unit tests for Stripe Service
Stripeサービスのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, MagicMock

from app.services.stripe_service import StripeService


class TestStripeService:
    """Stripeサービスのテストクラス"""

    @pytest.mark.asyncio
    async def test_create_customer_success(self, mock_stripe_customer):
        """
        顧客作成が成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.create_customer = AsyncMock(return_value=mock_stripe_customer)

        service = StripeService(stripe_client=mock_client)

        result = await service.create_customer(
            email="test@example.com",
            name="Test User",
            metadata={"user_id": "123"},
        )

        assert result["id"] == "cus_test123"
        assert result["email"] == "test@example.com"
        assert result["name"] == "Test User"
        mock_client.create_customer.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_subscription_success(self, mock_stripe_subscription):
        """
        サブスクリプション作成が成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.create_subscription = AsyncMock(return_value=mock_stripe_subscription)

        service = StripeService(stripe_client=mock_client)

        result = await service.create_subscription(
            customer_id="cus_test123",
            price_id="price_test123",
            payment_method_id="pm_test123",
            metadata={"user_id": "123"},
        )

        assert result["id"] == "sub_test123"
        assert result["status"] == "active"
        assert result["customer_id"] == "cus_test123"
        assert "latest_invoice" in result
        mock_client.create_subscription.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancel_subscription_success(self, mock_stripe_subscription):
        """
        サブスクリプションキャンセルが成功することをテスト
        """
        mock_subscription = MagicMock()
        mock_subscription.id = "sub_test123"
        mock_subscription.customer = "cus_test123"
        mock_subscription.status = "canceled"
        mock_subscription.canceled_at = 1234567890
        mock_subscription.cancel_at_period_end = True
        mock_subscription.current_period_end = 1234567890 + 2592000

        mock_client = AsyncMock()
        mock_client.cancel_subscription = AsyncMock(return_value=mock_subscription)

        service = StripeService(stripe_client=mock_client)

        result = await service.cancel_subscription("sub_test123")

        assert result["id"] == "sub_test123"
        assert result["status"] == "canceled"
        assert result["cancel_at_period_end"] is True
        mock_client.cancel_subscription.assert_called_once_with("sub_test123")

    @pytest.mark.asyncio
    async def test_get_subscription_success(self, mock_stripe_subscription):
        """
        サブスクリプション情報取得が成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.retrieve_subscription = AsyncMock(return_value=mock_stripe_subscription)

        service = StripeService(stripe_client=mock_client)

        result = await service.get_subscription("sub_test123")

        assert result["id"] == "sub_test123"
        assert result["status"] == "active"
        assert result["customer_id"] == "cus_test123"
        mock_client.retrieve_subscription.assert_called_once_with("sub_test123")

    @pytest.mark.asyncio
    async def test_get_customer_subscriptions_success(self):
        """
        顧客のサブスクリプション一覧取得が成功することをテスト
        """
        mock_customer = MagicMock()
        mock_customer.subscriptions = MagicMock()
        mock_customer.subscriptions.data = [
            MagicMock(id="sub_test123", status="active"),
            MagicMock(id="sub_test456", status="canceled"),
        ]

        mock_client = AsyncMock()
        mock_client.retrieve_customer = AsyncMock(return_value=mock_customer)

        service = StripeService(stripe_client=mock_client)

        result = await service.get_customer_subscriptions("cus_test123")

        assert len(result) == 2
        assert result[0]["id"] == "sub_test123"
        assert result[1]["id"] == "sub_test456"
        mock_client.retrieve_customer.assert_called_once_with("cus_test123")

    @pytest.mark.asyncio
    async def test_list_prices_success(self):
        """
        価格一覧取得が成功することをテスト
        """
        class MockPrice:
            def __init__(self, price_id):
                self.id = price_id
                self.product = "prod_test123"
                self.unit_amount = 1000
                self.currency = "jpy"
                self.recurring = type('obj', (object,), {
                    'interval': 'month',
                    'interval_count': 1,
                })()
                self.nickname = "Test Price"

        mock_prices = [
            MockPrice("price_test123"),
            MockPrice("price_test456"),
        ]

        mock_client = AsyncMock()
        mock_client.list_prices = AsyncMock(return_value=mock_prices)

        service = StripeService(stripe_client=mock_client)

        result = await service.list_prices()

        assert len(result) == 2
        assert result[0]["id"] == "price_test123"
        assert result[0]["currency"] == "jpy"
        assert result[0]["interval"] == "month"
        mock_client.list_prices.assert_called_once()

    def test_process_webhook_event_invoice_paid(self):
        """
        invoice.paid イベントが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "invoice.paid",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "in_test123",
                    "subscription": "sub_test123",
                    "amount": 1000,
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_called_once()

    def test_process_webhook_event_invoice_payment_failed(self):
        """
        invoice.payment_failed イベントが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "invoice.payment_failed",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "in_test123",
                    "subscription": "sub_test123",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_called_once()

    def test_process_webhook_event_subscription_created(self):
        """
        customer.subscription.created イベントが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "customer.subscription.created",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "sub_test123",
                    "customer": "cus_test123",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_called_once()

    def test_process_webhook_event_subscription_updated(self):
        """
        customer.subscription.updated イベントが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "customer.subscription.updated",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "sub_test123",
                    "status": "active",
                },
                "previous_attributes": {
                    "status": "trialing",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_called_once()

    def test_process_webhook_event_subscription_deleted(self):
        """
        customer.subscription.deleted イベントが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "customer.subscription.deleted",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "sub_test123",
                    "customer": "cus_test123",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_called_once()

    def test_process_webhook_event_already_processed(self):
        """
        既に処理済みのイベントがスキップされることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=True)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "invoice.paid",
            "created": 1234567890,
            "data": {
                "object": {
                    "id": "in_test123",
                    "subscription": "sub_test123",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_not_called()

    def test_process_webhook_event_missing_id(self):
        """
        IDがないイベントが適切に処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "type": "invoice.paid",
            "data": {
                "object": {
                    "id": "in_test123",
                }
            },
        }

        result = service.process_webhook_event(event)

        assert result is False
        mock_client.is_event_processed.assert_not_called()

    def test_process_webhook_event_unhandled_type(self):
        """
        不明なイベントタイプが適切に処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.is_event_processed = AsyncMock(return_value=False)
        mock_client.mark_event_processed = AsyncMock()

        service = StripeService(stripe_client=mock_client)

        event = {
            "id": "evt_test123",
            "type": "unhandled.event",
            "created": 1234567890,
            "data": {
                "object": {}
            },
        }

        result = service.process_webhook_event(event)

        assert result is True
        mock_client.mark_event_processed.assert_not_called()

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """
        ヘルスチェックが成功することをテスト
        """
        mock_prices = [
            MagicMock(id="price_test123"),
        ]

        mock_client = AsyncMock()
        mock_client.list_prices = AsyncMock(return_value=mock_prices)

        service = StripeService(stripe_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "healthy"
        assert result["service"] == "stripe"
        assert result["stripe_available"] is True
        assert result["prices_count"] == 1

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """
        ヘルスチェックが失敗した場合、適切なエラーレスポンスが返されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.list_prices = AsyncMock(side_effect=Exception("Connection error"))

        service = StripeService(stripe_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "unhealthy"
        assert result["service"] == "stripe"
        assert result["stripe_available"] is False
        assert "error" in result

"""
Unit tests for Stripe Client
Stripeクライアントのユニットテスト
"""

import pytest
from unittest.mock import MagicMock, patch
import stripe

from app.clients.stripe import StripeClient, StripeError


class TestStripeClient:
    """Stripeクライアントのテストクラス"""

    def test_verify_webhook_signature_success(self):
        """
        Webhook署名検証が成功することをテスト
        """
        with patch("app.clients.stripe.stripe.Webhook.construct_event") as mock_construct:
            mock_construct.return_value = {"id": "evt_test123"}

            client = StripeClient()
            payload = b'{"id": "evt_test123"}'
            signature_header = "t=1234567890,v1=test_signature"

            result = client.verify_webhook_signature(payload, signature_header)

            assert result is True
            mock_construct.assert_called_once()

    def test_verify_webhook_signature_invalid_payload(self):
        """
        無効なペイロードで署名検証が失敗することをテスト
        """
        with patch("app.clients.stripe.stripe.Webhook.construct_event") as mock_construct:
            mock_construct.side_effect = ValueError("Invalid payload")

            client = StripeClient()
            payload = b"invalid payload"
            signature_header = "t=1234567890,v1=test_signature"

            with pytest.raises(StripeError) as exc_info:
                client.verify_webhook_signature(payload, signature_header)

            assert "Invalid webhook payload" in str(exc_info.value)

    def test_verify_webhook_signature_invalid_signature(self):
        """
        無効な署名で署名検証が失敗することをテスト
        """
        with patch("app.clients.stripe.stripe.Webhook.construct_event") as mock_construct:
            mock_construct.side_effect = stripe.error.SignatureVerificationError(
                "Invalid signature",
                None,
                None,
            )

            client = StripeClient()
            payload = b'{"id": "evt_test123"}'
            signature_header = "t=1234567890,v1=invalid_signature"

            with pytest.raises(StripeError) as exc_info:
                client.verify_webhook_signature(payload, signature_header)

            assert "Invalid webhook signature" in str(exc_info.value)

    def test_is_event_processed(self):
        """
        イベントの処理済みチェックが正しく動作することをテスト
        """
        client = StripeClient()

        # 未処理のイベント
        assert client.is_event_processed("evt_test123") is False

        # イベントを処理済みとしてマーク
        client.mark_event_processed("evt_test123", {"processed_at": 1234567890})

        # 処理済みのイベント
        assert client.is_event_processed("evt_test123") is True

    def test_mark_event_processed(self):
        """
        イベントの処理済みマーキングが正しく動作することをテスト
        """
        client = StripeClient()
        event_data = {
            "event_type": "invoice.paid",
            "processed_at": 1234567890,
        }

        client.mark_event_processed("evt_test123", event_data)

        assert "evt_test123" in client._processed_events
        assert client._processed_events["evt_test123"] == event_data

    def test_clear_old_events(self):
        """
        古いイベントのクリアが正しく動作することをテスト
        """
        import datetime

        client = StripeClient()

        # 古いイベントを追加
        old_time = datetime.datetime.utcnow() - datetime.timedelta(hours=30)
        client.mark_event_processed(
            "evt_old123",
            {"processed_at": old_time}
        )

        # 新しいイベントを追加
        new_time = datetime.datetime.utcnow() - datetime.timedelta(hours=10)
        client.mark_event_processed(
            "evt_new123",
            {"processed_at": new_time}
        )

        # 24時間以上前のイベントをクリア
        cleared_count = client.clear_old_events(hours_old=24)

        assert cleared_count == 1
        assert "evt_old123" not in client._processed_events
        assert "evt_new123" in client._processed_events

    @patch("app.clients.stripe.stripe.Customer.create")
    def test_create_customer_success(self, mock_customer_create, mock_stripe_customer):
        """
        顧客作成が成功することをテスト
        """
        mock_customer_create.return_value = mock_stripe_customer

        client = StripeClient()
        customer = client.create_customer(
            email="test@example.com",
            name="Test User",
            metadata={"user_id": "123"},
        )

        assert customer.id == "cus_test123"
        assert customer.email == "test@example.com"
        assert customer.name == "Test User"
        mock_customer_create.assert_called_once()

    @patch("app.clients.stripe.stripe.Customer.create")
    def test_create_customer_error(self, mock_customer_create):
        """
        顧客作成エラーが適切に処理されることをテスト
        """
        mock_customer_create.side_effect = stripe.error.StripeError("Customer creation failed")

        client = StripeClient()

        with pytest.raises(StripeError) as exc_info:
            client.create_customer(email="test@example.com")

        assert "顧客作成エラー" in str(exc_info.value)

    @patch("app.clients.stripe.stripe.Subscription.create")
    def test_create_subscription_success(
        self,
        mock_subscription_create,
        mock_stripe_subscription
    ):
        """
        サブスクリプション作成が成功することをテスト
        """
        mock_subscription_create.return_value = mock_stripe_subscription

        client = StripeClient()
        subscription = client.create_subscription(
            customer_id="cus_test123",
            price_id="price_test123",
            payment_method_id="pm_test123",
            metadata={"user_id": "123"},
        )

        assert subscription.id == "sub_test123"
        assert subscription.status == "active"
        assert subscription.customer == "cus_test123"
        mock_subscription_create.assert_called_once()

    @patch("app.clients.stripe.stripe.Subscription.modify")
    def test_cancel_subscription_success(
        self,
        mock_subscription_modify,
        mock_stripe_subscription
    ):
        """
        サブスクリプションキャンセルが成功することをテスト
        """
        mock_stripe_subscription.cancel_at_period_end = True
        mock_subscription_modify.return_value = mock_stripe_subscription

        client = StripeClient()
        subscription = client.cancel_subscription("sub_test123")

        assert subscription.cancel_at_period_end is True
        mock_subscription_modify.assert_called_once_with(
            "sub_test123",
            cancel_at_period_end=True,
        )

    @patch("app.clients.stripe.stripe.Customer.retrieve")
    def test_retrieve_customer_success(self, mock_customer_retrieve, mock_stripe_customer):
        """
        顧客取得が成功することをテスト
        """
        mock_customer_retrieve.return_value = mock_stripe_customer

        client = StripeClient()
        customer = client.retrieve_customer("cus_test123")

        assert customer.id == "cus_test123"
        assert customer.email == "test@example.com"
        mock_customer_retrieve.assert_called_once_with("cus_test123")

    @patch("app.clients.stripe.stripe.Subscription.retrieve")
    def test_retrieve_subscription_success(
        self,
        mock_subscription_retrieve,
        mock_stripe_subscription
    ):
        """
        サブスクリプション取得が成功することをテスト
        """
        mock_subscription_retrieve.return_value = mock_stripe_subscription

        client = StripeClient()
        subscription = client.retrieve_subscription("sub_test123")

        assert subscription.id == "sub_test123"
        assert subscription.status == "active"
        mock_subscription_retrieve.assert_called_once_with("sub_test123")

    @patch("app.clients.stripe.stripe.Price.list")
    def test_list_prices_success(self, mock_price_list):
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

        mock_price_list.return_value.data = [
            MockPrice("price_test123"),
            MockPrice("price_test456"),
        ]

        client = StripeClient()
        prices = client.list_prices()

        assert len(prices) == 2
        assert prices[0].id == "price_test123"
        assert prices[1].id == "price_test456"
        mock_price_list.assert_called_once()

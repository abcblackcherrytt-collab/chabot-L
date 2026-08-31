"""
Unit tests for Stripe Service
Stripeサービスのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.stripe_service import StripeService


def _webhook_service(
    *,
    claim_result="claimed",
    user=None,
):
    """Firestore依存をモックしたWebhookサービスを返す。"""
    event_repository = MagicMock()
    event_repository.claim = AsyncMock(return_value=claim_result)
    event_repository.mark_completed = AsyncMock()
    event_repository.mark_failed = AsyncMock()
    user_repository = MagicMock()
    user_repository.find_by_stripe_customer_id = AsyncMock(return_value=user)
    user_repository.update_subscription_data = AsyncMock()
    line_service = MagicMock()
    line_service.send_subscription_notification = AsyncMock()
    service = StripeService(
        stripe_client=MagicMock(),
        event_repository=event_repository,
        user_repository=user_repository,
        line_service=line_service,
    )
    return service, event_repository, user_repository, line_service


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
        def make_subscription(sub_id, status, has_price):
            sub = MagicMock()
            sub.id = sub_id
            sub.status = status
            sub.current_period_start = 1234567890
            sub.current_period_end = 1234567890 + 2592000
            sub.cancel_at_period_end = False
            if has_price:
                item = MagicMock()
                item.price.id = "price_test123"
                sub.items.data = [item]
            else:
                sub.items.data = []
            return sub

        mock_subscriptions = MagicMock()
        mock_subscriptions.data = [
            make_subscription("sub_test123", "active", has_price=True),
            make_subscription("sub_test456", "canceled", has_price=False),
        ]

        mock_client = AsyncMock()
        mock_client.list_subscriptions = AsyncMock(return_value=mock_subscriptions)

        service = StripeService(stripe_client=mock_client)

        result = await service.get_customer_subscriptions("cus_test123")

        assert len(result) == 2
        assert result[0]["id"] == "sub_test123"
        assert result[0]["price_id"] == "price_test123"
        assert result[1]["id"] == "sub_test456"
        assert result[1]["price_id"] is None
        mock_client.list_subscriptions.assert_called_once_with(customer="cus_test123")

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

    @pytest.mark.asyncio
    async def test_process_webhook_event_invoice_paid_updates_firestore(self):
        """invoice.paidをFirestoreへ反映して完了マークすること。"""
        user = {"id": "user-123", "line_user_id": "U_test123"}
        service, events, users, _ = _webhook_service(user=user)
        event = {
            "id": "evt_paid",
            "type": "invoice.paid",
            "created": 1234567890,
            "data": {"object": {
                "id": "in_test123",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "period_start": 100,
                "period_end": 200,
            }},
        }

        assert await service.process_webhook_event(event) is True
        updates = users.update_subscription_data.await_args.args[1]
        assert updates["subscription_status"] == "active"
        assert updates["last_invoice_status"] == "paid"
        events.mark_completed.assert_awaited_once_with("evt_paid")

    @pytest.mark.asyncio
    async def test_process_webhook_event_payment_failed_updates_and_notifies(self):
        """支払い失敗を保存してLINE通知すること。"""
        user = {"id": "user-123", "line_user_id": "U_test123"}
        service, events, users, line = _webhook_service(user=user)
        event = {
            "id": "evt_failed",
            "type": "invoice.payment_failed",
            "created": 1234567890,
            "data": {"object": {
                "id": "in_test123",
                "customer": "cus_test123",
                "subscription": "sub_test123",
                "attempt_count": 2,
            }},
        }

        assert await service.process_webhook_event(event) is True
        updates = users.update_subscription_data.await_args.args[1]
        assert updates["subscription_status"] == "past_due"
        line.send_subscription_notification.assert_awaited_once()
        events.mark_completed.assert_awaited_once_with("evt_failed")

    @pytest.mark.asyncio
    async def test_subscription_created_and_updated_persist_full_state(self):
        """created/updatedでプラン・状態・請求期間を保存すること。"""
        user = {"id": "user-123", "line_user_id": "U_test123"}
        service, events, users, line = _webhook_service(user=user)
        subscription = {
            "id": "sub_test123",
            "customer": "cus_test123",
            "status": "active",
            "current_period_start": 100,
            "current_period_end": 200,
            "items": {"data": [{"price": {"id": "price_test_basic"}}]},
        }
        with patch("app.core.pricing.get_plan_from_price_id", return_value="basic"):
            created = {
                "id": "evt_created",
                "type": "customer.subscription.created",
                "created": 1,
                "data": {"object": subscription},
            }
            assert await service.process_webhook_event(created) is True
            updated = {
                "id": "evt_updated",
                "type": "customer.subscription.updated",
                "created": 2,
                "data": {"object": {**subscription, "status": "past_due"}},
            }
            assert await service.process_webhook_event(updated) is True

        first_updates = users.update_subscription_data.await_args_list[0].args[1]
        second_updates = users.update_subscription_data.await_args_list[1].args[1]
        assert first_updates["subscription_plan"] == "basic"
        assert second_updates["subscription_status"] == "past_due"
        line.send_subscription_notification.assert_awaited_once()
        assert events.mark_completed.await_count == 2

    @pytest.mark.asyncio
    async def test_subscription_deleted_returns_user_to_free(self):
        """解約イベントでfreeへ戻しサブスクリプションIDを消すこと。"""
        user = {"id": "user-123", "line_user_id": "U_test123"}
        service, events, users, line = _webhook_service(user=user)
        event = {
            "id": "evt_deleted",
            "type": "customer.subscription.deleted",
            "created": 1,
            "data": {"object": {
                "id": "sub_test123",
                "customer": "cus_test123",
            }},
        }

        assert await service.process_webhook_event(event) is True
        updates = users.update_subscription_data.await_args.args[1]
        assert updates["subscription_plan"] == "free"
        assert updates["stripe_subscription_id"] is None
        line.send_subscription_notification.assert_awaited_once()
        events.mark_completed.assert_awaited_once_with("evt_deleted")

    @pytest.mark.asyncio
    async def test_webhook_failure_is_retryable(self):
        """業務処理失敗時はfailedにして完了扱いしないこと。"""
        service, events, _, _ = _webhook_service(user=None)
        event = {
            "id": "evt_retry",
            "type": "customer.subscription.deleted",
            "created": 1,
            "data": {"object": {"id": "sub_1", "customer": "cus_1"}},
        }

        assert await service.process_webhook_event(event) is False
        events.mark_failed.assert_awaited_once_with("evt_retry", "handler_failed")
        events.mark_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_completed_webhook_is_skipped(self):
        """Firestoreで完了済みなら副作用を再実行しないこと。"""
        service, events, users, _ = _webhook_service(claim_result="completed")
        event = {"id": "evt_done", "type": "invoice.paid", "created": 1}

        assert await service.process_webhook_event(event) is True
        users.update_subscription_data.assert_not_awaited()
        events.mark_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_in_progress_webhook_returns_retryable_failure(self):
        """同時処理中の重複配信は非成功として再送させること。"""
        service, events, _, _ = _webhook_service(claim_result="in_progress")
        event = {"id": "evt_busy", "type": "invoice.paid", "created": 1}

        assert await service.process_webhook_event(event) is False
        events.mark_completed.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unhandled_webhook_is_recorded_completed(self):
        """未対応イベントも永続的に完了記録して再処理しないこと。"""
        service, events, _, _ = _webhook_service()
        event = {"id": "evt_unknown", "type": "unhandled.event", "created": 1}

        assert await service.process_webhook_event(event) is True
        events.mark_completed.assert_awaited_once_with("evt_unknown")

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

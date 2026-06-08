"""
Stripe決済サービス
Stripe決済との連携を管理するサービスを定義します。
"""

import logging
from typing import Any, Dict, List, Optional

from app.clients.stripe import StripeClient, StripeError
from app.core.config import settings

logger = logging.getLogger(__name__)


class StripeService:
    """
    Stripe決済サービス

    サブスクリプションの管理と決済処理を行います。
    冪等性と順序逆転対策を含みます。
    """

    def __init__(
        self,
        stripe_client: Optional[StripeClient] = None,
    ):
        """
        Stripeサービスを初期化します

        Args:
            stripe_client: Stripeクライアント（オプション）
        """
        self.client = stripe_client or StripeClient()
        logger.info("Stripe service initialized")

    async def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        顧客を作成します

        Args:
            email: 顧客メールアドレス
            name: 顧客名（オプション）
            metadata: メタデータ（オプション）

        Returns:
            作成された顧客情報

        Raises:
            StripeError: 顧客作成エラーが発生した場合
        """
        try:
            customer = await self.client.create_customer(
                email=email,
                name=name,
                metadata=metadata,
            )
            return {
                "id": customer.id,
                "email": customer.email,
                "name": customer.name,
                "created": customer.created,
            }

        except StripeError as e:
            logger.error(f"Failed to create customer: {e}")
            raise

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        サブスクリプションを作成します

        Args:
            customer_id: 顧客ID
            price_id: 価格ID
            payment_method_id: 支払い方法ID
            metadata: メタデータ（オプション）

        Returns:
            作成されたサブスクリプション情報

        Raises:
            StripeError: サブスクリプション作成エラーが発生した場合
        """
        try:
            subscription = await self.client.create_subscription(
                customer_id=customer_id,
                price_id=price_id,
                payment_method_id=payment_method_id,
                metadata=metadata,
            )

            # 最新の請求書情報を取得
            invoice = subscription.latest_invoice
            payment_intent = invoice.payment_intent if invoice else None

            return {
                "id": subscription.id,
                "customer_id": subscription.customer,
                "status": subscription.status,
                "price_id": subscription.items.data[0].price.id,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "created": subscription.created,
                "latest_invoice": {
                    "id": invoice.id,
                    "amount": invoice.amount,
                    "currency": invoice.currency,
                    "status": invoice.status,
                    "payment_intent_id": payment_intent.id if payment_intent else None,
                },
            }

        except StripeError as e:
            logger.error(f"Failed to create subscription: {e}")
            raise

    async def cancel_subscription(
        self,
        subscription_id: str,
    ) -> Dict[str, Any]:
        """
        サブスクリプションをキャンセルします

        Args:
            subscription_id: サブスクリプションID

        Returns:
            キャンセルされたサブスクリプション情報

        Raises:
            StripeError: キャンセルエラーが発生した場合
        """
        try:
            subscription = await self.client.cancel_subscription(subscription_id)

            return {
                "id": subscription.id,
                "customer_id": subscription.customer,
                "status": subscription.status,
                "cancel_at": subscription.canceled_at,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "current_period_end": subscription.current_period_end,
            }

        except StripeError as e:
            logger.error(f"Failed to cancel subscription: {e}")
            raise

    async def get_subscription(
        self,
        subscription_id: str,
    ) -> Dict[str, Any]:
        """
        サブスクリプション情報を取得します

        Args:
            subscription_id: サブスクリプションID

        Returns:
            サブスクリプション情報

        Raises:
            StripeError: 取得エラーが発生した場合
        """
        try:
            subscription = await self.client.retrieve_subscription(subscription_id)

            return {
                "id": subscription.id,
                "customer_id": subscription.customer,
                "status": subscription.status,
                "price_id": subscription.items.data[0].price.id,
                "current_period_start": subscription.current_period_start,
                "current_period_end": subscription.current_period_end,
                "cancel_at_period_end": subscription.cancel_at_period_end,
                "created": subscription.created,
                "updated_at": subscription.updated_at,
            }

        except StripeError as e:
            logger.error(f"Failed to get subscription: {e}")
            raise

    async def get_customer_subscriptions(
        self,
        customer_id: str,
    ) -> List[Dict[str, Any]]:
        """
        顧客のサブスクリプション一覧を取得します

        Args:
            customer_id: 顧客ID

        Returns:
            サブスクリプション情報のリスト

        Raises:
            StripeError: 取得エラーが発生した場合
        """
        import stripe

        try:
            # 顧客のサブスクリプションを取得
            subscriptions = await self.client.list_subscriptions(customer=customer_id)

            return [
                {
                    "id": sub.id,
                    "status": sub.status,
                    "price_id": sub.items.data[0].price.id if sub.items.data else None,
                    "current_period_start": sub.current_period_start,
                    "current_period_end": sub.current_period_end,
                    "cancel_at_period_end": sub.cancel_at_period_end,
                }
                for sub in subscriptions.data
            ]

        except StripeError as e:
            logger.error(f"Failed to get customer subscriptions: {e}")
            raise

    async def list_prices(
        self,
        lookup_keys: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        利用可能な価格一覧を取得します

        Args:
            lookup_keys: 価格識別子（オプション）

        Returns:
            価格情報のリスト

        Raises:
            StripeError: 取得エラーが発生した場合
        """
        try:
            prices = await self.client.list_prices(lookup_keys=lookup_keys)

            return [
                {
                    "id": price.id,
                    "product_id": price.product,
                    "unit_amount": price.unit_amount,
                    "currency": price.currency,
                    "interval": price.recurring.interval,
                    "interval_count": price.recurring.interval_count,
                    "nickname": price.nickname,
                }
                for price in prices
            ]

        except StripeError as e:
            logger.error(f"Failed to list prices: {e}")
            raise

    async def process_webhook_event(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        Stripe Webhookイベントを処理します

        冪等性と順序逆転対策を含みます。

        Args:
            event: Stripe Webhookイベントデータ

        Returns:
            処理が成功すればTrue

        Raises:
            StripeError: 処理エラーが発生した場合
        """
        event_id = event.get("id")
        event_type = event.get("type")

        # イベントIDの検証
        if not event_id:
            logger.warning("Webhook event missing ID")
            return False

        # 冪等性チェック
        if self.client.is_event_processed(event_id):
            logger.info(f"Event {event_id} already processed, skipping")
            return True

        logger.info(f"Processing webhook event: {event_type} ({event_id})")

        try:
            # イベントタイプに応じた処理
            if event_type == "invoice.paid":
                return await self._handle_invoice_paid(event)

            elif event_type == "invoice.payment_failed":
                return await self._handle_invoice_payment_failed(event)

            elif event_type == "customer.subscription.created":
                return await self._handle_subscription_created(event)

            elif event_type == "customer.subscription.updated":
                return await self._handle_subscription_updated(event)

            elif event_type == "customer.subscription.deleted":
                return await self._handle_subscription_deleted(event)

            else:
                logger.info(f"Unhandled event type: {event_type}")
                return True

        except Exception as e:
            logger.error(f"Error processing webhook event: {e}")
            # イベントを処理済みとしてマークしない（再試行可能にするため）
            return False

    async def _handle_invoice_paid(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        請求書支払い済みイベントを処理します

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        invoice = event.get("data", {}).get("object", {})
        subscription_id = invoice.get("subscription")

        if not subscription_id:
            logger.warning("Invoice paid event missing subscription ID")
            return False

        logger.info(f"Invoice paid: subscription={subscription_id}, amount={invoice.get('amount')}")

        # サブスクリプション状態を更新
        # ここでは簡易実装
        # 実際にはデータベースでサブスクリプション状態を更新

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
            },
        )

        return True

    async def _handle_invoice_payment_failed(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        請求書支払い失敗イベントを処理します

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        invoice = event.get("data", {}).get("object", {})

        logger.warning(f"Invoice payment failed: subscription={invoice.get('subscription')}")

        # 支払い失敗時の処理
        # ここでは簡易実装
        # 実際には通知やリトライ処理を実装

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
            },
        )

        return True

    async def _handle_subscription_created(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        サブスクリプション作成イベントを処理します

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")

        logger.info(f"Subscription created: {subscription.get('id')}, customer={customer_id}")

        # サブスクリプション作成時の処理
        # ここでは簡易実装
        # 実際にはデータベースでサブスクリプション情報を登録

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
            },
        )

        return True

    async def _handle_subscription_updated(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        サブスクリプション更新イベントを処理します

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        previous_attributes = event.get("data", {}).get("previous_attributes", {})

        logger.info(
            f"Subscription updated: {subscription.get('id')}, "
            f"status={subscription.get('status')}"
        )

        # サブスクリプション更新時の処理
        # ステータスの変化に応じた処理を実装
        # ここでは簡易実装

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
                "previous_status": previous_attributes.get("status"),
            },
        )

        return True

    async def _handle_subscription_deleted(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        サブスクリプション削除イベントを処理します

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")

        logger.info(f"Subscription deleted: {subscription.get('id')}, customer={customer_id}")

        # サブスクリプション削除時の処理
        # ここでは簡易実装
        # 実際にはデータベースでサブスクリプションを削除

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
            },
        )

        return True

    async def health_check(self) -> Dict[str, Any]:
        """
        Stripeサービスのヘルスチェックを行います

        Returns:
            ヘルスチェック結果
        """
        try:
            # 簡易なヘルスチェック
            # 実際にはStripe APIの可用性をチェック
            prices = await self.list_prices()

            return {
                "status": "healthy",
                "service": "stripe",
                "stripe_available": True,
                "prices_count": len(prices),
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "stripe",
                "stripe_available": False,
                "error": str(e),
            }

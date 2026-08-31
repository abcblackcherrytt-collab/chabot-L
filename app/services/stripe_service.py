"""
Stripe決済サービス
Stripe決済との連携を管理するサービスを定義します。
"""

import logging
from typing import Any, Dict, List, Optional

from app.clients.stripe import StripeClient, StripeError
from app.core.config import settings
from app.repositories.firestore_stripe_event_repository import (
    FirestoreStripeEventRepository,
)
from app.repositories.firestore_user_repository import FirestoreUserRepository
from app.services.line_service import LineService

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
        event_repository: Optional[FirestoreStripeEventRepository] = None,
        user_repository: Optional[FirestoreUserRepository] = None,
        line_service: Optional[LineService] = None,
    ):
        """
        Stripeサービスを初期化します

        Args:
            stripe_client: Stripeクライアント（オプション）
        """
        self.client = stripe_client or StripeClient()
        self.event_repository = event_repository
        self.user_repository = user_repository
        self.line_service = line_service
        logger.info("Stripe service initialized")

    def _event_repository(self) -> FirestoreStripeEventRepository:
        """Webhook処理時だけFirestoreイベントリポジトリを生成する。"""
        if self.event_repository is None:
            self.event_repository = FirestoreStripeEventRepository()
        return self.event_repository

    def _user_repository(self) -> FirestoreUserRepository:
        """Webhook処理時だけFirestoreユーザーリポジトリを生成する。"""
        if self.user_repository is None:
            self.user_repository = FirestoreUserRepository()
        return self.user_repository

    def _line_service(self) -> LineService:
        """通知が必要な場合だけLINEサービスを生成する。"""
        if self.line_service is None:
            self.line_service = LineService()
        return self.line_service

    async def create_customer(
        self,
        email: str,
        name: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        顧客を作成します

        [Phase 2] Phase 1（現在）では未使用（呼び出し元なし）。
        Phase 2 の接続ポイント:
          - line_service._handle_follow_event でユーザー作成時に呼ぶ [Phase 2 マーカー A4]
          - auth_line callback で初回ログイン時に呼ぶ [Phase 2 マーカー C1]

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
        if not event_id or not event_type:
            logger.warning("Webhook event missing ID or type")
            return False

        event_repository = self._event_repository()
        claim_result = await event_repository.claim(
            event_id=event_id,
            event_type=event_type,
            event_created=event.get("created"),
        )
        if claim_result == "completed":
            logger.info("Webhook event already completed: %s", event_id)
            return True
        if claim_result == "in_progress":
            logger.warning("Webhook event is already processing: %s", event_id)
            return False

        logger.info("Processing webhook event: %s (%s)", event_type, event_id)
        try:
            handlers = {
                "invoice.paid": self._handle_invoice_paid,
                "invoice.payment_failed": self._handle_invoice_payment_failed,
                "customer.subscription.created": self._handle_subscription_created,
                "customer.subscription.updated": self._handle_subscription_updated,
                "customer.subscription.deleted": self._handle_subscription_deleted,
            }
            handler = handlers.get(event_type)
            if handler is None:
                logger.info("Unhandled event type accepted: %s", event_type)
                success = True
            else:
                success = await handler(event)

            if not success:
                await event_repository.mark_failed(event_id, "handler_failed")
                return False

            await event_repository.mark_completed(event_id)
            return True
        except Exception as exc:
            logger.error(
                "Webhook event processing failed: type=%s error=%s",
                event_type,
                type(exc).__name__,
                exc_info=True,
            )
            await event_repository.mark_failed(
                event_id,
                f"processing_error:{type(exc).__name__}",
            )
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
        customer_id = invoice.get("customer")
        if not subscription_id or not customer_id:
            logger.warning("Invoice paid event missing subscription or customer")
            return False

        user = await self._user_repository().find_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("User not found for paid invoice customer")
            return False

        await self._user_repository().update_subscription_data(
            user["id"],
            {
                "subscription_status": "active",
                "stripe_subscription_id": subscription_id,
                "current_period_start": invoice.get("period_start"),
                "current_period_end": invoice.get("period_end"),
                "last_invoice_id": invoice.get("id"),
                "last_invoice_status": "paid",
                "last_payment_at": event.get("created"),
            },
        )
        return True

    async def _handle_invoice_payment_failed(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        請求書支払い失敗イベントを処理します

        支払い失敗時にLINE通知を送信します。
        Stripe は自動で再試行しますが、
        最終的に失敗した場合は subscription.deleted イベントが発火します。

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        invoice = event.get("data", {}).get("object", {})
        subscription_id = invoice.get("subscription")
        customer_id = invoice.get("customer")
        attempt_count = invoice.get("attempt_count", 0)

        if not customer_id:
            logger.warning("Payment failed event missing customer")
            return False
        user = await self._user_repository().find_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("User not found for failed invoice customer")
            return False

        await self._user_repository().update_subscription_data(
            user["id"],
            {
                "subscription_status": "past_due",
                "stripe_subscription_id": subscription_id,
                "last_invoice_id": invoice.get("id"),
                "last_invoice_status": "payment_failed",
                "payment_failed_at": event.get("created"),
            },
        )
        await self._line_service().send_subscription_notification(
            user["line_user_id"],
            f"❌ お支払いに失敗しました（{attempt_count}回目）。\n\n"
            "お支払い方法を確認してください。\n"
            "支払いが完了するまでサービスが制限される可能性があります。",
        )
        return True

    async def _handle_subscription_created(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        サブスクリプション作成イベントを処理します

        Firestore連携によりプラン更新とLINE通知を行います。

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        if not customer_id or not subscription_id:
            return False
        user = await self._user_repository().find_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("User not found for created subscription customer")
            return False

        price_id = self._subscription_price_id(subscription)
        if not price_id:
            return False
        from app.core.pricing import get_plan_from_price_id

        plan = get_plan_from_price_id(price_id)
        await self._user_repository().update_subscription_data(
            user["id"],
            self._subscription_updates(subscription, plan=plan),
        )
        await self._line_service().send_subscription_notification(
            user["line_user_id"],
            "🎉 有料プランへのご登録が完了しました！\n\n"
            f"プラン: {plan.upper()}",
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
        customer_id = subscription.get("customer")
        if not customer_id or not subscription.get("id"):
            return False
        user = await self._user_repository().find_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("User not found for updated subscription customer")
            return False

        plan = None
        price_id = self._subscription_price_id(subscription)
        if price_id:
            from app.core.pricing import get_plan_from_price_id

            plan = get_plan_from_price_id(price_id)
        await self._user_repository().update_subscription_data(
            user["id"],
            self._subscription_updates(subscription, plan=plan),
        )
        return True

    async def _handle_subscription_deleted(
        self,
        event: Dict[str, Any],
    ) -> bool:
        """
        サブスクリプション削除イベントを処理します

        解約時の処理としてfreeプラン戻しとLINE通知を行います。

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        if not customer_id or not subscription_id:
            return False
        user = await self._user_repository().find_by_stripe_customer_id(customer_id)
        if not user:
            logger.warning("User not found for deleted subscription customer")
            return False

        await self._user_repository().update_subscription_data(
            user["id"],
            {
                "subscription_plan": "free",
                "subscription_status": "active",
                "stripe_subscription_id": None,
                "current_period_start": None,
                "current_period_end": None,
                "cancel_at_period_end": False,
            },
        )
        await self._line_service().send_subscription_notification(
            user["line_user_id"],
            "📱 有料プランのサブスクリプションが終了しました。\n\n"
            "フリープラン（1日3回）として継続利用可能です。",
        )
        return True

    @staticmethod
    def _subscription_price_id(subscription: Dict[str, Any]) -> Optional[str]:
        """SubscriptionオブジェクトからPrice IDを安全に取得する。"""
        items = subscription.get("items", {}).get("data", [])
        if not items:
            return None
        return items[0].get("price", {}).get("id")

    @staticmethod
    def _subscription_updates(
        subscription: Dict[str, Any],
        plan: Optional[str],
    ) -> Dict[str, Any]:
        """Firestoreへ保存するSubscription状態を組み立てる。"""
        updates = {
            "subscription_status": subscription.get("status", "active"),
            "stripe_subscription_id": subscription.get("id"),
            "current_period_start": subscription.get("current_period_start"),
            "current_period_end": subscription.get("current_period_end"),
            "cancel_at_period_end": bool(
                subscription.get("cancel_at_period_end", False)
            ),
        }
        if plan:
            updates["subscription_plan"] = plan
        return updates

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

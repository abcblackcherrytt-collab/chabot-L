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

        # ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
        # 現状（Phase 1）: DB 更新なし（ログのみ）。
        # Phase 2 で有効化する接続ポイント:
        #   - subscription_id から該当 Subscription レコードを特定し、
        #     status / current_period_start / current_period_end を更新
        # 関連: models/subscription.py [Phase 2 マーカー H2]
        # ===================================================================
        # （簡易実装：実際にはデータベースでサブスクリプション状態を更新）

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

        logger.warning(
            f"Invoice payment failed: subscription={subscription_id}, "
            f"attempt={attempt_count}"
        )

        try:
            # Firestore連携とLINE通知
            from app.repositories.firestore_user_repository import FirestoreUserRepository
            from app.services.line_service import LineService

            user_repo = FirestoreUserRepository()
            line_service = LineService()

            # Stripe顧客IDからユーザーを検索
            user = await user_repo.find_by_stripe_customer_id(customer_id)
            if user:
                # LINE通知（既存メソッド活用）
                await line_service.send_subscription_notification(
                    user["line_user_id"],
                    f"❌ お支払いに失敗しました（{attempt_count}回目）。\n\n"
                    "お支払い方法を確認してください。\n"
                    "支払いが完了するまでサービスが制限される可能性があります。"
                )

                logger.info(f"Sent payment failure notification to user {user['id']}")

        except Exception as e:
            logger.error(f"Error in payment failed handler: {e}")

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

        Firestore連携によりプラン更新とLINE通知を行います。

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        logger.info(f"Subscription created: {subscription_id}, customer={customer_id}")

        try:
            # Firestore連携
            from app.repositories.firestore_user_repository import FirestoreUserRepository
            from app.core.pricing import get_plan_from_price_id
            from app.services.line_service import LineService

            user_repo = FirestoreUserRepository()
            line_service = LineService()

            # Stripe顧客IDからユーザーを検索（既存メソッド活用）
            user = await user_repo.find_by_stripe_customer_id(customer_id)
            if not user:
                logger.warning(f"User not found for customer: {customer_id}")
                return False

            # 価格IDからプランを特定
            price_id = subscription.get("items", {}).get("data", [{}])[0].get("price", {}).get("id")
            if not price_id:
                logger.warning(f"Price ID not found in subscription: {subscription_id}")
                return False

            try:
                plan = get_plan_from_price_id(price_id)

                # Firestoreでプラン更新（既存メソッド活用）
                await user_repo.update_subscription_plan(user["id"], plan)

                logger.info(
                    f"Updated user {user['id']} to plan {plan} after subscription created"
                )

                # LINE通知（既存メソッド活用）
                await line_service.send_subscription_notification(
                    user["line_user_id"],
                    f"🎉 有料プランへのご登録が完了しました！\n\n"
                    f"プラン: {plan.upper()}\n"
                    f"サブスクリプションID: {subscription_id}"
                )

            except ValueError as e:
                logger.error(f"Invalid price ID: {price_id}")
                return False

        except Exception as e:
            logger.error(f"Error in subscription created handler: {e}")
            # エラーがあってもイベントを処理済みとしてマークしない（再試行可能にするため）
            self.client.mark_event_processed(
                event["id"],
                {
                    "event_type": event["type"],
                    "processed_at": event["created"],
                    "error": str(e),
                },
            )
            return False

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

        # ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
        # 現状（Phase 1）: DB 更新なし（ログのみ）。
        # Phase 2 で有効化する接続ポイント:
        #   - previous_attributes.status と新 status の差分から
        #     Subscription.status / plan / 請求期間を更新
        #   - 期限切れ（past_due/unpaid/canceled）への遷移でアクセス制限を強化
        # 関連: models/subscription.py is_restricted() [Phase 2 マーカー H2]
        # ===================================================================
        # （簡易実装：ステータスの変化に応じた処理を実装）

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

        解約時の処理としてfreeプラン戻しとLINE通知を行います。

        Args:
            event: イベントデータ

        Returns:
            処理が成功すればTrue
        """
        subscription = event.get("data", {}).get("object", {})
        customer_id = subscription.get("customer")
        subscription_id = subscription.get("id")

        logger.info(f"Subscription deleted: {subscription_id}, customer={customer_id}")

        try:
            # Firestore連携
            from app.repositories.firestore_user_repository import FirestoreUserRepository
            from app.services.line_service import LineService

            user_repo = FirestoreUserRepository()
            line_service = LineService()

            # Stripe顧客IDからユーザーを検索
            user = await user_repo.find_by_stripe_customer_id(customer_id)
            if not user:
                logger.warning(f"User not found for customer: {customer_id}")
                return False

            # freeプランに戻す（有料解約後もfreeで継続利用可能）
            await user_repo.update_subscription_plan(user["id"], "free")

            logger.info(f"Updated user {user['id']} to free plan after subscription deleted")

            # ユーザーは無効化しない（freeプランとして継続利用可能）
            # LINE unfollowや明示的退会時のみ無効化

            # LINE通知（既存メソッド活用）
            await line_service.send_subscription_notification(
                user["line_user_id"],
                "📱 有料プランのサブスクリプションが終了しました。\n\n"
                "フリープラン（1日3回）として継続利用可能です。\n\n"
                "またのご利用をお待ちしております！"
            )

        except Exception as e:
            logger.error(f"Error in subscription deleted handler: {e}")
            # エラーがあってもイベントを処理済みとしてマークしない
            self.client.mark_event_processed(
                event["id"],
                {
                    "event_type": event["type"],
                    "processed_at": event["created"],
                    "error": str(e),
                },
            )
            return False

        # イベントを処理済みとしてマーク
        self.client.mark_event_processed(
            event["id"],
            {
                "event_type": event["type"],
                "processed_at": event["created"],
            },
        )

        return True
        #        )

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

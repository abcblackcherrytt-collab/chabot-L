"""
Stripeクライアント
Stripeとの通信を管理するクライアントを定義します。
"""

import asyncio
import hashlib
import hmac
import logging
from typing import Any, Dict

import stripe

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


class StripeError(BaseClientError):
    """
    Stripeエラークラス
    """

    def __init__(
        self,
        message: str,
        status_code: int | None = None,
        response: Any | None = None,
    ):
        super().__init__(message, status_code, response)


class StripeClient(BaseClient):
    """
    Stripeクライアント

    Stripe決済サービスとの通信を管理します。
    Webhook署名検証、冪等性、順序逆転対策を含みます。
    """

    def __init__(
        self,
        secret_key: str | None = None,
        webhook_secret: str | None = None,
    ):
        """
        Stripeクライアントを初期化します

        Args:
            secret_key: Stripeシークレットキー
            webhook_secret: Stripe Webhook署名検証用シークレット
        """
        # ベースクライアントは使用しない（Stripe SDKを使用）
        self.secret_key = secret_key or settings.stripe_secret_key
        self.webhook_secret = webhook_secret or settings.stripe_webhook_secret

        # Stripe SDKを初期化
        stripe.api_key = self.secret_key

        # 冪等性管理用のイベントID辞書
        self._processed_events: Dict[str, Any] = {}

        logger.info("Stripe client initialized")

    def verify_webhook_signature(
        self,
        payload: bytes,
        signature_header: str,
    ) -> bool:
        """
        Webhook署名を検証します

        重要: JSONパース前に署名検証を行う必要があります。

        Args:
            payload: 生のリクエストボディ（JSONパース前）
            signature_header: Stripe-Signatureヘッダーの値

        Returns:
            署名が有効であればTrue

        Raises:
            StripeError: 署名検証に失敗した場合
        """
        try:
            # Stripe SDKで署名検証
            event = stripe.Webhook.construct_event(
                payload,
                signature_header,
                self.webhook_secret,
            )

            logger.info("Webhook signature verified successfully")
            return True

        except ValueError as e:
            # JSONパースエラー
            logger.error(f"Invalid payload in webhook: {e}")
            raise StripeError(
                "Invalid webhook payload",
                status_code=400,
            )

        except stripe.error.SignatureVerificationError as e:
            # 署名検証エラー
            logger.error(f"Webhook signature verification failed: {e}")
            raise StripeError(
                "Invalid webhook signature",
                status_code=401,
            )

    def is_event_processed(self, event_id: str) -> bool:
        """
        イベントが既に処理済みかをチェックします

        冪等性管理のために使用します。

        Args:
            event_id: StripeイベントID

        Returns:
            既に処理済みであればTrue
        """
        return event_id in self._processed_events

    def mark_event_processed(
        self,
        event_id: str,
        event_data: Dict[str, Any],
    ) -> None:
        """
        イベントを処理済みとしてマークします

        冪等性管理のために使用します。

        Args:
            event_id: StripeイベントID
            event_data: イベントデータ
        """
        self._processed_events[event_id] = event_data
        logger.debug(f"Event {event_id} marked as processed")

    def clear_old_events(self, hours_old: int = 24) -> int:
        """
        古い処理済みイベントをクリアします

        Args:
            hours_old: 何時間前より古いイベントをクリアするか

        Returns:
            クリアされたイベント数
        """
        import datetime

        cutoff_time = datetime.datetime.utcnow() - datetime.timedelta(hours=hours_old)

        cleared_count = 0
        for event_id, event_data in list(self._processed_events.items()):
            event_time = event_data.get("processed_at")
            if event_time and event_time < cutoff_time:
                del self._processed_events[event_id]
                cleared_count += 1

        if cleared_count > 0:
            logger.info(f"Cleared {cleared_count} old events")

        return cleared_count

    async def create_customer(
        self,
        email: str,
        name: str | None = None,
        metadata: dict[str, str] | None = None,
    ) -> stripe.Customer:
        """
        Stripe顧客を作成します

        Args:
            email: 顧客メールアドレス
            name: 顧客名
            metadata: メタデータ

        Returns:
            作成されたStripe顧客

        Raises:
            StripeError: 顧客作成エラーが発生した場合
        """
        try:
            customer_data: Dict[str, Any] = {"email": email}

            if name:
                customer_data["name"] = name

            if metadata:
                customer_data["metadata"] = metadata

            customer = await asyncio.to_thread(
                stripe.Customer.create, **customer_data
            )
            logger.info(f"Customer created: {customer.id}")
            return customer

        except stripe.error.StripeError as e:
            logger.error(f"Customer creation error: {e}")
            raise StripeError(f"顧客作成エラー: {e}")

    async def create_subscription(
        self,
        customer_id: str,
        price_id: str,
        payment_method_id: str,
        metadata: dict[str, str] | None = None,
    ) -> stripe.Subscription:
        """
        サブスクリプションを作成します

        Args:
            customer_id: 顧客ID
            price_id: 価格ID
            payment_method_id: 支払い方法ID
            metadata: メタデータ

        Returns:
            作成されたサブスクリプション

        Raises:
            StripeError: サブスクリプション作成エラーが発生した場合
        """
        try:
            subscription_data: Dict[str, Any] = {
                "customer": customer_id,
                "items": [{"price": price_id}],
                "default_payment_method": payment_method_id,
                "payment_behavior": "default_incomplete",
                "expand": ["latest_invoice.payment_intent"],
            }

            if metadata:
                subscription_data["metadata"] = metadata

            subscription = await asyncio.to_thread(
                stripe.Subscription.create, **subscription_data
            )
            logger.info(f"Subscription created: {subscription.id}")
            return subscription

        except stripe.error.StripeError as e:
            logger.error(f"Subscription creation error: {e}")
            raise StripeError(f"サブスクリプション作成エラー: {e}")

    async def cancel_subscription(
        self,
        subscription_id: str,
    ) -> stripe.Subscription:
        """
        サブスクリプションをキャンセルします

        Args:
            subscription_id: サブスクリプションID

        Returns:
            キャンセルされたサブスクリプション

        Raises:
            StripeError: サブスクリプションキャンセルエラーが発生した場合
        """
        try:
            subscription = await asyncio.to_thread(
                stripe.Subscription.modify,
                subscription_id,
                cancel_at_period_end=True,
            )
            logger.info(f"Subscription canceled: {subscription_id}")
            return subscription

        except stripe.error.StripeError as e:
            logger.error(f"Subscription cancellation error: {e}")
            raise StripeError(f"サブスクリプションキャンセルエラー: {e}")

    async def retrieve_customer(
        self,
        customer_id: str,
    ) -> stripe.Customer:
        """
        顧客情報を取得します

        Args:
            customer_id: 顧客ID

        Returns:
            Stripe顧客

        Raises:
            StripeError: 顧客取得エラーが発生した場合
        """
        try:
            customer = await asyncio.to_thread(
                stripe.Customer.retrieve, customer_id
            )
            return customer

        except stripe.error.StripeError as e:
            logger.error(f"Customer retrieval error: {e}")
            raise StripeError(f"顧客取得エラー: {e}")

    async def retrieve_subscription(
        self,
        subscription_id: str,
    ) -> stripe.Subscription:
        """
        サブスクリプション情報を取得します

        Args:
            subscription_id: サブスクリプションID

        Returns:
            Stripeサブスクリプション

        Raises:
            StripeError: サブスクリプション取得エラーが発生した場合
        """
        try:
            subscription = await asyncio.to_thread(
                stripe.Subscription.retrieve, subscription_id
            )
            return subscription

        except stripe.error.StripeError as e:
            logger.error(f"Subscription retrieval error: {e}")
            raise StripeError(f"サブスクリプション取得エラー: {e}")

    async def list_subscriptions(
        self,
        customer: str,
    ) -> stripe.ListObject:
        """
        顧客のサブスクリプション一覧を取得します

        Args:
            customer: 顧客ID

        Returns:
            サブスクリプションリスト

        Raises:
            StripeError: サブスクリプション取得エラーが発生した場合
        """
        try:
            subscriptions = await asyncio.to_thread(
                stripe.Subscription.list, customer=customer
            )
            return subscriptions

        except stripe.error.StripeError as e:
            logger.error(f"Subscriptions list error: {e}")
            raise StripeError(f"サブスクリプション一覧取得エラー: {e}")

    async def list_prices(
        self,
        lookup_keys: list[str] | None = None,
    ) -> list[stripe.Price]:
        """
        価格の一覧を取得します

        Args:
            lookup_keys: 価格識別子のリスト（フィルタリング用）

        Returns:
            価格のリスト

        Raises:
            StripeError: 価格取得エラーが発生した場合
        """
        try:
            params: Dict[str, Any] = {"active": True}

            if lookup_keys:
                params["lookup_keys"] = lookup_keys

            prices = await asyncio.to_thread(stripe.Price.list, **params)
            return prices.data

        except stripe.error.StripeError as e:
            logger.error(f"Price listing error: {e}")
            raise StripeError(f"価格取得エラー: {e}")

    async def create_checkout_session(
        self,
        customer_id: str,
        price_id: str,
        success_url: str,
        cancel_url: str,
        metadata: dict[str, str] | None = None,
    ) -> stripe.checkout.Session:
        """
        Stripe Checkoutセッションを作成

        Args:
            customer_id: 顧客ID
            price_id: 価格ID
            success_url: 成功時のリダイレクトURL
            cancel_url: キャンセル時のリダイレクトURL
            metadata: メタデータ

        Returns:
            作成されたCheckoutセッション

        Raises:
            StripeError: Checkout作成エラーが発生した場合
        """
        try:
            session_data = {
                "customer": customer_id,
                "mode": "subscription",
                "payment_method_types": ["card"],
                "line_items": [{"price": price_id, "quantity": 1}],
                "success_url": success_url,
                "cancel_url": cancel_url,
            }

            if metadata:
                session_data["metadata"] = metadata

            session = await asyncio.to_thread(
                stripe.checkout.Session.create, **session_data
            )
            logger.info(f"Checkout session created: {session.id}")
            return session

        except stripe.error.StripeError as e:
            logger.error(f"Checkout session creation error: {e}")
            raise StripeError(f"Checkout作成エラー: {e}")

    async def get_checkout_session(
        self,
        session_id: str,
    ) -> stripe.checkout.Session:
        """
        Checkoutセッションを取得

        Args:
            session_id: セッションID

        Returns:
            Checkoutセッション

        Raises:
            StripeError: セッション取得エラーが発生した場合
        """
        try:
            session = await asyncio.to_thread(
                stripe.checkout.Session.retrieve, session_id
            )
            return session

        except stripe.error.StripeError as e:
            logger.error(f"Checkout session retrieval error: {e}")
            raise StripeError(f"Checkout取得エラー: {e}")

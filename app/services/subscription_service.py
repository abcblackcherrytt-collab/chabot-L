"""
サブスクリプションサービス

Stripe Checkoutセッション作成とサブスクリプション管理の業務ロジックを提供します。
"""

import logging
import uuid
from typing import Any, Dict, Optional

from app.clients.stripe import StripeClient, StripeError
from app.core.config import settings
from app.core.pricing import get_plan_config, get_plan_from_price_id, get_checkout_urls
from app.repositories.firestore_user_repository import FirestoreUserRepository

logger = logging.getLogger(__name__)


class SubscriptionService:
    """
    サブスクリプションサービス

    Stripe CheckoutとFirestoreの連携を管理します。
    """

    def __init__(
        self,
        stripe_client: Optional[StripeClient] = None,
    ):
        """
        サブスクリプションサービスを初期化

        Args:
            stripe_client: Stripeクライアント（オプション）
        """
        self.stripe_client = stripe_client or StripeClient()
        self.user_repo = FirestoreUserRepository()
        logger.info("Subscription service initialized")

    async def create_checkout_session(
        self,
        user_id: str,
        plan: str,
    ) -> str:
        """
        Stripe Checkoutセッションを作成

        Args:
            user_id: ユーザーID
            plan: プラン名（basic, pro）

        Returns:
            Checkout URL

        Raises:
            ValueError: 不正なプラン名の場合
            StripeError: Checkout作成エラーの場合
        """
        try:
            # プラン設定を取得
            plan_config = get_plan_config(plan)
            price_id = plan_config["price_id"]

            if not price_id:
                raise ValueError(f"Price ID not configured for plan: {plan}")

            # ユーザー情報を取得
            user = await self.user_repo.find_by_id(user_id)
            if not user:
                raise ValueError(f"User not found: {user_id}")

            logger.info(
                f"Creating checkout session for user {user_id}, plan {plan}"
            )

            # Stripe顧客IDの取得または作成
            stripe_customer_id = await self._get_or_create_stripe_customer(user)

            # FirestoreにStripe顧客IDを紐付け（まだの場合）
            if not user.get("stripe_customer_id"):
                await self.user_repo.update_stripe_customer_id(
                    user_id, stripe_customer_id
                )
                logger.info(f"Linked Stripe customer {stripe_customer_id} to user {user_id}")

            # Checkout URLの取得
            checkout_urls = get_checkout_urls()

            # Stripe Checkoutセッション作成
            checkout_session = await self.stripe_client.create_checkout_session(
                customer_id=stripe_customer_id,
                price_id=price_id,
                success_url=checkout_urls["success_url"],
                cancel_url=checkout_urls["cancel_url"],
                metadata={
                    "user_id": user_id,
                    "line_user_id": user.get("line_user_id", ""),
                    "plan": plan,
                },
            )

            checkout_url = checkout_session.get("url")
            logger.info(f"Created checkout session: {checkout_session.get('id')}")

            return checkout_url

        except ValueError as e:
            logger.error(f"Validation error: {e}")
            raise
        except StripeError as e:
            logger.error(f"Stripe error: {e}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            raise

    async def _get_or_create_stripe_customer(
        self,
        user: Dict[str, Any],
    ) -> str:
        """
        Stripe顧客を取得または作成

        Args:
            user: ユーザーデータ辞書

        Returns:
            Stripe顧客ID
        """
        try:
            # 既存のStripe顧客IDを確認
            existing_customer_id = user.get("stripe_customer_id")
            if existing_customer_id:
                logger.info(f"Using existing Stripe customer: {existing_customer_id}")
                return existing_customer_id

            # 新規Stripe顧客作成
            customer = await self.stripe_client.create_customer(
                email=user.get("email"),
                name=user.get("display_name"),
                metadata={
                    "user_id": user.get("id"),
                    "line_user_id": user.get("line_user_id", ""),
                },
            )

            customer_id = customer.get("id")
            logger.info(f"Created new Stripe customer: {customer_id}")

            return customer_id

        except StripeError as e:
            logger.error(f"Failed to create Stripe customer: {e}")
            raise

    async def handle_checkout_success(
        self,
        session_id: str,
    ) -> Dict[str, Any]:
        """
        Checkout成功後の処理

        Args:
            session_id: CheckoutセッションID

        Returns:
            処理結果
        """
        try:
            # セッション情報を取得
            session = await self.stripe_client.get_checkout_session(session_id)

            customer_id = session.get("customer")
            subscription_id = session.get("subscription")
            metadata = session.get("metadata", {})

            logger.info(
                f"Checkout success: customer={customer_id}, subscription={subscription_id}"
            )

            # ユーザー情報を確認
            user = await self.user_repo.find_by_stripe_customer_id(customer_id)
            if not user:
                logger.warning(f"User not found for customer: {customer_id}")
                return {"status": "user_not_found", "session_id": session_id}

            # サブスクリプション情報を取得
            if subscription_id:
                subscription = await self.stripe_client.retrieve_subscription(
                    subscription_id
                )

                # 価格IDからプランを特定
                price_id = subscription.get("items", {}).get("data", [{}])[0].get(
                    "price", {}
                ).get("id")

                try:
                    plan = get_plan_from_price_id(price_id)

                    # Firestoreでプラン更新（webhookでも更新されるが念のため）
                    await self.user_repo.update_subscription_plan(
                        user["id"], plan
                    )

                    logger.info(
                        f"Updated user {user['id']} to plan {plan} after checkout"
                    )

                    return {
                        "status": "success",
                        "plan": plan,
                        "user_id": user["id"],
                        "subscription_id": subscription_id,
                    }

                except ValueError as e:
                    logger.error(f"Invalid price ID: {price_id}")
                    return {
                        "status": "invalid_price",
                        "session_id": session_id,
                    }

            return {
                "status": "success",
                "session_id": session_id,
                "customer_id": customer_id,
            }

        except StripeError as e:
            logger.error(f"Stripe error handling checkout success: {e}")
            return {"status": "error", "error": str(e)}
        except Exception as e:
            logger.error(f"Unexpected error handling checkout success: {e}")
            return {"status": "error", "error": str(e)}

    async def get_user_subscription_status(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        ユーザーのサブスクリプション状態を取得

        Args:
            user_id: ユーザーID

        Returns:
            サブスクリプション状態情報
        """
        try:
            # ユーザー情報を取得
            user = await self.user_repo.find_by_id(user_id)
            if not user:
                return {"status": "user_not_found"}

            # Stripe顧客IDを取得
            stripe_customer_id = user.get("stripe_customer_id")
            if not stripe_customer_id:
                return {
                    "status": "no_subscription",
                    "plan": user.get("subscription_plan", "free"),
                }

            # Stripeサブスクリプションを取得
            subscriptions = await self.stripe_client.list_subscriptions(
                customer_id=stripe_customer_id
            )

            # アクティブなサブスクリプションを探す
            active_subscriptions = [
                sub
                for sub in subscriptions.get("data", [])
                if sub.get("status") == "active"
            ]

            if not active_subscriptions:
                return {
                    "status": "no_active_subscription",
                    "plan": user.get("subscription_plan", "free"),
                }

            subscription = active_subscriptions[0]

            # 価格IDからプランを特定
            price_id = subscription.get("items", {}).get("data", [{}])[0].get(
                "price", {}
            ).get("id")

            try:
                plan = get_plan_from_price_id(price_id)
                plan_config = get_plan_config(plan)

                return {
                    "status": "active",
                    "plan": plan,
                    "subscription_id": subscription.get("id"),
                    "current_period_end": subscription.get("current_period_end"),
                    "cancel_at_period_end": subscription.get("cancel_at_period_end"),
                    "monthly_limit": plan_config.get("monthly_limit"),
                }

            except ValueError:
                return {
                    "status": "invalid_price",
                    "plan": user.get("subscription_plan", "free"),
                }

        except Exception as e:
            logger.error(f"Error getting subscription status: {e}")
            return {"status": "error", "error": str(e)}
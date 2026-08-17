"""
サブスクリプション整合性チェックサービス

StripeとFirestoreのデータ整合性を維持するサービスを提供します。
"""

import logging
from typing import Any, Dict, Optional

from app.clients.stripe import StripeClient, StripeError
from app.core.pricing import get_plan_from_price_id
from app.repositories.firestore_user_repository import FirestoreUserRepository

logger = logging.getLogger(__name__)


class SubscriptionSyncService:
    """
    サブスクリプション整合性チェックサービス

    StripeとFirestoreのデータ整合性を確認・修正します。
    """

    def __init__(
        self,
        stripe_client: Optional[StripeClient] = None,
    ):
        """
        整合性チェックサービスを初期化

        Args:
            stripe_client: Stripeクライアント（オプション）
        """
        self.stripe_client = stripe_client or StripeClient()
        self.user_repo = FirestoreUserRepository()
        logger.info("Subscription sync service initialized")

    async def check_user_subscription_consistency(
        self,
        line_user_id: str,
    ) -> Dict[str, Any]:
        """
        LINEユーザーIDのサブスクリプション整合性をチェック

        Args:
            line_user_id: LINEユーザーID

        Returns:
            整合性チェック結果
        """
        try:
            # Firestoreからユーザーを取得
            user = await self.user_repo.find_by_line_user_id(line_user_id)
            if not user:
                return {
                    "status": "user_not_found",
                    "line_user_id": line_user_id,
                    "consistent": False,
                    "error": "User not found in Firestore"
                }

            user_id = user.get("id")
            firestore_plan = user.get("subscription_plan", "free")
            stripe_customer_id = user.get("stripe_customer_id")

            logger.info(
                f"Checking consistency for user {user_id}: "
                f"firestore_plan={firestore_plan}, has_stripe_customer={bool(stripe_customer_id)}"
            )

            # Stripe顧客IDがない場合、freeプランで整合性確認
            if not stripe_customer_id:
                if firestore_plan == "free":
                    return {
                        "status": "consistent",
                        "line_user_id": line_user_id,
                        "user_id": user_id,
                        "firestore_plan": firestore_plan,
                        "stripe_plan": None,
                        "consistent": True,
                        "message": "No Stripe customer, free plan consistent"
                    }
                else:
                    return {
                        "status": "inconsistent",
                        "line_user_id": line_user_id,
                        "user_id": user_id,
                        "firestore_plan": firestore_plan,
                        "stripe_plan": None,
                        "consistent": False,
                        "error": "User has paid plan in Firestore but no Stripe customer"
                    }

            # Stripeサブスクリプションを確認
            try:
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
                    # Stripeにアクティブなサブスクリプションがない場合
                    if firestore_plan == "free":
                        return {
                            "status": "consistent",
                            "line_user_id": line_user_id,
                            "user_id": user_id,
                            "firestore_plan": firestore_plan,
                            "stripe_plan": None,
                            "consistent": True,
                            "message": "No active Stripe subscription, free plan consistent"
                        }
                    else:
                        return {
                            "status": "inconsistent",
                            "line_user_id": line_user_id,
                            "user_id": user_id,
                            "firestore_plan": firestore_plan,
                            "stripe_plan": None,
                            "consistent": False,
                            "error": "User has paid plan in Firestore but no active Stripe subscription"
                        }

                # アクティブなサブスクリプションがある場合
                subscription = active_subscriptions[0]
                price_id = subscription.get("items", {}).get("data", [{}])[0].get(
                    "price", {}
                ).get("id")

                try:
                    stripe_plan = get_plan_from_price_id(price_id)

                    if stripe_plan == firestore_plan:
                        return {
                            "status": "consistent",
                            "line_user_id": line_user_id,
                            "user_id": user_id,
                            "firestore_plan": firestore_plan,
                            "stripe_plan": stripe_plan,
                            "subscription_id": subscription.get("id"),
                            "consistent": True,
                            "message": "Plans match between Stripe and Firestore"
                        }
                    else:
                        return {
                            "status": "inconsistent",
                            "line_user_id": line_user_id,
                            "user_id": user_id,
                            "firestore_plan": firestore_plan,
                            "stripe_plan": stripe_plan,
                            "subscription_id": subscription.get("id"),
                            "consistent": False,
                            "error": f"Plan mismatch: Firestore={firestore_plan}, Stripe={stripe_plan}"
                        }

                except ValueError:
                    return {
                        "status": "unknown_price",
                        "line_user_id": line_user_id,
                        "user_id": user_id,
                        "firestore_plan": firestore_plan,
                        "consistent": False,
                        "error": "Unknown price ID in Stripe subscription"
                    }

            except StripeError as e:
                logger.error(f"Stripe API error: {e}")
                return {
                    "status": "stripe_error",
                    "line_user_id": line_user_id,
                    "user_id": user_id,
                    "consistent": False,
                    "error": f"Stripe API error: {str(e)}"
                }

        except Exception as e:
            logger.error(f"Error checking consistency: {e}")
            return {
                "status": "error",
                "line_user_id": line_user_id,
                "consistent": False,
                "error": str(e)
            }

    async def sync_stripe_to_firestore(
        self,
        stripe_customer_id: str,
    ) -> Dict[str, Any]:
        """
        Stripeを正としてFirestoreを更新

        Args:
            stripe_customer_id: Stripe顧客ID

        Returns:
            同期結果
        """
        try:
            # ユーザーを検索
            user = await self.user_repo.find_by_stripe_customer_id(stripe_customer_id)
            if not user:
                return {
                    "status": "user_not_found",
                    "stripe_customer_id": stripe_customer_id,
                    "success": False,
                    "error": "User not found in Firestore"
                }

            # Stripeサブスクリプションを確認
            subscriptions = await self.stripe_client.list_subscriptions(
                customer_id=stripe_customer_id
            )

            active_subscriptions = [
                sub
                for sub in subscriptions.get("data", [])
                if sub.get("status") == "active"
            ]

            if not active_subscriptions:
                # アクティブなサブスクリプションがない場合、freeプランに設定
                await self.user_repo.update_subscription_plan(user["id"], "free")
                logger.info(f"Synced user {user['id']} to free plan (no active subscription)")

                return {
                    "status": "success",
                    "user_id": user["id"],
                    "updated_plan": "free",
                    "previous_plan": user.get("subscription_plan"),
                    "success": True
                }
            else:
                # アクティブなサブスクリプションがある場合、プランを更新
                subscription = active_subscriptions[0]
                price_id = subscription.get("items", {}).get("data", [{}])[0].get(
                    "price", {}
                ).get("id")

                try:
                    stripe_plan = get_plan_from_price_id(price_id)
                    previous_plan = user.get("subscription_plan")

                    await self.user_repo.update_subscription_plan(user["id"], stripe_plan)

                    logger.info(
                        f"Synced user {user['id']} to plan {stripe_plan} "
                        f"(previous: {previous_plan})"
                    )

                    return {
                        "status": "success",
                        "user_id": user["id"],
                        "updated_plan": stripe_plan,
                        "previous_plan": previous_plan,
                        "subscription_id": subscription.get("id"),
                        "success": True
                    }

                except ValueError as e:
                    return {
                        "status": "invalid_price",
                        "user_id": user["id"],
                        "success": False,
                        "error": str(e)
                    }

        except Exception as e:
            logger.error(f"Error syncing Stripe to Firestore: {e}")
            return {
                "status": "error",
                "success": False,
                "error": str(e)
            }

    async def sync_firestore_to_stripe(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        Firestoreを正としてStripe更新（異常時の修復用）

        Args:
            user_id: ユーザーID

        Returns:
            同期結果
        """
        try:
            # ユーザーを取得
            user = await self.user_repo.find_by_id(user_id)
            if not user:
                return {
                    "status": "user_not_found",
                    "user_id": user_id,
                    "success": False,
                    "error": "User not found in Firestore"
                }

            firestore_plan = user.get("subscription_plan", "free")
            stripe_customer_id = user.get("stripe_customer_id")

            if not stripe_customer_id:
                return {
                    "status": "no_stripe_customer",
                    "user_id": user_id,
                    "firestore_plan": firestore_plan,
                    "success": False,
                    "error": "No Stripe customer linked to user"
                }

            # Firestoreがfreeプランの場合、Stripeサブスクリプションをキャンセル
            if firestore_plan == "free":
                subscriptions = await self.stripe_client.list_subscriptions(
                    customer_id=stripe_customer_id
                )

                active_subscriptions = [
                    sub
                    for sub in subscriptions.get("data", [])
                    if sub.get("status") == "active"
                ]

                if active_subscriptions:
                    # 最初のアクティブサブスクリプションをキャンセル
                    subscription = active_subscriptions[0]
                    await self.stripe_client.cancel_subscription(subscription.get("id"))

                    logger.info(f"Canceled Stripe subscription {subscription.get('id')}")

                    return {
                        "status": "success",
                        "user_id": user_id,
                        "canceled_subscription": subscription.get("id"),
                        "success": True
                    }
                else:
                    return {
                        "status": "no_active_subscription",
                        "user_id": user_id,
                        "firestore_plan": firestore_plan,
                        "success": True,
                        "message": "No active subscription to cancel"
                    }

            return {
                "status": "not_applicable",
                "user_id": user_id,
                "firestore_plan": firestore_plan,
                "success": True,
                "message": "User has paid plan, manual review required"
            }

        except Exception as e:
            logger.error(f"Error syncing Firestore to Stripe: {e}")
            return {
                "status": "error",
                "success": False,
                "error": str(e)
            }
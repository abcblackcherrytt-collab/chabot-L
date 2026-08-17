"""
サブスクリプション管理エンドポイント

Stripe Checkoutとサブスクリプション管理のAPIエンドポイントを提供します。
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from app.core.pricing import PLANS, get_plan_config, validate_plan_availability
from app.services.subscription_service import SubscriptionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/subscription", tags=["subscription"])


# ========== 依存性注入 ==========

def get_subscription_service() -> SubscriptionService:
    """サブスクリプションサービスの依存性"""
    return SubscriptionService()


# ========== Pydanticスキーマ ==========

class CheckoutRequest(BaseModel):
    """Checkoutセッション作成リクエスト"""

    plan: str = Field(..., description="プラン名（basic, pro）")


class CheckoutResponse(BaseModel):
    """Checkoutセッション作成レスポンス"""

    checkout_url: str = Field(..., description="Stripe Checkout URL")
    plan: str = Field(..., description="プラン名")


class SubscriptionStatusResponse(BaseModel):
    """サブスクリプションステータスレスポンス"""

    status: str = Field(..., description="サブスクリプションステータス")
    plan: str | None = Field(None, description="プラン名")
    subscription_id: str | None = Field(None, description="StripeサブスクリプションID")
    current_period_end: str | None = Field(None, description="現在の期間終了日")
    monthly_limit: int | None = Field(None, description="月次メッセージ制限")


class PlanInfoResponse(BaseModel):
    """プラン情報レスポンス"""

    plans: dict = Field(..., description="利用可能なプラン情報")


# ========== エンドポイント ==========

@router.post("/checkout/create", response_model=CheckoutResponse)
async def create_checkout_session(
    request: CheckoutRequest,
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> CheckoutResponse:
    """
    Stripe Checkoutセッションを作成

    認証済みユーザーが指定プランのサブスクリプション登録を行うための
    Checkout URLを生成します。

    Args:
        request: Checkoutリクエスト（プラン名）
        subscription_service: サブスクリプションサービス

    Returns:
        Checkoutレスポンス（Checkout URL）

    Raises:
        HTTPException: バリデーションエラー、Stripeエラーの場合
    """
    try:
        plan = request.plan

        # プランバリデーション
        if not validate_plan_availability(plan):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid or unavailable plan: {plan}"
            )

        # ユーザーID取得（認証ミドルウェアから取得する実装が必要）
        # 仮実装としてテストユーザーIDを使用
        user_id = "test_user_id"  # TODO: 認証ミドルウェアから取得

        # Checkoutセッション作成
        checkout_url = await subscription_service.create_checkout_session(
            user_id=user_id,
            plan=plan,
        )

        logger.info(f"Created checkout session for plan {plan}")

        return CheckoutResponse(
            checkout_url=checkout_url,
            plan=plan,
        )

    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e),
        )
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Checkout session creation failed",
        )


@router.get("/plans", response_model=PlanInfoResponse)
async def get_available_plans() -> PlanInfoResponse:
    """
    利用可能なプラン情報を取得

    Returns:
        プラン情報レスポンス
    """
    try:
        plans_info = {}

        for plan_name in ["free", "basic", "pro"]:
            try:
                plan_config = get_plan_config(plan_name)
                plans_info[plan_name] = {
                    "name": plan_config["name"],
                    "monthly_limit": plan_config["monthly_limit"],
                    "available": validate_plan_availability(plan_name),
                }
            except ValueError:
                plans_info[plan_name] = {
                    "name": "Unknown",
                    "monthly_limit": 0,
                    "available": False,
                }

        return PlanInfoResponse(plans=plans_info)

    except Exception as e:
        logger.error(f"Error getting plan info: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get plan information",
        )


@router.get("/status", response_model=SubscriptionStatusResponse)
async def get_subscription_status(
    subscription_service: Annotated[SubscriptionService, Depends(get_subscription_service)],
) -> SubscriptionStatusResponse:
    """
    ユーザーのサブスクリプションステータスを取得

    Returns:
        サブスクリプションステータスレスポンス

    Raises:
        HTTPException: ステータス取得エラーの場合
    """
    try:
        # ユーザーID取得（認証ミドルウェアから取得する実装が必要）
        user_id = "test_user_id"  # TODO: 認証ミドルウェアから取得

        # サブスクリプションステータス取得
        status_data = await subscription_service.get_user_subscription_status(
            user_id
        )

        logger.info(f"Retrieved subscription status: {status_data.get('status')}")

        return SubscriptionStatusResponse(**status_data)

    except Exception as e:
        logger.error(f"Error getting subscription status: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to get subscription status",
        )
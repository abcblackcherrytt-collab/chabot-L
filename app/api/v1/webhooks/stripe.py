"""
Stripe Webhookエンドポイント
StripeからのWebhookイベントを受信・処理するエンドポイントを定義します。
"""

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.clients.stripe import StripeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])


class ErrorResponse(BaseModel):
    """エラーレスポンススキーマ"""
    error: str = Field(..., description="エラータイプ")
    message: str = Field(..., description="エラーメッセージ")
    detail: Optional[str] = Field(None, description="詳細情報")


class WebhookResponse(BaseModel):
    """Webhookレスポンススキーマ"""
    status: str = Field(..., description="処理ステータス")
    event_id: str = Field(..., description="イベントID")
    event_type: str = Field(..., description="イベントタイプ")


@router.post(
    "/stripe",
    status_code=status.HTTP_200_OK,
    response_model=WebhookResponse,
    responses={
        400: {"model": ErrorResponse, "description": "バリデーションエラー"},
        401: {"model": ErrorResponse, "description": "署名検証エラー"},
        500: {"model": ErrorResponse, "description": "サーバーエラー"},
    },
)
async def handle_stripe_webhook(
    request: Request,
    stripe_signature: str = Header(..., alias="stripe-signature"),
):
    """
    Stripe Webhookイベントを処理します

    署名検証とイベント処理を行います。
    """
    from app.clients.stripe import StripeClient
    from app.services.stripe_service import StripeService

    try:
        # 生のリクエストボディを取得（重要：JSONパース前）
        payload_bytes = await request.body()

        if not payload_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty request body",
            )

        # Stripeクライアントで署名検証
        stripe_client = StripeClient()
        stripe_client.verify_webhook_signature(
            payload=payload_bytes,
            signature_header=stripe_signature,
        )

        # 署名が有効なため、ペイロードをパース
        import json
        event = json.loads(payload_bytes.decode("utf-8"))

        logger.info(
            f"Received Stripe webhook: {event.get('type')} "
            f"(id: {event.get('id')})"
        )

        # Stripeサービスでイベント処理
        stripe_service = StripeService(stripe_client=stripe_client)
        success = await stripe_service.process_webhook_event(event=event)

        if not success:
            logger.warning(f"Webhook event processing failed: {event.get('id')}")
            # 失敗しても200を返す（再試行を防ぐため）
            # Stripeは200以外のステータスで再試行する

        return WebhookResponse(
            status="processed",
            event_id=event.get("id", ""),
            event_type=event.get("type", ""),
        )

    except StripeError as e:
        logger.error(f"Stripe error in webhook: {e}")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(e),
        )

    except json.JSONDecodeError as e:
        logger.error(f"JSON decode error: {e}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid JSON payload",
        )

    except HTTPException:
        raise

    except Exception as e:
        logger.error(f"Error processing webhook: {e}", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal server error",
        )

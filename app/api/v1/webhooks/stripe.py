"""
Stripe Webhookエンドポイント
StripeからのWebhookイベントを受信・処理するエンドポイントを定義します。
"""

import json
import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field

from app.clients.stripe import StripeError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["Webhooks"])
MAX_WEBHOOK_BODY_BYTES = 1024 * 1024


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

    署名検証後にFirestoreで冪等処理し、業務処理失敗時はStripeが
    再送できるようHTTP 500を返します。
    """
    from app.clients.stripe import StripeClient
    from app.services.stripe_service import StripeService

    try:
        content_length = request.headers.get("content-length")
        if content_length and int(content_length) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload too large",
            )

        # 生のリクエストボディを取得（重要：JSONパース前）
        payload_bytes = await request.body()

        if not payload_bytes:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty request body",
            )
        if len(payload_bytes) > MAX_WEBHOOK_BODY_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                detail="Webhook payload too large",
            )

        # Stripeクライアントで署名検証
        stripe_client = StripeClient()
        stripe_client.verify_webhook_signature(
            payload=payload_bytes,
            signature_header=stripe_signature,
        )

        # 署名が有効なため、ペイロードをパース
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
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Webhook event processing failed",
            )

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

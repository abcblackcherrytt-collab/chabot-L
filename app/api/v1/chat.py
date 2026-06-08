"""
チャットAPIエンドポイント
Discodeチャットボットとの連携APIを定義します。
"""

import logging
from typing import TYPE_CHECKING, Annotated, Any, Dict

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query as QueryField, Request
from pydantic import BaseModel, Field

from app.core.deps import get_current_user
from app.models.user import User

if TYPE_CHECKING:
    from app.services.discode_service import DiscodeService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["チャットボット"])


class ChatRequest(BaseModel):
    """チャットリクエストスキーマ"""
    message: str = Field(..., min_length=1, max_length=1000, description="チャットメッセージ")
    channel_id: str | None = Field(None, description="チャンネルID")
    user_id: str | None = Field(None, description="ユーザーID")
    include_context: bool | None = Field(False, description="コンテキストを含めるか")


class ChatResponse(BaseModel):
    """チャットレスポンススキーマ"""
    answer: str = Field(..., description="AIによる回答")
    user_id: str | None = Field(None, description="ユーザーID")
    confidence: float | None = Field(None, description="信頼度（0.0〜1.0）")
    contexts: list[dict[str, Any]] | None = Field(None, description="参照されたコンテキスト")
    denied: bool = Field(default=False, description="回答が拒否されたか")
    reason: str | None = Field(None, description="拒否理由")


class ErrorResponse(BaseModel):
    """エラーレスポンススキーマ"""
    error: str = Field(..., description="エラータイプ")
    message: str = Field(..., description="エラーメッセージ")
    detail: str | None = Field(None, description="詳細情報")


class HealthCheckResponse(BaseModel):
    """ヘルスチェックレスポンス"""
    status: str = Field(..., description="ステータス")
    service: str = Field(..., description="サービス名")


class DeepHealthCheckResponse(BaseModel):
    """詳細ヘルスチェックレスポンス"""
    status: str = Field(..., description="ステータス")
    service: str = Field(..., description="サービス名")
    services: Dict[str, Dict[str, Any]] = Field(..., description="サービスの詳細情報")


async def send_discode_message(
    channel_id: str,
    text: str,
    user_id: str | None,
    discode_service: "DiscodeService",
):
    """
    Discodeへのメッセージ送信をバックグラウンドで実行します

    送信失敗時はログに記録し、ユーザー応答には影響しません。
    """
    try:
        await discode_service.send_chat_message(
            channel_id=channel_id,
            text=text,
            user_id=user_id,
        )
        logger.debug(f"Message sent to channel: {channel_id}")
    except Exception as e:
        logger.error(f"Failed to send message to Discode (channel: {channel_id}): {e}")
        # 必要に応じて再試行ロジックや監査ログを追加


@router.post(
    "/message",
    response_model=ChatResponse,
    status_code=200,
    responses={
        400: {"model": ErrorResponse, "description": "バリデーションエラー"},
        401: {"model": ErrorResponse, "description": "認証エラー"},
        403: {"model": ErrorResponse, "description": "権限エラー"},
        500: {"model": ErrorResponse, "description": "サーバーエラー"},
    },
)
async def send_message(
    request: ChatRequest,
    background_tasks: BackgroundTasks,
    http_request: Request,
    current_user: Annotated[User, Depends(get_current_user)],
) -> ChatResponse:
    """
    チャットメッセージを送信してAIの回答を取得します

    Discodeチャットボットとして動作し、RAGサービスを使用して回答を生成します。
    認証されたユーザーのみアクセス可能です。
    Discodeへの送信はバックグラウンドで実行され、ユーザー応答には影響しません。
    """
    # アプリケーション状態からサービスを取得（lifespanで初期化済み）
    rag_service = http_request.app.state.rag_service
    discode_service = http_request.app.state.discode_service

    try:
        # RAGで回答を生成（max_results=3で軽量化、include_contextはリクエスト次第）
        rag_result = await rag_service.query(
            text=request.message,
            max_results=3,
            include_context=request.include_context,
            user_id=str(current_user.id),
            metadata={"channel_id": request.channel_id},
        )

        # 回答が拒否された場合
        if rag_result.get("denied"):
            logger.debug(f"RAG query denied: {rag_result.get('reason')}")

        # Discodeチャンネルへの送信をバックグラウンドタスクに追加
        if request.channel_id:
            background_tasks.add_task(
                send_discode_message,
                channel_id=request.channel_id,
                text=rag_result.get("answer", ""),
                user_id=str(current_user.id),
                discode_service=discode_service,
            )

        return ChatResponse(
            answer=rag_result.get("answer", ""),
            user_id=str(current_user.id),
            confidence=rag_result.get("confidence"),
            contexts=rag_result.get("contexts") if request.include_context else None,
            denied=rag_result.get("denied", False),
            reason=rag_result.get("reason"),
        )

    except Exception as e:
        logger.error(f"Error processing chat message: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )


@router.get(
    "/health",
    response_model=HealthCheckResponse,
    status_code=200,
    responses={
        500: {"model": ErrorResponse, "description": "サーバーエラー"},
    },
)
async def health_check() -> HealthCheckResponse:
    """
    チャットサービスの軽量ヘルスチェックを行います

    プロセス生存確認のみを行い、外部API呼び出しは行いません。
    """
    return HealthCheckResponse(
        status="healthy",
        service="chat",
    )


@router.get(
    "/health/deep",
    response_model=DeepHealthCheckResponse,
    status_code=200,
    responses={
        500: {"model": ErrorResponse, "description": "サーバーエラー"},
    },
)
async def deep_health_check(http_request: Request) -> DeepHealthCheckResponse:
    """
    チャットサービスの詳細ヘルスチェックを行います

    外部API（RAG/Discode）の疎通確認を行います。
    """
    rag_service = http_request.app.state.rag_service
    discode_service = http_request.app.state.discode_service

    try:
        # 両サービスのヘルスチェックを並列実行
        import asyncio

        rag_health: dict[str, Any]
        discode_health: dict[str, Any]
        rag_health, discode_health = await asyncio.gather(
            rag_service.health_check(),
            discode_service.health_check(),
            return_exceptions=True,
        )

        # 例外が発生した場合はunhealthyを返す
        if isinstance(rag_health, Exception):
            rag_health = {"status": "unhealthy", "error": str(rag_health)}
        if isinstance(discode_health, Exception):
            discode_health = {"status": "unhealthy", "error": str(discode_health)}

        overall_status = "healthy" if (
            rag_health.get("status") == "healthy" and
            discode_health.get("status") == "healthy"
        ) else "unhealthy"

        return DeepHealthCheckResponse(
            status=overall_status,
            service="chat",
            services={
                "rag": rag_health,
                "discode": discode_health,
            },
        )

    except Exception as e:
        logger.error(f"Deep health check failed: {e}")
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        )

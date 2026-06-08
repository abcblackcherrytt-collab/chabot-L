"""
Discord Interactions エンドポイント
DiscordのスラッシュコマンドInteractionsを処理します。
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Request, Response

from app.core.config import settings
from app.core.security import verify_discord_signature
from app.services.discode_service import DiscodeService
from app.services.rag_service import RAGService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/interactions", tags=["Discord Interactions"])


async def process_chat_command(
    interaction_token: str,
    message: str,
    rag_service: RAGService,
    discode_service: DiscodeService,
) -> None:
    """
    スラッシュコマンドをバックグラウンドで処理します

    Vertex AIに問い合わせ、結果をDiscordのdeferredメッセージに反映します。

    Args:
        interaction_token: Interactionのトークン
        message: ユーザーのメッセージ
        rag_service: RAGサービスインスタンス
        discode_service: Discodeサービスインスタンス
    """
    try:
        logger.info(f"Processing chat command: {message[:50]}...")

        # Vertex AIに問い合わせ
        rag_result = await rag_service.query(
            text=message,
            max_results=3,
        )

        answer = rag_result.get("answer", "申し訳ありません、回答を生成できませんでした。")
        logger.info("RAG query completed, sending response")

        # deferredメッセージを更新
        await discode_service.edit_interaction_response(
            interaction_token=interaction_token,
            content=answer,
        )

    except Exception as e:
        logger.error(f"Error processing chat command: {e}")
        # エラー時もユーザーに通知
        try:
            await discode_service.edit_interaction_response(
                interaction_token=interaction_token,
                content="申し訳ありません、エラーが発生しました。しばらくしてからもう一度お試しください。",
            )
        except Exception as followup_error:
            logger.error(f"Failed to send error response: {followup_error}")


@router.post("/discord")
async def handle_discord_interaction(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    Discord Interactionsを処理します

    DiscordからのスラッシュコマンドInteractionを受け付けます。
    Ed25519署名でリクエストを検証し、PINGまたはAPPLICATION_COMMANDを処理します。

    Returns:
        PING: {"type": 1}
        APPLICATION_COMMAND: {"type": 5}（deferred response）
    """
    # raw bodyを取得（署名検証に必要）
    body = await request.body()

    # 署名ヘッダーを取得
    signature = request.headers.get("X-Signature-Ed25519")
    timestamp = request.headers.get("X-Signature-Timestamp")

    # Ed25519署名検証
    if not verify_discord_signature(
        public_key=settings.resolved_discord_public_key,
        signature=signature or "",
        timestamp=timestamp or "",
        body=body,
    ):
        logger.warning("Invalid Discord signature")
        return Response(
            content=json.dumps({"error": "Invalid signature"}),
            status_code=401,
            media_type="application/json",
        )

    # JSONパース
    try:
        data: Dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in Discord interaction")
        return Response(
            content=json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            media_type="application/json",
        )

    interaction_type = data.get("type")

    # PING → PONG
    if interaction_type == 1:
        logger.info("Received Discord PING, responding with PONG")
        return Response(
            content=json.dumps({"type": 1}),
            media_type="application/json",
        )

    # APPLICATION_COMMAND（スラッシュコマンド）
    if interaction_type == 2:
        interaction_token = data.get("token", "")
        command_data = data.get("data", {})
        command_name = command_data.get("name", "")

        logger.info(f"Received Discord command: /{command_name}")

        # /chat コマンドの処理
        if command_name == "chat":
            # オプションからメッセージを取得
            options = command_data.get("options", [])
            message = ""
            for option in options:
                if option.get("name") == "message":
                    message = option.get("value", "")
                    break

            if not message:
                return Response(
                    content=json.dumps({
                        "type": 4,
                        "data": {"content": "メッセージを入力してください。"},
                    }),
                    media_type="application/json",
                )

            # 即座にdeferred responseを返却（3秒以内）
            # バックグラウンドでVertex AI処理を実行
            background_tasks.add_task(
                process_chat_command,
                interaction_token=interaction_token,
                message=message,
                rag_service=request.app.state.rag_service,
                discode_service=request.app.state.discode_service,
            )

            return Response(
                content=json.dumps({"type": 5}),
                media_type="application/json",
            )

        # 未対応のコマンド
        logger.warning(f"Unknown command: {command_name}")
        return Response(
            content=json.dumps({
                "type": 4,
                "data": {"content": f"コマンド `/{command_name}` は未対応です。"},
            }),
            media_type="application/json",
        )

    # その他のInteraction type
    logger.warning(f"Unknown interaction type: {interaction_type}")
    return Response(
        content=json.dumps({"error": "Unknown interaction type"}),
        status_code=400,
        media_type="application/json",
    )

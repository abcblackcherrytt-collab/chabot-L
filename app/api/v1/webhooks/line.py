"""
LINE Webhook エンドポイント
LINE Messaging APIからのWebhookイベントを処理します。
"""

import json
import logging
from typing import Any, Dict

from fastapi import APIRouter, BackgroundTasks, Request
from fastapi.responses import Response

from app.core.config import settings
from app.core.security import verify_webhook_signature

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/webhooks", tags=["LINE Webhooks"])


async def _process_line_events(
    events: list,
    line_service: Any,
    rag_service: Any,
) -> None:
    """
    LINE イベントをバックグラウンドで処理します

    Webhook は即座に 200 OK を返す必要があるため、
    メッセージ処理はバックグラウンドタスクで実行します。

    Phase 1（現在）のメインフロー（Stripe/DB 不要）:
      message イベント → RAG 応答生成 → リプライ送信。
    Phase 2: line_service.process_webhook_event 内でサブスク検証が入り、
      result に制限/拒否フラグが設定される（下記 [Phase 2] マーカー参照）。

    Args:
        events: LINE イベントのリスト
        line_service: LineService インスタンス
        rag_service: RAGService インスタンス
    """
    for event in events:
        try:
            result = await line_service.process_webhook_event(event)

            if not result:
                continue

            # メッセージイベントの場合、RAGで応答生成
            # [Phase 2] ここでサブスク検証結果を分岐する接続ポイント。
            #   Phase 2 では result に制限/拒否フラグを持たせ、
            #   未契約/期限切れの場合は RAG クエリせず制限メッセージを返す。
            if (
                result.get("status") == "processed"
                and result.get("message")
                and result.get("reply_token")
            ):
                try:
                    rag_result = await rag_service.query(
                        text=result["message"],
                        max_results=3,
                    )
                    answer = rag_result.get(
                        "answer",
                        "申し訳ありません、回答を生成できませんでした。",
                    )
                except Exception as e:
                    logger.error(f"RAG query failed: {e}")
                    answer = (
                        "申し訳ありません、エラーが発生しました。"
                        "しばらくしてからもう一度お試しください。"
                    )

                # リプライ送信
                await line_service._send_reply(result["reply_token"], answer)

        except Exception as e:
            logger.error(f"Error processing LINE event: {e}")


@router.post("/line")
async def handle_line_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Response:
    """
    LINE Webhook を処理します

    LINE Platform からの Webhook リクエストを受け付けます。
    HMAC-SHA256 署名でリクエストを検証し、即座に 200 OK を返却した後、
    バックグラウンドでメッセージ処理を実行します。

    Returns:
        200 OK（即座に返却）
    """
    # raw body を取得（署名検証に必要）
    body = await request.body()

    # 署名ヘッダーを取得
    signature = request.headers.get("X-Line-Signature", "")

    # 署名検証
    if not verify_webhook_signature(body, signature, settings.line_channel_secret):
        logger.warning("Invalid LINE webhook signature")
        return Response(
            content=json.dumps({"error": "Invalid signature"}),
            status_code=401,
            media_type="application/json",
        )

    # JSON パース
    try:
        data: Dict[str, Any] = json.loads(body)
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in LINE webhook")
        return Response(
            content=json.dumps({"error": "Invalid JSON"}),
            status_code=400,
            media_type="application/json",
        )

    # イベントを取得
    events = data.get("events", [])
    if not events:
        return Response(content="{}", media_type="application/json")

    # バックグラウンドでイベント処理
    background_tasks.add_task(
        _process_line_events,
        events=events,
        line_service=request.app.state.line_service,
        rag_service=request.app.state.rag_service,
    )

    # 即座に 200 OK を返す（LINE の要件）
    return Response(content="{}", media_type="application/json")

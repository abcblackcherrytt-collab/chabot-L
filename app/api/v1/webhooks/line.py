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
from app.db.session import async_session_maker

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

    並列化最適化（Step 2.5）:
      FirestoreアクセスとRAG処理を並列実行し、レスポンス時間を100-300ms短縮します。

    Args:
        events: LINE イベントのリスト
        line_service: LineService インスタンス
        rag_service: RAGService インスタンス
    """
    for event in events:
        # BackgroundTasks はリクエストスコープ外のため get_db（Depends）が使えない。
        # DATABASE_BACKEND に応じてDBセッションを取得
        try:
            # メッセージイベント以外は従来通り処理
            if event.get("type") != "message":
                if settings.database_backend == "firestore":
                    await line_service.process_webhook_event(event, db=None)
                else:
                    async with async_session_maker() as db:
                        await line_service.process_webhook_event(event, db)
                continue

            # メッセージイベントの場合、FirestoreアクセスとRAG処理を並列実行
            source = event.get("source", {})
            line_user_id = source.get("userId", "")
            reply_token = event.get("replyToken", "")
            message = event.get("message", {})

            if not reply_token or not line_user_id or message.get("type") != "text":
                continue

            user_message = message.get("text", "").strip()
            if not user_message:
                continue

            logger.info(f"Processing message from LINE user: {line_user_id[:4]}...")

            # FirestoreアクセスとRAG処理を並列実行
            import asyncio

            if settings.database_backend == "firestore":
                user_data_task = asyncio.create_task(
                    line_service._get_user_data_for_parallel(line_user_id)
                )
            else:
                user_data_task = asyncio.create_task(
                    line_service._get_user_data_for_parallel(line_user_id, db_maker=async_session_maker)
                )

            rag_task = asyncio.create_task(
                rag_service.query(
                    text=user_message,
                    max_results=10,
                    user_id=line_user_id,
                )
            )

            # 並列実行の完了を待機
            user_data, rag_result = await asyncio.gather(
                user_data_task,
                rag_task,
                return_exceptions=True
            )

            # エラーハンドリング
            if isinstance(user_data, Exception):
                logger.error(f"User data fetch failed: {user_data}")
                await line_service._send_reply(
                    reply_token,
                    "申し訳ありません、ユーザー情報の取得に失敗しました。"
                )
                continue

            if isinstance(rag_result, Exception):
                logger.error(f"RAG query failed: {rag_result}")
                await line_service._send_reply(
                    reply_token,
                    "申し訳ありません、エラーが発生しました。"
                    "しばらくしてからもう一度お試しください。"
                )
                continue

            # ユーザーデータチェック
            if not user_data or user_data.get("status") == "error":
                await line_service._send_reply(
                    reply_token,
                    user_data.get("message", "ユーザー情報が見つかりません。")
                    if user_data else "ユーザー情報が見つかりません。"
                )
                continue

            # 回数制限チェック（並列実行の後に実行）
            if settings.database_backend == "firestore":
                limit_result = await line_service._check_and_increment_usage(
                    user_data["user_id"],
                    user_data["plan"]
                )
            else:
                limit_result = await line_service._check_and_increment_usage(
                    user_data["user_id"],
                    user_data["plan"],
                    db_maker=async_session_maker
                )

            if not limit_result.get("success"):
                # 回数制限超過メッセージを作成
                limit_message = f"📊 {limit_result['message']}"
                plan = user_data["plan"]
                if plan == "free":
                    limit_message += (
                        "\n\n💡 さらに利用するにはプラン登録をご検討ください。"
                        f"\n\n📱 ベーシックプラン（1日100回まで）:\n"
                        f"{settings.subscription_basic_url}"
                        f"\n\n🚀 プロプラン（1日500回まで）:\n"
                        f"{settings.subscription_pro_url}"
                    )
                elif plan == "basic":
                    limit_message += (
                        "\n\n🚀 プロプラン（1日500回まで）への変更はこちら:\n"
                        f"{settings.subscription_pro_url}"
                    )
                limit_message += "\n\n明日になると利用回数がリセットされます。"
                await line_service._send_reply(reply_token, limit_message)
                logger.info(
                    f"Daily limit reached for user {user_data['user_id']}, "
                    f"plan={plan}, discarded RAG result"
                )
                continue

            logger.info(
                f"Parallel execution completed: user_check={user_data.get('status')}, "
                f"rag_success={rag_result.get('answer', '')[:50] if rag_result else 'N/A'}..."
            )

            # RAG回答をLINE返信
            answer = rag_result.get(
                "answer",
                "申し訳ありません、回答を生成できませんでした。",
            )
            await line_service._send_reply(reply_token, answer)

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

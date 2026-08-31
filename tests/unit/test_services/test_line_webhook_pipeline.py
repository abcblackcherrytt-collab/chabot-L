"""LINE WebhookからRAG実行までの安全な処理順を検証する。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.api.v1.webhooks.line import _process_line_events
from app.services.rag_service import RAGService


@pytest.mark.asyncio
async def test_rag_runs_after_plan_resolution_with_selected_configuration() -> None:
    """確定済みのユーザーID・コーパス・モデルをRAGへ渡すこと。"""
    line_service = MagicMock()
    line_service.process_webhook_event = AsyncMock(
        return_value={
            "status": "processed",
            "message": "肩関節を評価するには？",
            "reply_token": "reply-token",
            "user_id": "user-123",
            "corpus_id": "free-corpus",
            "model_name": "gemini-test",
            "plan": "free",
        }
    )
    line_service._send_reply = AsyncMock()
    rag_service = MagicMock()
    rag_service.query = AsyncMock(return_value={"answer": "回答です"})

    await _process_line_events(
        [{"type": "message"}],
        line_service=line_service,
        rag_service=rag_service,
    )

    rag_service.query.assert_awaited_once_with(
        text="肩関節を評価するには？",
        max_results=10,
        corpus_id="free-corpus",
        model_name="gemini-test",
        plan="free",
        user_id="user-123",
    )
    line_service._send_reply.assert_awaited_once_with("reply-token", "回答です")


@pytest.mark.asyncio
async def test_limit_reached_does_not_call_rag() -> None:
    """回数上限到達時はVertex AIを呼び出さないこと。"""
    line_service = MagicMock()
    line_service.process_webhook_event = AsyncMock(
        return_value={"status": "limit_reached", "plan": "free"}
    )
    line_service._send_reply = AsyncMock()
    rag_service = MagicMock()
    rag_service.query = AsyncMock()

    await _process_line_events(
        [{"type": "message"}],
        line_service=line_service,
        rag_service=rag_service,
    )

    rag_service.query.assert_not_awaited()
    line_service._send_reply.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_uses_real_rag_service_interface() -> None:
    """Webhookと実RAGServiceの引数契約が一致すること。"""
    line_service = MagicMock()
    line_service.process_webhook_event = AsyncMock(
        return_value={
            "status": "processed",
            "message": "肩関節を評価するには？",
            "reply_token": "reply-token",
            "user_id": "user-123",
            "corpus_id": "paid-corpus",
            "model_name": "gemini-test",
            "plan": "pro",
        }
    )
    line_service._send_reply = AsyncMock()
    vertex_client = MagicMock()
    vertex_client.__aenter__ = AsyncMock(return_value=vertex_client)
    vertex_client.__aexit__ = AsyncMock(return_value=False)
    vertex_client.query = AsyncMock(return_value={"answer": "回答です"})
    rag_service = RAGService(vertex_ai_client=vertex_client)

    await _process_line_events(
        [{"type": "message"}],
        line_service=line_service,
        rag_service=rag_service,
    )

    vertex_client.query.assert_awaited_once_with(
        text="肩関節を評価するには？",
        max_results=10,
        include_context=True,
        corpus_id="paid-corpus",
        model_name="gemini-test",
        plan="pro",
    )
    line_service._send_reply.assert_awaited_once_with("reply-token", "回答です")

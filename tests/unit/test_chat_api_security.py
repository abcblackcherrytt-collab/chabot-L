"""公開チャットAPIの利用上限とRAGメタデータ保護を検証する。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import chat as chat_api


def _request_with_rag_service(rag_service: MagicMock) -> MagicMock:
    """RAGサービスを保持する最小のRequestモックを返す。"""
    request = MagicMock()
    request.app.state.rag_service = rag_service
    return request


@pytest.mark.asyncio
async def test_public_chat_rejects_context_metadata(monkeypatch) -> None:
    """公開APIからRAG文書タイトルやURIを要求できないこと。"""
    usage_repository = MagicMock()
    usage_repository.increment_with_limit_check = AsyncMock()
    monkeypatch.setattr(
        chat_api,
        "FirestoreUsageRepository",
        lambda: usage_repository,
    )

    with pytest.raises(HTTPException) as exc_info:
        await chat_api.send_message(
            request=chat_api.ChatRequest(message="質問", include_context=True),
            background_tasks=MagicMock(),
            http_request=MagicMock(),
            current_user=SimpleNamespace(
                id="user-1",
                role="user",
                subscription_plan="free",
            ),
        )

    assert exc_info.value.status_code == 403
    usage_repository.increment_with_limit_check.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_chat_applies_daily_limit_before_rag(monkeypatch) -> None:
    """日次上限到達時はVertex AIを呼び出さないこと。"""
    usage_repository = MagicMock()
    usage_repository.increment_with_limit_check = AsyncMock(
        return_value={"success": False, "remaining": 0}
    )
    monkeypatch.setattr(
        chat_api,
        "FirestoreUsageRepository",
        lambda: usage_repository,
    )
    conversation_repository = MagicMock()
    conversation_repository.save_limit_denied = AsyncMock()
    monkeypatch.setattr(
        chat_api,
        "FirestoreConversationRepository",
        lambda: conversation_repository,
    )
    rag_service = MagicMock()
    rag_service.query = AsyncMock()

    with pytest.raises(HTTPException) as exc_info:
        await chat_api.send_message(
            request=chat_api.ChatRequest(message="質問"),
            background_tasks=MagicMock(),
            http_request=_request_with_rag_service(rag_service),
            current_user=SimpleNamespace(
                id="user-1",
                role="user",
                subscription_plan="free",
            ),
        )

    assert exc_info.value.status_code == 429
    conversation_repository.save_limit_denied.assert_awaited_once_with(
        user_id="user-1",
        plan="free",
    )
    usage_repository.increment_with_limit_check.assert_awaited_once_with(
        "user-1",
        "free",
        3,
    )
    rag_service.query.assert_not_awaited()


@pytest.mark.asyncio
async def test_public_chat_never_returns_contexts(monkeypatch) -> None:
    """成功時も公開レスポンスへRAGメタデータを含めないこと。"""
    usage_repository = MagicMock()
    usage_repository.increment_with_limit_check = AsyncMock(
        return_value={"success": True, "remaining": 2}
    )
    permission_repository = MagicMock()
    permission_repository.get_by_plan = AsyncMock(
        return_value={"rag_corpus_id": "free-corpus", "model_name": "model"}
    )
    monkeypatch.setattr(
        chat_api,
        "FirestoreUsageRepository",
        lambda: usage_repository,
    )
    monkeypatch.setattr(
        chat_api,
        "FirestoreRagPermissionRepository",
        lambda: permission_repository,
    )
    rag_service = MagicMock()
    rag_service.query = AsyncMock(
        return_value={
            "answer": "回答",
            "classification": {
                "question_type": "evaluation",
                "answer_aspects": ["range_of_motion"],
            },
            "contexts": [{"content": "private", "source": "private-uri"}],
            "denied": False,
        }
    )
    background_tasks = MagicMock()

    response = await chat_api.send_message(
        request=chat_api.ChatRequest(message="質問"),
        background_tasks=background_tasks,
        http_request=_request_with_rag_service(rag_service),
        current_user=SimpleNamespace(
            id="user-1",
            role="user",
            subscription_plan="free",
        ),
    )

    assert response.answer == "回答"
    assert response.contexts is None
    background_tasks.add_task.assert_called_once()
    assert background_tasks.add_task.call_args.args[0] == chat_api.save_chat_conversation
    assert background_tasks.add_task.call_args.kwargs == {
        "user_id": "user-1",
        "question_text": "質問",
        "answer_text": "回答",
        "plan": "free",
        "denied": False,
        "question_type": "evaluation",
        "answer_aspects": ["range_of_motion"],
    }
    rag_service.query.assert_awaited_once_with(
        text="質問",
        max_results=10,
        include_context=False,
        user_id="user-1",
        corpus_id="free-corpus",
        model_name="model",
        plan="free",
    )


@pytest.mark.asyncio
async def test_chat_conversation_save_failure_does_not_raise(monkeypatch) -> None:
    """保存失敗時にAPI応答後の保存タスクが例外を外へ出さないこと。"""
    conversation_repository = MagicMock()
    conversation_repository.save_conversation = AsyncMock(
        side_effect=RuntimeError("firestore unavailable")
    )
    monkeypatch.setattr(
        chat_api,
        "FirestoreConversationRepository",
        lambda: conversation_repository,
    )

    await chat_api.save_chat_conversation(
        user_id="user-1",
        question_text="質問",
        answer_text="回答",
        plan="free",
        denied=False,
        question_type=None,
        answer_aspects=[],
    )

    conversation_repository.save_conversation.assert_awaited_once()

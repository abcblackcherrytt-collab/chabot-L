"""公開チャットAPIの利用上限とRAGメタデータ保護を検証する。"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.api.v1 import chat as chat_api


@pytest.fixture(autouse=True)
def _mock_plan_settings(monkeypatch) -> None:
    """plan_settings読み取りをモックし、実Firestoreへ接続しないようにする。"""
    repository = MagicMock()
    repository.get_published_daily_limit = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "app.repositories.firestore_plan_settings_repository.FirestorePlanSettingsRepository",
        lambda: repository,
    )


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
        "reasoning_roles": [],
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
        reasoning_roles=[],
    )

    conversation_repository.save_conversation.assert_awaited_once()


@pytest.mark.asyncio
async def test_deep_health_rejects_unauthenticated_without_external_calls() -> None:
    """未認証のdeep healthアクセスを拒否し、外部APIを呼び出させないこと。"""
    from httpx import ASGITransport, AsyncClient

    from app.server import app

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/chat/health/deep")

    assert response.status_code == 401


@pytest.mark.asyncio
async def test_deep_health_rejects_non_admin_user(monkeypatch) -> None:
    """一般ユーザーのdeep healthアクセスを403で拒否すること。"""
    from httpx import ASGITransport, AsyncClient

    from app.core.deps import get_current_user
    from app.server import app

    async def _regular_user():
        return SimpleNamespace(id="user-1", role="user")

    app.dependency_overrides[get_current_user] = _regular_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/chat/health/deep")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 403


@pytest.mark.asyncio
async def test_deep_health_for_admin_hides_exception_details(monkeypatch) -> None:
    """管理者のdeep healthで例外が発生しても、応答へ例外文字列を出さないこと。"""
    from httpx import ASGITransport, AsyncClient

    from app.core.deps import get_current_user
    from app.server import app

    rag_service = MagicMock()
    rag_service.health_check = AsyncMock(
        side_effect=Exception("projects/secret-project/locations/us-central1 leaked")
    )
    line_service = MagicMock()
    line_service.health_check = AsyncMock(
        return_value={"status": "healthy", "service": "line"}
    )
    app.state.rag_service = rag_service
    app.state.line_service = line_service

    async def _admin_user():
        return SimpleNamespace(id="admin-1", role="admin")

    app.dependency_overrides[get_current_user] = _admin_user
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/v1/chat/health/deep")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "unhealthy"
    assert body["services"]["rag"]["error"] == "RAG service unavailable"
    assert "secret-project" not in response.text


def test_openapi_docs_are_hidden_only_in_production(monkeypatch) -> None:
    """本番構成ではOpenAPIとdocs UIを無効化し、開発構成では有効に保つこと。"""
    from app.core.config import settings
    from app.server import create_app

    monkeypatch.setattr(settings, "app_env", "development")
    dev_app = create_app()
    assert dev_app.docs_url == "/docs"
    assert dev_app.openapi_url == "/openapi.json"

    monkeypatch.setattr(settings, "app_env", "production")
    prod_app = create_app()
    assert prod_app.docs_url is None
    assert prod_app.redoc_url is None
    assert prod_app.openapi_url is None

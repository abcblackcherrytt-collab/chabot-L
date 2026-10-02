"""AdminService.list_corpora（管理UIコーパスタブ）の単体テスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

import app.services.admin_service as admin_service_module
from app.clients.vertex_ai_rag import VertexRagCorpusError
from app.core.config import settings
from app.services.admin_service import AdminService


def _service(get_by_plan) -> AdminService:
    """外部依存を置き換えたAdminServiceを組立てる。"""
    repo = MagicMock()
    repo.get_by_plan = AsyncMock(side_effect=get_by_plan)
    return AdminService(
        plan_settings_repository=MagicMock(),
        invite_repository=MagicMock(),
        coupon_repository=MagicMock(),
        audit_repository=MagicMock(),
        feedback_repository=MagicMock(),
        stats_repository=MagicMock(),
        admin_user_repository=MagicMock(),
        user_repository=MagicMock(),
        conversation_repository=MagicMock(),
        representative_answer_repository=MagicMock(),
        rag_permission_repository=repo,
    )


def _perm(plan: str, corpus_id: str) -> dict:
    return {
        "plan": plan,
        "rag_corpus_id": corpus_id,
        "model_name": "gemini-3.5-flash-lite",
        "daily_message_limit": 3,
        "enabled": True,
        "updated_at": "2026-09-30T00:00:00+09:00",
    }


@pytest.mark.asyncio
async def test_corpora_orders_plans_and_dedupes_vertex_calls(monkeypatch) -> None:
    """free/basic/pro順で返し、同一コーパスIDのVertex参照を1回にまとめること。"""
    monkeypatch.setattr(settings, "google_corpus_id", "111")
    monkeypatch.setattr(settings, "google_corpus_id_plan1", "222")
    overview = AsyncMock(
        return_value={"display_name": "shoulder", "description": "", "create_time": "", "file_count": 1, "files": []}
    )
    monkeypatch.setattr(admin_service_module, "get_corpus_overview", overview)

    perm_by_plan = {"free": _perm("free", "111"), "basic": _perm("basic", "222"), "pro": _perm("pro", "222")}
    result = await _service(lambda plan: perm_by_plan[plan]).list_corpora()

    assert [item["plan"] for item in result["items"]] == ["free", "basic", "pro"]
    assert result["location"] == settings.google_location
    assert result["items"][0]["source"] == "firestore"
    assert result["items"][0]["corpus"]["display_name"] == "shoulder"
    assert result["items"][1]["corpus"]["display_name"] == "shoulder"
    overview.assert_any_await("111")
    overview.assert_any_await("222")
    assert overview.await_count == 2


@pytest.mark.asyncio
async def test_corpora_falls_back_when_plan_missing(monkeypatch) -> None:
    """rag_permissions未設定プランは設定fallbackを表示すること。"""
    monkeypatch.setattr(settings, "google_corpus_id", "111")
    monkeypatch.setattr(settings, "google_corpus_id_plan1", "222")
    overview = AsyncMock(return_value={"display_name": "x", "description": "", "create_time": "", "file_count": 0, "files": []})
    monkeypatch.setattr(admin_service_module, "get_corpus_overview", overview)

    result = await _service(lambda plan: None).list_corpora()

    free = result["items"][0]
    paid = result["items"][1]
    assert free["configured"] is False
    assert free["source"] == "fallback"
    assert free["rag_corpus_id"] == "111"
    assert paid["rag_corpus_id"] == "222"
    assert free["daily_message_limit"] is None


@pytest.mark.asyncio
async def test_corpora_degrades_when_vertex_fails(monkeypatch) -> None:
    """Vertex参照失敗はHTTP例外にせずstatus=errorを返すこと。"""
    monkeypatch.setattr(settings, "google_corpus_id", "111")
    monkeypatch.setattr(settings, "google_corpus_id_plan1", "111")
    overview = AsyncMock(side_effect=VertexRagCorpusError("NotFound"))
    monkeypatch.setattr(admin_service_module, "get_corpus_overview", overview)

    result = await _service(lambda plan: None).list_corpora()

    assert overview.await_count == 1
    assert result["items"][0]["corpus"]["status"] == "error"
    assert result["items"][0]["corpus"]["error"] == "NotFound"
    assert result["items"][0]["rag_corpus_id"] == "111"


@pytest.mark.asyncio
async def test_corpora_survives_firestore_read_error(monkeypatch) -> None:
    """rag_permissions読取失敗時もfallback表示で応答すること。"""
    monkeypatch.setattr(settings, "google_corpus_id", "111")
    monkeypatch.setattr(settings, "google_corpus_id_plan1", "222")
    overview = AsyncMock(return_value={"display_name": "x", "description": "", "create_time": "", "file_count": 0, "files": []})
    monkeypatch.setattr(admin_service_module, "get_corpus_overview", overview)

    def raise_for(plan: str):
        raise RuntimeError("firestore down")

    result = await _service(raise_for).list_corpora()

    assert result["items"][0]["firestore_error"] == "RuntimeError"
    assert result["items"][0]["source"] == "fallback"
    assert result["items"][2]["plan"] == "pro"


@pytest.mark.asyncio
async def test_corpora_marks_placeholder_ids_unconfigured(monkeypatch) -> None:
    """プレースホルダIDはVertex参照せず未設定扱いにすること。"""
    monkeypatch.setattr(settings, "google_corpus_id", "your-free-corpus-id")
    monkeypatch.setattr(settings, "google_corpus_id_plan1", "your-paid-corpus-id")
    overview = AsyncMock()
    monkeypatch.setattr(admin_service_module, "get_corpus_overview", overview)

    result = await _service(lambda plan: None).list_corpora()

    overview.assert_not_awaited()
    assert result["items"][0]["corpus"]["status"] == "unconfigured"

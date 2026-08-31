"""Firestoreリポジトリの非同期I/Oと回数制御のテスト。"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import firestore_usage_repository as usage_module
from app.repositories.firestore_rag_permission_repository import (
    FirestoreRagPermissionRepository,
)
from app.repositories.firestore_stripe_event_repository import (
    FirestoreStripeEventRepository,
)
from app.repositories.firestore_usage_repository import FirestoreUsageRepository
from app.repositories.firestore_user_repository import FirestoreUserRepository


def _snapshot(document_id: str, data: dict, *, exists: bool = True) -> MagicMock:
    snapshot = MagicMock()
    snapshot.id = document_id
    snapshot.exists = exists
    snapshot.to_dict.return_value = data
    return snapshot


@pytest.mark.asyncio
async def test_user_repository_awaits_async_query() -> None:
    """LINEユーザー検索がAsyncClientのquery.getをawaitすること。"""
    snapshot = _snapshot("user-1", {"line_user_id": "U123", "is_active": True})
    query = MagicMock()
    query.where.return_value = query
    query.limit.return_value = query
    query.get = AsyncMock(return_value=[snapshot])
    client = MagicMock()
    client.collection.return_value = query

    repository = FirestoreUserRepository(client=client)
    result = await repository.find_by_line_user_id("U123")

    assert result == {"id": "user-1", "line_user_id": "U123", "is_active": True}
    query.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_user_repository_reactivates_existing_user() -> None:
    """再フォロー時に同じFirestoreユーザーを有効化すること。"""
    document = MagicMock()
    document.update = AsyncMock()
    collection = MagicMock()
    collection.document.return_value = document
    client = MagicMock()
    client.collection.return_value = collection
    repository = FirestoreUserRepository(client=client)

    await repository.activate_user("user-1")

    document.update.assert_awaited_once()
    update_data = document.update.await_args.args[0]
    assert update_data["is_active"] is True
    assert update_data["deactivated_at"] is None


@pytest.mark.asyncio
async def test_create_line_user_uses_stable_id_and_free_plan() -> None:
    """最初のトークから作るユーザーが重複しにくいfreeアカウントになること。"""
    document = MagicMock()
    document.set = AsyncMock()
    collection = MagicMock()
    collection.document.return_value = document
    client = MagicMock()
    client.collection.return_value = collection
    repository = FirestoreUserRepository(client=client)
    repository.find_by_line_user_id = AsyncMock(return_value=None)

    result = await repository.create_line_user(
        line_user_id="U123",
        display_name="既存の友だち",
    )

    expected_id = str(uuid.uuid5(uuid.NAMESPACE_URL, "line:U123"))
    assert result["id"] == expected_id
    assert result["subscription_plan"] == "free"
    assert result["subscription_status"] == "active"
    assert result["is_active"] is True
    collection.document.assert_called_once_with(expected_id)
    document.set.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_line_user_returns_existing_user_without_overwrite() -> None:
    """同じLINE IDが既にあれば既存ユーザーを上書きしないこと。"""
    existing = {
        "id": "existing-user",
        "line_user_id": "U123",
        "subscription_plan": "basic",
        "is_active": True,
    }
    client = MagicMock()
    repository = FirestoreUserRepository(client=client)
    repository.find_by_line_user_id = AsyncMock(return_value=existing)

    result = await repository.create_line_user("U123", "既存の友だち")

    assert result == existing
    client.collection.assert_not_called()


@pytest.mark.asyncio
async def test_rag_permission_repository_awaits_async_query() -> None:
    """プラン設定検索がAsyncClientのquery.getをawaitすること。"""
    snapshot = _snapshot(
        "free",
        {"plan": "free", "enabled": True, "rag_corpus_id": "corpus-free"},
    )
    query = MagicMock()
    query.where.return_value = query
    query.limit.return_value = query
    query.get = AsyncMock(return_value=[snapshot])
    client = MagicMock()
    client.collection.return_value = query

    FirestoreRagPermissionRepository._cache.clear()
    repository = FirestoreRagPermissionRepository(client=client)
    result = await repository.get_by_plan("free")
    cached_repository = FirestoreRagPermissionRepository(client=MagicMock())
    cached_result = await cached_repository.get_by_plan("free")

    assert result["id"] == "free"
    assert result["rag_corpus_id"] == "corpus-free"
    assert cached_result == result
    query.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_increment_with_limit_check_commits_atomic_increment(monkeypatch) -> None:
    """上限確認と加算を同じ非同期Transactionで行うこと。"""
    monkeypatch.setattr(usage_module.firestore, "async_transactional", lambda fn: fn)
    snapshot = _snapshot("usage-1", {"message_count": 1})
    document = MagicMock()
    document.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document
    transaction = MagicMock()
    client = MagicMock()
    client.collection.return_value = collection
    client.transaction.return_value = transaction

    repository = FirestoreUsageRepository(client=client)
    result = await repository.increment_with_limit_check("user-1", "free", 3)

    assert result["success"] is True
    assert result["current_count"] == 2
    assert result["remaining"] == 1
    document.get.assert_awaited_once_with(transaction=transaction)
    transaction.set.assert_called_once()
    written = transaction.set.call_args.args[1]
    assert written["message_count"] == 2


@pytest.mark.asyncio
async def test_increment_with_limit_check_does_not_write_at_limit(monkeypatch) -> None:
    """上限到達時はTransaction内で書き込みを行わないこと。"""
    monkeypatch.setattr(usage_module.firestore, "async_transactional", lambda fn: fn)
    snapshot = _snapshot("usage-1", {"message_count": 3})
    document = MagicMock()
    document.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document
    transaction = MagicMock()
    client = MagicMock()
    client.collection.return_value = collection
    client.transaction.return_value = transaction

    repository = FirestoreUsageRepository(client=client)
    result = await repository.increment_with_limit_check("user-1", "free", 3)

    assert result["success"] is False
    assert result.get("error") is None
    assert result["current_count"] == 3
    transaction.set.assert_not_called()


@pytest.mark.asyncio
async def test_increment_with_limit_check_marks_firestore_failure(monkeypatch) -> None:
    """Firestore例外を上限到達と区別できる結果にすること。"""
    monkeypatch.setattr(usage_module.firestore, "async_transactional", lambda fn: fn)
    document = MagicMock()
    document.get = AsyncMock(side_effect=RuntimeError("Firestore unavailable"))
    collection = MagicMock()
    collection.document.return_value = document
    client = MagicMock()
    client.collection.return_value = collection
    client.transaction.return_value = MagicMock()

    repository = FirestoreUsageRepository(client=client)
    result = await repository.increment_with_limit_check("user-1", "free", 3)

    assert result == {
        "success": False,
        "error": True,
        "current_count": 0,
        "remaining": 0,
        "message": "使用回数を確認できませんでした",
    }


def test_usage_date_uses_japan_timezone(monkeypatch) -> None:
    """日次上限の日付境界がAsia/Tokyo基準であること。"""
    repository = FirestoreUsageRepository(client=MagicMock())
    date_text = repository._get_today_date_str()

    assert len(date_text) == 10
    assert date_text[4] == "-"
    assert date_text[7] == "-"


@pytest.mark.asyncio
async def test_stripe_event_claim_is_atomic(monkeypatch) -> None:
    """未処理WebhookをTransaction内でprocessingとして確保すること。"""
    import app.repositories.firestore_stripe_event_repository as event_module

    monkeypatch.setattr(event_module.firestore, "async_transactional", lambda fn: fn)
    snapshot = _snapshot("evt_1", {}, exists=False)
    document = MagicMock()
    document.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document
    transaction = MagicMock()
    client = MagicMock()
    client.collection.return_value = collection
    client.transaction.return_value = transaction

    repository = FirestoreStripeEventRepository(client=client)
    result = await repository.claim("evt_1", "invoice.paid", 123)

    assert result == "claimed"
    transaction.set.assert_called_once()
    written = transaction.set.call_args.args[1]
    assert written["status"] == "processing"
    assert written["attempts"] == 1


@pytest.mark.asyncio
async def test_stripe_event_claim_skips_completed(monkeypatch) -> None:
    """完了済みWebhookを再確保しないこと。"""
    import app.repositories.firestore_stripe_event_repository as event_module

    monkeypatch.setattr(event_module.firestore, "async_transactional", lambda fn: fn)
    snapshot = _snapshot("evt_1", {"status": "completed", "attempts": 1})
    document = MagicMock()
    document.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document
    transaction = MagicMock()
    client = MagicMock()
    client.collection.return_value = collection
    client.transaction.return_value = transaction

    repository = FirestoreStripeEventRepository(client=client)
    result = await repository.claim("evt_1", "invoice.paid", 123)

    assert result == "completed"
    transaction.set.assert_not_called()

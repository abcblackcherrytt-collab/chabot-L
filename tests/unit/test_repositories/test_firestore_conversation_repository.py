"""Firestore会話保存リポジトリ（利用者非紐付け版）のテスト。"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories.firestore_conversation_repository import (
    FirestoreConversationRepository,
)


def _client_with_add(document_id: str = "conversation-1"):
    """add()がawaitできるAsyncClientモックを返す。"""
    document_ref = MagicMock()
    document_ref.id = document_id
    collection = MagicMock()
    collection.add = AsyncMock(return_value=(MagicMock(), document_ref))
    client = MagicMock()
    client.collection.return_value = collection
    return client, collection


@pytest.mark.asyncio
async def test_save_conversation_stores_only_three_fields() -> None:
    """質問・回答・日付だけを保存し、利用者情報を含まないこと。"""
    client, collection = _client_with_add("conversation-1")
    repository = FirestoreConversationRepository(client=client)

    saved_id = await repository.save_conversation(
        question_text="肩関節の可動域評価を教えてください。",
        answer_text="外旋と挙上を確認します。",
        date="2026-10-20",
    )

    assert saved_id == "conversation-1"
    collection.add.assert_awaited_once()
    document = collection.add.call_args.args[0]
    assert set(document.keys()) == {"question_text", "answer_text", "date"}
    assert document["question_text"] == "肩関節の可動域評価を教えてください。"
    assert document["answer_text"] == "外旋と挙上を確認します。"
    assert document["date"] == "2026-10-20"


@pytest.mark.asyncio
async def test_save_conversation_defaults_to_jst_date() -> None:
    """日付未指定時は現在のJST日付を使うこと。"""
    client, collection = _client_with_add()
    repository = FirestoreConversationRepository(client=client)

    await repository.save_conversation(
        question_text="質問",
        answer_text="回答",
    )

    document = collection.add.call_args.args[0]
    assert len(document["date"]) == 10
    assert document["date"][4] == "-"


@pytest.mark.asyncio
async def test_get_question_returns_allowed_fields_only() -> None:
    """旧形式文書からも利用者情報を返さないこと。"""
    snapshot = MagicMock()
    snapshot.exists = True
    snapshot.id = "conv-1"
    snapshot.to_dict.return_value = {
        "question_text": "質問",
        "answer_text": "回答",
        "user_id": "user-1",
        "plan": "pro",
        "question_type": "evaluation",
        "pii_suspected": True,
        "created_at": "2026-10-20T09:00:00+09:00",
    }
    document_ref = MagicMock()
    document_ref.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document_ref
    client = MagicMock()
    client.collection.return_value = collection
    repository = FirestoreConversationRepository(client=client)

    question = await repository.get_question("conv-1")

    assert question == {
        "id": "conv-1",
        "question_text": "質問",
        "answer_text": "回答",
        "date": "2026-10-20",
    }


@pytest.mark.asyncio
async def test_get_question_returns_none_for_missing() -> None:
    """存在しない会話はNoneを返すこと。"""
    snapshot = MagicMock()
    snapshot.exists = False
    document_ref = MagicMock()
    document_ref.get = AsyncMock(return_value=snapshot)
    collection = MagicMock()
    collection.document.return_value = document_ref
    client = MagicMock()
    client.collection.return_value = collection
    repository = FirestoreConversationRepository(client=client)

    assert await repository.get_question("conv-404") is None


@pytest.mark.asyncio
async def test_list_metadata_exposes_allowed_fields_only() -> None:
    """一覧は日付と本文のみで、利用者列を含まないこと。"""
    doc = MagicMock()
    doc.id = "conv-1"
    doc.to_dict.return_value = {
        "question_text": "質問",
        "answer_text": "回答",
        "date": "2026-10-20",
        "user_id": "user-1",
    }
    query = MagicMock()
    query.order_by.return_value.limit.return_value.get = AsyncMock(
        return_value=[doc]
    )
    collection = MagicMock()
    collection.order_by.return_value = query.order_by.return_value
    client = MagicMock()
    client.collection.return_value = collection
    repository = FirestoreConversationRepository(client=client)

    result = await repository.list_metadata(limit=10)

    assert result["count"] == 1
    item = result["items"][0]
    assert item["id"] == "conv-1"
    assert item["date"] == "2026-10-20"
    assert item["question_text"] == "質問"
    assert item["answer_text"] == "回答"
    assert "user_id" not in item

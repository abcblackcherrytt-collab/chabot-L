"""Firestore会話保存リポジトリのテスト。"""

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
async def test_save_conversation_writes_one_document() -> None:
    """質問・回答・分類・プランを1ドキュメントとして保存すること。"""
    client, collection = _client_with_add("conversation-1")
    repository = FirestoreConversationRepository(client=client)

    saved_id = await repository.save_conversation(
        user_id="user-1",
        question_text="肩関節の可動域評価を教えてください。",
        answer_text="外旋と挙上を確認します。",
        plan="basic",
        question_type="evaluation",
        answer_aspects=["range_of_motion", "strength"],
    )

    assert saved_id == "conversation-1"
    collection.add.assert_awaited_once()
    document = collection.add.call_args.args[0]
    assert document["user_id"] == "user-1"
    assert document["question_text"] == "肩関節の可動域評価を教えてください。"
    assert document["answer_text"] == "外旋と挙上を確認します。"
    assert document["plan"] == "basic"
    assert document["question_type"] == "evaluation"
    assert document["answer_aspects"] == ["range_of_motion", "strength"]
    assert document["denied"] is False
    assert document["pii_suspected"] is False
    assert document["created_at"]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("田中様の肩が挙上できません。", True),
        ("A病院で肩の注射を受けました。", True),
        ("近所のクリニックを受診すべきですか。", True),
        ("肩関節の可動域評価を教えてください。", False),
    ],
)
def test_detect_pii_suspected(text: str, expected: bool) -> None:
    """氏名・施設名らしい表現を検知フラグに反映すること。"""
    client, _ = _client_with_add()
    repository = FirestoreConversationRepository(client=client)

    assert repository.detect_pii_suspected(text) is expected


@pytest.mark.asyncio
async def test_save_limit_denied_keeps_content_out_of_firestore() -> None:
    """日次上限拒否は本文なしのメタデータだけを保存すること。"""
    client, collection = _client_with_add("conversation-denied")
    repository = FirestoreConversationRepository(client=client)

    saved_id = await repository.save_limit_denied(user_id="user-1", plan="free")

    assert saved_id == "conversation-denied"
    document = collection.add.call_args.args[0]
    assert document["user_id"] == "user-1"
    assert document["question_text"] is None
    assert document["answer_text"] is None
    assert document["plan"] == "free"
    assert document["denied"] is True
    assert document["denial_reason"] == "daily_limit"
    assert document["pii_suspected"] is False

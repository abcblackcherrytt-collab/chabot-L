"""管理用Firestoreリポジトリのテスト。"""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.repositories import firestore_plan_settings_repository as plan_module
from app.repositories import firestore_admin_invite_repository as invite_module
from app.repositories.firestore_admin_invite_repository import (
    FirestoreAdminInviteRepository,
)
from app.repositories.firestore_feedback_repository import (
    FirestoreFeedbackRepository,
)
from app.repositories.firestore_conversation_repository import (
    FirestoreConversationRepository,
)
from app.repositories.firestore_representative_answer_repository import (
    FirestoreRepresentativeAnswerRepository,
)
from app.repositories.firestore_plan_settings_repository import (
    FirestorePlanSettingsRepository,
)
from app.repositories.firestore_admin_user_repository import (
    FirestoreAdminUserRepository,
)


def _snapshot(data: dict, *, exists: bool = True) -> MagicMock:
    snapshot = MagicMock()
    snapshot.exists = exists
    snapshot.to_dict.return_value = data
    snapshot.id = data.get("id", "doc-1")
    return snapshot


class TestPlanSettingsRepository:
    """plan_settingsの読み書きテスト。"""

    def setup_method(self) -> None:
        """キャッシュを毎テスト初期化する。"""
        FirestorePlanSettingsRepository._limit_cache.clear()

    @pytest.mark.asyncio
    async def test_published_limit_uses_cache(self) -> None:
        """公開済み上限を60秒キャッシュから返すこと。"""
        document = MagicMock()
        document.get = AsyncMock(return_value=_snapshot({"daily_message_limit": 5}))
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestorePlanSettingsRepository(client=client)

        first = await repository.get_published_daily_limit("free")
        second = await repository.get_published_daily_limit("free")

        assert first == 5
        assert second == 5
        assert document.get.await_count == 1

    @pytest.mark.asyncio
    async def test_published_limit_falls_back_on_read_failure(self) -> None:
        """読取失敗時はNoneを返し、例外を利用者へ露出しないこと。"""
        document = MagicMock()
        document.get = AsyncMock(side_effect=RuntimeError("firestore down"))
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestorePlanSettingsRepository(client=client)

        assert await repository.get_published_daily_limit("free") is None

    @pytest.mark.asyncio
    async def test_invalid_published_limit_is_ignored(self) -> None:
        """範囲外・型不正な公開値を無視すること。"""
        document = MagicMock()
        document.get = AsyncMock(return_value=_snapshot({"daily_message_limit": 0}))
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestorePlanSettingsRepository(client=client)

        assert await repository.get_published_daily_limit("free") is None

    @pytest.mark.asyncio
    async def test_publish_rejects_revision_conflict(self, monkeypatch) -> None:
        """revision不一致の反映を拒否すること。"""
        monkeypatch.setattr(plan_module.firestore, "async_transactional", lambda fn: fn)
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot(
                {"published_revision": 3, "draft_daily_message_limit": 5}
            )
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        transaction = MagicMock()
        client.transaction.return_value = transaction
        repository = FirestorePlanSettingsRepository(client=client)

        with pytest.raises(ValueError, match="revision_conflict"):
            await repository.publish(plan="free", revision=2, published_by="admin")

    @pytest.mark.asyncio
    async def test_rollback_requires_history(self, monkeypatch) -> None:
        """履歴が1件以下のロールバックを拒否すること。"""
        monkeypatch.setattr(plan_module.firestore, "async_transactional", lambda fn: fn)
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot(
                {"published_revision": 1, "history": [{"revision": 1}]}
            )
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        client.transaction.return_value = MagicMock()
        repository = FirestorePlanSettingsRepository(client=client)

        with pytest.raises(ValueError, match="no_rollback_target"):
            await repository.rollback(plan="free", performed_by="admin")


class TestAdminInviteRepository:
    """admin_invitesのテスト。"""

    @pytest.mark.asyncio
    async def test_issue_stores_only_hash(self) -> None:
        """発行時にトークン平文を保存せずハッシュだけを渡すこと。"""
        document = MagicMock()
        document.set = AsyncMock()
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreAdminInviteRepository(client=client)

        result = await repository.issue(
            token_sha256="abc123",
            expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            created_by="admin",
        )

        assert result["status"] == "unused"
        stored = document.set.await_args.args[0]
        assert stored["token_sha256"] == "abc123"
        assert "token" not in stored

    @pytest.mark.asyncio
    async def test_consume_rejects_used_invite(self, monkeypatch) -> None:
        """使用済み招待の再消費を拒否すること。"""
        monkeypatch.setattr(invite_module.firestore, "async_transactional", lambda fn: fn)
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot({"status": "consumed", "expires_at": None})
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        transaction = MagicMock()
        client.transaction.return_value = transaction
        repository = FirestoreAdminInviteRepository(client=client)

        assert await repository.consume(invite_id="inv-1", user_id="u1") is False


class TestAdminUserRepository:
    """管理ユーザー一覧の実効プラン表示・絞り込みテスト。"""

    @pytest.mark.asyncio
    async def test_summary_uses_effective_plan(self) -> None:
        """service overrideを一覧の実効プランとして返すこと。"""
        summary = FirestoreAdminUserRepository._summary(
            {
                "subscription_plan": "free",
                "plan_override": {"plan": "service"},
                "is_active": True,
            },
            "user-1",
        )

        assert summary["effective_plan"] == "pro"

    @pytest.mark.asyncio
    async def test_summary_admin_override_beats_subscription(self) -> None:
        """管理者overrideをStripe契約より優先して表示すること。"""
        summary = FirestoreAdminUserRepository._summary(
            {
                "subscription_plan": "basic",
                "plan_override": {"plan": "service", "source": "admin"},
                "is_active": True,
            },
            "user-2",
        )

        assert summary["effective_plan"] == "pro"

    @pytest.mark.asyncio
    async def test_summary_coupon_override_keeps_subscription(self) -> None:
        """coupon由来のoverrideで有料契約の表示をdowngradeしないこと。"""
        summary = FirestoreAdminUserRepository._summary(
            {
                "subscription_plan": "pro",
                "plan_override": {"plan": "basic", "source": "coupon"},
                "is_active": True,
            },
            "user-3",
        )

        assert summary["effective_plan"] == "pro"

    @pytest.mark.asyncio
    async def test_search_users_filters_by_effective_plan(self) -> None:
        """検索結果のプラン絞り込みが実効プランを使うこと。"""
        snapshots = [
            _snapshot(
                {
                    "display_name": "service user",
                    "subscription_plan": "free",
                    "plan_override": {"plan": "service"},
                    "is_active": True,
                    "created_at": "2026-10-05T00:00:00+00:00",
                }
            ),
            _snapshot(
                {
                    "display_name": "free user",
                    "subscription_plan": "free",
                    "is_active": True,
                    "created_at": "2026-10-04T00:00:00+00:00",
                }
            ),
        ]
        query = MagicMock()
        query.start_at.return_value = query
        query.end_at.return_value = query
        query.limit.return_value.get = AsyncMock(return_value=snapshots)
        collection = MagicMock()
        collection.order_by.return_value = query
        usage_document = MagicMock()
        usage_document.get = AsyncMock(return_value=_snapshot({}, exists=False))
        collection.document.return_value = usage_document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreAdminUserRepository(client=client)

        result = await repository.list_users(q="service", plan="pro")

        assert result["count"] == 1
        assert result["users"][0]["effective_plan"] == "pro"
        query.limit.assert_called_once_with(20)

    @pytest.mark.asyncio
    async def test_search_by_user_id_reads_one_document(self) -> None:
        """内部ID検索はusers全体を走査せず、対象文書だけを読むこと。"""
        user_document = MagicMock()
        user_document.get = AsyncMock(
            return_value=_snapshot(
                {
                    "id": "user-1",
                    "display_name": "テスト",
                    "subscription_plan": "free",
                    "is_active": True,
                }
            )
        )
        usage_document = MagicMock()
        usage_document.get = AsyncMock(return_value=_snapshot({}, exists=False))
        users_collection = MagicMock()
        users_collection.document.side_effect = lambda document_id: (
            user_document if document_id == "user-1" else usage_document
        )
        usage_collection = MagicMock()
        usage_collection.document.return_value = usage_document
        client = MagicMock()
        client.collection.side_effect = lambda name: (
            users_collection if name == "users" else usage_collection
        )
        repository = FirestoreAdminUserRepository(client=client)

        result = await repository.list_users(
            q="user-1",
            search_field="user_id",
        )

        assert result["count"] == 1
        users_collection.document.assert_called_once_with("user-1")
        users_collection.order_by.assert_not_called()

    @pytest.mark.asyncio
    async def test_search_rejects_blank_query_without_firestore_read(self) -> None:
        """空検索ではFirestoreへアクセスしないこと。"""
        client = MagicMock()
        repository = FirestoreAdminUserRepository(client=client)

        with pytest.raises(ValueError, match="search_query_required"):
            await repository.list_users(q="  ")

        client.collection.assert_not_called()


class TestAdminUserRepository:
    """管理ユーザー詳細の応答絞り込みテスト。"""

    @pytest.mark.asyncio
    async def test_get_user_detail_returns_whitelisted_fields_only(self) -> None:
        """連携ID等を応答へ含めず、実効プランを付与すること。"""
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot(
                {
                    "id": "user-1",
                    "display_name": "テスト",
                    "line_user_id": "U_test123",
                    "email": None,
                    "subscription_plan": "basic",
                    "subscription_status": "active",
                    "stripe_customer_id": "cus_secret",
                    "admin_invite_id": "inv_x",
                    "registration_source": "admin_invite",
                    "role": "user",
                    "plan_override": {"plan": "service", "source": "admin"},
                    "is_active": True,
                    "created_at": "2026-08-31T00:00:00+00:00",
                    "updated_at": "2026-10-05T00:00:00+00:00",
                }
            )
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreAdminUserRepository(client=client)

        detail = await repository.get_user_detail("user-1")

        assert detail is not None
        assert detail["id"] == "user-1"
        assert detail["display_name"] == "テスト"
        assert detail["effective_plan"] == "pro"
        assert "stripe_customer_id" not in detail
        assert "admin_invite_id" not in detail
        assert "registration_source" not in detail
        assert "role" not in detail


class TestFeedbackRepository:
    """feedback / feedback_pendingのテスト。"""

    @pytest.mark.asyncio
    async def test_pending_expires_lazily(self) -> None:
        """期限切れの受付モードをNone扱いにすること。"""
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot(
                {
                    "user_id": "u1",
                    "expires_at": (
                        datetime.now(timezone.utc) - timedelta(minutes=1)
                    ).isoformat(),
                }
            )
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreFeedbackRepository(client=client)

        assert await repository.get_pending("u1") is None

    @pytest.mark.asyncio
    async def test_update_status_validates_status(self) -> None:
        """不正なステータス値を拒否すること。"""
        repository = FirestoreFeedbackRepository(client=MagicMock())

        with pytest.raises(ValueError, match="invalid_status"):
            await repository.update_status(
                "fb-1", status="unknown", admin_note=None, handled_by="admin"
            )


class TestConversationQuestionExtraction:
    """conversationsの質問抽出テスト。"""

    @pytest.mark.asyncio
    async def test_get_question_returns_allowed_fields_only(self) -> None:
        """質問・回答・日付だけを返し、利用者情報を含めないこと。"""
        document = MagicMock()
        document.get = AsyncMock(
            return_value=_snapshot(
                {
                    "question_text": "2nd肢位の外旋制限をどう評価しますか",
                    "answer_text": "botの回答",
                    "question_type": "assessment",
                    "plan": "free",
                    "user_id": "user-1",
                    "created_at": "2026-10-02T10:00:00+09:00",
                }
            )
        )
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreConversationRepository(client=client)

        question = await repository.get_question("conv-1")

        assert question is not None
        assert question["question_text"].startswith("2nd肢位")
        assert question["answer_text"] == "botの回答"
        assert question["date"] == "2026-10-02"
        assert "user_id" not in question
        assert "plan" not in question
        assert "question_type" not in question

    @pytest.mark.asyncio
    async def test_get_question_returns_none_for_missing(self) -> None:
        """存在しない会話IDではNoneを返すこと。"""
        document = MagicMock()
        document.get = AsyncMock(return_value=_snapshot({}, exists=False))
        collection = MagicMock()
        collection.document.return_value = document
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreConversationRepository(client=client)

        assert await repository.get_question("conv-404") is None


class TestRepresentativeAnswerRepository:
    """representative_answersの読み書きテスト。"""

    @pytest.mark.asyncio
    async def test_upsert_uses_conversation_key_and_three_fields(self) -> None:
        """会話キー文書へ質問・回答・日付のみを保存すること。"""
        collection = MagicMock()
        document_ref = MagicMock()
        document_ref.set = AsyncMock()
        collection.document.return_value = document_ref
        client = MagicMock()
        client.collection.return_value = collection
        repository = FirestoreRepresentativeAnswerRepository(client=client)

        saved = await repository.upsert(
            conversation_id="conv-1",
            question_text="質問",
            representative_answer="代表回答",
            date="2026-10-02",
        )

        collection.document.assert_called_once_with("conv-1")
        assert saved["id"] == "conv-1"
        assert saved["representative_answer"] == "代表回答"
        document = document_ref.set.call_args.args[0]
        assert set(document.keys()) == {
            "question_text",
            "representative_answer",
            "date",
        }

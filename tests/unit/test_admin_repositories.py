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
from app.repositories.firestore_plan_settings_repository import (
    FirestorePlanSettingsRepository,
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

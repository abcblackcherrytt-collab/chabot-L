"""
LINE サービスのユニットテスト
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.line import LINEError
from app.services.line_service import LineService


@pytest.fixture
def mock_line_client():
    """モック LINE クライアント"""
    client = MagicMock(spec=[])
    client.reply_message = AsyncMock(return_value={})
    client.push_message = AsyncMock(return_value={})
    client.get_profile = AsyncMock(return_value={
        "displayName": "テストユーザー",
        "userId": "U_test123",
    })
    client.health_check = AsyncMock(return_value={
        "status": "healthy",
        "service": "line",
    })
    return client


@pytest.fixture
def line_service(mock_line_client, monkeypatch):
    """テスト用 LINE サービス"""
    user_repo = MagicMock()
    user_repo.find_by_line_user_id = AsyncMock(return_value={
        "id": "user-123",
        "line_user_id": "U_test123",
        "email": None,
        "display_name": "テストユーザー",
        "role": "user",
        "is_active": True,
        "subscription_plan": "free",
    })
    user_repo.create_line_user = AsyncMock()
    user_repo.is_active = AsyncMock(return_value=True)
    user_repo.get_subscription_plan = AsyncMock(return_value="free")
    user_repo.deactivate_user = AsyncMock()
    user_repo.activate_user = AsyncMock()

    rag_permission_repo = MagicMock()
    rag_permission_repo.get_by_plan = AsyncMock(return_value={
        "rag_corpus_id": "test-corpus",
        "model_name": "test-model",
    })

    usage_repo = MagicMock()
    usage_repo.increment_with_limit_check = AsyncMock(return_value={
        "success": True,
        "current_count": 1,
        "remaining": 2,
        "message": "ok",
    })

    service = LineService(line_client=mock_line_client)
    monkeypatch.setattr(service, "_get_user_repository", lambda db=None: user_repo)
    monkeypatch.setattr(
        service,
        "_get_rag_permission_repository",
        lambda: rag_permission_repo,
    )
    monkeypatch.setattr(
        "app.repositories.firestore_usage_repository.FirestoreUsageRepository",
        lambda: usage_repo,
    )
    revoke_all = AsyncMock(return_value=1)
    monkeypatch.setattr(service, "_revoke_all_user_tokens", revoke_all)
    service._test_usage_repo = usage_repo
    service._test_revoke_all = revoke_all
    return service


class TestProcessWebhookEvent:
    """Webhook イベント処理テスト"""

    @pytest.mark.asyncio
    async def test_message_event(self, line_service):
        """メッセージイベントが正常処理されること"""
        event = {
            "type": "message",
            "replyToken": "test_reply_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "こんにちは"},
        }

        result = await line_service.process_webhook_event(event)

        assert result["status"] == "processed"
        assert result["message"] == "こんにちは"
        assert result["line_user_id"] == "U_test123"
        user_repo = line_service._get_user_repository()
        user_repo.is_active.assert_not_awaited()
        user_repo.get_subscription_plan.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_message_event_non_text(self, line_service, mock_line_client):
        """テキスト以外のメッセージはエラーメッセージが返ること"""
        event = {
            "type": "message",
            "replyToken": "test_reply_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "image", "id": "msg_image"},
        }

        result = await line_service.process_webhook_event(event)

        assert result["status"] == "processed"
        mock_line_client.reply_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_follow_event(self, line_service, mock_line_client):
        """フォローイベントが正常処理されること"""
        event = {
            "type": "follow",
            "replyToken": "test_follow_token",
            "source": {"userId": "U_test123"},
        }

        result = await line_service.process_webhook_event(event)

        assert result["status"] == "processed"
        assert result["action"] == "follow"
        mock_line_client.reply_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_unfollow_event(self, line_service):
        """アンフォローイベントが正常処理されること"""
        event = {
            "type": "unfollow",
            "source": {"userId": "U_test123"},
        }

        result = await line_service.process_webhook_event(event)

        assert result["status"] == "processed"
        assert result["action"] == "unfollow"
        user_repo = line_service._get_user_repository()
        user_repo.deactivate_user.assert_awaited_once_with("user-123")
        line_service._test_revoke_all.assert_awaited_once_with("user-123", None)

    @pytest.mark.asyncio
    async def test_unhandled_event(self, line_service):
        """未対応イベントは None が返ること"""
        event = {"type": "beacon"}

        result = await line_service.process_webhook_event(event)

        assert result is None


class TestFollowEvent:
    """フォローイベント詳細テスト"""

    @pytest.mark.asyncio
    async def test_missing_user_id(self, line_service, db_session):
        """userId がない場合はスキップされること"""
        event = {
            "type": "follow",
            "replyToken": "test_token",
            "source": {},
        }

        result = await line_service._handle_follow_event(event, db_session)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_profile_fetch_failure(self, line_service, mock_line_client, db_session):
        """プロフィール取得失敗時にエラーにならないこと"""
        mock_line_client.get_profile.side_effect = LINEError("API Error")

        event = {
            "type": "follow",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
        }

        result = await line_service._handle_follow_event(event, db_session)
        assert result["status"] == "processed"
        mock_line_client.reply_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_refollow_reactivates_existing_user(self, line_service, db_session):
        """unfollow後の再フォローで既存ユーザーIDを再有効化すること。"""
        user_repo = line_service._get_user_repository()
        user_repo.find_by_line_user_id.return_value = {
            "id": "user-123",
            "line_user_id": "U_test123",
            "is_active": False,
        }
        event = {
            "type": "follow",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
        }

        result = await line_service._handle_follow_event(event, db_session)

        assert result["status"] == "processed"
        user_repo.activate_user.assert_awaited_once_with("user-123")
        user_repo.create_line_user.assert_not_awaited()


class TestMessageEvent:
    """メッセージイベント詳細テスト"""

    @pytest.mark.asyncio
    async def test_first_message_backfills_existing_friend_as_free_user(
        self,
        line_service,
        mock_line_client,
        db_session,
    ):
        """Phase 2導入前からの友だちは最初のメッセージでfree登録すること。"""
        user_repo = line_service._get_user_repository()
        user_repo.find_by_line_user_id.return_value = None
        user_repo.create_line_user.return_value = {
            "id": "backfilled-user",
            "line_user_id": "U_test123",
            "display_name": "テストユーザー",
            "is_active": True,
            "subscription_plan": "free",
        }
        event = {
            "type": "message",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "最初の質問"},
        }

        result = await line_service._handle_message_event(event, db_session)

        assert result["status"] == "processed"
        assert result["user_id"] == "backfilled-user"
        assert result["plan"] == "free"
        mock_line_client.get_profile.assert_awaited_once_with("U_test123")
        user_repo.create_line_user.assert_awaited_once_with(
            line_user_id="U_test123",
            display_name="テストユーザー",
        )
        line_service._test_usage_repo.increment_with_limit_check.assert_awaited_once_with(
            "backfilled-user",
            "free",
            3,
        )

    @pytest.mark.asyncio
    async def test_first_message_backfills_user_when_profile_fetch_fails(
        self,
        line_service,
        mock_line_client,
        db_session,
    ):
        """プロフィール取得失敗でもWebhookのuserIdからfree登録を継続すること。"""
        user_repo = line_service._get_user_repository()
        user_repo.find_by_line_user_id.return_value = None
        user_repo.create_line_user.return_value = {
            "id": "backfilled-user",
            "line_user_id": "U_test123",
            "display_name": "User_U_test12",
            "is_active": True,
            "subscription_plan": "free",
        }
        mock_line_client.get_profile.side_effect = LINEError("profile unavailable")
        event = {
            "type": "message",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "最初の質問"},
        }

        result = await line_service._handle_message_event(event, db_session)

        assert result["status"] == "processed"
        assert result["plan"] == "free"
        user_repo.create_line_user.assert_awaited_once_with(
            line_user_id="U_test123",
            display_name="",
        )

    @pytest.mark.asyncio
    async def test_empty_message(self, line_service, mock_line_client, db_session):
        """空メッセージはエラーメッセージが返ること"""
        event = {
            "type": "message",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "   "},
        }

        result = await line_service._handle_message_event(event, db_session)
        assert result["status"] == "processed"
        assert result["reason"] == "empty_message"

    @pytest.mark.asyncio
    async def test_missing_reply_token(self, line_service, db_session):
        """replyToken がない場合はスキップされること"""
        event = {
            "type": "message",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "hello"},
        }

        result = await line_service._handle_message_event(event, db_session)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_firestore_usage_failure_is_not_reported_as_limit(
        self,
        line_service,
        mock_line_client,
        db_session,
    ):
        """Firestore障害を回数上限として誤案内しないこと"""
        line_service._test_usage_repo.increment_with_limit_check.return_value = {
            "success": False,
            "error": True,
            "current_count": 0,
            "remaining": 0,
            "message": "使用回数を確認できませんでした",
        }
        event = {
            "type": "message",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "hello"},
        }

        result = await line_service._handle_message_event(event, db_session)

        assert result == {
            "status": "error",
            "reason": "usage_check_failed",
            "plan": "free",
        }
        sent_message = mock_line_client.reply_message.await_args.args[1][0]["text"]
        assert "利用回数を確認できません" in sent_message
        assert "上限" not in sent_message


class TestInputSanitization:
    """入力サニタイズテスト"""

    def test_strip_whitespace(self, line_service):
        """前後の空白が除去されること"""
        assert line_service._sanitize_input("  hello  ") == "hello"

    def test_empty_input(self, line_service):
        """空入力は空文字が返ること"""
        assert line_service._sanitize_input("") == ""

    def test_long_input_truncated(self, line_service):
        """長すぎる入力が制限されること"""
        long_text = "a" * 20000
        result = line_service._sanitize_input(long_text)
        assert len(result) == 10000


class TestMessageSplit:
    """メッセージ分割テスト"""

    def test_short_message_no_split(self, line_service):
        """短いメッセージは分割されないこと"""
        messages = line_service._split_message("Hello")
        assert len(messages) == 1
        assert messages[0]["type"] == "text"

    def test_long_message_split(self, line_service):
        """長いメッセージが分割されること"""
        long_text = "a" * 12000
        messages = line_service._split_message(long_text, max_length=5000)
        assert len(messages) == 3

    def test_max_five_messages(self, line_service):
        """最大5メッセージに制限されること"""
        very_long_text = "a" * 30000
        messages = line_service._split_message(very_long_text, max_length=5000)
        assert len(messages) <= 5


class TestUserIdMasking:
    """ユーザーID マスキングテスト"""

    def test_mask_user_id(self, line_service):
        """ユーザーID がマスキングされること"""
        masked = line_service._mask_user_id("U_abcdefghij123456")
        assert masked == "U_ab...3456"
        assert "abcdefghij123456" not in masked

    def test_mask_short_user_id(self, line_service):
        """短いIDは完全にマスキングされること"""
        masked = line_service._mask_user_id("U_abcd")
        assert masked == "***masked***"


class TestSubscriptionNotification:
    """サブスクリプション通知テスト"""

    @pytest.mark.asyncio
    async def test_send_notification_success(self, line_service, mock_line_client):
        """通知が正常送信されること"""
        result = await line_service.send_subscription_notification(
            line_user_id="U_test123",
            message="解約通知テスト",
        )
        assert result is True
        mock_line_client.push_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_notification_failure(self, line_service, mock_line_client):
        """通知送信失敗時に False が返ること"""
        mock_line_client.push_message.side_effect = LINEError("Push failed")

        result = await line_service.send_subscription_notification(
            line_user_id="U_test123",
            message="テスト",
        )
        assert result is False


class TestHealthCheck:
    """ヘルスチェックテスト"""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, line_service):
        """正常時のヘルスチェック"""
        result = await line_service.health_check()
        assert result["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_failure(self, line_service, mock_line_client):
        """異常時のヘルスチェック"""
        mock_line_client.health_check.side_effect = Exception("Connection failed")

        result = await line_service.health_check()
        assert result["status"] == "unhealthy"

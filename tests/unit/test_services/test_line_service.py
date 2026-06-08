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
def line_service(mock_line_client):
    """テスト用 LINE サービス"""
    return LineService(line_client=mock_line_client)


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

    @pytest.mark.asyncio
    async def test_unhandled_event(self, line_service):
        """未対応イベントは None が返ること"""
        event = {"type": "beacon"}

        result = await line_service.process_webhook_event(event)

        assert result is None


class TestFollowEvent:
    """フォローイベント詳細テスト"""

    @pytest.mark.asyncio
    async def test_missing_user_id(self, line_service):
        """userId がない場合はスキップされること"""
        event = {
            "type": "follow",
            "replyToken": "test_token",
            "source": {},
        }

        result = await line_service._handle_follow_event(event)
        assert result["status"] == "skipped"

    @pytest.mark.asyncio
    async def test_profile_fetch_failure(self, line_service, mock_line_client):
        """プロフィール取得失敗時にエラーにならないこと"""
        mock_line_client.get_profile.side_effect = LINEError("API Error")

        event = {
            "type": "follow",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
        }

        result = await line_service._handle_follow_event(event)
        assert result["status"] == "processed"
        mock_line_client.reply_message.assert_called_once()


class TestMessageEvent:
    """メッセージイベント詳細テスト"""

    @pytest.mark.asyncio
    async def test_empty_message(self, line_service, mock_line_client):
        """空メッセージはエラーメッセージが返ること"""
        event = {
            "type": "message",
            "replyToken": "test_token",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "   "},
        }

        result = await line_service._handle_message_event(event)
        assert result["status"] == "processed"
        assert result["reason"] == "empty_message"

    @pytest.mark.asyncio
    async def test_missing_reply_token(self, line_service):
        """replyToken がない場合はスキップされること"""
        event = {
            "type": "message",
            "source": {"userId": "U_test123"},
            "message": {"type": "text", "text": "hello"},
        }

        result = await line_service._handle_message_event(event)
        assert result["status"] == "skipped"


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

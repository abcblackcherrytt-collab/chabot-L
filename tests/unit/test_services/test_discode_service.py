"""
Unit tests for Discode Service
Discodeサービスのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock

from app.services.discode_service import DiscodeService


class TestDiscodeService:
    """Discodeサービスのテストクラス"""

    @pytest.mark.asyncio
    async def test_send_chat_message_success(self, mock_discode_message):
        """
        チャットメッセージ送信が成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.send_message = AsyncMock(return_value=mock_discode_message)

        service = DiscodeService(discode_client=mock_client)

        result = await service.send_chat_message(
            channel_id="ch_test123",
            text="This is a test message.",
            user_id="user123",
            metadata={"key": "value"},
        )

        assert result["id"] == "msg_test123"
        assert result["text"] == "This is a test message."
        mock_client.send_message.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_channel_success(self):
        """
        チャンネル作成が成功することをテスト
        """
        mock_channel = {
            "id": "ch_new123",
            "name": "new-channel",
            "description": "New channel description",
        }

        mock_client = AsyncMock()
        mock_client.create_channel = AsyncMock(return_value=mock_channel)

        service = DiscodeService(discode_client=mock_client)

        result = await service.create_channel(
            name="new-channel",
            description="New channel description",
            owner_id="user123",
        )

        assert result["id"] == "ch_new123"
        assert result["name"] == "new-channel"
        mock_client.create_channel.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_channel_info_success(self, mock_discode_channel):
        """
        チャンネル情報取得が成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.get_channel = AsyncMock(return_value=mock_discode_channel)

        service = DiscodeService(discode_client=mock_client)

        result = await service.get_channel_info("ch_test123")

        assert result["id"] == "ch_test123"
        assert result["name"] == "test-channel"
        mock_client.get_channel.assert_called_once_with("ch_test123")

    @pytest.mark.asyncio
    async def test_list_user_channels_success(self):
        """
        ユーザーのチャンネル一覧取得が成功することをテスト
        """
        mock_channels = [
            {"id": "ch_test123", "name": "channel1"},
            {"id": "ch_test456", "name": "channel2"},
        ]

        mock_client = AsyncMock()
        mock_client.list_channels = AsyncMock(return_value=mock_channels)

        service = DiscodeService(discode_client=mock_client)

        result = await service.list_user_channels(
            user_id="user123",
            limit=50,
            offset=0,
        )

        assert len(result) == 2
        assert result[0]["id"] == "ch_test123"
        assert result[1]["id"] == "ch_test456"
        mock_client.list_channels.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self):
        """
        チャンネル削除が成功することをテスト
        """
        mock_response = {
            "id": "ch_test123",
            "deleted": True,
        }

        mock_client = AsyncMock()
        mock_client.delete_channel = AsyncMock(return_value=mock_response)

        service = DiscodeService(discode_client=mock_client)

        result = await service.delete_channel("ch_test123")

        assert result["id"] == "ch_test123"
        assert result["deleted"] is True
        mock_client.delete_channel.assert_called_once_with("ch_test123")

    @pytest.mark.asyncio
    async def test_get_user_info_success(self):
        """
        ユーザー情報取得が成功することをテスト
        """
        mock_user = {
            "id": "user123",
            "username": "testuser",
            "email": "test@example.com",
        }

        mock_client = AsyncMock()
        mock_client.get_user = AsyncMock(return_value=mock_user)

        service = DiscodeService(discode_client=mock_client)

        result = await service.get_user_info("user123")

        assert result["id"] == "user123"
        assert result["username"] == "testuser"
        mock_client.get_user.assert_called_once_with("user123")

    def test_process_webhook_payload_message(self):
        """
        メッセージWebhookペイロードが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.verify_webhook_signature = AsyncMock(return_value=True)

        service = DiscodeService(discode_client=mock_client)

        payload = {
            "event_type": "message",
            "channel_id": "ch_test123",
            "message": "This is a test message.",
            "user_id": "user123",
        }

        result = service.process_webhook_payload(
            payload=payload,
            signature="test_signature",
        )

        assert result is True

    def test_process_webhook_payload_channel_created(self):
        """
        チャンネル作成Webhookペイロードが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.verify_webhook_signature = AsyncMock(return_value=True)

        service = DiscodeService(discode_client=mock_client)

        payload = {
            "event_type": "channel_created",
            "channel_id": "ch_new123",
        }

        result = service.process_webhook_payload(payload=payload)

        assert result is True

    def test_process_webhook_payload_channel_deleted(self):
        """
        チャンネル削除Webhookペイロードが正しく処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.verify_webhook_signature = AsyncMock(return_value=True)

        service = DiscodeService(discode_client=mock_client)

        payload = {
            "event_type": "channel_deleted",
            "channel_id": "ch_test123",
        }

        result = service.process_webhook_payload(payload=payload)

        assert result is True

    def test_process_webhook_payload_invalid_signature(self):
        """
        無効な署名のWebhookペイロードが適切に処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.verify_webhook_signature = AsyncMock(return_value=False)

        service = DiscodeService(discode_client=mock_client)

        payload = {
            "event_type": "message",
            "channel_id": "ch_test123",
        }

        with pytest.raises(Exception):
            service.process_webhook_payload(
                payload=payload,
                signature="invalid_signature",
            )

    def test_process_webhook_payload_unknown_event(self):
        """
        不明なイベントタイプのWebhookペイロードが適切に処理されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.verify_webhook_signature = AsyncMock(return_value=True)

        service = DiscodeService(discode_client=mock_client)

        payload = {
            "event_type": "unknown_event",
            "data": {},
        }

        result = service.process_webhook_payload(payload=payload)

        assert result is False

    def test_format_chat_message(self):
        """
        チャットメッセージのフォーマットが正しく動作することをテスト
        """
        service = DiscodeService()

        # メタデータなし
        message = service.format_chat_message(
            text="Test message",
            include_metadata=False,
        )

        assert message["text"] == "Test message"
        assert "metadata" not in message

        # メタデータあり
        message_with_metadata = service.format_chat_message(
            text="Test message",
            include_metadata=True,
        )

        assert message_with_metadata["text"] == "Test message"
        assert "metadata" in message_with_metadata
        assert message_with_metadata["metadata"]["bot"] == "chabot"
        assert message_with_metadata["metadata"]["version"] == "1.0.0"

    def test_validate_channel_id(self):
        """
        チャンネルIDの検証が正しく動作することをテスト
        """
        service = DiscodeService()

        # 有効なチャンネルID
        is_valid, error = service.validate_channel_id("ch_test123")
        assert is_valid is True
        assert error is None

        # 空のチャンネルID
        is_valid, error = service.validate_channel_id("")
        assert is_valid is False
        assert error == "チャンネルIDが空です"

        # 短すぎるチャンネルID
        is_valid, error = service.validate_channel_id("ab")
        assert is_valid is False
        assert "短すぎます" in error

    def test_sanitize_message(self):
        """
        メッセージのサニタイズが正しく動作することをテスト
        """
        service = DiscodeService()

        # 前後の空白の削除
        assert service.sanitize_message("  test message  ") == "test message"

        # 複数の空白の削除
        assert service.sanitize_message("test   message") == "test message"

        # 長さ制限
        long_message = "a" * 6000
        assert len(service.sanitize_message(long_message, max_length=5000)) == 5000

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """
        ヘルスチェックが成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.list_channels = AsyncMock(return_value=[])

        service = DiscodeService(discode_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "healthy"
        assert result["service"] == "discode"
        assert result["discode_available"] is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """
        ヘルスチェックが失敗した場合、適切なエラーレスポンスが返されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.list_channels = AsyncMock(side_effect=Exception("Connection error"))

        service = DiscodeService(discode_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "unhealthy"
        assert result["service"] == "discode"
        assert result["discode_available"] is False
        assert "error" in result

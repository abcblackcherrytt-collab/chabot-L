"""
Unit tests for Discode Client
Discodeクライアントのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.clients.discode import DiscodeClient, DiscodeError


class TestDiscodeClient:
    """Discodeクライアントのテストクラス"""

    @pytest.mark.asyncio
    async def test_send_message_success(self, mock_discode_message):
        """
        メッセージ送信が成功することをテスト
        """
        with patch("app.clients.discode.BaseClient.post") as mock_post:
            mock_post.return_value = mock_discode_message

            client = DiscodeClient()
            result = await client.send_message(
                channel_id="ch_test123",
                text="This is a test message.",
                user_id="user123",
                metadata={"key": "value"},
            )

            assert result["id"] == "msg_test123"
            assert result["channel_id"] == "ch_test123"
            assert result["text"] == "This is a test message."
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_error(self):
        """
        メッセージ送信エラーが適切に処理されることをテスト
        """
        with patch("app.clients.discode.BaseClient.post") as mock_post:
            mock_post.side_effect = Exception("Network error")

            client = DiscodeClient()

            with pytest.raises(DiscodeError) as exc_info:
                await client.send_message(
                    channel_id="ch_test123",
                    text="Test message",
                )

            assert "メッセージ送信エラー" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_get_user_success(self):
        """
        ユーザー取得が成功することをテスト
        """
        mock_user = {
            "id": "user123",
            "username": "testuser",
            "email": "test@example.com",
        }

        with patch("app.clients.discode.BaseClient.get") as mock_get:
            mock_get.return_value = mock_user

            client = DiscodeClient()
            result = await client.get_user("user123")

            assert result["id"] == "user123"
            assert result["username"] == "testuser"
            assert result["email"] == "test@example.com"
            mock_get.assert_called_once_with("users/user123")

    @pytest.mark.asyncio
    async def test_get_channel_success(self, mock_discode_channel):
        """
        チャンネル取得が成功することをテスト
        """
        with patch("app.clients.discode.BaseClient.get") as mock_get:
            mock_get.return_value = mock_discode_channel

            client = DiscodeClient()
            result = await client.get_channel("ch_test123")

            assert result["id"] == "ch_test123"
            assert result["name"] == "test-channel"
            mock_get.assert_called_once_with("channels/ch_test123")

    @pytest.mark.asyncio
    async def test_list_channels_success(self):
        """
        チャンネル一覧取得が成功することをテスト
        """
        mock_channels = {
            "channels": [
                {"id": "ch_test123", "name": "channel1"},
                {"id": "ch_test456", "name": "channel2"},
            ],
            "total": 2,
        }

        with patch("app.clients.discode.BaseClient.get") as mock_get:
            mock_get.return_value = mock_channels

            client = DiscodeClient()
            result = await client.list_channels(
                user_id="user123",
                limit=50,
                offset=0,
            )

            assert len(result) == 2
            assert result[0]["id"] == "ch_test123"
            assert result[1]["id"] == "ch_test456"
            mock_get.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_channel_success(self):
        """
        チャンネル作成が成功することをテスト
        """
        mock_channel = {
            "id": "ch_new123",
            "name": "new-channel",
            "description": "New channel description",
            "created_at": 1234567890,
        }

        with patch("app.clients.discode.BaseClient.post") as mock_post:
            mock_post.return_value = mock_channel

            client = DiscodeClient()
            result = await client.create_channel(
                name="new-channel",
                description="New channel description",
                metadata={"owner_id": "user123"},
            )

            assert result["id"] == "ch_new123"
            assert result["name"] == "new-channel"
            mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_update_channel_success(self):
        """
        チャンネル更新が成功することをテスト
        """
        mock_channel = {
            "id": "ch_test123",
            "name": "updated-channel",
            "description": "Updated description",
        }

        with patch("app.clients.discode.BaseClient.put") as mock_put:
            mock_put.return_value = mock_channel

            client = DiscodeClient()
            result = await client.update_channel(
                channel_id="ch_test123",
                name="updated-channel",
                description="Updated description",
            )

            assert result["name"] == "updated-channel"
            assert result["description"] == "Updated description"
            mock_put.assert_called_once()

    @pytest.mark.asyncio
    async def test_delete_channel_success(self):
        """
        チャンネル削除が成功することをテスト
        """
        mock_response = {
            "id": "ch_test123",
            "deleted": True,
        }

        with patch("app.clients.discode.BaseClient.delete") as mock_delete:
            mock_delete.return_value = mock_response

            client = DiscodeClient()
            result = await client.delete_channel("ch_test123")

            assert result["id"] == "ch_test123"
            assert result["deleted"] is True
            mock_delete.assert_called_once_with("channels/ch_test123")

    @pytest.mark.asyncio
    async def test_verify_webhook_signature_valid(self):
        """
        有効なWebhook署名で検証が成功することをテスト
        """
        from unittest.mock import patch

        with patch("app.clients.discode.settings.discord_webhook_secret", "test_secret"):
            client = DiscodeClient()

            # 署名の生成をモック
            import hmac
            import hashlib

            payload = b'{"event_type": "message", "channel_id": "ch_test123"}'
            expected_signature = hmac.new(
                "test_secret".encode(),
                payload,
                hashlib.sha256,
            ).hexdigest()

            result = await client.verify_webhook_signature(
                payload,
                expected_signature,
            )

            assert result is True

    @pytest.mark.asyncio
    async def test_verify_webhook_signature_invalid(self):
        """
        無効なWebhook署名で検証が失敗することをテスト
        """
        from unittest.mock import patch

        with patch("app.clients.discode.settings.discord_webhook_secret", "test_secret"):
            client = DiscodeClient()

            payload = b'{"event_type": "message", "channel_id": "ch_test123"}'
            invalid_signature = "invalid_signature_hash"

            result = await client.verify_webhook_signature(
                payload,
                invalid_signature,
            )

            assert result is False

    @pytest.mark.asyncio
    async def test_get_webhook_config_success(self):
        """
        Webhook設定取得が成功することをテスト
        """
        mock_webhook_config = {
            "webhook_url": "https://example.com/webhooks/discode",
            "secret": "test_secret",
            "events": ["message", "channel_created", "channel_deleted"],
        }

        with patch("app.clients.discode.BaseClient.get") as mock_get:
            mock_get.return_value = mock_webhook_config

            client = DiscodeClient()
            result = await client.get_webhook_config("ch_test123")

            assert result["webhook_url"] == "https://example.com/webhooks/discode"
            assert len(result["events"]) == 3
            mock_get.assert_called_once_with("channels/ch_test123/webhooks")

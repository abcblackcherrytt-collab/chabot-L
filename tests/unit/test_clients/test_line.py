"""
LINE クライアントのユニットテスト
"""

import base64
import hashlib
import hmac
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.line import LINEClient, LINEError


@pytest.fixture
def line_client():
    """テスト用 LINE クライアント"""
    return LINEClient(
        channel_access_token="test_channel_access_token",
        channel_secret="test_channel_secret",
        base_url="https://api.line.me",
    )


@pytest.fixture
def mock_http_response():
    """モック HTTP レスポンスを作成するヘルパー"""
    def _make_response(status_code=200, json_data=None):
        response = MagicMock()
        response.status_code = status_code
        response.json.return_value = json_data or {}
        return response
    return _make_response


class TestLINEClientInit:
    """LINE クライアント初期化テスト"""

    def test_init_with_credentials(self, line_client):
        """正しい認証情報で初期化されること"""
        assert line_client.api_key == "test_channel_access_token"
        assert line_client._channel_secret == "test_channel_secret"

    def test_default_headers(self, line_client):
        """Bearer 認証ヘッダーが設定されること"""
        headers = line_client._get_default_headers()
        assert headers["Authorization"] == "Bearer test_channel_access_token"
        assert headers["Content-Type"] == "application/json"


class TestWebhookSignatureVerification:
    """Webhook 署名検証テスト"""

    def test_valid_signature(self, line_client):
        """正しい署名が検証されること"""
        body = b'{"events":[]}'
        expected = hmac.new(
            b"test_channel_secret",
            body,
            hashlib.sha256,
        ).digest()
        signature = base64.b64encode(expected).decode()

        assert line_client.verify_webhook_signature(body, signature) is True

    def test_invalid_signature(self, line_client):
        """不正な署名が拒否されること"""
        body = b'{"events":[]}'
        signature = "invalid_signature_base64"

        assert line_client.verify_webhook_signature(body, signature) is False

    def test_empty_signature(self, line_client):
        """空の署名が拒否されること"""
        assert line_client.verify_webhook_signature(b"body", "") is False

    def test_empty_secret(self):
        """空のシークレットで検証が失敗すること"""
        client = LINEClient(
            channel_access_token="token",
            channel_secret="",
        )
        assert client.verify_webhook_signature(b"body", "sig") is False

    def test_none_signature(self, line_client):
        """None署名が拒否されること"""
        assert line_client.verify_webhook_signature(b"body", None) is False


class TestReplyMessage:
    """リプライメッセージ送信テスト"""

    @pytest.mark.asyncio
    async def test_reply_message_success(self, line_client, mock_http_response):
        """リプライメッセージが正常送信されること"""
        with patch.object(
            line_client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {}

            result = await line_client.reply_message(
                reply_token="test_reply_token",
                messages=[{"type": "text", "text": "Hello"}],
            )

            mock_post.assert_called_once_with(
                "/v2/bot/message/reply",
                json={
                    "replyToken": "test_reply_token",
                    "messages": [{"type": "text", "text": "Hello"}],
                },
            )
            assert result == {}


class TestPushMessage:
    """プッシュメッセージ送信テスト"""

    @pytest.mark.asyncio
    async def test_push_message_success(self, line_client):
        """プッシュメッセージが正常送信されること"""
        with patch.object(
            line_client, "post", new_callable=AsyncMock
        ) as mock_post:
            mock_post.return_value = {}

            result = await line_client.push_message(
                to="U_test_user",
                messages=[{"type": "text", "text": "Notification"}],
            )

            mock_post.assert_called_once_with(
                "/v2/bot/message/push",
                json={
                    "to": "U_test_user",
                    "messages": [{"type": "text", "text": "Notification"}],
                },
            )


class TestGetProfile:
    """プロフィール取得テスト"""

    @pytest.mark.asyncio
    async def test_get_profile_success(self, line_client):
        """プロフィールが正常取得されること"""
        profile_data = {
            "displayName": "テストユーザー",
            "userId": "U_test123",
        }
        with patch.object(
            line_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = profile_data

            result = await line_client.get_profile("U_test123")

            mock_get.assert_called_once_with("/v2/bot/profile/U_test123")
            assert result["displayName"] == "テストユーザー"


class TestHealthCheck:
    """ヘルスチェックテスト"""

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, line_client):
        """API到達可能時に healthy が返ること"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200

        with patch.object(
            line_client._http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_resp

            result = await line_client.health_check()

            assert result["status"] == "healthy"
            assert result["line_api_available"] is True

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self, line_client):
        """API到達不能時に unhealthy が返ること"""
        mock_resp = MagicMock()
        mock_resp.status_code = 401

        with patch.object(
            line_client._http_client, "get", new_callable=AsyncMock
        ) as mock_get:
            mock_get.return_value = mock_resp

            result = await line_client.health_check()

            assert result["status"] == "unhealthy"
            assert result["line_api_available"] is False

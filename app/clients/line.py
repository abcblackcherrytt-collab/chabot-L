"""
LINE Messaging API クライアント
LINE Messaging APIとの通信を管理するクライアントを定義します。
BaseClientを継承し、LINE固有のAPIメソッドを提供します。
"""

import base64
import hashlib
import hmac
import logging
from typing import Any, Dict, List, Optional

from app.clients.base import BaseClient, BaseClientError

logger = logging.getLogger(__name__)


class LINEError(BaseClientError):
    """LINE API エラー"""

    pass


class LINEClient(BaseClient):
    """
    LINE Messaging API クライアント

    LINE Messaging APIとの通信を管理します。
    認証には Channel Access Token（Bearer）を使用します。
    """

    def __init__(
        self,
        channel_access_token: str,
        channel_secret: str,
        base_url: str = "https://api.line.me",
        timeout: int = 30,
    ):
        """
        LINE クライアントを初期化します

        Args:
            channel_access_token: LINE Channel Access Token
            channel_secret: LINE Channel Secret（署名検証用）
            base_url: LINE API ベースURL
            timeout: リクエストタイムアウト（秒）
        """
        super().__init__(
            base_url=base_url,
            api_key=channel_access_token,
            timeout=timeout,
        )
        self._channel_secret = channel_secret
        logger.info("LINE client initialized")

    def _get_default_headers(self) -> Dict[str, str]:
        """
        LINE API 用のデフォルトヘッダーを取得します

        Returns:
            ヘッダー辞書（Bearer 認証付き）
        """
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "User-Agent": "chabot-line/1.0.0",
        }

    def verify_webhook_signature(
        self,
        body: bytes,
        signature: str,
    ) -> bool:
        """
        LINE Webhook の署名を検証します

        LINE Messaging API は HMAC-SHA256 を使用して
        リクエストボディの署名を生成します。

        Args:
            body: リクエストボディ（バイト列）
            signature: X-Line-Signature ヘッダーの値（Base64）

        Returns:
            署名が有効であれば True
        """
        if not signature or not self._channel_secret:
            return False

        expected = hmac.new(
            self._channel_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()

        try:
            received = base64.b64decode(signature)
        except Exception:
            return False

        return hmac.compare_digest(received, expected)

    async def reply_message(
        self,
        reply_token: str,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        リプライメッセージを送信します

        Webhook 受信から30秒以内に呼び出す必要があります。

        Args:
            reply_token: Webhook イベントの replyToken
            messages: 送信するメッセージのリスト（最大5件）

        Returns:
            API レスポンス

        Raises:
            LINEError: 送信に失敗した場合
        """
        payload = {
            "replyToken": reply_token,
            "messages": messages,
        }
        return await self.post("/v2/bot/message/reply", json=payload)

    async def push_message(
        self,
        to: str,
        messages: List[Dict[str, Any]],
    ) -> Dict[str, Any]:
        """
        プッシュメッセージを送信します

        ユーザーに能動的にメッセージを送信します。
        （サブスクリプション通知などで使用）

        Args:
            to: 送信先（LINE userId、グループID、ルームID）
            messages: 送信するメッセージのリスト（最大5件）

        Returns:
            API レスポンス

        Raises:
            LINEError: 送信に失敗した場合
        """
        payload = {
            "to": to,
            "messages": messages,
        }
        return await self.post("/v2/bot/message/push", json=payload)

    async def get_profile(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        ユーザーのプロフィール情報を取得します

        Args:
            user_id: LINE ユーザーID

        Returns:
            プロフィール情報（displayName, pictureUrl, statusMessage 等）

        Raises:
            LINEError: 取得に失敗した場合
        """
        return await self.get(f"/v2/bot/profile/{user_id}")

    async def leave_group(self, group_id: str) -> Dict[str, Any]:
        """
        グループから退出します

        Args:
            group_id: グループID

        Returns:
            API レスポンス

        Raises:
            LINEError: 退出に失敗した場合
        """
        return await self.post(f"/v2/bot/group/{group_id}/leave")

    async def leave_room(self, room_id: str) -> Dict[str, Any]:
        """
        ルームから退出します

        Args:
            room_id: ルームID

        Returns:
            API レスポンス

        Raises:
            LINEError: 退出に失敗した場合
        """
        return await self.post(f"/v2/bot/room/{room_id}/leave")

    async def get_message_content(
        self,
        message_id: str,
    ) -> bytes:
        """
        メッセージに添付されたコンテンツ（画像・ファイル等）を取得します

        Args:
            message_id: メッセージID

        Returns:
            コンテンツのバイナリデータ

        Raises:
            LINEError: 取得に失敗した場合
        """
        url = self._build_url(f"/v2/bot/message/{message_id}/content")
        response = await self._http_client.get(
            url,
            headers=self._get_default_headers(),
        )
        if response.status_code != 200:
            raise LINEError(
                f"Failed to get message content: {response.status_code}",
                status_code=response.status_code,
            )
        return response.content

    async def health_check(self) -> Dict[str, Any]:
        """
        LINE API のヘルスチェックを行います

        自分のボット情報を取得してAPI到達性を確認します。

        Returns:
            ヘルスチェック結果
        """
        try:
            # Bot情報取得でAPI到達性を確認
            url = self._build_url("/v2/bot/info")
            response = await self._http_client.get(
                url,
                headers=self._get_default_headers(),
            )

            if response.status_code == 200:
                return {
                    "status": "healthy",
                    "service": "line",
                    "line_api_available": True,
                }
            return {
                "status": "unhealthy",
                "service": "line",
                "line_api_available": False,
                "status_code": response.status_code,
            }

        except Exception as e:
            logger.error(f"LINE health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "line",
                "line_api_available": False,
                "error": str(e),
            }

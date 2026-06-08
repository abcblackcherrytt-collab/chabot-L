"""
Discodeクライアント
Discode APIとの通信を管理するクライアントを定義します。
"""

import logging
from typing import Any, Dict, List, Optional

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


class DiscodeError(BaseClientError):
    """
    Discodeエラークラス
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response)


class DiscodeClient(BaseClient):
    """
    Discodeクライアント

    DiscodeチャットボットAPIとの通信を管理します。
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        base_url: Optional[str] = None,
        timeout: int = 30,
    ):
        """
        Discodeクライアントを初期化します

        Args:
            bot_token: Discord Bot Token
            base_url: APIのベースURL
            timeout: リクエストタイムアウト（秒）
        """
        base_url = base_url or settings.discord_api_base_url
        bot_token = bot_token or settings.discord_bot_token

        super().__init__(
            base_url=base_url,
            api_key=bot_token,
            timeout=timeout,
        )

    def _get_default_headers(self) -> Dict[str, str]:
        """
        Discord API用のデフォルトHTTPヘッダーを取得します

        Discord APIは 'Bot <token>' 形式の認証を要求するため、
        BaseClientの 'Bearer' 形式を上書きします。

        Returns:
            デフォルトのHTTPヘッダーの辞書
        """
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "chabot/1.0.0",
        }

        if self.api_key:
            headers["Authorization"] = f"Bot {self.api_key}"

        return headers

    async def send_message(
        self,
        channel_id: str,
        text: str,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        チャットメッセージを送信します

        Args:
            channel_id: チャンネルID
            text: メッセージテキスト
            user_id: ユーザーID（オプション）
            metadata: メタデータ（オプション）

        Returns:
            APIレスポンス

        Raises:
            DiscodeError: 送信エラーが発生した場合
        """
        payload: Dict[str, Any] = {
            "channel_id": channel_id,
            "text": text,
        }

        if user_id:
            payload["user_id"] = user_id

        if metadata:
            payload["metadata"] = metadata

        logger.info(f"Sending message to channel {channel_id}")

        try:
            response = await self.post("messages", json=payload)
            logger.info(f"Message sent successfully: {response.get('message_id', 'N/A')}")
            return response

        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise DiscodeError(f"メッセージ送信エラー: {e}")

    async def get_user(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """
        ユーザー情報を取得します

        Args:
            user_id: ユーザーID

        Returns:
            ユーザー情報

        Raises:
            DiscodeError: 取得エラーが発生した場合
        """
        logger.info(f"Getting user info: {user_id}")

        try:
            response = await self.get(f"users/{user_id}")
            return response

        except Exception as e:
            logger.error(f"Failed to get user: {e}")
            raise DiscodeError(f"ユーザー情報取得エラー: {e}")

    async def get_channel(
        self,
        channel_id: str,
    ) -> Dict[str, Any]:
        """
        チャンネル情報を取得します

        Args:
            channel_id: チャンネルID

        Returns:
            チャンネル情報

        Raises:
            DiscodeError: 取得エラーが発生した場合
        """
        logger.info(f"Getting channel info: {channel_id}")

        try:
            response = await self.get(f"channels/{channel_id}")
            return response

        except Exception as e:
            logger.error(f"Failed to get channel: {e}")
            raise DiscodeError(f"チャンネル情報取得エラー: {e}")

    async def list_channels(
        self,
        user_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        チャンネル一覧を取得します

        Args:
            user_id: ユーザーID（フィルタリング用）
            limit: 取得数
            offset: オフセット

        Returns:
            チャンネル情報のリスト

        Raises:
            DiscodeError: 取得エラーが発生した場合
        """
        params: Dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        if user_id:
            params["user_id"] = user_id

        logger.info(f"Listing channels (limit: {limit}, offset: {offset})")

        try:
            response = await self.get("channels", params=params)
            channels = response.get("channels", [])
            logger.info(f"Retrieved {len(channels)} channels")
            return channels

        except Exception as e:
            logger.error(f"Failed to list channels: {e}")
            raise DiscodeError(f"チャンネル一覧取得エラー: {e}")

    async def create_channel(
        self,
        name: str,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        新しいチャンネルを作成します

        Args:
            name: チャンネル名
            description: チャンネルの説明
            metadata: メタデータ

        Returns:
            作成されたチャンネル情報

        Raises:
            DiscodeError: 作成エラーが発生した場合
        """
        payload: Dict[str, Any] = {
            "name": name,
        }

        if description:
            payload["description"] = description

        if metadata:
            payload["metadata"] = metadata

        logger.info(f"Creating channel: {name}")

        try:
            response = await self.post("channels", json=payload)
            logger.info(f"Channel created successfully: {response.get('id', 'N/A')}")
            return response

        except Exception as e:
            logger.error(f"Failed to create channel: {e}")
            raise DiscodeError(f"チャンネル作成エラー: {e}")

    async def update_channel(
        self,
        channel_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        チャンネルを更新します

        Args:
            channel_id: チャンネルID
            name: 新しいチャンネル名（オプション）
            description: 新しい説明（オプション）
            metadata: メタデータ（オプション）

        Returns:
            更新されたチャンネル情報

        Raises:
            DiscodeError: 更新エラーが発生した場合
        """
        payload: Dict[str, Any] = {}

        if name:
            payload["name"] = name

        if description:
            payload["description"] = description

        if metadata:
            payload["metadata"] = metadata

        logger.info(f"Updating channel {channel_id}")

        try:
            response = await self.put(f"channels/{channel_id}", json=payload)
            logger.info(f"Channel updated successfully: {channel_id}")
            return response

        except Exception as e:
            logger.error(f"Failed to update channel: {e}")
            raise DiscodeError(f"チャンネル更新エラー: {e}")

    async def delete_channel(
        self,
        channel_id: str,
    ) -> Dict[str, Any]:
        """
        チャンネルを削除します

        Args:
            channel_id: チャンネルID

        Returns:
            削除確認のレスポンス

        Raises:
            DiscodeError: 削除エラーが発生した場合
        """
        logger.info(f"Deleting channel {channel_id}")

        try:
            response = await self.delete(f"channels/{channel_id}")
            logger.info(f"Channel deleted successfully: {channel_id}")
            return response

        except Exception as e:
            logger.error(f"Failed to delete channel: {e}")
            raise DiscodeError(f"チャンネル削除エラー: {e}")

    async def get_webhook_config(
        self,
        channel_id: str,
    ) -> Dict[str, Any]:
        """
        チャンネルのWebhook設定を取得します

        Args:
            channel_id: チャンネルID

        Returns:
            Webhook設定情報

        Raises:
            DiscodeError: 取得エラーが発生した場合
        """
        logger.info(f"Getting webhook config for channel {channel_id}")

        try:
            response = await self.get(f"channels/{channel_id}/webhooks")
            return response

        except Exception as e:
            logger.error(f"Failed to get webhook config: {e}")
            raise DiscodeError(f"Webhook設定取得エラー: {e}")

    async def edit_interaction_response(
        self,
        interaction_token: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Discord Interactionのdeferredメッセージを更新します

        スラッシュコマンド応答で「考え中...」と表示された後、
        実際の回答でメッセージを更新します。

        Args:
            interaction_token: Interactionのトークン
            content: 更新するメッセージ内容

        Returns:
            APIレスポンス

        Raises:
            DiscodeError: 更新エラーが発生した場合
        """
        from app.core.config import settings

        url = (
            f"{self.base_url}/webhooks/"
            f"{settings.resolved_discord_application_id}/{interaction_token}/messages/@original"
        )

        payload = {"content": content}

        logger.info("Editing interaction response")

        try:
            response = await self._http_client.patch(
                url,
                json=payload,
                headers=self._get_default_headers(),
            )
            logger.info("Interaction response updated successfully")
            return response.json()

        except Exception as e:
            logger.error(f"Failed to edit interaction response: {e}")
            raise DiscodeError(f"Interaction応答更新エラー: {e}")

    async def create_followup_message(
        self,
        interaction_token: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Discord Interactionのフォローアップメッセージを送信します

        Args:
            interaction_token: Interactionのトークン
            content: 送信するメッセージ内容

        Returns:
            APIレスポンス

        Raises:
            DiscodeError: 送信エラーが発生した場合
        """
        from app.core.config import settings

        url = (
            f"{self.base_url}/webhooks/"
            f"{settings.resolved_discord_application_id}/{interaction_token}"
        )

        payload = {"content": content}

        logger.info("Creating followup message")

        try:
            response = await self._http_client.post(
                url,
                json=payload,
                headers=self._get_default_headers(),
            )
            logger.info("Followup message created successfully")
            return response.json()

        except Exception as e:
            logger.error(f"Failed to create followup message: {e}")
            raise DiscodeError(f"フォローアップメッセージ送信エラー: {e}")

    async def verify_webhook_signature(
        self,
        payload: bytes,
        signature: str,
    ) -> bool:
        """
        Webhook署名を検証します

        Args:
            payload: 生のリクエストボディ
            signature: Discode Webhook署名

        Returns:
            署名が有効であればTrue

        Raises:
            DiscodeError: 検証エラーが発生した場合
        """
        import hmac
        import hashlib

        # Discode Webhook署名検証
        # ここでは簡易実装を提供します
        # 本番環境ではDiscodeのドキュメントに従った検証を実装します

        expected_signature = hmac.new(
            settings.discord_webhook_secret.encode(),
            payload,
            hashlib.sha256,
        ).hexdigest()

        is_valid = hmac.compare_digest(expected_signature, signature)

        if is_valid:
            logger.info("Webhook signature verified successfully")
        else:
            logger.warning("Webhook signature verification failed")

        return is_valid

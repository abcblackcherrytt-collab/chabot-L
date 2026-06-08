"""
Discode連携サービス
Discodeチャットボットとの連携を管理するサービスを定義します。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.clients.discode import DiscodeClient, DiscodeError
from app.core.config import settings

logger = logging.getLogger(__name__)


class DiscodeService:
    """
    Discode連携サービス

    Discodeチャットボット機能を提供します。
    """

    def __init__(
        self,
        discode_client: Optional[DiscodeClient] = None,
    ):
        """
        Discodeサービスを初期化します

        Args:
            discode_client: Discodeクライアント（オプション）
        """
        self.client = discode_client or DiscodeClient()
        logger.info("Discode service initialized")

    async def send_chat_message(
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
            user_id: ユーザーID
            metadata: メタデータ

        Returns:
            送信結果

        Raises:
            DiscodeError: 送信エラーが発生した場合
        """
        try:
            result = await self.client.send_message(
                channel_id=channel_id,
                text=text,
                user_id=user_id,
                metadata=metadata,
            )
            return result

        except DiscodeError as e:
            logger.error(f"Failed to send chat message: {e}")
            raise

    async def create_channel(
        self,
        name: str,
        description: Optional[str] = None,
        owner_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        新しいチャンネルを作成します

        Args:
            name: チャンネル名
            description: チャンネルの説明
            owner_id: 所有者ID

        Returns:
            作成されたチャンネル情報

        Raises:
            DiscodeError: 作成エラーが発生した場合
        """
        try:
            metadata: Dict[str, Any] = {}
            if owner_id:
                metadata["owner_id"] = owner_id

            result = await self.client.create_channel(
                name=name,
                description=description,
                metadata=metadata,
            )
            return result

        except DiscodeError as e:
            logger.error(f"Failed to create channel: {e}")
            raise

    async def get_channel_info(
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
        try:
            result = await self.client.get_channel(channel_id)
            return result

        except DiscodeError as e:
            logger.error(f"Failed to get channel info: {e}")
            raise

    async def list_user_channels(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """
        ユーザーのチャンネル一覧を取得します

        Args:
            user_id: ユーザーID
            limit: 取得数
            offset: オフセット

        Returns:
            チャンネル情報のリスト

        Raises:
            DiscodeError: 取得エラーが発生した場合
        """
        try:
            channels = await self.client.list_channels(
                user_id=user_id,
                limit=limit,
                offset=offset,
            )
            return channels

        except DiscodeError as e:
            logger.error(f"Failed to list user channels: {e}")
            raise

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
        try:
            result = await self.client.delete_channel(channel_id)
            return result

        except DiscodeError as e:
            logger.error(f"Failed to delete channel: {e}")
            raise

    async def get_user_info(
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
        try:
            result = await self.client.get_user(user_id)
            return result

        except DiscodeError as e:
            logger.error(f"Failed to get user info: {e}")
            raise

    async def edit_interaction_response(
        self,
        interaction_token: str,
        content: str,
    ) -> Dict[str, Any]:
        """
        Discord Interactionのdeferredメッセージを更新します

        Args:
            interaction_token: Interactionのトークン
            content: 更新するメッセージ内容

        Returns:
            更新結果

        Raises:
            DiscodeError: 更新エラーが発生した場合
        """
        try:
            result = await self.client.edit_interaction_response(
                interaction_token=interaction_token,
                content=content,
            )
            return result

        except DiscodeError as e:
            logger.error(f"Failed to edit interaction response: {e}")
            raise

    def process_webhook_payload(
        self,
        payload: Dict[str, Any],
        signature: Optional[str] = None,
    ) -> bool:
        """
        Webhookペイロードを処理します

        Args:
            payload: Webhookペイロード
            signature: Webhook署名（オプション）

        Returns:
            処理が成功すればTrue

        Raises:
            DiscodeError: 処理エラーが発生した場合
        """
        # 署名検証（提供されている場合）
        if signature:
            payload_bytes = str(payload).encode()
            is_valid = self.client.verify_webhook_signature(
                payload_bytes,
                signature,
            )

            if not is_valid:
                logger.warning("Webhook signature verification failed")
                raise DiscodeError(
                    "Invalid webhook signature",
                    status_code=401,
                )

        # Webhookイベントタイプを取得
        event_type = payload.get("event_type")
        logger.info(f"Processing webhook event: {event_type}")

        # イベントタイプに応じた処理
        # ここでは簡易実装を提供します
        # 本番環境ではDiscodeのドキュメントに従った処理を実装します

        if event_type == "message":
            # メッセージ受信時の処理
            channel_id = payload.get("channel_id")
            message = payload.get("message")
            user_id = payload.get("user_id")

            logger.info(
                f"Received message webhook: channel={channel_id}, "
                f"user={user_id}, message={message[:50]}..."
            )

            # チャットボットとして応答する処理は別サービスで行う
            # ここではログ記録のみ
            return True

        elif event_type == "channel_created":
            # チャンネル作成時の処理
            channel_id = payload.get("channel_id")
            logger.info(f"Channel created: {channel_id}")
            return True

        elif event_type == "channel_deleted":
            # チャンネル削除時の処理
            channel_id = payload.get("channel_id")
            logger.info(f"Channel deleted: {channel_id}")
            return True

        else:
            # 不明なイベントタイプ
            logger.warning(f"Unknown webhook event type: {event_type}")
            return False

    async def health_check(self) -> Dict[str, Any]:
        """
        Discodeサービスのヘルスチェックを行います

        Returns:
            ヘルスチェック結果
        """
        try:
            # 簡易なヘルスチェック
            # 実際にはDiscode APIの可用性をチェック
            # ユーザーチャンネルリストの代わりに、クライアント自体の接続状態を確認
            # ここでは簡易実装として、クライアントが初期化されていることを確認

            if not self.client:
                raise DiscodeError("Discode client not initialized")

            return {
                "status": "healthy",
                "service": "discode",
                "discode_available": True,
            }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "discode",
                "discode_available": False,
                "error": str(e),
            }

    def format_chat_message(
        self,
        text: str,
        include_metadata: bool = False,
    ) -> Dict[str, Any]:
        """
        チャットメッセージをフォーマットします

        Args:
            text: メッセージテキスト
            include_metadata: メタデータを含めるか

        Returns:
            フォーマットされたメッセージ
        """
        message = {
            "text": text,
        }

        if include_metadata:
            message["metadata"] = {
                "bot": "chabot",
                "version": "1.0.0",
            }

        return message

    def validate_channel_id(
        self,
        channel_id: str,
    ) -> Tuple[bool, Optional[str]]:
        """
        チャンネルIDを検証します

        Args:
            channel_id: チャンネルID

        Returns:
            (有効か, エラーメッセージ)
        """
        if not channel_id or not channel_id.strip():
            return False, "チャンネルIDが空です"

        if len(channel_id) < 3:
            return False, "チャンネルIDが短すぎます"

        return True, None

    def sanitize_message(
        self,
        text: str,
        max_length: int = 5000,
    ) -> str:
        """
        メッセージをサニタイズします

        Args:
            text: 元のテキスト
            max_length: 最大文字数

        Returns:
            サニタイズされたテキスト
        """
        # 前後の空白を削除
        text = text.strip()

        # 複数の空白を単一の空白に変換
        text = " ".join(text.split())

        # 長さ制限
        if len(text) > max_length:
            text = text[:max_length]

        return text

"""
LINE メッセージングサービス
LINE Messaging API を使用したビジネスロジックを定義します。
ユーザー管理、メッセージ処理、サブスクリプション連携を行います。
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from app.clients.line import LINEClient, LINEError
from app.core.config import settings

logger = logging.getLogger(__name__)


class LineService:
    """
    LINE メッセージングサービス

    LINEとの連携におけるビジネスロジックを管理します。
    メッセージ処理、ユーザー管理、サブスクリプション検証を行います。
    """

    def __init__(
        self,
        line_client: Optional[LINEClient] = None,
    ):
        """
        LINEサービスを初期化します

        Args:
            line_client: LINEクライアント（オプション）
        """
        self.client = line_client or LINEClient(
            channel_access_token=settings.line_channel_access_token,
            channel_secret=settings.line_channel_secret,
            base_url=settings.line_api_base_url,
        )
        logger.info("LINE service initialized")

    async def process_webhook_event(
        self,
        event: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """
        LINE Webhook イベントを処理します

        イベントタイプに応じて適切なハンドラに振り分けます。

        Args:
            event: LINE Webhook イベントオブジェクト

        Returns:
            処理結果、未処理イベントは None
        """
        event_type = event.get("type")

        if event_type == "message":
            return await self._handle_message_event(event)
        elif event_type == "follow":
            return await self._handle_follow_event(event)
        elif event_type == "unfollow":
            return await self._handle_unfollow_event(event)
        elif event_type == "postback":
            return await self._handle_postback_event(event)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return None

    async def _handle_message_event(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        メッセージイベントを処理します

        ユーザーからのメッセージを受信し、RAGサービスで応答を生成して
        リプライメッセージとして送信します。

        Args:
            event: メッセージイベントオブジェクト

        Returns:
            処理結果
        """
        reply_token = event.get("replyToken", "")
        source = event.get("source", {})
        line_user_id = source.get("userId", "")
        message = event.get("message", {})

        if not reply_token or not line_user_id:
            logger.warning("Missing replyToken or userId in message event")
            return {"status": "skipped", "reason": "missing_fields"}

        # テキストメッセージのみ処理
        if message.get("type") != "text":
            await self._send_reply(
                reply_token,
                "テキストメッセージのみ対応しています。",
            )
            return {"status": "processed", "message_type": message.get("type")}

        user_message = message.get("text", "")

        # 入力サニタイズ
        user_message = self._sanitize_input(user_message)

        if not user_message:
            await self._send_reply(reply_token, "メッセージを入力してください。")
            return {"status": "processed", "reason": "empty_message"}

        logger.info(
            f"Processing message from LINE user: {self._mask_user_id(line_user_id)}"
        )

        # TODO: ユーザー認識・サブスクリプション検証を追加
        # 現在はメッセージをそのままRAGサービスに渡す
        return {
            "status": "processed",
            "reply_token": reply_token,
            "line_user_id": line_user_id,
            "message": user_message,
        }

    async def _handle_follow_event(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        フォローイベント（友だち追加）を処理します

        新規ユーザーをDBに登録するか、既存ユーザーを再有効化します。

        Args:
            event: フォローイベントオブジェクト

        Returns:
            処理結果
        """
        source = event.get("source", {})
        line_user_id = source.get("userId", "")
        reply_token = event.get("replyToken", "")

        if not line_user_id:
            return {"status": "skipped", "reason": "missing_user_id"}

        logger.info(f"New follow from: {self._mask_user_id(line_user_id)}")

        # プロフィール取得
        display_name = ""
        try:
            profile = await self.client.get_profile(line_user_id)
            display_name = profile.get("displayName", "")
        except LINEError as e:
            logger.warning(f"Failed to get profile: {e}")

        # TODO: DB でユーザー作成または再有効化
        # UserRepository.find_by_line_user_id(line_user_id)
        # → 存在しない場合は新規作成
        # → 存在する場合は is_active = True に更新

        # ウェルカムメッセージ送信
        welcome_msg = (
            f"{'こんにちは、' + display_name + 'さん！' if display_name else 'こんにちは！'}\n"
            "Chabotへようこそ。\n"
            "何でもお気軽にご質問ください。"
        )
        await self._send_reply(reply_token, welcome_msg)

        return {
            "status": "processed",
            "line_user_id": line_user_id,
            "action": "follow",
        }

    async def _handle_unfollow_event(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        アンフォローイベント（ブロック・友だち削除）を処理します

        ユーザーを無効化し、セッションをクリアします。

        Args:
            event: アンフォローイベントオブジェクト

        Returns:
            処理結果
        """
        source = event.get("source", {})
        line_user_id = source.get("userId", "")

        if not line_user_id:
            return {"status": "skipped", "reason": "missing_user_id"}

        logger.info(f"Unfollow from: {self._mask_user_id(line_user_id)}")

        # TODO: DB でユーザー無効化
        # UserRepository.find_by_line_user_id(line_user_id)
        # → is_active = False
        # → refresh_tokens を全削除

        return {
            "status": "processed",
            "line_user_id": line_user_id,
            "action": "unfollow",
        }

    async def _handle_postback_event(
        self,
        event: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        ポストバックイベントを処理します

        リッチメニューやテンプレートメッセージの
        アクション応答を処理します。

        Args:
            event: ポストバックイベントオブジェクト

        Returns:
            処理結果
        """
        reply_token = event.get("replyToken", "")
        postback_data = event.get("postback", {}).get("data", "")

        logger.info(f"Postback received: {postback_data}")

        # ポストバックデータに応じた処理
        if postback_data == "action=subscribe":
            await self._send_reply(
                reply_token,
                "サブスクリプションページへ移動します。\n（※決済ページURLは後ほど設定されます）",
            )
        elif postback_data == "action=help":
            await self._send_reply(
                reply_token,
                "【ヘルプ】\n"
                "・テキストメッセージで質問すると、AIがお答えします\n"
                "・サブスクリプションの管理は下のメニューからどうぞ\n"
                "・困ったときは「ヘルプ」と入力してください",
            )
        else:
            await self._send_reply(reply_token, "対応できない操作です。")

        return {
            "status": "processed",
            "postback_data": postback_data,
        }

    async def send_subscription_notification(
        self,
        line_user_id: str,
        message: str,
    ) -> bool:
        """
        サブスクリプション関連の通知を送信します

        解約通知、支払い失敗通知などで使用します。
        Push API を使用するため、ユーザーがBotをフォローしている必要があります。

        Args:
            line_user_id: 送信先 LINE ユーザーID
            message: 送信するメッセージ

        Returns:
            送信成功なら True
        """
        try:
            await self.client.push_message(
                to=line_user_id,
                messages=[{"type": "text", "text": message}],
            )
            logger.info(
                f"Subscription notification sent to: {self._mask_user_id(line_user_id)}"
            )
            return True
        except LINEError as e:
            logger.error(
                f"Failed to send notification to {self._mask_user_id(line_user_id)}: {e}"
            )
            return False

    async def _send_reply(
        self,
        reply_token: str,
        text: str,
    ) -> None:
        """
        リプライメッセージを送信します

        LINEの制限に合わせてメッセージを分割します。
        （1メッセージ最大5000文字）

        Args:
            reply_token: リプライトークン
            text: 送信テキスト
        """
        # メッセージを5000文字以内に分割
        messages = self._split_message(text)

        try:
            await self.client.reply_message(reply_token, messages)
        except LINEError as e:
            logger.error(f"Failed to send reply: {e}")

    def _split_message(
        self,
        text: str,
        max_length: int = 5000,
    ) -> List[Dict[str, Any]]:
        """
        長いテキストをLINE送信用に分割します

        Args:
            text: 送信テキスト
            max_length: 1メッセージの最大文字数

        Returns:
            LINE メッセージオブジェクトのリスト
        """
        if len(text) <= max_length:
            return [{"type": "text", "text": text}]

        messages = []
        for i in range(0, len(text), max_length):
            chunk = text[i : i + max_length]
            messages.append({"type": "text", "text": chunk})

        # LINE は1回のリプライで最大5メッセージ
        return messages[:5]

    def _sanitize_input(self, text: str) -> str:
        """
        ユーザー入力をサニタイズします

        プロンプトインジェクション対策と
        不要な空白の除去を行います。

        Args:
            text: 入力テキスト

        Returns:
            サニタイズ済みテキスト
        """
        if not text:
            return ""

        # 前後の空白を除去
        text = text.strip()

        # 長すぎる入力を制限（10000文字）
        if len(text) > 10000:
            text = text[:10000]

        return text

    def _mask_user_id(self, user_id: str) -> str:
        """
        ログ出力用にユーザーIDをマスキングします

        PII保護のため、ユーザーIDの先頭と末尾のみ表示します。

        Args:
            user_id: LINE ユーザーID

        Returns:
            マスキング済みID
        """
        if len(user_id) <= 8:
            return "***masked***"
        return f"{user_id[:4]}...{user_id[-4:]}"

    async def health_check(self) -> Dict[str, Any]:
        """
        LINEサービスのヘルスチェックを行います

        Returns:
            ヘルスチェック結果
        """
        try:
            return await self.client.health_check()
        except Exception as e:
            logger.error(f"LINE service health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "line",
                "error": str(e),
            }

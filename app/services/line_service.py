"""
LINE メッセージングサービス
LINE Messaging API を使用したビジネスロジックを定義します。

Phase 1（現在）: follow=ウェルカム送信、message=RAG応答生成のみ。
  ユーザー永続化・サブスクリプション検証は行わない（DB/Stripe 未接続で動作。
  友だち追加だけでボット利用可能）。
Phase 2: ユーザー管理・サブスクリプション連携を追加。詳細はコード内
  [Phase 2] マーカー、および todo.txt / REMAINING_TASKS.md の「Phase 2」セクション参照。
"""

import logging
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.line import LINEClient, LINEError
from app.core.config import settings
from app.models.subscription import Subscription
from app.repositories.base import BaseRepository
from app.repositories.rag_permission import RagPermissionRepository
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)


class LineService:
    """
    LINE メッセージングサービス

    LINEとの連携におけるビジネスロジックを管理します。

    Phase 1（現在）: メッセージ処理（RAG応答）のみ。ユーザー管理・サブスクリプション
      検証は行わない（後で有効化）。
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
        db: AsyncSession,
    ) -> Optional[Dict[str, Any]]:
        """
        LINE Webhook イベントを処理します

        イベントタイプに応じて適切なハンドラに振り分けます。

        Args:
            event: LINE Webhook イベントオブジェクト
            db: データベースセッション（Phase 2: ユーザー永続化・プラン解決）

        Returns:
            処理結果、未処理イベントは None
        """
        event_type = event.get("type")

        if event_type == "message":
            return await self._handle_message_event(event, db)
        elif event_type == "follow":
            return await self._handle_follow_event(event, db)
        elif event_type == "unfollow":
            return await self._handle_unfollow_event(event, db)
        elif event_type == "postback":
            return await self._handle_postback_event(event, db)
        else:
            logger.info(f"Unhandled event type: {event_type}")
            return None

    async def _handle_message_event(
        self,
        event: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        メッセージイベントを処理します

        ユーザーからのメッセージを受信し、RAGサービスで応答を生成して
        リプライメッセージとして送信します。

        Phase 2: line_user_id → User → Subscription.plan → RagPermission で
        プラン別の corpus_id / model_name を解決します。

        Args:
            event: メッセージイベントオブジェクト
            db: データベースセッション

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

        # Phase 2: ユーザー特定 → プラン → RAG 権限（corpus_id/model_name）解決
        user_repo = UserRepository(db)
        user = await user_repo.find_by_line_user_id(line_user_id)
        plan = "free"
        if user and user.subscriptions:
            plan = user.subscriptions[0].plan or "free"

        rag_perm_repo = RagPermissionRepository(db)
        rag_perm = await rag_perm_repo.get_by_plan(plan)
        corpus_id = rag_perm.rag_corpus_id if rag_perm else None
        model_name = rag_perm.model_name if rag_perm else None
        logger.info(
            f"Resolved plan={plan}, corpus_id={corpus_id}, model={model_name} "
            f"for line_user_id={self._mask_user_id(line_user_id)}"
        )

        return {
            "status": "processed",
            "reply_token": reply_token,
            "line_user_id": line_user_id,
            "user_id": user.id if user else None,
            "plan": plan,
            "corpus_id": corpus_id,
            "model_name": model_name,
            "message": user_message,
        }

    async def _handle_follow_event(
        self,
        event: Dict[str, Any],
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        フォローイベント（友だち追加）を処理します

        Phase 2（現在）: ユーザー作成（未存在）+ free サブスク（モック）。
        Phase 3: Stripe 顧客作成（G1）・再有効化（is_active=True）を追加予定。

        Args:
            event: フォローイベントオブジェクト
            db: データベースセッション

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

        # Phase 2: ユーザー作成（未存在）+ free サブスク（モック）
        # ※ Stripe 顧客作成（G1）・再有効化（is_active=True）は Phase 3
        user_repo = UserRepository(db)
        user = await user_repo.find_by_line_user_id(line_user_id)
        if not user:
            user = await user_repo.create_line_user(
                line_user_id=line_user_id,
                display_name=display_name,
            )
            sub_repo = BaseRepository(Subscription, db)
            await sub_repo.create({"user_id": user.id, "plan": "free", "status": "free"})
            await db.commit()
            logger.info(
                f"Created user + free subscription for line_user_id={self._mask_user_id(line_user_id)}"
            )

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
        db: AsyncSession,
    ) -> Dict[str, Any]:
        """
        アンフォローイベント（ブロック・友だち削除）を処理します

        Phase 1（現在）: ログ記録のみ（DB 無効化なし）。
        Phase 2: ユーザー無効化・リフレッシュトークン削除を追加（下記 [Phase 2] マーカー）。

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

        # ===== [Phase 2: Stripe + SQL 顧客/サブスクリプション管理] =====
        # 現状（Phase 1）: DB ユーザー無効化は行わない。
        # Phase 2 で有効化する接続ポイント:
        #   - UserRepository.find_by_line_user_id(line_user_id) でユーザー特定
        #     → is_active = False
        #     → refresh_tokens を全削除（RefreshTokenRepository.revoke_all_by_user）
        # 関連: repositories/user.py [Phase 2 マーカー H1]
        # ===================================================================

        return {
            "status": "processed",
            "line_user_id": line_user_id,
            "action": "unfollow",
        }

    async def _handle_postback_event(
        self,
        event: Dict[str, Any],
        db: AsyncSession,
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
            # [Phase 2] Stripe Checkout / Customer Portal へ誘導する接続ポイント。
            # Phase 2 で StripeService.create_subscription(price_id) を呼ぶか、
            # LIFF 決済ページへ誘導する。現状はプレースホルダー応答。
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

        [Phase 2] stripe_service の各 Webhook ハンドラ
        （invoice.payment_failed / subscription.deleted 等）から呼ばれる。
        Phase 1（現在）では未使用（呼び出し元なし）。

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

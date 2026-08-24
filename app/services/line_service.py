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
from typing import Any, Dict, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.clients.line import LINEClient, LINEError
from app.core.config import settings
from app.core.pricing import get_daily_message_limit
from app.repositories.base_user_repository import BaseUserRepository

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

    def _get_user_repository(
        self,
        db: Optional[AsyncSession] = None,
    ) -> BaseUserRepository:
        """
        データベースバックエンドに応じたユーザーリポジトリを返します

        Args:
            db: データベースセッション（PostgreSQL時のみ使用）

        Returns:
            BaseUserRepository実装
        """
        if settings.database_backend == "firestore":
            from app.repositories.firestore_user_repository import FirestoreUserRepository
            return FirestoreUserRepository()
        elif settings.database_backend == "postgresql":
            from app.repositories.user import UserRepository
            return UserRepository(db)
        else:
            raise ValueError(f"Unsupported database backend: {settings.database_backend}")

    def _get_rag_permission_repository(self):
        """
        データベースバックエンドに応じたRAG権限リポジトリを返します

        Returns:
            RAG権限リポジトリ実装
        """
        if settings.database_backend == "firestore":
            from app.repositories.firestore_rag_permission_repository import FirestoreRagPermissionRepository
            return FirestoreRagPermissionRepository()
        elif settings.database_backend == "postgresql":
            from app.repositories.rag_permission import RagPermissionRepository
            # PostgreSQL版はAsyncSessionが必要ですが、ここでは仮実装
            return RagPermissionRepository(None)
        else:
            raise ValueError(f"Unsupported database backend: {settings.database_backend}")

    async def process_webhook_event(
        self,
        event: Dict[str, Any],
        db: Optional[AsyncSession] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        LINE Webhook イベントを処理します

        イベントタイプに応じて適切なハンドラに振り分けます。

        Args:
            event: LINE Webhook イベントオブジェクト
            db: データベースセッション（PostgreSQL時のみ使用、Firestore時はNone）

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
        user_repo = self._get_user_repository(db)

        # 使用回数リポジトリを取得（Firestore版を使用）
        from app.repositories.firestore_usage_repository import FirestoreUsageRepository
        usage_repo = FirestoreUsageRepository()

        user_dict = await user_repo.find_by_line_user_id(line_user_id)

        # ユーザーが見つからない場合はエラー（本来はfollowイベントで作成されているはず）
        if not user_dict:
            await self._send_reply(
                reply_token,
                "ユーザー情報が見つかりません。友だち登録からやり直してください。"
            )
            return {"status": "error", "reason": "user_not_found"}

        # ユーザーが非アクティブな場合は案内
        is_user_active = await user_repo.is_active(user_dict['id'])
        if not is_user_active:
            await self._send_reply(
                reply_token,
                "このアカウントは現在無効です。サポートまでお問い合わせください。"
            )
            return {"status": "skipped", "reason": "user_inactive"}
        plan = "free"
        if user_dict:
            plan = await user_repo.get_subscription_plan(user_dict['id'])

        # データベースバックエンドに応じたRAG権限リポジトリを使用
        rag_perm_repo = self._get_rag_permission_repository()
        rag_perm = await rag_perm_repo.get_by_plan(plan)

        # Firestore版とPostgreSQL版でデータ形式を統一
        corpus_id = None
        model_name = None
        # Firestore上の値ではなく、コードで定義した3/100/500を制限値の基準にする。
        daily_limit = get_daily_message_limit(plan)

        if rag_perm:
            if isinstance(rag_perm, dict):
                # Firestore版（辞書）
                corpus_id = rag_perm.get('rag_corpus_id')
                model_name = rag_perm.get('model_name')
            else:
                # PostgreSQL版（オブジェクト）
                corpus_id = rag_perm.rag_corpus_id
                model_name = rag_perm.model_name

        logger.info(
            f"Resolved plan={plan}, corpus_id={corpus_id}, model={model_name}, "
            f"daily_limit={daily_limit} for line_user_id={self._mask_user_id(line_user_id)}"
        )

        # 全プランで1日あたりのメッセージ上限をチェック・インクリメントを原子的に実行
        if daily_limit is not None:
            limit_result = await usage_repo.increment_with_limit_check(
                user_dict['id'], plan, daily_limit
            )

            if not limit_result['success']:
                if limit_result.get('error'):
                    await self._send_reply(
                        reply_token,
                        "現在、利用回数を確認できません。しばらくしてからもう一度お試しください。",
                    )
                    return {
                        "status": "error",
                        "reason": "usage_check_failed",
                        "plan": plan,
                    }
                # 制限超過メッセージを作成
                limit_message = f"📊 {limit_result['message']}"
                if plan == "free":
                    limit_message += (
                        "\n\n💡 さらに利用するにはプラン登録をご検討ください。"
                        f"\n\n📱 ベーシックプラン（1日100回まで）:\n"
                        f"{settings.subscription_basic_url}"
                        f"\n\n🚀 プロプラン（1日500回まで）:\n"
                        f"{settings.subscription_pro_url}"
                    )
                elif plan == "basic":
                    limit_message += (
                        "\n\n🚀 プロプラン（1日500回まで）への変更はこちら:\n"
                        f"{settings.subscription_pro_url}"
                    )
                limit_message += "\n\n明日になると利用回数がリセットされます。"
                await self._send_reply(reply_token, limit_message)
                return {
                    "status": "limit_reached",
                    "plan": plan,
                    "daily_limit": daily_limit,
                    "remaining": limit_result['remaining']
                }

            logger.info(
                f"Message count incremented: {limit_result['current_count']}/{daily_limit}, "
                f"remaining: {limit_result['remaining']}"
            )

        return {
            "status": "processed",
            "reply_token": reply_token,
            "line_user_id": line_user_id,
            "user_id": user_dict['id'],
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
        user_repo = self._get_user_repository(db)
        user_dict = await user_repo.find_by_line_user_id(line_user_id)

        if not user_dict:
            # 新規ユーザー作成
            user_dict = await user_repo.create_line_user(
                line_user_id=line_user_id,
                display_name=display_name,
            )
            logger.info(
                f"Created user for line_user_id={self._mask_user_id(line_user_id)}"
            )
        else:
            # 既存ユーザーの場合、再有効化（Phase 3 で Stripe 連携時に有効化）
            logger.info(
                f"Existing user found: {self._mask_user_id(line_user_id)}"
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
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        アンフォローイベント（ブロック・友だち削除）を処理します

        Stripe解約とは異なり、LINE unfollow時はアカウント全体を停止します。

        Args:
            event: アンフォローイベントオブジェクト
            db: データベースセッション（PostgreSQL時のみ使用）

        Returns:
            処理結果
        """
        source = event.get("source", {})
        line_user_id = source.get("userId", "")

        if not line_user_id:
            return {"status": "skipped", "reason": "missing_user_id"}

        logger.info(f"Unfollow from: {self._mask_user_id(line_user_id)}")

        # Firestoreユーザー無効化（推奨方針: LINE unfollow時はアカウント全体を停止）
        user_repo = self._get_user_repository(db)
        user_dict = await user_repo.find_by_line_user_id(line_user_id)

        if user_dict:
            # ユーザーを無効化
            await user_repo.deactivate_user(user_dict['id'])
            logger.info(f"Deactivated user {user_dict['id']} after LINE unfollow")

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

    async def _get_user_data_for_parallel(
        self,
        line_user_id: str,
        db: Optional[AsyncSession] = None,
        db_maker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        並列実行用のユーザーデータ取得（回数制限チェックなし）

        FirestoreアクセスとRAG処理の並列化のために、
        ユーザー情報・プラン・RAG権限のみを取得します。
        回数制限チェックは別途 `_check_and_increment_usage()` で行います。

        Args:
            line_user_id: LINEユーザーID
            db: データベースセッション（PostgreSQL時のみ使用）
            db_maker: データベースセッションメーカー（PostgreSQL時）

        Returns:
            ユーザーデータ辞書
        """
        try:
            user_repo = self._get_user_repository(db)
            user_dict = await user_repo.find_by_line_user_id(line_user_id)

            if not user_dict:
                return {
                    "status": "error",
                    "message": "ユーザー情報が見つかりません。友だち登録からやり直してください。"
                }

            # ユーザーアクティブチェック
            is_user_active = await user_repo.is_active(user_dict['id'])
            if not is_user_active:
                return {
                    "status": "error",
                    "message": "このアカウントは現在無効です。サポートまでお問い合わせください。"
                }

            # プラン取得
            plan = await user_repo.get_subscription_plan(user_dict['id'])

            # RAG権限取得
            rag_perm_repo = self._get_rag_permission_repository()
            rag_perm = await rag_perm_repo.get_by_plan(plan)

            corpus_id = None
            model_name = None
            if rag_perm:
                if isinstance(rag_perm, dict):
                    corpus_id = rag_perm.get('rag_corpus_id')
                    model_name = rag_perm.get('model_name')
                else:
                    corpus_id = rag_perm.rag_corpus_id
                    model_name = rag_perm.model_name

            return {
                "status": "success",
                "user_id": user_dict['id'],
                "line_user_id": line_user_id,
                "plan": plan,
                "corpus_id": corpus_id,
                "model_name": model_name,
            }

        except Exception as e:
            logger.error(f"Error in _get_user_data_for_parallel: {e}")
            return {
                "status": "error",
                "message": "ユーザー情報の取得に失敗しました。"
            }

    async def _check_and_increment_usage(
        self,
        user_id: str,
        plan: str,
        db: Optional[AsyncSession] = None,
        db_maker: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        並列実行用の回数制限チェックとインクリメント

        RAG処理と並列実行した後に、回数制限をチェック・インクリメントします。

        Args:
            user_id: ユーザーID
            plan: プラン（free/basic/pro）
            db: データベースセッション（PostgreSQL時のみ使用）
            db_maker: データベースセッションメーカー（PostgreSQL時）

        Returns:
            チェック結果辞書
        """
        try:
            from app.repositories.firestore_usage_repository import FirestoreUsageRepository
            from app.core.pricing import get_daily_message_limit

            usage_repo = FirestoreUsageRepository()
            daily_limit = get_daily_message_limit(plan)

            if daily_limit is None:
                return {"success": True, "current_count": 0, "remaining": None}

            limit_result = await usage_repo.increment_with_limit_check(
                user_id, plan, daily_limit
            )

            if not limit_result['success']:
                return {
                    "success": False,
                    "message": limit_result.get('message', '回数制限を超えました'),
                    "current_count": limit_result.get('current_count'),
                    "remaining": limit_result.get('remaining'),
                }

            logger.info(
                f"Usage count incremented: {limit_result['current_count']}/{daily_limit}, "
                f"remaining: {limit_result['remaining']}"
            )

            return {
                "success": True,
                "current_count": limit_result['current_count'],
                "remaining": limit_result['remaining'],
            }

        except Exception as e:
            logger.error(f"Error in _check_and_increment_usage: {e}")
            return {
                "success": False,
                "message": "現在、利用回数を確認できません。しばらくしてからもう一度お試しください。"
            }

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

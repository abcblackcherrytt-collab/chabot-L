"""LINE要望受付サービス。

クイックリプライ／ポストバックの「要望を送る」で受付モード（TTL10分）を開始し、
次の1通を要望として保存する。1日5通まで。「やめる」で取消できる。
"""

import logging
from typing import Optional

from app.repositories.firestore_feedback_repository import (
    FEEDBACK_DAILY_LIMIT,
    FirestoreFeedbackRepository,
)

logger = logging.getLogger(__name__)


FEEDBACK_ENTRY_TEXTS = {"要望を送る", "要望"}
FEEDBACK_CANCEL_TEXTS = {"やめる", "キャンセル", "取消"}


class FeedbackService:
    """要望受付モードと要望保存を担う。"""

    def __init__(self, feedback_repository: Optional[FirestoreFeedbackRepository] = None):
        """リポジトリを初期化する。"""
        self.feedback_repository = feedback_repository or FirestoreFeedbackRepository()

    async def start_pending(self, *, user_id: str) -> str:
        """受付モードを開始する。日次上限時は案内だけ返す。"""
        count = await self.feedback_repository.count_today_feedback(user_id)
        if count >= FEEDBACK_DAILY_LIMIT:
            return (
                "本日の要望受け付けは終了しました。\n"
                "また明日お送りください。ご協力ありがとうございます。"
            )
        await self.feedback_repository.start_pending(user_id=user_id)
        return (
            "この後のメッセージ1通を要望として受け付けます。\n"
            "機能要望・不具合・その他など、自由にお書きください。\n"
            "（取り消す場合は「やめる」と入力してください。10分間操作がないと自動的に終了します）"
        )

    async def handle_pending_message(
        self,
        *,
        user_id: str,
        text: str,
        display_name: str,
    ) -> Optional[str]:
        """受付モード中のメッセージを処理する。未処理（通常質問）ならNoneを返す。

        Returns:
            辞書（reply: 返信文, saved: 要望を保存したか）またはNone
        """
        pending = await self.feedback_repository.get_pending(user_id)
        if not pending:
            return None
        if text.strip() in FEEDBACK_CANCEL_TEXTS:
            await self.feedback_repository.cancel_pending(user_id)
            return {"reply": "要望の送信を取り消しました。通常どおりご質問ください。", "saved": False}
        count = await self.feedback_repository.count_today_feedback(user_id)
        if count >= FEEDBACK_DAILY_LIMIT:
            await self.feedback_repository.cancel_pending(user_id)
            return {"reply": "本日の要望受け付けは終了しました。また明日お送りください。", "saved": False}
        await self.feedback_repository.save(
            user_id=user_id,
            display_name=display_name,
            content=text,
        )
        await self.feedback_repository.cancel_pending(user_id)
        return {"reply": "要望を受け付けました。ご意見ありがとうございます。", "saved": True}

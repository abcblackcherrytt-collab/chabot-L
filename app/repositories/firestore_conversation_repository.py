"""Firestore会話保存リポジトリ"""

import logging
import re
from datetime import datetime
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")


# 氏名・施設名らしい表現だけを検知する。回答品質を保つためマスキングは行わない。
PII_SUSPECT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"[一-鿿]{2,4}(様|さん)"),
    re.compile(
        r"[一-鿿A-Za-z0-9ぁ-ゖァ-ヺ]+"
        r"(病院|医院|クリニック|接骨院|整体院|施設|センター)"
    ),
)


class FirestoreConversationRepository:
    """質問と回答のペアをFirestoreのconversationsコレクションへ保存する。"""

    collection_name = "conversations"

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    def detect_pii_suspected(self, *texts: Optional[str]) -> bool:
        """氏名・施設名らしいパターンが含まれるかだけを判定する。"""
        for text in texts:
            if not text:
                continue
            if any(pattern.search(text) for pattern in PII_SUSPECT_PATTERNS):
                return True
        return False

    async def save_conversation(
        self,
        *,
        user_id: str,
        question_text: str,
        answer_text: str,
        plan: str,
        denied: bool = False,
        question_type: Optional[str] = None,
        answer_aspects: Optional[Iterable[str]] = None,
    ) -> str:
        """回答済みの質問・回答ペアを1ドキュメントとして保存する。"""
        document: Dict[str, Any] = {
            "user_id": user_id,
            "question_text": question_text,
            "answer_text": answer_text,
            "plan": plan,
            "question_type": question_type,
            "answer_aspects": list(answer_aspects or []),
            "denied": denied,
            "pii_suspected": self.detect_pii_suspected(question_text, answer_text),
            "created_at": datetime.now(JST).isoformat(),
        }
        _, document_ref = await self.db.collection(self.collection_name).add(document)
        logger.info(
            "Conversation save completed: denied=%s pii_suspected=%s",
            document["denied"],
            document["pii_suspected"],
        )
        return document_ref.id

    async def save_limit_denied(self, *, user_id: str, plan: str) -> str:
        """日次上限拒否を本文なしのメタデータとして保存する。"""
        document: Dict[str, Any] = {
            "user_id": user_id,
            "question_text": None,
            "answer_text": None,
            "plan": plan,
            "question_type": None,
            "answer_aspects": [],
            "denied": True,
            "denial_reason": "daily_limit",
            "pii_suspected": False,
            "created_at": datetime.now(JST).isoformat(),
        }
        _, document_ref = await self.db.collection(self.collection_name).add(document)
        logger.info("Limit-denied conversation metadata saved: plan=%s", plan)
        return document_ref.id

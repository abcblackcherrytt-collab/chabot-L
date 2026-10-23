"""Firestore会話保存リポジトリ（利用者非紐付け版）。

会話アーカイブは質問本文・回答本文・日付（JST）の3フィールドのみを保存する。
ユーザーID・LINE ID・プラン・分類・正確な時刻・PII検知フラグは保存しない。
Firestoreの文書IDは自動採番のランダムキーで、ユーザーとの対応は保持しない。
認証・課金・回数管理に必要な利用者データは users / usage_daily 等の既存
コレクションで管理され、このリポジトリから参照しない。
"""

import logging
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)
JST = ZoneInfo("Asia/Tokyo")

ALLOWED_CONVERSATION_FIELDS = ("question_text", "answer_text", "date")


class FirestoreConversationRepository:
    """質問・回答・日付のみをconversationsコレクションへ保存する。"""

    collection_name = "conversations"

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    @staticmethod
    def _today_str() -> str:
        """現在のJST日付（YYYY-MM-DD）を返す。"""
        return datetime.now(JST).strftime("%Y-%m-%d")

    @classmethod
    def _build_document(
        cls,
        *,
        question_text: str,
        answer_text: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """許可された3フィールドだけの文書を組み立てる。"""
        normalized_date = date.strip() if isinstance(date, str) else ""
        return {
            "question_text": question_text,
            "answer_text": answer_text,
            "date": normalized_date or cls._today_str(),
        }

    @staticmethod
    def _pick_allowed_fields(data: Dict[str, Any]) -> Dict[str, Any]:
        """旧形式を含む文書から許可フィールドのみを取り出す。"""
        date_value = data.get("date")
        if not date_value:
            created_at = data.get("created_at")
            if isinstance(created_at, str) and len(created_at) >= 10:
                date_value = created_at[:10]
        return {
            "question_text": data.get("question_text"),
            "answer_text": data.get("answer_text"),
            "date": date_value,
        }

    async def save_conversation(
        self,
        *,
        question_text: str,
        answer_text: str,
        date: Optional[str] = None,
    ) -> str:
        """質問・回答・日付のみを1ドキュメントとして保存する。

        Args:
            question_text: 質問本文
            answer_text: 回答本文
            date: 保存する日付（YYYY-MM-DD）。未指定時は現在のJST日付

        Returns:
            保存されたドキュメントID（ランダムキー・利用者と無関係）
        """
        document = self._build_document(
            question_text=question_text,
            answer_text=answer_text,
            date=date,
        )
        _, document_ref = await self.db.collection(self.collection_name).add(document)
        logger.info("Conversation save completed: date=%s", document["date"])
        return document_ref.id

    async def list_metadata(self, limit: int = 100) -> Dict[str, Any]:
        """管理UI表示用に許可フィールドだけを新しい順に返す。"""
        docs = await (
            self.db.collection(self.collection_name)
            .order_by("date", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        items = []
        for doc in docs:
            item = {"id": doc.id}
            item.update(self._pick_allowed_fields(doc.to_dict() or {}))
            items.append(item)
        return {"items": items, "count": len(items)}

    async def get_question(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """代表回答入力用に会話の許可フィールドだけを返す。"""
        doc = await self.db.collection(self.collection_name).document(conversation_id).get()
        if not doc.exists:
            return None
        result = {"id": doc.id}
        result.update(self._pick_allowed_fields(doc.to_dict() or {}))
        return result

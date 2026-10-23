"""Firestore代表回答リポジトリ（representative_answers）。

会話保管から抽出した質問へ管理者が入力した代表回答を保存する。
1会話につき1件とし、上書き保存で更新する。
文書IDは対象会話のランダムキーを再利用し、利用者属性・分類・更新者などの
付帯情報は本文文書へ保存しない。管理操作の記録は監査ログ基盤で行う。
"""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)

REPRESENTATIVE_ANSWERS_COLLECTION = "representative_answers"

ALLOWED_REPRESENTATIVE_FIELDS = (
    "question_text",
    "representative_answer",
    "date",
)


class FirestoreRepresentativeAnswerRepository:
    """representative_answers コレクションの読み書きを提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    async def upsert(
        self,
        *,
        conversation_id: str,
        question_text: Optional[str],
        representative_answer: str,
        date: Optional[str] = None,
    ) -> Dict[str, Any]:
        """1会話1件で代表回答を保存・更新する。

        文書IDに会話のランダムキーを使うため、本文文書へ会話IDや
        利用者情報をフィールドとして保持する必要がない。
        """
        base = {
            "question_text": question_text,
            "representative_answer": representative_answer,
            "date": date,
        }
        doc_ref = self.db.collection(REPRESENTATIVE_ANSWERS_COLLECTION).document(
            conversation_id
        )
        await doc_ref.set(base)
        data = dict(base)
        data["id"] = conversation_id
        logger.info("Representative answer saved")
        return data

    async def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """許可フィールドのみを日付の新しい順に返す。"""
        docs = await (
            self.db.collection(REPRESENTATIVE_ANSWERS_COLLECTION)
            .order_by("date", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict() or {}
            item = {"id": doc.id}
            for field in ALLOWED_REPRESENTATIVE_FIELDS:
                item[field] = data.get(field)
            results.append(item)
        return results

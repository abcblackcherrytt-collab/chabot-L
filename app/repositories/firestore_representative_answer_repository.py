"""Firestore代表回答リポジトリ（representative_answers）。

会話保管から抽出した質問へ管理者が入力した代表回答を保存する。
1会話につき1件とし、上書き保存で更新する。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


REPRESENTATIVE_ANSWERS_COLLECTION = "representative_answers"


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
        question_type: Optional[str],
        plan: Optional[str],
        representative_answer: str,
        updated_by: str,
    ) -> Dict[str, Any]:
        """1会話1件で代表回答を保存・更新する。"""
        now = datetime.now(timezone.utc).isoformat()
        docs = await (
            self.db.collection(REPRESENTATIVE_ANSWERS_COLLECTION)
            .where("conversation_id", "==", conversation_id)
            .limit(1)
            .get()
        )
        base = {
            "conversation_id": conversation_id,
            "question_text": question_text,
            "question_type": question_type,
            "plan": plan,
            "representative_answer": representative_answer,
            "updated_by": updated_by,
            "updated_at": now,
        }
        if docs:
            ref = docs[0].reference
            await ref.update(base)
            data = dict(base)
            data["id"] = docs[0].id
            return data
        _, created = await (
            self.db.collection(REPRESENTATIVE_ANSWERS_COLLECTION).add(base)
        )
        data = dict(base)
        data["id"] = created.id
        logger.info("Representative answer saved: conversation_id=%s", conversation_id)
        return data

    async def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """更新順に代表回答の一覧を返す。"""
        docs = await (
            self.db.collection(REPRESENTATIVE_ANSWERS_COLLECTION)
            .order_by("updated_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

"""Firestore監査ログリポジトリ（admin_audit_logs）。

管理操作の監査記録の保存と参照を担う。本文・トークン平文・不要な個人情報は保存しない。
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from google.cloud import firestore

from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


AUDIT_LOGS_COLLECTION = "admin_audit_logs"
AUDIT_DETAIL_MAX_LENGTH = 200


class FirestoreAuditLogRepository:
    """admin_audit_logs コレクションの読み書きを提供する。"""

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestoreクライアントを初期化する。"""
        self.db = client or get_firestore_client_sync()

    async def record(
        self,
        *,
        actor: str,
        action: str,
        target_type: str,
        target_id: Optional[str] = None,
        revision: Optional[int] = None,
        result: str = "success",
        detail: Optional[str] = None,
    ) -> None:
        """監査ログを1件保存する。保存失敗は呼び出し側の操作を止めない設計とする。"""
        document = {
            "actor": actor,
            "action": action,
            "target_type": target_type,
            "target_id": target_id,
            "revision": revision,
            "result": result,
            "detail": (detail or "")[:AUDIT_DETAIL_MAX_LENGTH],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self.db.collection(AUDIT_LOGS_COLLECTION).add(document)
        except Exception as exc:
            logger.error(
                "Audit log write failed: action=%s error_type=%s",
                action,
                type(exc).__name__,
            )

    async def list(self, limit: int = 100) -> List[Dict[str, Any]]:
        """新しい順に監査ログを返す。"""
        docs = await (
            self.db.collection(AUDIT_LOGS_COLLECTION)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
            .get()
        )
        results = []
        for doc in docs:
            data = doc.to_dict()
            data["id"] = doc.id
            results.append(data)
        return results

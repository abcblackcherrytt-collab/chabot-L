"""
Firestore RAG権限リポジトリ
プラン別の RAG 設定（コーパスID・モデル・制限）の参照を提供します。

Firestore版実装で、プラン別にコーパスを切り替えるために使用します。
"""

import logging
import time
from typing import Optional, Dict, Any

from google.cloud import firestore

from app.core.config import settings
from app.core.firestore import get_firestore_client_sync

logger = logging.getLogger(__name__)


class FirestoreRagPermissionRepository:
    """
    Firestore RAG 権限リポジトリ

    プラン別の RAG 設定（rag_corpus_id / model_name / daily_message_limit 等）を
    Firestore から参照します。
    """

    _cache: Dict[str, tuple[float, Optional[Dict[str, Any]]]] = {}
    _cache_ttl_seconds = 60.0

    def __init__(self, client: Optional[firestore.AsyncClient] = None):
        """Firestore クライアントを初期化します"""
        self.db = client or get_firestore_client_sync()
        self.collection_name = 'rag_permissions'
        logger.info("Firestore RAG permission repository initialized")

    async def get_by_plan(self, plan: str) -> Optional[Dict[str, Any]]:
        """
        プラン名で RAG 権限を取得

        Args:
            plan: プラン名（free / basic / pro 等）

        Returns:
            RAG 権限データの辞書、存在しない場合は None
        """
        cache_key = (
            f"{settings.firestore_project_id}:"
            f"{settings.firestore_database_id}:{plan}"
        )
        cached = self._cache.get(cache_key)
        if cached and time.monotonic() - cached[0] < self._cache_ttl_seconds:
            value = cached[1]
            return dict(value) if value is not None else None

        try:
            docs = await self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .where('enabled', '==', True)\
                .limit(1)\
                .get()

            for doc in docs:
                perm_data = doc.to_dict()
                perm_data['id'] = doc.id
                logger.debug(f"RAG permission found for plan: {plan}")
                self._cache[cache_key] = (time.monotonic(), dict(perm_data))
                return perm_data

            logger.debug(f"RAG permission not found for plan: {plan}")
            self._cache[cache_key] = (time.monotonic(), None)
            return None

        except Exception as e:
            logger.error(f"Error getting RAG permission by plan: {e}")
            raise

    async def get_all_plans(self) -> list[Dict[str, Any]]:
        """
        全ての有効なプラン設定を取得

        Returns:
            RAG 権限データの辞書リスト
        """
        try:
            docs = await self.db.collection(self.collection_name)\
                .where('enabled', '==', True)\
                .get()

            permissions = []
            for doc in docs:
                perm_data = doc.to_dict()
                perm_data['id'] = doc.id
                permissions.append(perm_data)

            logger.debug(f"Retrieved {len(permissions)} RAG permissions")
            return permissions

        except Exception as e:
            logger.error(f"Error getting all RAG permissions: {e}")
            raise

    async def create_permission(
        self,
        plan: str,
        rag_corpus_id: str,
        model_name: str,
        max_input_tokens: int = 8000,
        max_output_tokens: int = 4000,
        daily_message_limit: int = 100,
        enabled: bool = True,
    ) -> Dict[str, Any]:
        """
        RAG 権限設定を作成

        Args:
            plan: プラン名
            rag_corpus_id: RAG コーパスID
            model_name: モデル名
            max_input_tokens: 最大入力トークン数
            max_output_tokens: 最大出力トークン数
            daily_message_limit: 1日のメッセージ上限
            enabled: 有効フラグ

        Returns:
            作成された RAG 権限データ
        """
        try:
            from datetime import datetime
            import uuid

            now = datetime.utcnow()
            perm_id = str(uuid.uuid4())

            perm_data = {
                'id': perm_id,
                'plan': plan,
                'rag_corpus_id': rag_corpus_id,
                'model_name': model_name,
                'max_input_tokens': max_input_tokens,
                'max_output_tokens': max_output_tokens,
                'daily_message_limit': daily_message_limit,
                'enabled': enabled,
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }

            await self.db.collection(self.collection_name).document(perm_id).set(perm_data)

            self._invalidate_plan_cache(plan)

            logger.info(f"Created RAG permission for plan: {plan}")
            return perm_data

        except Exception as e:
            logger.error(f"Error creating RAG permission: {e}")
            raise

    async def update_permission(
        self,
        plan: str,
        **updates,
    ) -> Optional[Dict[str, Any]]:
        """
        RAG 権限設定を更新

        Args:
            plan: プラン名
            **updates: 更新するフィールド

        Returns:
            更新後の RAG 権限データ、存在しない場合は None
        """
        try:
            from datetime import datetime

            # まず対象のドキュメントを検索
            docs = await self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .limit(1)\
                .get()

            for doc in docs:
                doc_ref = self.db.collection(self.collection_name).document(doc.id)

                # 更新データにタイムスタンプを追加
                update_data = {**updates, 'updated_at': datetime.utcnow().isoformat()}

                await doc_ref.update(update_data)

                self._invalidate_plan_cache(plan)

                # 更新後のデータを取得
                updated_doc = await doc_ref.get()
                if not updated_doc.exists:
                    raise LookupError(f"RAG permission disappeared during update: {plan}")
                updated_data = updated_doc.to_dict()
                updated_data['id'] = updated_doc.id

                logger.info(f"Updated RAG permission for plan: {plan}")
                return updated_data

            logger.debug(f"RAG permission not found for update: {plan}")
            return None

        except Exception as e:
            logger.error(f"Error updating RAG permission: {e}")
            raise

    async def delete_permission(self, plan: str) -> bool:
        """
        RAG 権限設定を削除

        Args:
            plan: プラン名

        Returns:
            削除成功なら True
        """
        try:
            # 対象のドキュメントを検索して削除
            docs = await self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .limit(1)\
                .get()

            for doc in docs:
                await self.db.collection(self.collection_name).document(doc.id).delete()
                self._invalidate_plan_cache(plan)
                logger.info(f"Deleted RAG permission for plan: {plan}")
                return True

            logger.debug(f"RAG permission not found for deletion: {plan}")
            return False

        except Exception as e:
            logger.error(f"Error deleting RAG permission: {e}")
            raise

    @classmethod
    def _invalidate_plan_cache(cls, plan: str) -> None:
        """指定プランの全環境キャッシュを破棄する。"""
        suffix = f":{plan}"
        for key in [key for key in cls._cache if key.endswith(suffix)]:
            cls._cache.pop(key, None)

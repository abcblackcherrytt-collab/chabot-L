"""
Firestore RAG権限リポジトリ
プラン別の RAG 設定（コーパスID・モデル・制限）の参照を提供します。

Firestore版実装で、プラン別にコーパスを切り替えるために使用します。
"""

import logging
from typing import Optional, Dict, Any

from google.cloud import firestore

logger = logging.getLogger(__name__)


class FirestoreRagPermissionRepository:
    """
    Firestore RAG 権限リポジトリ

    プラン別の RAG 設定（rag_corpus_id / model_name / daily_message_limit 等）を
    Firestore から参照します。
    """

    def __init__(self):
        """Firestore クライアントを初期化します"""
        self.db = firestore.Client()
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
        try:
            docs = self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .where('enabled', '==', True)\
                .limit(1)\
                .get()

            for doc in docs:
                perm_data = doc.to_dict()
                perm_data['id'] = doc.id
                logger.debug(f"RAG permission found for plan: {plan}")
                return perm_data

            logger.debug(f"RAG permission not found for plan: {plan}")
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
            docs = self.db.collection(self.collection_name)\
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

            self.db.collection(self.collection_name).document(perm_id).set(perm_data)

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
            docs = self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .limit(1)\
                .get()

            for doc in docs:
                doc_ref = self.db.collection(self.collection_name).document(doc.id)

                # 更新データにタイムスタンプを追加
                update_data = {**updates, 'updated_at': datetime.utcnow().isoformat()}

                doc_ref.update(update_data)

                # 更新後のデータを取得
                updated_doc = doc_ref.get()
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
            docs = self.db.collection(self.collection_name)\
                .where('plan', '==', plan)\
                .limit(1)\
                .get()

            for doc in docs:
                self.db.collection(self.collection_name).document(doc.id).delete()
                logger.info(f"Deleted RAG permission for plan: {plan}")
                return True

            logger.debug(f"RAG permission not found for deletion: {plan}")
            return False

        except Exception as e:
            logger.error(f"Error deleting RAG permission: {e}")
            raise

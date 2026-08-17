"""
Firestore使用記録リポジトリ
ユーザーのメッセージ使用回数の追跡・制限管理を行います。

Firestore版実装で、freeプランのメッセージ制限（3件/日）を実装します。
"""

import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from google.cloud import firestore

from app.core.pricing import get_daily_message_limit

logger = logging.getLogger(__name__)


class FirestoreUsageRepository:
    """
    Firestore使用記録リポジトリ

    ユーザーのメッセージ使用回数を追跡し、プラン別の制限管理を行います。
    """

    def __init__(self):
        """Firestoreクライアントを初期化します"""
        self.db = firestore.Client()
        self.daily_collection_name = 'usage_daily'
        logger.info("Firestore usage repository initialized")

    def _get_today_date_str(self) -> str:
        """
        今日の日付文字列（YYYY-MM-DD）を取得

        Returns:
            今日の日付文字列
        """
        return datetime.utcnow().strftime('%Y-%m-%d')

    async def get_daily_message_count(self, user_id: str) -> int:
        """
        今日のメッセージ使用回数を取得

        Args:
            user_id: ユーザーID

        Returns:
            今日のメッセージ回数
        """
        try:
            today = self._get_today_date_str()
            doc_id = f"{user_id}_{today}"

            doc = self.db.collection(self.daily_collection_name).document(doc_id).get()

            if doc.exists:
                usage_data = doc.to_dict()
                return usage_data.get('message_count', 0)

            return 0

        except Exception as e:
            logger.error(f"Error getting daily message count: {e}")
            return 0

    async def increment_message_count(self, user_id: str) -> int:
        """
        メッセージ使用回数をインクリメント

        Args:
            user_id: ユーザーID

        Returns:
            インクリメント後の今日のメッセージ回数
        """
        try:
            today = self._get_today_date_str()
            doc_id = f"{user_id}_{today}"
            doc_ref = self.db.collection(self.daily_collection_name).document(doc_id)

            # 現在の値を取得
            doc = doc_ref.get()
            if doc.exists:
                current_count = doc.to_dict().get('message_count', 0)
            else:
                current_count = 0

            new_count = current_count + 1

            # 更新データを設定
            update_data = {
                'user_id': user_id,
                'date': today,
                'message_count': new_count,
                'updated_at': datetime.utcnow().isoformat()
            }

            # 新規作成の場合はcreated_atを追加
            if not doc.exists:
                update_data['created_at'] = datetime.utcnow().isoformat()

            # ドキュメントを設定（createまたはupdate）
            doc_ref.set(update_data)

            logger.debug(f"Incremented message count for user {user_id}: {new_count}")
            return new_count

        except Exception as e:
            logger.error(f"Error incrementing message count: {e}")
            raise

    async def is_within_limit(self, user_id: str, plan: str, daily_limit: Optional[int] = None) -> bool:
        """
        メッセージ使用回数が制限内か確認

        Args:
            user_id: ユーザーID
            plan: サブスクリプションプラン（free/basic/pro）
            daily_limit: 1日のメッセージ上限（指定がない場合はプランデフォルト値）

        Returns:
            制限内ならTrue、超過ならFalse
        """
        try:
            # プランごとのデフォルト上限
            if daily_limit is None:
                daily_limit = get_daily_message_limit(plan)

            current_count = await self.get_daily_message_count(user_id)

            return current_count < daily_limit

        except Exception as e:
            logger.error(f"Error checking message limit: {e}")
            return False

    async def increment_with_limit_check(
        self,
        user_id: str,
        plan: str,
        daily_limit: Optional[int] = None
    ) -> dict:
        """
        上限確認とインクリメントを原子的に実行（Transaction版）

        同時実行時に制限超過を防ぐため、Firestore Transactionで
        「上限確認 + 加算」を1つのトランザクションで実行します。

        Args:
            user_id: ユーザーID
            plan: サブスクリプションプラン（free/basic/pro）
            daily_limit: 1日のメッセージ上限（指定がない場合はプランデフォルト値）

        Returns:
            辞書:
            - success: bool（制限内でインクリメント成功ならTrue）
            - current_count: int（インクリメント後の回数）
            - remaining: int（残り回数）
            - message: str（結果メッセージ）
        """
        try:
            # プランごとのデフォルト上限
            if daily_limit is None:
                daily_limit = get_daily_message_limit(plan)

            today = self._get_today_date_str()
            doc_id = f"{user_id}_{today}"
            doc_ref = self.db.collection(self.daily_collection_name).document(doc_id)

            # Firestore Transactionで原子的に実行
            transaction = self.db.transaction()

            @firestore.async_transactional
            def update_in_transaction(tx):
                # トランザクション内でドキュメントを取得
                doc = tx.get(doc_ref)[0]

                if doc.exists:
                    current_count = doc.to_dict().get('message_count', 0)
                else:
                    current_count = 0

                # 上限確認
                if current_count >= daily_limit:
                    return {
                        'success': False,
                        'current_count': current_count,
                        'remaining': 0,
                        'message': f'日次メッセージ上限に達しました（{daily_limit}件/日）'
                    }

                # インクリメント
                new_count = current_count + 1

                # 更新データを設定
                update_data = {
                    'user_id': user_id,
                    'date': today,
                    'message_count': new_count,
                    'updated_at': datetime.utcnow().isoformat()
                }

                # 新規作成の場合はcreated_atを追加
                if not doc.exists:
                    update_data['created_at'] = datetime.utcnow().isoformat()

                # ドキュメントを設定（createまたはupdate）
                tx.set(doc_ref, update_data)

                return {
                    'success': True,
                    'current_count': new_count,
                    'remaining': daily_limit - new_count,
                    'message': f'メッセージ回数をインクリメントしました（残り{daily_limit - new_count}件）'
                }

            result = await transaction(update_in_transaction)

            logger.info(f"Transaction result for user {user_id}: {result}")
            return result

        except Exception as e:
            logger.error(f"Error in increment_with_limit_check: {e}")
            return {
                'success': False,
                'current_count': 0,
                'remaining': 0,
                'message': f'エラーが発生しました: {str(e)}'
            }

    async def get_remaining_messages(self, user_id: str, plan: str, daily_limit: Optional[int] = None) -> int:
        """
        残りメッセージ回数を取得

        Args:
            user_id: ユーザーID
            plan: サブスクリプションプラン
            daily_limit: 1日のメッセージ上限（指定がない場合はプランデフォルト値）

        Returns:
            残りメッセージ回数
        """
        try:
            # プランごとのデフォルト上限
            if daily_limit is None:
                daily_limit = get_daily_message_limit(plan)

            current_count = await self.get_daily_message_count(user_id)
            remaining = daily_limit - current_count

            return max(0, remaining)

        except Exception as e:
            logger.error(f"Error getting remaining messages: {e}")
            return 0

    async def cleanup_old_records(self, days_to_keep: int = 7) -> int:
        """
        古い使用記録を削除

        Args:
            days_to_keep: 保持する日数（デフォルト: 7日）

        Returns:
            削除したレコード数
        """
        try:
            cutoff_date = (datetime.utcnow() - timedelta(days=days_to_keep)).strftime('%Y-%m-%d')

            # 古い日付のドキュメントを検索して削除
            docs = self.db.collection(self.daily_collection_name)\
                .where('date', '<', cutoff_date)\
                .get()

            deleted_count = 0
            batch = self.db.batch()
            batch_size = 0

            for doc in docs:
                batch.delete(doc.reference)
                batch_size += 1
                deleted_count += 1

                # Firestoreは1回のバッチで最大500操作
                if batch_size >= 500:
                    batch.commit()
                    batch = self.db.batch()
                    batch_size = 0

            if batch_size > 0:
                batch.commit()

            logger.info(f"Cleaned up {deleted_count} old usage records")
            return deleted_count

        except Exception as e:
            logger.error(f"Error cleaning up old records: {e}")
            return 0

    async def reset_daily_count(self, user_id: str) -> bool:
        """
        テスト用：今日のメッセージ回数をリセット

        Args:
            user_id: ユーザーID

        Returns:
            リセット成功ならTrue
        """
        try:
            today = self._get_today_date_str()
            doc_id = f"{user_id}_{today}"

            self.db.collection(self.daily_collection_name).document(doc_id).delete()
            logger.info(f"Reset daily count for user: {user_id}")
            return True

        except Exception as e:
            logger.error(f"Error resetting daily count: {e}")
            return False

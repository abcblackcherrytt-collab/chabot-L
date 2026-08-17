"""
テストデータのクリーンアップスクリプト

テスト用に作成したユーザーデータをFirestoreから削除します。

使用方法:
    # 特定のユーザーを削除
    python scripts/cleanup_test_data.py --user-id USER_ID

    # テストユーザーを一括削除（display_nameに"テスト"を含むユーザー）
    python scripts/cleanup_test_data.py --all-test-users
"""

import logging
import sys
import os
import argparse

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore
from app.core.config import settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def delete_user(db, user_id: str) -> bool:
    """
    ユーザーを削除

    Args:
        db: Firestoreクライアント
        user_id: 削除するユーザーID

    Returns:
        削除成功ならTrue
    """
    try:
        user_ref = db.collection('users').document(user_id)

        # ユーザーが存在するか確認
        doc = user_ref.get()
        if not doc.exists:
            logger.warning(f"User {user_id} does not exist")
            return False

        # ユーザー情報を取得して表示
        user_data = doc.to_dict()
        display_name = user_data.get('display_name', 'Unknown')
        line_user_id = user_data.get('line_user_id', 'Unknown')

        logger.info(f"Deleting user: {display_name} (line_user_id: {line_user_id}, id: {user_id})")

        # ユーザーを削除
        user_ref.delete()
        logger.info(f"✅ Successfully deleted user {user_id}")
        return True

    except Exception as e:
        logger.error(f"❌ Error deleting user {user_id}: {e}")
        return False


def cleanup_test_users(db) -> int:
    """
    テストユーザーを一括削除

    Args:
        db: Firestoreクライアント

    Returns:
        削除したユーザー数
    """
    try:
        # テストユーザーを検索（display_nameに"テスト"を含む）
        docs = db.collection('users')\
            .where('display_name', '>=', 'テスト')\
            .where('display_name', '<=', 'テスト￿')\
            .get()

        deleted_count = 0
        for doc in docs:
            user_id = doc.id
            if delete_user(db, user_id):
                deleted_count += 1

                # 関連する使用記録も削除
                cleanup_usage_records_by_user(db, user_id)

        logger.info(f"Total test users deleted: {deleted_count}")
        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up test users: {e}")
        return 0


def cleanup_usage_records_by_user(db, user_id: str) -> int:
    """
    ユーザーの使用記録を削除

    Args:
        db: Firestoreクライアント
        user_id: ユーザーID

    Returns:
        削除したレコード数
    """
    try:
        # ユーザーIDで始まるドキュメントを検索（usage_dailyコレクション）
        # 注: Firestoreでは前方一致検索が制限されているため、
        # 日付範囲を指定して削除するか、個別に削除する必要があります
        docs = db.collection('usage_daily').where('user_id', '==', user_id).get()

        deleted_count = 0
        batch = db.batch()
        batch_size = 0

        for doc in docs:
            batch.delete(doc.reference)
            batch_size += 1
            deleted_count += 1

            # Firestoreは1回のバッチで最大500操作
            if batch_size >= 500:
                batch.commit()
                batch = db.batch()
                batch_size = 0

        if batch_size > 0:
            batch.commit()

        if deleted_count > 0:
            logger.info(f"Deleted {deleted_count} usage records for user {user_id}")

        return deleted_count

    except Exception as e:
        logger.error(f"Error cleaning up usage records: {e}")
        return 0


def list_users(db, limit: int = 20):
    """
    ユーザー一覧を表示

    Args:
        db: Firestoreクライアント
        limit: 表示件数
    """
    try:
        logger.info(f"Listing users (limit: {limit}):")
        docs = db.collection('users').limit(limit).get()

        for doc in docs:
            user_data = doc.to_dict()
            logger.info(f"  - {user_data.get('display_name', 'Unknown')} "
                       f"(id: {doc.id}, line_user_id: {user_data.get('line_user_id', 'N/A')}, "
                       f"plan: {user_data.get('subscription_plan', 'N/A')})")

    except Exception as e:
        logger.error(f"Error listing users: {e}")


def main():
    """メイン処理"""
    parser = argparse.ArgumentParser(description='テストデータのクリーンアップ')
    parser.add_argument('--user-id', type=str, help='削除するユーザーID')
    parser.add_argument('--all-test-users', action='store_true', help='テストユーザーを一括削除')
    parser.add_argument('--list', action='store_true', help='ユーザー一覧を表示')
    parser.add_argument('--limit', type=int, default=20, help='一覧表示の最大件数（デフォルト: 20）')

    args = parser.parse_args()

    # Firestoreクライアントの初期化
    db = firestore.Client(project=settings.firestore_project_id)

    if args.user_id:
        # 特定のユーザーを削除
        delete_user(db, args.user_id)

    elif args.all_test_users:
        # テストユーザーを一括削除
        cleanup_test_users(db)

    elif args.list:
        # ユーザー一覧を表示
        list_users(db, args.limit)

    else:
        # ヘルプを表示
        parser.print_help()
        print("\n例:")
        print("  python scripts/cleanup_test_data.py --user-id abc123")
        print("  python scripts/cleanup_test_data.py --all-test-users")
        print("  python scripts/cleanup_test_data.py --list --limit 10")


if __name__ == "__main__":
    main()

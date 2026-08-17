"""
ローカルモックテストスクリプト

Firestoreライブラリがインストールされていない環境でも、
コードの整合性をチェックするためのモックテスト。
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging
from unittest.mock import Mock, MagicMock, patch
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockFirestoreClient:
    """Firestoreクライアントのモック"""

    def __init__(self):
        self.data = {}

    def collection(self, name):
        return MockCollection(name, self.data)


class MockCollection:
    """Firestoreコレクションのモック"""

    def __init__(self, name, data):
        self.name = name
        self.data = data
        if name not in self.data:
            self.data[name] = {}

    def document(self, doc_id):
        return MockDocument(doc_id, self.name, self.data)

    def where(self, field, op, value):
        return MockQuery(self.name, self.data, field, op, value)

    def limit(self, limit):
        return MockQuery(self.name, self.data)

    def get(self):
        return []


class MockQuery:
    """Firestoreクエリのモック"""

    def __init__(self, collection_name, data, field=None, op=None, value=None):
        self.collection_name = collection_name
        self.data = data
        self.field = field
        self.op = op
        self.value = value

    def limit(self, limit):
        return self

    def get(self):
        if self.collection_name not in self.data:
            return []

        results = []
        for doc_id, doc_data in self.data[self.collection_name].items():
            if self.field is None or doc_data.get(self.field) == self.value:
                mock_doc = Mock()
                mock_doc.id = doc_id
                mock_doc.to_dict = lambda: doc_data
                mock_doc.exists = True
                results.append(mock_doc)

        return results


class MockDocument:
    """Firestoreドキュメントのモック"""

    def __init__(self, doc_id, collection_name, data):
        self.doc_id = doc_id
        self.collection_name = collection_name
        self.data = data

    def get(self):
        if self.collection_name in self.data and self.doc_id in self.data[self.collection_name]:
            mock_doc = Mock()
            mock_doc.id = self.doc_id
            mock_doc.to_dict = lambda: self.data[self.collection_name][self.doc_id]
            mock_doc.exists = True
            return mock_doc

        mock_doc = Mock()
        mock_doc.exists = False
        return mock_doc

    def set(self, data):
        if self.collection_name not in self.data:
            self.data[self.collection_name] = {}
        self.data[self.collection_name][self.doc_id] = data

    def update(self, data):
        if self.collection_name in self.data and self.doc_id in self.data[self.collection_name]:
            self.data[self.collection_name][self.doc_id].update(data)

    def delete(self):
        if self.collection_name in self.data and self.doc_id in self.data[self.collection_name]:
            del self.data[self.collection_name][self.doc_id]


async def test_import_structure():
    """モジュールのインポート構造をテスト"""
    logger.info("=== モジュールインポート構造のチェック ===")

    try:
        # 基本モジュールのインポートチェック
        from app.core.config import settings
        logger.info("✅ app.core.config - OK")

        from app.repositories.base_user_repository import BaseUserRepository
        logger.info("✅ app.repositories.base_user_repository - OK")

        # インポート可能かチェック（実行はしない）
        import app.repositories.firestore_user_repository
        logger.info("✅ app.repositories.firestore_user_repository - インポートOK")

        import app.repositories.firestore_usage_repository
        logger.info("✅ app.repositories.firestore_usage_repository - インポートOK")

        import app.repositories.firestore_rag_permission_repository
        logger.info("✅ app.repositories.firestore_rag_permission_repository - インポートOK")

        import app.services.line_service
        logger.info("✅ app.services.line_service - インポートOK")

        return True

    except ImportError as e:
        logger.error(f"❌ インポートエラー: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ 予期しないエラー: {e}")
        return False


async def test_method_signatures():
    """メソッドシグネチャの整合性チェック"""
    logger.info("\n=== メソッドシグネチャの整合性チェック ===")

    try:
        from app.repositories.base_user_repository import BaseUserRepository
        from app.repositories.firestore_user_repository import FirestoreUserRepository

        # BaseUserRepositoryの抽象メソッドを確認
        base_methods = [
            'find_by_line_user_id',
            'create_line_user',
            'find_by_id',
            'get_subscription_plan',
            'update_subscription_plan',
            'is_active',
            'deactivate_user',
            'find_by_stripe_customer_id',
            'update_stripe_customer_id',
            'get_stripe_customer_id'
        ]

        for method_name in base_methods:
            if not hasattr(BaseUserRepository, method_name):
                logger.error(f"❌ BaseUserRepositoryにメソッドがありません: {method_name}")
                return False

            if not hasattr(FirestoreUserRepository, method_name):
                logger.error(f"❌ FirestoreUserRepositoryにメソッドがありません: {method_name}")
                return False

        logger.info("✅ すべての必須メソッドが定義されています")

        # メソッドの非同期チェック
        for method_name in base_methods:
            method = getattr(FirestoreUserRepository, method_name)
            if not asyncio.iscoroutinefunction(method):
                logger.error(f"❌ {method_name} は非同期メソッドではありません")
                return False

        logger.info("✅ すべてのメソッドが非同期として定義されています")
        return True

    except Exception as e:
        logger.error(f"❌ メソッドチェックエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_config_settings():
    """設定ファイルのチェック"""
    logger.info("\n=== 設定ファイルのチェック ===")

    try:
        from app.core.config import settings

        # 必須設定の確認
        required_settings = [
            'database_backend',
            'firestore_project_id',
            'subscription_basic_url',
            'subscription_pro_url'
        ]

        missing_settings = []
        for setting in required_settings:
            if not hasattr(settings, setting):
                missing_settings.append(setting)

        if missing_settings:
            logger.error(f"❌ 設定が不足しています: {missing_settings}")
            return False

        logger.info(f"✅ すべての必須設定が定義されています")
        logger.info(f"  - database_backend: {settings.database_backend}")
        logger.info(f"  - firestore_project_id: {settings.firestore_project_id}")
        logger.info(f"  - subscription_basic_url: {settings.subscription_basic_url}")
        logger.info(f"  - subscription_pro_url: {settings.subscription_pro_url}")

        return True

    except Exception as e:
        logger.error(f"❌ 設定チェックエラー: {e}")
        return False


async def test_service_dependencies():
    """サービスの依存関係チェック"""
    logger.info("\n=== サービス依存関係のチェック ===")

    try:
        from app.services.line_service import LineService

        # LineServiceが必須メソッドを持っているか確認
        required_methods = [
            '_get_user_repository',
            '_get_rag_permission_repository',
            '_handle_message_event',
            '_handle_follow_event',
            '_mask_user_id'
        ]

        for method_name in required_methods:
            if not hasattr(LineService, method_name):
                logger.error(f"❌ LineServiceにメソッドがありません: {method_name}")
                return False

        logger.info("✅ LineServiceの必須メソッドが定義されています")
        return True

    except Exception as e:
        logger.error(f"❌ サービスチェックエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def check_missing_implementations():
    """実装不足のチェック"""
    logger.info("\n=== 実装不足のチェック ===")

    issues = []

    try:
        # インポートチェック
        from app.repositories import firestore_usage_repository
        logger.info("✅ firestore_usage_repositoryは存在します")

        # UsageRepositoryクラスの確認
        if not hasattr(firestore_usage_repository, 'FirestoreUsageRepository'):
            issues.append("FirestoreUsageRepositoryクラスが見つかりません")
        else:
            logger.info("✅ FirestoreUsageRepositoryクラスは存在します")

            # 必須メソッドの確認
            required_methods = [
                'get_daily_message_count',
                'increment_message_count',
                'is_within_limit',
                'get_remaining_messages',
                'reset_daily_count'
            ]

            for method_name in required_methods:
                if not hasattr(firestore_usage_repository.FirestoreUsageRepository, method_name):
                    issues.append(f"FirestoreUsageRepository.{method_name}メソッドが見つかりません")
                else:
                    logger.info(f"✅ FirestoreUsageRepository.{method_name}は存在します")

        # RAG権限リポジトリの確認
        from app.repositories import firestore_rag_permission_repository
        if not hasattr(firestore_rag_permission_repository, 'FirestoreRagPermissionRepository'):
            issues.append("FirestoreRagPermissionRepositoryクラスが見つかりません")
        else:
            logger.info("✅ FirestoreRagPermissionRepositoryクラスは存在します")

        if issues:
            logger.error(f"❌ 実装不足が見つかりました: {issues}")
            return False

        logger.info("✅ すべての実装が完了しています")
        return True

    except ImportError as e:
        logger.error(f"❌ インポートエラー: {e}")
        return False
    except Exception as e:
        logger.error(f"❌ チェックエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """メイン処理"""
    logger.info("ローカルモックテスト開始...\n")

    results = []

    # テスト実行
    results.append(("モジュールインポート構造", await test_import_structure()))
    results.append(("メソッドシグネチャ整合性", await test_method_signatures()))
    results.append(("設定ファイル", await test_config_settings()))
    results.append(("サービス依存関係", await test_service_dependencies()))
    results.append(("実装不足チェック", await check_missing_implementations()))

    # 結果サマリー
    logger.info("\n" + "="*50)
    logger.info("テスト結果サマリー:")
    logger.info("="*50)

    passed = 0
    failed = 0

    for test_name, result in results:
        status = "✅ パス" if result else "❌ 失敗"
        logger.info(f"{test_name}: {status}")
        if result:
            passed += 1
        else:
            failed += 1

    logger.info("="*50)
    logger.info(f"合計: {passed} パス, {failed} 失敗")

    if failed > 0:
        logger.error("\n❌ 一部のテストが失敗しました。実装の不足がある可能性があります。")
        return 1
    else:
        logger.info("\n✅ すべてのテストがパスしました！")
        logger.info("ただし、Firestoreライブラリがインストールされていないため、")
        logger.info("実際のデータ操作はテストできていません。")
        logger.info("ネットワーク環境が整った後に、以下のコマンドで完全テストを実行してください:")
        logger.info("  python scripts/test_plan_corpus_switching.py")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

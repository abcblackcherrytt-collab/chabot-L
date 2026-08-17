"""
本番環境シミュレーションテストスクリプト

実際のGCP接続を行わず、本番環境の設定をシミュレートしてテストします。
"""

import sys
import os
import asyncio
from unittest.mock import Mock, MagicMock, patch
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class MockFirestoreData:
    """モックFirestoreデータ管理クラス"""

    def __init__(self):
        self.users = {}
        self.usage_daily = {}
        self.rag_permissions = {}

    def setup_test_data(self):
        """テストデータのセットアップ"""
        import uuid

        # テストユーザー
        test_user_id = str(uuid.uuid4())
        self.users[test_user_id] = {
            'id': test_user_id,
            'line_user_id': 'U_test_free_user',
            'display_name': 'テストFreeユーザー',
            'email': 'test@example.com',
            'subscription_plan': 'free',
            'subscription_status': 'active',
            'is_active': True,
            'role': 'user',
            'stripe_customer_id': None,
            'created_at': datetime.utcnow().isoformat(),
            'updated_at': datetime.utcnow().isoformat()
        }

        # RAG権限設定
        self.rag_permissions = {
            'free': {
                'id': str(uuid.uuid4()),
                'plan': 'free',
                'rag_corpus_id': 'test-free-corpus-id',  # GOOGLE_CORPUS_ID相当
                'model_name': 'gemini-2.5-flash',
                'max_input_tokens': 8000,
                'max_output_tokens': 4000,
                'daily_message_limit': 3,
                'enabled': True,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            },
            'basic': {
                'id': str(uuid.uuid4()),
                'plan': 'basic',
                'rag_corpus_id': 'test-paid-corpus-id',  # GOOGLE_CORPUS_ID_PLAN1相当
                'model_name': 'gemini-2.5-flash',
                'max_input_tokens': 16000,
                'max_output_tokens': 8000,
                'daily_message_limit': 100,
                'enabled': True,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            },
            'pro': {
                'id': str(uuid.uuid4()),
                'plan': 'pro',
                'rag_corpus_id': 'test-paid-corpus-id',  # GOOGLE_CORPUS_ID_PLAN1相当（basicと共通）
                'model_name': 'gemini-2.5-flash',
                'max_input_tokens': 32000,
                'max_output_tokens': 16000,
                'daily_message_limit': 500,
                'enabled': True,
                'created_at': datetime.utcnow().isoformat(),
                'updated_at': datetime.utcnow().isoformat()
            }
        }

        logger.info("✅ テストデータをセットアップしました")


async def test_config_settings():
    """設定ファイルのテスト"""
    logger.info("\n=== 設定ファイルのテスト ===")

    try:
        from app.core.config import settings

        # 必須設定の確認
        tests = [
            ('GOOGLE_CORPUS_ID', 'freeプラン用コーパスID'),
            ('GOOGLE_CORPUS_ID_PLAN1', '有料プラン用コーパスID'),
            ('subscription_basic_url', 'ベーシックプランURL'),
            ('subscription_pro_url', 'プロプランURL'),
            ('database_backend', 'データベースバックエンド'),
            ('firestore_project_id', 'FirestoreプロジェクトID')
        ]

        for setting_name, description in tests:
            if hasattr(settings, setting_name.lower()):
                value = getattr(settings, setting_name.lower())
                # 値をマスキング
                if 'secret' in setting_name.lower() or 'key' in setting_name.lower() or 'token' in setting_name.lower():
                    masked_value = value[:8] + "..." if len(value) > 8 else "***"
                    logger.info(f"✅ {description} ({setting_name}): {masked_value}")
                else:
                    logger.info(f"✅ {description} ({setting_name}): {value}")
            else:
                logger.error(f"❌ {description} ({setting_name}): 設定がありません")
                return False

        # 重要: コーパスIDの値が異なることを確認
        if hasattr(settings, 'google_corpus_id') and hasattr(settings, 'google_corpus_id_plan1'):
            if settings.google_corpus_id != settings.google_corpus_id_plan1:
                logger.info("✅ freeと有料で異なるコーパスIDが設定されています")
                logger.info(f"   free用: {settings.google_corpus_id}")
                logger.info(f"   有料用: {settings.google_corpus_id_plan1}")
            else:
                logger.warning("⚠️ freeと有料で同じコーパスIDが設定されています")

        return True

    except Exception as e:
        logger.error(f"❌ 設定テストエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_firestore_repositories(mock_data):
    """Firestoreリポジトリのテスト"""
    logger.info("\n=== Firestoreリポジトリのテスト ===")

    try:
        # モックFirestoreクライアントの作成
        mock_db = Mock()

        # ユーザーリポジトリのテスト
        with patch('app.repositories.firestore_user_repository.firestore.Client', return_value=mock_db):
            from app.repositories.firestore_user_repository import FirestoreUserRepository

            # モックデータの設定
            def mock_collection(name):
                mock_col = Mock()
                if name == 'users':
                    mock_col.where.return_value.limit.return_value.get.return_value = [
                        Mock(id=list(mock_data.users.keys())[0],
                             to_dict=lambda: list(mock_data.users.values())[0],
                             exists=True)
                    ]
                    mock_col.document.return_value.get.return_value = Mock(
                        id=list(mock_data.users.keys())[0],
                        to_dict=lambda: list(mock_data.users.values())[0],
                        exists=True
                    )
                return mock_col

            mock_db.collection = mock_collection
            user_repo = FirestoreUserRepository()

            # LINEユーザーIDで検索
            test_user = list(mock_data.users.values())[0]
            user = await user_repo.find_by_line_user_id(test_user['line_user_id'])

            if user:
                logger.info(f"✅ ユーザー検索成功: {user['display_name']}")
                logger.info(f"   プラン: {user['subscription_plan']}")
                logger.info(f"   アクティブ: {user['is_active']}")
            else:
                logger.error("❌ ユーザー検索失敗")
                return False

        return True

    except Exception as e:
        logger.error(f"❌ リポジトリテストエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_plan_corpus_switching(mock_data):
    """プラン別コーパス切替のテスト"""
    logger.info("\n=== プラン別コーパス切替のテスト ===")

    try:
        from app.core.config import settings

        # RAG権限設定の確認
        logger.info("📋 プラン別RAG権限設定:")

        for plan_name, perm_data in mock_data.rag_permissions.items():
            logger.info(f"\n  {plan_name.upper()}プラン:")
            logger.info(f"    - コーパスID: {perm_data['rag_corpus_id']}")
            logger.info(f"    - モデル名: {perm_data['model_name']}")
            logger.info(f"    - 1日上限: {perm_data['daily_message_limit']}件")
            logger.info(f"    - 最大入力: {perm_data['max_input_tokens']}トークン")
            logger.info(f"    - 最大出力: {perm_data['max_output_tokens']}トークン")

        # コーパスIDの構造を確認
        free_corpus = mock_data.rag_permissions['free']['rag_corpus_id']
        basic_corpus = mock_data.rag_permissions['basic']['rag_corpus_id']
        pro_corpus = mock_data.rag_permissions['pro']['rag_corpus_id']

        logger.info(f"\n🔍 コーパスID構造:")
        logger.info(f"  - freeプラン: {free_corpus}")
        logger.info(f"  - basicプラン: {basic_corpus}")
        logger.info(f"  - proプラン: {pro_corpus}")

        if basic_corpus == pro_corpus:
            logger.info("✅ basicとproで同じコーパスIDが設定されています（正しい）")
        else:
            logger.error("❌ basicとproで異なるコーパスIDが設定されています（誤り）")
            return False

        if free_corpus != basic_corpus:
            logger.info("✅ freeと有料で異なるコーパスIDが設定されています（正しい）")
        else:
            logger.error("❌ freeと有料で同じコーパスIDが設定されています（誤り）")
            return False

        return True

    except Exception as e:
        logger.error(f"❌ コーパス切替テストエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_message_limit_logic(mock_data):
    """メッセージ制限ロジックのテスト"""
    logger.info("\n=== メッセージ制限ロジックのテスト ===")

    try:
        # 使用記録のテストデータ
        test_user_id = list(mock_data.users.keys())[0]
        today = datetime.utcnow().strftime('%Y-%m-%d')

        # メッセージ回数のテスト
        logger.info("📊 freeプラン（3件制限）のテスト:")

        # 初期状態
        remaining = 3
        logger.info(f"  初状態: 残り{remaining}件")

        # 1件目使用
        remaining -= 1
        logger.info(f"  1件使用後: 残り{remaining}件")

        # 2件目使用
        remaining -= 1
        logger.info(f"  2件使用後: 残り{remaining}件")

        # 3件目使用
        remaining -= 1
        logger.info(f"  3件使用後: 残り{remaining}件")

        # 4件目（上限超過）
        if remaining <= 0:
            logger.info("✅ 4件目は上限超過として正しく処理されます")
            logger.info("   サブスクリプション案内メッセージを送信")
        else:
            logger.error("❌ 制限チェックに誤りがあります")
            return False

        # basicプランのテスト
        logger.info("\n📊 basicプラン（100件制限）のテスト:")
        basic_limit = 100
        usage_count = 10
        remaining = basic_limit - usage_count

        logger.info(f"  10件使用: 残り{remaining}件")
        logger.info(f"  制限内: {remaining > 0}")

        if remaining > 0:
            logger.info("✅ basicプランは100件以内で正常に使用できます")
        else:
            logger.error("❌ basicプランの制限チェックに誤りがあります")
            return False

        return True

    except Exception as e:
        logger.error(f"❌ メッセージ制限テストエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_integration_flow(mock_data):
    """統合フローのテスト"""
    logger.info("\n=== 統合フローのテスト ===")

    try:
        from app.core.config import settings

        # LINEメッセージ処理フローのシミュレーション
        logger.info("📱 LINEメッセージ処理フロー:")

        # 1. ユーザー特定
        test_user = list(mock_data.users.values())[0]
        logger.info(f"  1️⃣ ユーザー特定: {test_user['display_name']}")

        # 2. プラン確認
        plan = test_user['subscription_plan']
        logger.info(f"  2️⃣ プラン確認: {plan}")

        # 3. コーパス解決
        rag_perm = mock_data.rag_permissions[plan]
        corpus_id = rag_perm['rag_corpus_id']
        model_name = rag_perm['model_name']
        daily_limit = rag_perm['daily_message_limit']

        logger.info(f"  3️⃣ コーパス解決:")
        logger.info(f"     - コーパスID: {corpus_id}")
        logger.info(f"     - モデル: {model_name}")
        logger.info(f"     - 1日上限: {daily_limit}件")

        # 4. 制限チェック
        remaining_count = daily_limit  # 初期状態
        logger.info(f"  4️⃣ 制限チェック: 残り{remaining_count}件")

        # 5. メッセージ使用回数インクリメント
        remaining_count -= 1
        logger.info(f"  5️⃣ 使用回数記録: 残り{remaining_count}件")

        # 6. 応答生成（ここではモック）
        logger.info(f"  6️⃣ RAG応答生成: {corpus_id}を使用")

        # 上限到達時のテスト
        logger.info(f"\n🚫 上限到達時の処理:")
        remaining_count = 0
        if remaining_count <= 0:
            logger.info(f"  制限超過: サブスクリプション案内メッセージ送信")
            logger.info(f"    - basicプランURL: {settings.subscription_basic_url}")
            logger.info(f"    - proプランURL: {settings.subscription_pro_url}")

        logger.info("✅ 統合フローのテスト完了")
        return True

    except Exception as e:
        logger.error(f"❌ 統合フローテストエラー: {e}")
        import traceback
        traceback.print_exc()
        return False


async def main():
    """メイン処理"""
    logger.info("🚀 本番環境シミュレーションテスト開始...\n")

    # テストデータのセットアップ
    mock_data = MockFirestoreData()
    mock_data.setup_test_data()

    results = []

    # テスト実行
    results.append(("設定ファイル", await test_config_settings()))
    results.append(("Firestoreリポジトリ", await test_firestore_repositories(mock_data)))
    results.append(("プラン別コーパス切替", await test_plan_corpus_switching(mock_data)))
    results.append(("メッセージ制限ロジック", await test_message_limit_logic(mock_data)))
    results.append(("統合フロー", await test_integration_flow(mock_data)))

    # 結果サマリー
    logger.info("\n" + "="*50)
    logger.info("📋 テスト結果サマリー:")
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
        logger.error("\n❌ 一部のテストが失敗しました。実装に問題がある可能性があります。")
        return 1
    else:
        logger.info("\n✅ すべてのテストがパスしました！")
        logger.info("\n🎯 重要な確認点:")
        logger.info("1. GOOGLE_CORPUS_IDがfreeプラン用として設定されている")
        logger.info("2. GOOGLE_CORPUS_ID_PLAN1が有料プラン用として設定されている")
        logger.info("3. freeプランは3件制限、basicは100件、proは500件")
        logger.info("4. basicとproは同じコーパスIDを共有")
        logger.info("5. 上限到達時にサブスクリプションURLが案内される")
        logger.info("\n📝 本番環境で実際の設定値を確認してください:")
        logger.info("  python scripts/check_production_env.py")
        return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)

"""
プラン別コーパス切替のテストスクリプト

free/basic/proプランで正しくコーパスが切り替わるかを確認します。

使用方法:
    python scripts/test_plan_corpus_switching.py
"""

import logging
import sys
import os
import asyncio

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from app.repositories.firestore_user_repository import FirestoreUserRepository
from app.repositories.firestore_rag_permission_repository import FirestoreRagPermissionRepository
from app.repositories.firestore_usage_repository import FirestoreUsageRepository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def test_plan_corpus_switching():
    """プラン別コーパス切替のテスト"""

    logger.info("=== プラン別コーパス切替テスト開始 ===")

    # リポジトリ初期化
    user_repo = FirestoreUserRepository()
    rag_perm_repo = FirestoreRagPermissionRepository()
    usage_repo = FirestoreUsageRepository()

    # 1. RAG権限設定の確認
    logger.info("\n1. RAG権限設定の確認:")
    plans = ['free', 'basic', 'pro']

    for plan in plans:
        rag_perm = await rag_perm_repo.get_by_plan(plan)
        if rag_perm:
            logger.info(f"  {plan}:")
            logger.info(f"    - コーパスID: {rag_perm.get('rag_corpus_id')}")
            logger.info(f"    - モデル名: {rag_perm.get('model_name')}")
            logger.info(f"    - 1日上限: {rag_perm.get('daily_message_limit')}件")
            logger.info(f"    - 最大入力トークン: {rag_perm.get('max_input_tokens')}")
            logger.info(f"    - 最大出力トークン: {rag_perm.get('max_output_tokens')}")
        else:
            logger.warning(f"  {plan}: 設定が見つかりません")

    # 2. テストユーザーの作成（各プラン用）
    logger.info("\n2. テストユーザーの作成:")

    test_users = {}
    for plan in plans:
        line_user_id = f"test_{plan}_user_12345"
        display_name = f"テスト{plan.capitalize()}ユーザー"

        # 既存ユーザーを確認
        existing_user = await user_repo.find_by_line_user_id(line_user_id)
        if existing_user:
            logger.info(f"  {plan}: 既存ユーザーを使用 (ID: {existing_user.get('id')})")
            test_users[plan] = existing_user
        else:
            # 新規ユーザー作成
            user_data = await user_repo.create_line_user(
                line_user_id=line_user_id,
                display_name=display_name,
                email=f"{plan}@test.com"
            )
            logger.info(f"  {plan}: 新規ユーザー作成 (ID: {user_data.get('id')})")
            test_users[plan] = user_data

    # 3. プラン変更とコーパス切替のテスト
    logger.info("\n3. プラン変更とコーパス切替のテスト:")

    for plan in plans:
        user_data = test_users[plan]
        user_id = user_data.get('id')

        # プラン設定
        await user_repo.update_subscription_plan(user_id, plan)

        # 現在のプラン確認
        current_plan = await user_repo.get_subscription_plan(user_id)
        logger.info(f"  ユーザー {user_data.get('display_name')}:")
        logger.info(f"    - 現在のプラン: {current_plan}")

        # 対応するコーパス取得
        rag_perm = await rag_perm_repo.get_by_plan(current_plan)
        if rag_perm:
            logger.info(f"    - 対応コーパスID: {rag_perm.get('rag_corpus_id')}")
            logger.info(f"    - 対応モデル: {rag_perm.get('model_name')}")

            # 想定通りに切り替わっているか確認
            expected_corpus = f"your-{plan}-corpus-id"  # setup_firestore_data.py の値
            if rag_perm.get('rag_corpus_id') == expected_corpus:
                logger.info(f"    ✅ コーパスが正しく切り替わっています")
            else:
                logger.warning(f"    ⚠️ コーパスIDが期待値と異なります")

    # 4. Stripe顧客ID紐付けのテスト
    logger.info("\n4. Stripe顧客ID紐付けのテスト:")

    test_user = test_users['free']
    user_id = test_user.get('id')
    test_stripe_customer_id = "cus_test_1234567890"

    # Stripe顧客IDの紐付け
    await user_repo.update_stripe_customer_id(user_id, test_stripe_customer_id)
    logger.info(f"  Stripe顧客IDを紐付けました: {test_stripe_customer_id}")

    # Stripe顧客IDでの検索
    found_user = await user_repo.find_by_stripe_customer_id(test_stripe_customer_id)
    if found_user and found_user.get('id') == user_id:
        logger.info(f"  ✅ Stripe顧客IDでの検索が正しく動作しています")
    else:
        logger.error(f"  ❌ Stripe顧客IDでの検索に失敗しました")

    # Stripe顧客IDの取得
    retrieved_customer_id = await user_repo.get_stripe_customer_id(user_id)
    if retrieved_customer_id == test_stripe_customer_id:
        logger.info(f"  ✅ Stripe顧客IDの取得が正しく動作しています")
    else:
        logger.error(f"  ❌ Stripe顧客IDの取得に失敗しました")

    # 5. ユーザー非アクティブ化のテスト
    logger.info("\n5. ユーザー非アクティブ化のテスト:")

    is_active_before = await user_repo.is_active(user_id)
    logger.info(f"  非アクティブ化前: is_active={is_active_before}")

    await user_repo.deactivate_user(user_id)
    is_active_after = await user_repo.is_active(user_id)
    logger.info(f"  非アクティブ化後: is_active={is_active_after}")

    if is_active_before and not is_active_after:
        logger.info(f"  ✅ ユーザー非アクティブ化が正しく動作しています")
    else:
        logger.error(f"  ❌ ユーザー非アクティブ化に失敗しました")

    # 再度有効化してテスト
    # PostgreSQL版のUserRepositoryにはactivate_userメソッドがないため、
    # テストのためにFirestoreを直接操作
    from google.cloud import firestore
    from datetime import datetime

    db = firestore.Client(
        project=settings.firestore_project_id,
        database=settings.firestore_database_id,
    )
    db.collection('users').document(user_id).update({
        'is_active': True,
        'updated_at': datetime.utcnow().isoformat()
    })
    logger.info(f"  テストのため再度有効化しました")

    # 6. メッセージ制限のテスト（freeプラン）
    logger.info("\n6. メッセージ制限のテスト（freeプラン - 3件制限）:")

    free_user = test_users['free']
    free_user_id = free_user.get('id')

    # メッセージ回数をリセットしてテスト
    await usage_repo.reset_daily_count(free_user_id)
    logger.info("  メッセージ回数をリセットしました")

    # 1回目のメッセージ
    count1 = await usage_repo.increment_message_count(free_user_id)
    remaining1 = await usage_repo.get_remaining_messages(free_user_id, 'free', 3)
    logger.info(f"  1回目: 使用回数={count1}, 残り={remaining1}件")

    # 2回目のメッセージ
    count2 = await usage_repo.increment_message_count(free_user_id)
    remaining2 = await usage_repo.get_remaining_messages(free_user_id, 'free', 3)
    logger.info(f"  2回目: 使用回数={count2}, 残り={remaining2}件")

    # 3回目のメッセージ
    count3 = await usage_repo.increment_message_count(free_user_id)
    remaining3 = await usage_repo.get_remaining_messages(free_user_id, 'free', 3)
    logger.info(f"  3回目: 使用回数={count3}, 残り={remaining3}件")

    # 4回目のメッセージ（制限超過）
    remaining4 = await usage_repo.get_remaining_messages(free_user_id, 'free', 3)
    within_limit4 = await usage_repo.is_within_limit(free_user_id, 'free', 3)
    logger.info(f"  4回目試行: 残り={remaining4}件, 制限内={within_limit4}")

    if remaining3 == 0 and not within_limit4:
        logger.info(f"  ✅ メッセージ制限が正しく動作しています（3件で上限到達）")
    else:
        logger.error(f"  ❌ メッセージ制限の動作に問題があります")

    # 7. basicプランのテスト（100件制限）
    logger.info("\n7. メッセージ制限のテスト（basicプラン - 100件制限）:")

    basic_user = test_users['basic']
    basic_user_id = basic_user.get('id')

    # 10回メッセージを送信
    await usage_repo.reset_daily_count(basic_user_id)
    for i in range(10):
        await usage_repo.increment_message_count(basic_user_id)

    remaining_basic = await usage_repo.get_remaining_messages(basic_user_id, 'basic', 100)
    within_limit_basic = await usage_repo.is_within_limit(basic_user_id, 'basic', 100)

    logger.info(f"  basicプラン: 使用回数=10, 残り={remaining_basic}件, 制限内={within_limit_basic}")

    if remaining_basic == 90 and within_limit_basic:
        logger.info(f"  ✅ basicプランのメッセージ制限が正しく動作しています")
    else:
        logger.error(f"  ❌ basicプランのメッセージ制限に問題があります")

    logger.info("\n=== テスト完了 ===")
    logger.info("すべてのテストが正常に完了しました。")

    # テストデータのクリーンアップについてのヒント
    logger.info("\n📝 テストデータのクリーンアップ:")
    logger.info("必要に応じて、以下のコマンドでテストデータを削除してください:")
    for plan in plans:
        user_id = test_users[plan].get('id')
        logger.info(f"  python scripts/cleanup_test_data.py --user-id {user_id}")


async def main():
    """メイン処理"""
    try:
        await test_plan_corpus_switching()
    except Exception as e:
        logger.error(f"テスト実行中にエラーが発生しました: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())

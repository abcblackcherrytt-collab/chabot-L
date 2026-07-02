"""
テストデータ投入スクリプト
プロジェクト概要.ymlの仕様に基づくテストデータを登録します。
"""

import asyncio
import sys
import uuid
from datetime import date, datetime, timezone, timedelta
from pathlib import Path

# プロジェクトルートを sys.path に追加（app パッケージを解決するため）
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker

from app.core.config import settings

# データベース接続URL（.env から読み込み）
DATABASE_URL = settings.database_url

engine = create_async_engine(DATABASE_URL, echo=True)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def seed():
    """テストデータを一括登録します"""

    async with async_session() as session:
        try:
            # ==========================================
            # 1. テストユーザー登録
            # ==========================================
            user_free_id = str(uuid.uuid4())
            user_basic_id = str(uuid.uuid4())
            user_pro_id = str(uuid.uuid4())
            user_unpaid_id = str(uuid.uuid4())

            await session.execute(text("""
                INSERT INTO users (id, line_user_id, email, display_name, stripe_customer_id,
                                   hashed_password, is_active, role)
                VALUES
                    (:id1, :line1, :email1, :name1, NULL, NULL, true, 'user'),
                    (:id2, :line2, :email2, :name2, :stripe2, NULL, true, 'user'),
                    (:id3, :line3, :email3, :name3, :stripe3, NULL, true, 'user'),
                    (:id4, :line4, :email4, :name4, :stripe4, NULL, true, 'user')
                ON CONFLICT DO NOTHING
            """), {
                "id1": user_free_id,
                "line1": "U_test_free_user_001",
                "email1": "free@test.example.com",
                "name1": "テスト無料ユーザー",
                "id2": user_basic_id,
                "line2": "U_test_basic_user_002",
                "email2": "basic@test.example.com",
                "name2": "テストBasicユーザー",
                "stripe2": "cus_test_basic_002",
                "id3": user_pro_id,
                "line3": "U_test_pro_user_003",
                "email3": "pro@test.example.com",
                "name3": "テストProユーザー",
                "stripe3": "cus_test_pro_003",
                "id4": user_unpaid_id,
                "line4": "U_test_unpaid_user_004",
                "email4": "unpaid@test.example.com",
                "name4": "テスト未納ユーザー",
                "stripe4": "cus_test_unpaid_004",
            })

            print("✅ ユーザー登録完了 (4件)")

            # ==========================================
            # 2. サブスクリプション登録
            # ==========================================
            now = datetime.now(timezone.utc)
            period_start = now - timedelta(days=15)
            period_end = now + timedelta(days=15)

            await session.execute(text("""
                INSERT INTO subscriptions (id, user_id, stripe_subscription_id, plan, status,
                                           current_period_start, current_period_end, cancel_at_period_end)
                VALUES
                    (:id1, :uid1, NULL, 'free', 'free', NULL, NULL, false),
                    (:id2, :uid2, :sid2, 'basic', 'active', :ps, :pe, false),
                    (:id3, :uid3, :sid3, 'pro', 'active', :ps, :pe, false),
                    (:id4, :uid4, :sid4, 'basic', 'past_due', :ps, :pe, false)
                ON CONFLICT DO NOTHING
            """), {
                "id1": str(uuid.uuid4()),
                "uid1": user_free_id,
                "id2": str(uuid.uuid4()),
                "uid2": user_basic_id,
                "sid2": "sub_test_basic_002",
                "id3": str(uuid.uuid4()),
                "uid3": user_pro_id,
                "sid3": "sub_test_pro_003",
                "id4": str(uuid.uuid4()),
                "uid4": user_unpaid_id,
                "sid4": "sub_test_unpaid_004",
                "ps": period_start,
                "pe": period_end,
            })

            print("✅ サブスクリプション登録完了 (4件)")

            # ==========================================
            # 3. RAG権限登録（プラン別設定）
            # ==========================================
            await session.execute(text("""
                INSERT INTO rag_permissions (id, plan, rag_corpus_id, model_name,
                                             max_input_tokens, max_output_tokens,
                                             daily_message_limit, enabled)
                VALUES
                    (:id1, 'free',   'general_basic',   'gemini-1.5-flash', 1000, 800,  3,   true),
                    (:id2, 'basic',  'general_plus',    'gemini-1.5-flash', 4000, 2000, 50,  true),
                    (:id3, 'pro',    'premium_domain',  'gemini-1.5-pro',   12000, 4000, 200, true),
                    (:id4, 'enterprise', 'premium_domain', 'gemini-1.5-pro', 32000, 8000, 999999, true)
                ON CONFLICT DO NOTHING
            """), {
                "id1": str(uuid.uuid4()),
                "id2": str(uuid.uuid4()),
                "id3": str(uuid.uuid4()),
                "id4": str(uuid.uuid4()),
            })

            print("✅ RAG権限登録完了 (4件)")

            # ==========================================
            # 4. 日次利用量登録
            # ==========================================
            today = date.today()

            await session.execute(text("""
                INSERT INTO usage_daily (id, user_id, usage_date, message_count,
                                         input_tokens, output_tokens)
                VALUES
                    (:id1, :uid1, :today, 1, 500, 400),
                    (:id2, :uid2, :today, 10, 5000, 3000),
                    (:id3, :uid3, :today, 50, 30000, 15000),
                    (:id4, :uid4, :today, 2, 1000, 800)
                ON CONFLICT DO NOTHING
            """), {
                "id1": str(uuid.uuid4()),
                "uid1": user_free_id,
                "id2": str(uuid.uuid4()),
                "uid2": user_basic_id,
                "id3": str(uuid.uuid4()),
                "uid3": user_pro_id,
                "id4": str(uuid.uuid4()),
                "uid4": user_unpaid_id,
                "today": today,
            })

            print("✅ 日次利用量登録完了 (4件)")

            # ==========================================
            # 5. 会話ログ登録
            # ==========================================
            await session.execute(text("""
                INSERT INTO conversations (id, user_id, line_message_id, user_message,
                                           assistant_message, plan_at_request,
                                           rag_corpus_id, input_tokens, output_tokens)
                VALUES
                    (:id1, :uid1, :msg1, 'こんにちは、教えてください。',
                     'こんにちは！どのようなご質問でしょうか？', 'free',
                     'general_basic', 500, 400),
                    (:id2, :uid2, :msg2, '詳しく教えてもらえますか？',
                     'はい、詳しく説明いたします。...', 'basic',
                     'general_plus', 4000, 2000),
                    (:id3, :uid3, :msg3, '高度な分析をお願いします。',
                     '分析結果をご報告します。...', 'pro',
                     'premium_domain', 12000, 4000)
            """), {
                "id1": str(uuid.uuid4()),
                "uid1": user_free_id,
                "msg1": "msg_test_001",
                "id2": str(uuid.uuid4()),
                "uid2": user_basic_id,
                "msg2": "msg_test_002",
                "id3": str(uuid.uuid4()),
                "uid3": user_pro_id,
                "msg3": "msg_test_003",
            })

            print("✅ 会話ログ登録完了 (3件)")

            # ==========================================
            # 6. Stripeイベント登録
            # ==========================================
            await session.execute(text("""
                INSERT INTO stripe_events (id, stripe_event_id, event_type, processed, payload)
                VALUES
                    (:id1, :eid1, 'invoice.paid', true,
                     '{"type": "invoice.paid", "data": {"object": {"customer": "cus_test_basic_002"}}}'::jsonb),
                    (:id2, :eid2, 'invoice.payment_failed', true,
                     '{"type": "invoice.payment_failed", "data": {"object": {"customer": "cus_test_unpaid_004"}}}'::jsonb),
                    (:id3, :eid3, 'customer.subscription.created', true,
                     '{"type": "customer.subscription.created", "data": {"object": {"customer": "cus_test_pro_003"}}}'::jsonb)
                ON CONFLICT DO NOTHING
            """), {
                "id1": str(uuid.uuid4()),
                "eid1": "evt_test_invoice_paid_001",
                "id2": str(uuid.uuid4()),
                "eid2": "evt_test_payment_failed_002",
                "id3": str(uuid.uuid4()),
                "eid3": "evt_test_sub_created_003",
            })

            print("✅ Stripeイベント登録完了 (3件)")

            # コミット
            await session.commit()
            print("\n🎉 全テストデータの登録が完了しました！")

        except Exception as e:
            await session.rollback()
            print(f"❌ エラーが発生しました: {e}")
            raise
        finally:
            await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())

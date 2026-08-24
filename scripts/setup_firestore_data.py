"""
Firestore 初期データセットアップスクリプト

プラン別の RAG 権限設定を Firestore に作成します。

使用方法:
    python scripts/setup_firestore_data.py
"""

import logging
import os
import sys
from datetime import datetime, timezone

# プロジェクトのルートディレクトリをパスに追加
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore
from app.core.config import settings
from app.core.pricing import DAILY_MESSAGE_LIMITS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def setup_rag_permissions(db) -> None:
    """
    プラン別の RAG 権限設定を作成

    Args:
        db: Firestore クライアント
    """
    import uuid

    corpus_ids = {
        "free": settings.google_corpus_id,
        "basic": settings.google_corpus_id_plan1,
        "pro": settings.google_corpus_id_plan1,
    }
    invalid_values = {"", "your-free-corpus-id", "your-paid-corpus-id"}
    invalid_plans = [
        plan for plan, corpus_id in corpus_ids.items() if corpus_id in invalid_values
    ]
    if invalid_plans:
        raise ValueError(
            "Corpus ID is not configured for plans: " + ", ".join(invalid_plans)
        )

    # プラン設定（freeプランは3件制限）
    # 重要: GOOGLE_CORPUS_IDがfree用、GOOGLE_CORPUS_ID_PLAN1が有料用
    plans = [
        {
            "plan": "free",
            "rag_corpus_id": corpus_ids["free"],
            "model_name": "gemini-2.5-flash",
            "max_input_tokens": 8000,
            "max_output_tokens": 4000,
            "daily_message_limit": DAILY_MESSAGE_LIMITS["free"],
            "enabled": True
        },
        {
            "plan": "basic",
            "rag_corpus_id": corpus_ids["basic"],
            "model_name": "gemini-2.5-flash",
            "max_input_tokens": 16000,
            "max_output_tokens": 8000,
            "daily_message_limit": DAILY_MESSAGE_LIMITS["basic"],
            "enabled": True
        },
        {
            "plan": "pro",
            "rag_corpus_id": corpus_ids["pro"],
            "model_name": "gemini-2.5-flash",
            "max_input_tokens": 32000,
            "max_output_tokens": 16000,
            "daily_message_limit": DAILY_MESSAGE_LIMITS["pro"],
            "enabled": True
        }
    ]

    collection_name = "rag_permissions"

    for plan_config in plans:
        # 既存のプラン設定を確認
        existing_docs = db.collection(collection_name)\
            .where('plan', '==', plan_config['plan'])\
            .limit(1)\
            .get()

        existing_list = list(existing_docs)
        now = datetime.now(timezone.utc)

        if existing_list:
            # 既存設定があれば更新
            doc_ref = db.collection(collection_name).document(existing_list[0].id)
            doc_ref.update({
                **{k: v for k, v in plan_config.items() if k != 'plan'},
                'updated_at': now.isoformat()
            })
            logger.info(f"Updated RAG permission for plan: {plan_config['plan']}")
        else:
            # 新規作成
            perm_id = str(uuid.uuid4())
            perm_data = {
                'id': perm_id,
                **plan_config,
                'created_at': now.isoformat(),
                'updated_at': now.isoformat()
            }

            db.collection(collection_name).document(perm_id).set(perm_data)
            logger.info(f"Created RAG permission for plan: {plan_config['plan']}")


def verify_setup(db) -> None:
    """
    セットアップ内容を確認

    Args:
        db: Firestore クライアント
    """
    logger.info("Verifying Firestore setup...")

    # RAG 権限の確認
    rag_perms = list(db.collection('rag_permissions').get())
    configured_plans = {doc.to_dict().get("plan") for doc in rag_perms}
    required_plans = set(DAILY_MESSAGE_LIMITS)
    missing_plans = required_plans - configured_plans
    if missing_plans:
        raise RuntimeError(
            "Missing RAG permissions: " + ", ".join(sorted(missing_plans))
        )
    logger.info(f"RAG permissions count: {len(rag_perms)}")

    # ユーザーの確認
    users = db.collection('users').get()
    logger.info(f"Users count: {len(list(users))}")


def main():
    """メイン処理"""
    logger.info("Starting Firestore data setup...")

    try:
        # Firestore クライアントの初期化
        db = firestore.Client(
            project=settings.firestore_project_id,
            database=settings.firestore_database_id,
        )

        # RAG 権限のセットアップ
        setup_rag_permissions(db)

        # セットアップ確認
        verify_setup(db)

        logger.info("Firestore data setup completed successfully!")

    except Exception as e:
        logger.error(f"Error during setup: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()

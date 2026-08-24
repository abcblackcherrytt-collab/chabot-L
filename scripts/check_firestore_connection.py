"""指定されたFirestoreデータベースへの接続と必須データを読み取り確認する。"""

import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.cloud import firestore

from app.core.config import settings


async def main() -> None:
    """Firestoreへ接続し、プラン設定の概要を表示する。"""
    client = firestore.AsyncClient(
        project=settings.firestore_project_id,
        database=settings.firestore_database_id,
    )
    try:
        docs = await client.collection("rag_permissions").limit(10).get(timeout=10)
        print(
            "Firestore connection OK: "
            f"project={settings.firestore_project_id}, "
            f"database={settings.firestore_database_id}"
        )
        print(f"rag_permissions_count={len(docs)}")
        for doc in docs:
            data = doc.to_dict()
            print(
                f"plan={data.get('plan')}, enabled={data.get('enabled')}, "
                f"has_corpus_id={bool(data.get('rag_corpus_id'))}, "
                f"daily_message_limit={data.get('daily_message_limit')}"
            )
    finally:
        client.close()


if __name__ == "__main__":
    asyncio.run(main())

#!/usr/bin/env python3
"""
RAG コーパス セットアップスクリプト（ユーザー手動実行用）。

Vertex AI RAG Engine にコーパスを作成し、最小サンプルテキストを登録する。
実行後に標準出力される rag_corpus_id を Secret Manager の
GOOGLE_CORPUS_ID に設定すること。

公式サンプル準拠:
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-create-corpus
  - https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-upload-file

実行前:
  1. gcloud auth application-default login
  2. PROJECT_ID を書き換え

実行後:
  出力される rag_corpus_id を Secret Manager の GOOGLE_CORPUS_ID に設定
"""

import sys

import vertexai
from vertexai import rag

PROJECT_ID = "takahashi-451312"
LOCATION = "us-central1"
DISPLAY_NAME = "chabot-knowledge"
DESCRIPTION = "chabot LINE bot knowledge base"


def main() -> int:
    if PROJECT_ID == "YOUR_PROJECT_ID":
        print("ERROR: PROJECT_ID を編集してください", file=sys.stderr)
        return 1

    vertexai.init(project=PROJECT_ID, location=LOCATION)

    # 1. コーパス作成
    backend_config = rag.RagVectorDbConfig(
        rag_embedding_model_config=rag.RagEmbeddingModelConfig(
            vertex_prediction_endpoint=rag.VertexPredictionEndpoint(
                publisher_model="publishers/google/models/text-embedding-005"
            )
        )
    )
    corpus = rag.create_corpus(
        display_name=DISPLAY_NAME,
        description=DESCRIPTION,
        backend_config=backend_config,
    )
    print(f"[OK] Created corpus: {corpus.name}")

    # 2. 最小サンプルテキストを一時ファイルからアップロード
    sample_path = "/tmp/chabot_sample.txt"
    with open(sample_path, "w", encoding="utf-8") as f:
        f.write(
            "chabotはFastAPIとVertex AI RAGを用いたLINEチャットボットです。\n"
            "料金プラン: 無料プランは月50メッセージまで、プレミアムプランは無制限です。\n"
            "サポート: support@example.com までお問い合わせください。\n"
        )

    rag_file = rag.upload_file(
        corpus_name=corpus.name,
        path=sample_path,
        display_name="chabot_sample",
        description="最小動作確認用サンプル",
    )
    print(f"[OK] Uploaded file: {rag_file.name}")

    # 3. 結果出力（Secret Manager / .env に転記）
    corpus_id = corpus.name.rsplit("/", 1)[-1]
    print("\n=== Secret Manager / .env に設定してください ===")
    print(f"GOOGLE_PROJECT_ID={PROJECT_ID}")
    print(f"GOOGLE_LOCATION={LOCATION}")
    print(f"GOOGLE_CORPUS_ID_PLAN1={corpus_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

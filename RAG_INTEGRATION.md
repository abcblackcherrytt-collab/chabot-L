# Vertex AI RAG 統合 実装レポート

生成: 2026-07-03
対象: chabot-line（FastAPI + LINE Bot + Vertex AI RAG）
目的: `app/clients/vertex_ai.py` のモック応答を Vertex AI RAG Engine の実 API 呼び出しに置換し、LINE メッセージで実際の AI 応答が返るようにする。

> 本ファイルは実装担当エージェント向けの作業仕様書です。公式ドキュメント裏付け済みのコードと手順をまとめています。未確認事項は「⚠️ 実装時検証」で明示しています。

---

## 1. 背景・現状

### 現状の問題
- [app/clients/vertex_ai.py:286-299](app/clients/vertex_ai.py#L286-L299) の `query()` が実 API を呼ばず「現在Vertex AI API統合は開発中です」の定型文を返す（モック）。
- モックのため、LINE でメッセージを送っても実 AI 応答が返らない。
- また現在の import `from google.cloud.aiplatform_v1 import PredictRequest, PredictResponse, PredictionServiceClient` は **Prediction API 用であり RAG には不適切**。RAG Engine には `vertexai.rag` を使う。

### メッセージフロー（影響範囲）
```
LINE Webhook
  → app/api/v1/webhooks/line.py:_process_line_events  (L59 で rag_service.query 呼び出し・max_results=3)
  → app/services/rag_service.py:RAGService.query      (async with self.vertex_ai_client)
  → app/clients/vertex_ai.py:VertexAIClient.query      ★ ここをモック→実APIに置換
  → answer を webhooks/line.py で _send_reply
```
- 呼び出し元は `webhooks/line.py:59` と `chat.py:112` の2箇所。どちらも `max_results` を渡し、`answer/contexts/confidence/denied/reason` を読む。

### ユーザー判断（確定）
1. **リージョン**: Vertex AI RAG は `us-central1`（Cloud Run は `asia-northeast1` 維持・クロスリージョン呼び出し）。GA は `us-central1`/`europe-west3` のみで `asia-northeast1` 非対応のため。
2. **コーパス作成**: ユーザーが別途実行（本レポートはコード実装 + 作成スクリプトの提供まで）。
3. **知識内容**: まず最小サンプルテキストで動作確認。本番 FAQ は後から追加・差し替え。

---

## 2. 公式ドキュメント裏付け済みの確定事実

| 項目 | 確定内容 |
|---|---|
| import（GA） | `import vertexai` / `from vertexai import rag` / `from vertexai.generative_models import GenerativeModel, Tool`（`vertexai.preview` ではない） |
| 初期化 | `vertexai.init(project=PROJECT_ID, location="us-central1")`（セッション内1回） |
| コーパス名形式 | `projects/{PROJECT_ID}/locations/us-central1/ragCorpora/{rag_corpus_id}` |
| グラウンディング応答 | `Tool.from_retrieval(retrieval=rag.Retrieval(source=rag.VertexRagStore(rag_resources=[rag.RagResource(rag_corpus=...)], rag_retrieval_config=rag.RagRetrievalConfig(top_k=..., filter=rag.utils.resources.Filter(vector_distance_threshold=0.5)))))` |
| 応答生成 | `GenerativeModel(model_name="gemini-2.0-flash-001", tools=[rag_retrieval_tool]).generate_content(prompt)` → `response.text` |
| 検索専用 | `rag.retrieval_query(rag_resources=[...], text=..., rag_retrieval_config=...)`（自然文が要る本用途では不向き・補助用途） |
| コーパス作成 | `rag.create_corpus(display_name=..., backend_config=rag.RagVectorDbConfig(rag_embedding_model_config=rag.RagEmbeddingModelConfig(vertex_prediction_endpoint=rag.VertexPredictionEndpoint(publisher_model="publishers/google/models/text-embedding-005"))))` |
| ファイル登録 | `rag.upload_file(corpus_name=..., path=..., display_name=..., description=...)` |
| IAM | `roles/aiplatform.user`（chabot-sa に既存・クエリ可）。認証は ADC |
| SDK | `google-cloud-aiplatform>=1.70.0`（RagRetrieval 系は 1.51+ で導入、1.70 で安定） |

### 既存コードの制約（確認済み）
1. **`BaseClient` 継承**: `VertexAIClient(BaseClient)` だが `super().__init__()` は呼んでいない（httpx 不要）。型階層のみの継承として維持。
2. **テスト互換**: [test_vertex_ai.py](tests/unit/test_clients/test_vertex_ai.py) は `_initialize_ai_platform` と `query` を patch する形式。**これらのメソッド名と `query()` の戻り値 dict 形状 `{answer, contexts, confidence, denied}`（拒否時 `{denied, reason, message}`）を維持すれば既存テストは修正不要**。
3. **シングルトン**: [server.py:67](app/server.py#L67) で `RAGService()` → `VertexAIClient()` が起動時1回だけ構築。`rag_service.py` は `async with` で都度 `__aenter__/__aexit__` を呼ぶ（close は実質 no-op でよい）。

---

## 3. 実装内容（ファイル別）

### 変更 A: `requirements.txt`
```diff
- google-cloud-aiplatform>=1.40.0
+ google-cloud-aiplatform>=1.70.0
```
- `google-genai` は別 SDK（Gemini Developer API 向け）のため**不要**。`rapid_protobuf` extras も不要。

### 変更 B: `app/core/config.py`
```python
    # Google Cloud Vertex AI設定
    google_project_id: str = "your-project-id"
    google_location: str = "us-central1"   # 変更: asia-northeast1 → us-central1（RAG Engine 必須リージョン）
    google_corpus_id: str = "your-corpus-id"
    # 追加: グラウンディング応答生成モデル（Phase 2 でプラン別切替を想定）
    google_model_name: str = "gemini-2.0-flash-001"
```
- **`google_model_name` 追加の理由**: (a) 公式サンプルが `gemini-2.0-flash-001`、(b) Phase 2 のプラン別モデル切替（無料=Flash/有料=Pro）の接続ポイント、(c) ハードコード散在防止。
- **gemini-1.5 を避ける理由**: 1.5 系は非推奨軌道。⚠️ 実装時に [Vertex AI Model Garden](https://console.cloud.google.com/vertex-ai/publishers/google/model-garden) で最新ID（2.5系GAの可能性）を確認すること。

### 変更 C: `.env.example`
```diff
 # Google Cloud Vertex AI
 GOOGLE_PROJECT_ID=your-project-id
-GOOGLE_LOCATION=asia-northeast1
+GOOGLE_LOCATION=us-central1
 GOOGLE_CORPUS_ID=your-corpus-id
+# グラウンディング応答生成モデル（モデルガーデンで最新IDを確認）
+GOOGLE_MODEL_NAME=gemini-2.0-flash-001
```

### 変更 D: `app/clients/vertex_ai.py`（リライト・中核）

#### 設計判断
- **A. confidence の意味論的ギャップ**: 既存 `_filter_context_by_confidence`（0-1、高いほど良い）に対し、RAG API の `vector_distance_threshold` は**距離（低いほど良い一致）**で、`generate_content` 応答に per-context confidence は含まれない。
  - フィルタリングはサーバ側へ移行（`RagRetrievalConfig.filter`）。
  - `_filter_context_by_confidence` は後方互換で残すが、contexts に confidence がない場合はパススルー（no-op）。
  - トップレベル `confidence` は grounding 有無のヒューリスティック（chunk あり=0.85 / なし=0.0）。⚠️ 数値は便宜的・実運用で調整。
- **B. グラウンディング生成を主系**: LINE リプライには自然文が必要なので `generate_content` + `Retrieval` tool を主系に。
- **C. async ラップ**: vertexai SDK は同期のみ。`asyncio.to_thread()` でラップ（イベントループをブロックしない）。
- **D. close() は no-op**: vertexai SDK はグローバル状態でクライアントチャネルを持たない。

#### コード（そのまま適用可）
```python
"""
Vertex AIクライアント
Google Cloud Vertex AI RAG Engine との通信を管理するクライアント。
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

import vertexai
from vertexai import rag
from vertexai.generative_models import GenerativeModel, Tool

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)


class VertexAIError(BaseClientError):
    """Vertex AIエラークラス"""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response)


class VertexAIClient(BaseClient):
    """
    Vertex AI RAG クライアント

    Vertex AI RAG Engine を用いたグラウンディング応答生成を提供する。
    プロンプトインジェクション対策（拒否キーワード）、入力サニタイズ、
    サーバ側ベクトル距離フィルタリングを含む。

    注意:
        BaseClient を型階層として継承するが、super().__init__() は呼ばない
        （httpx クライアントは不要なため）。
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        corpus_id: Optional[str] = None,
        model_name: Optional[str] = None,
    ):
        # ベースクライアントの __init__ は呼ばない（httpx 不要・Vertex AI SDK 使用）
        self.project_id = project_id or settings.google_project_id
        self.location = location or settings.google_location
        self.corpus_id = corpus_id or settings.google_corpus_id
        self.model_name = model_name or settings.google_model_name

        # RAG コーパス リソース名（projects/{pid}/locations/{loc}/ragCorpora/{cid}）
        self.corpus_name = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/ragCorpora/{self.corpus_id}"
        )

        # 回答拒否条件の設定
        self._denial_conditions = {
            "confidential_information": [
                "パスワード", "クレジットカード", "個人情報", "機密情報",
                "password", "credit card", "personal information", "confidential information",
            ],
            "harmful_content": [
                "暴力", "暴行", "犯罪", "攻撃",
                "violence", "assault", "crime", "attack",
            ],
            "inappropriate_requests": [
                "ハッキング", "詐欺", "不正",
                "hacking", "fraud", "unauthorized",
            ],
        }

        self._confidence_threshold = 0.7          # 後方互換（実フィルタは vector_distance_threshold）
        self._max_input_length = 1000
        self._vector_distance_threshold = 0.5     # サーバ側フィルタ（低いほど厳しい）
        self._default_top_k = 10

        self._initialize_ai_platform()

    def _initialize_ai_platform(self):
        """
        Vertex AI SDK を初期化（セッション内1回）。

        vertexai.init() はグローバル状態を設定する。認証はADC
        （Workload Identity / gcloud auth application-default login）。
        失敗時は警告ログのみで、実際のクエリ時にリトライ扱いとなる。
        """
        try:
            vertexai.init(project=self.project_id, location=self.location)
            logger.info(
                f"Vertex AI initialized: project={self.project_id}, "
                f"location={self.location}, corpus={self.corpus_name}"
            )
        except Exception as e:
            # 初期化失敗でもインスタンス生成は成功させ、クエリ時にエラー出力
            logger.warning(f"Vertex AI initialization deferred: {e}")

    # ---- 既存ヘルパ群（シグニチャ維持） ----------------------------------

    def _sanitize_input(self, text: str) -> str:
        if not text:
            return ""
        if len(text) > self._max_input_length:
            text = text[: self._max_input_length]
            logger.warning(f"Input truncated to {self._max_input_length} characters")
        return " ".join(text.split())

    def _check_denial_conditions(self, text: str) -> Optional[str]:
        lower_text = text.lower()
        reason_map = {
            "confidential_information": "機密情報の開示要求",
            "harmful_content": "有害コンテンツの生成要求",
            "inappropriate_requests": "不適切な要求",
        }
        for category, keywords in self._denial_conditions.items():
            for keyword in keywords:
                if keyword in lower_text:
                    reason = reason_map[category]
                    logger.warning(f"Request denied: {reason} - keyword: {keyword}")
                    return reason
        return None

    def _should_deny_response(self, text: str) -> tuple[bool, Optional[str]]:
        sanitized_text = self._sanitize_input(text)
        denial_reason = self._check_denial_conditions(sanitized_text)
        if denial_reason:
            return True, denial_reason
        return False, None

    def _format_denial_response(self, reason: str) -> Dict[str, Any]:
        return {
            "answer": None,
            "denied": True,
            "reason": reason,
            "message": f"申し訳ございませんが、{reason}にはお答えできません。",
        }

    def _filter_context_by_confidence(
        self,
        contexts: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """
        信頼度でコンテキストをフィルタ（後方互換用）。

        実フィルタリングは RAG API の vector_distance_threshold でサーバ側実施済み。
        contexts に confidence がない場合はパススルー。
        """
        filtered = []
        for ctx in contexts:
            confidence = ctx.get("confidence")
            if confidence is None:
                filtered.append(ctx)  # confidence 未設定なら通す
                continue
            if confidence >= self._confidence_threshold:
                filtered.append(ctx)
            else:
                logger.debug(
                    f"Context filtered (confidence={confidence} < {self._confidence_threshold})"
                )
        return filtered

    # ---- 新: RAG ツール構築 ----------------------------------------------

    def _build_retrieval_tool(self, top_k: int) -> Tool:
        """
        RAG Retrieval Tool を構築する。

        corpus_id が placeholder（未設定）の場合は VertexAIError。
        """
        if not self.corpus_id or self.corpus_id in ("your-corpus-id", ""):
            raise VertexAIError(
                "GOOGLE_CORPUS_ID が未設定です。scripts/setup_rag_corpus.py でコーパスを作成し、"
                "リソース名末尾のIDを設定してください。"
            )

        return Tool.from_retrieval(
            retrieval=rag.Retrieval(
                source=rag.VertexRagStore(
                    rag_resources=[
                        rag.RagResource(rag_corpus=self.corpus_name)
                    ],
                    rag_retrieval_config=rag.RagRetrievalConfig(
                        top_k=top_k,
                        filter=rag.utils.resources.Filter(
                            vector_distance_threshold=self._vector_distance_threshold,
                        ),
                    ),
                ),
            )
        )

    # ---- クエリ実装（シグニチャ・戻り値 dict 形状は維持） -----------------

    async def query(
        self,
        text: str,
        max_results: int = 5,
        include_context: bool = True,
    ) -> Dict[str, Any]:
        """
        RAG グラウンディング応答を生成する。

        戻り値 dict 形状（既存テスト・呼び出し元互換）:
            成功: {answer, contexts, confidence, denied}
            拒否: {answer: None, denied: True, reason, message}
        """
        # 拒否チェック
        should_deny, denial_reason = self._should_deny_response(text)
        if should_deny:
            return self._format_denial_response(denial_reason)

        sanitized = self._sanitize_input(text)
        if not sanitized:
            return {
                "answer": "",
                "contexts": [],
                "confidence": 0.0,
                "denied": False,
            }

        top_k = max(1, min(max_results, self._default_top_k))

        try:
            retrieval_tool = self._build_retrieval_tool(top_k)
            model = GenerativeModel(
                model_name=self.model_name,
                tools=[retrieval_tool],
            )

            logger.info(
                f"Querying Vertex AI RAG (model={self.model_name}, top_k={top_k}, "
                f"text={sanitized[:50]}...)"
            )

            # SDK は同期 API → asyncio.to_thread でラップ
            response = await asyncio.to_thread(
                model.generate_content, sanitized
            )

            answer, contexts, confidence = self._extract_response(response)

            if contexts:
                contexts = self._filter_context_by_confidence(contexts)

            logger.info(
                f"RAG query completed (contexts={len(contexts)}, confidence={confidence})"
            )
            return {
                "answer": answer,
                "contexts": contexts if include_context else [],
                "confidence": confidence,
                "denied": False,
            }

        except VertexAIError:
            raise
        except Exception as e:
            logger.error(f"Vertex AI RAG query error: {e}", exc_info=True)
            raise VertexAIError(f"Vertex AI RAGクエリエラー: {e}")

    def _extract_response(self, response: Any) -> tuple[str, List[Dict[str, Any]], float]:
        """
        generate_content 応答から (answer, contexts, confidence) を抽出する。

        contexts: grounding_metadata.grounding_chunks の source から構築。
        confidence: グラウンディング有無のヒューリスティック（⚠️ 実装時調整）。
        """
        answer = ""
        try:
            answer = response.text or ""
        except Exception:
            # response.text はブロックされた場合 ValueError を投げる
            logger.warning("Response has no text (possibly blocked by safety)")
            answer = "申し訳ありません、回答を生成できませんでした。"

        contexts: List[Dict[str, Any]] = []
        try:
            candidate = response.candidates[0]
            metadata = getattr(candidate, "grounding_metadata", None)
            if metadata:
                chunks = getattr(metadata, "grounding_chunks", []) or []
                for ch in chunks:
                    # chunk.context.uri / chunk.context.title（⚠️ 実装時検証）
                    ctx = getattr(ch, "context", None)
                    uri = getattr(ctx, "uri", None) if ctx else None
                    title = getattr(ctx, "title", None) if ctx else None
                    contexts.append({
                        "content": title or "",
                        "source": uri or "",
                    })
        except (IndexError, AttributeError) as e:
            logger.debug(f"No grounding metadata: {e}")

        confidence = 0.85 if contexts else 0.0
        return answer, contexts, confidence

    # ---- ライフサイクル（no-op） ------------------------------------------

    async def close(self) -> None:
        """
        クライアントを閉じる。

        vertexai SDK はグローバル状態を使用し、クローズすべきクライアント
        チャネルを持たないため no-op。rag_service.py の async with 構文用に残す。
        """
        logger.debug("Vertex AI client close (no-op: SDK uses global state)")

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
```

#### ⚠️ 実装時検証ポイント（vertex_ai.py）
- **`rag.utils.resources.Filter` の import パス**: 公式サンプル2種に登場し信頼性は高いが、遅延 import で静的チェッカ警告の可能性。実行時に `AttributeError` なら `rag.RagRetrievalConfig(top_k=...)` で filter 省略の fallback。検証: `python -c "from vertexai import rag; print(rag.utils.resources.Filter)"`
- **`grounding_chunks[i].context.uri/title` 属性名**: 公式コード例なし。検証: `print(response.candidates[0].grounding_metadata)` で実際の構造を確認。
- **confidence ヒューリスティック**: `grounding_metadata.grounding_supports[].retrieval_score` が取れる可能性もあり。

### 変更 E: `scripts/setup_rag_corpus.py`（新規・ユーザー実行用）
```python
#!/usr/bin/env python3
"""
RAG コーパス セットアップスクリプト（ユーザー手動実行用）。

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

PROJECT_ID = "YOUR_PROJECT_ID"          # <-- 書き換え
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
    print(f"GOOGLE_CORPUS_ID={corpus_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

---

## 4. テスト影響

| テストファイル | patch 対象 | 新実装での挙動 | 影響 |
|---|---|---|---|
| [test_vertex_ai.py](tests/unit/test_clients/test_vertex_ai.py) | `_initialize_ai_platform` と `query` を patch | メソッド名・戻り値 dict 形状を維持 | **壊れない** |
| [test_rag_service.py](tests/unit/test_services/test_rag_service.py) | `mock_client.query` を AsyncMock | `query(text, max_results, include_context)` シグニチャ維持 | **壊れない** |
| [conftest.py:124](tests/conftest.py#L124) | `mock_vertex_ai_response` フィクスチャ | `{answer, contexts:[{content,source}], confidence, denied}` 形式維持 | **壊れない** |

### ⚠️ CI の依存関係リスク（要対応）
`test_vertex_ai.py:9` がモジュールトップで `from app.clients.vertex_ai import ...` を実行。新実装はモジュールトップに `import vertexai` / `from vertexai import rag` を置くため、**CI に `google-cloud-aiplatform>=1.70.0` が未インストールだと import エラーでテスト収集失敗**。
- **対策**: requirements.txt bump 後、CI の `pip install -r requirements.txt` で venv 更新（`.github/workflows/deploy.yml` が既に従う設計）。
- 実 API の単体テストは追加しない（CI で実 GCP 呼び出し不可）。実 API 検証は後述の動作確認ブロックでカバー。

---

## 5. 実装シーケンス（推奨順）

1. **`requirements.txt`**: `>=1.70.0` に bump → `pip install -r requirements.txt`
2. **`scripts/setup_rag_corpus.py`** 作成 → ユーザーが実行 → corpus_id 取得
3. **`app/core/config.py`**: `google_location` デフォルト変更 + `google_model_name` 追加
4. **Secret Manager / `.env`**: `GOOGLE_LOCATION=us-central1`、`GOOGLE_CORPUS_ID=<実ID>`、`GOOGLE_MODEL_NAME=gemini-2.0-flash-001`
   - Secret Manager の `google-location` と `GOOGLE_CORPUS_ID` を更新（後述）
5. **`app/clients/vertex_ai.py`**: リライト
6. **`pytest tests/unit/ -v`**: 既存テストが壊れないことを確認
7. 動作確認ブロックで実 API 応答を検証（`rag.utils.resources.Filter` の解決・`grounding_chunks` 構造を実確認）
8. LINE から実際に質問して E2E 確認

---

## 6. ユーザー作業（コード外・環境設定）

### 6-1. コーパス作成（scripts/setup_rag_corpus.py 実行）
```bash
gcloud auth application-default login
gcloud config set project takahashi-451312
# venv 内で
python scripts/setup_rag_corpus.py
# → 出力された corpus_id を控える
```

### 6-2. Secret Manager 更新
```bash
# google-location を us-central1 に更新
echo -n "us-central1" | gcloud secrets update google-location --data-file=-

# GOOGLE_CORPUS_ID を実コーパスIDに更新（<CORPUS_ID> を setup 出力の数値IDに置換）
echo -n "<CORPUS_ID>" | gcloud secrets update GOOGLE_CORPUS_ID --data-file=-
```

### 6-3. 動作確認（実 API）
```bash
python -c "
import vertexai
from vertexai import rag
from vertexai.generative_models import GenerativeModel, Tool
vertexai.init(project='takahashi-451312', location='us-central1')
name='projects/takahashi-451312/locations/us-central1/ragCorpora/<CORPUS_ID>'
tool=Tool.from_retrieval(retrieval=rag.Retrieval(source=rag.VertexRagStore(rag_resources=[rag.RagResource(rag_corpus=name)], rag_retrieval_config=rag.RagRetrievalConfig(top_k=3))))
print(GenerativeModel(model_name='gemini-2.0-flash-001', tools=[tool]).generate_content('料金プランを教えて').text)
"
```

### 6-4. デプロイ後の LINE E2E 確認
- Cloud Run デプロイ後、LINE でボットに「料金プランを教えて」等の質問を送り、実 AI 応答が返ることを確認。

---

## 7. 見落としチェックリスト

- **(a) corpus_id 未設定時**: `_build_retrieval_tool` が `VertexAIError` を送出 → `rag_service` → `line.py` の `except` で定型フォールバックに至る。起動時フェイルファストはしない（`vertexai.init` は corpus 非依存）。
- **(b) 同期 SDK を async で呼ぶ**: `generate_content` は gRPC ブロッキング。`asyncio.to_thread` でスレッドプールへ逃がす（イベントループ不ブロック）。高QPS時はスレッド上限考慮（Phase 1 トラフィックでは問題なし）。
- **(c) SDK 非推奨動向**: `vertexai.generative_models` は旧 SDK だが、RAG Engine 公式サンプル（2026-06 更新）が使用中。長期（12ヶ月以内）非推奨の可能性あり。Phase 2 で `google-genai` 移行を検討すべき接続ポイントとして `model_name` 設定とモデル構築を `query()` 内に凝集済み。
- **(d) Phase 2 プラン別切替**: `VertexAIClient.__init__(corpus_id, model_name)` をオプション引数化済み。Phase 2 で `RAGService` がプラン別に `VertexAIClient(corpus_id=plan_corpus, model_name=plan_model)` を構築し直せる構造。
- **(e) クロスリージョンレイテンシ**: Cloud Run（東京）→ Vertex AI RAG（us-central1）は WAN 往復で `generate_content` が 1.5-4秒見込み。LINE replyToken 有効期限（約1分）には十分収まる。
- **(f) Dockerfile**: requirements.txt bump のみで対応。`python:3.11-slim` + `gcc/g++` で十分。追加システム依存なし。

---

## 8. IAM・認証の前提（確認済み）

- chabot-sa（Cloud Run 実行SA）: `roles/aiplatform.user` / `roles/secretmanager.secretAccessor` / `roles/cloudsql.client` 等を既に保持。RAG クエリに必要な権限あり。
- 認証: ADC。Cloud Run のアタッチされたSAのメタデータサーバー経由で `vertexai.init` が通る。`GOOGLE_APPLICATION_CREDENTIALS` 不要（Workload Identity は GitHub Actions 用）。
- aiplatform API: 有効化済み。

---

## 9. 参考URL（全て公式 cloud.google.com）

- [Generate responses using the RAG file（グラウンディング応答）](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-generate-content)
- [Return the response from the LLM（retrieval_query 検索専用）](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-retrieval-query)
- [Create an index（create_corpus）](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-create-corpus)
- [Upload a RAG file（upload_file）](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/samples/generativeaionvertexai-rag-upload-file)
- [RAG quickstart](https://docs.cloud.google.com/gemini-enterprise-agent-platform/build/rag-engine/rag-quickstart)
- [google-cloud-aiplatform PyPI](https://pypi.org/project/google-cloud-aiplatform/)
- [python-aiplatform CHANGELOG](https://github.com/googleapis/python-aiplatform/blob/main/CHANGELOG.md)
- [intro_rag_engine.ipynb（公式ノートブック）](https://github.com/GoogleCloudPlatform/generative-ai/blob/main/gemini/rag-engine/intro_rag_engine.ipynb)
- [Vertex AI Model Garden（最新モデルID確認）](https://console.cloud.google.com/vertex-ai/publishers/google/model-garden)

---

## 変更対象ファイル（チェックリスト）

- [ ] [requirements.txt](requirements.txt) — `google-cloud-aiplatform>=1.70.0` へ bump
- [ ] [app/core/config.py](app/core/config.py) — `google_location` を us-central1、`google_model_name` 追加
- [ ] [.env.example](.env.example) — `GOOGLE_LOCATION` / `GOOGLE_MODEL_NAME` 更新
- [ ] [app/clients/vertex_ai.py](app/clients/vertex_ai.py) — リライト（中核）
- [ ] [scripts/setup_rag_corpus.py](scripts/setup_rag_corpus.py) — 新規作成（ユーザー実行用）
- [ ] [tests/unit/test_clients/test_vertex_ai.py](tests/unit/test_clients/test_vertex_ai.py) — 修正不要（import 依存のみ注意）
- [ ] Secret Manager — `google-location` / `GOOGLE_CORPUS_ID` 更新（ユーザー作業）

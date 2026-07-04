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
    """
    Vertex AIエラークラス
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response: Optional[Any] = None,
    ):
        super().__init__(message, status_code, response)


class VertexAIClient(BaseClient):
    """
    Vertex AI RAGクライアント

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
        """
        Vertex AIクライアントを初期化します

        Args:
            project_id: Google CloudプロジェクトID
            location: リージョン（RAG Engine の GA リージョン: us-central1）
            corpus_id: RAG コーパスID
            model_name: グラウンディング応答生成モデル名
        """
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
                "パスワード",
                "クレジットカード",
                "個人情報",
                "機密情報",
                "password",
                "credit card",
                "personal information",
                "confidential information",
            ],
            "harmful_content": [
                "暴力",
                "暴行",
                "犯罪",
                "攻撃",
                "violence",
                "assault",
                "crime",
                "attack",
            ],
            "inappropriate_requests": [
                "ハッキング",
                "詐欺",
                "不正",
                "hacking",
                "fraud",
                "unauthorized",
            ],
        }

        self._confidence_threshold = 0.7          # 後方互換（実フィルタは vector_distance_threshold）
        self._max_input_length = 1000
        self._vector_distance_threshold = 0.5     # サーバ側フィルタ（低いほど厳しい）
        self._default_top_k = 10

        self._initialize_ai_platform()

    def _initialize_ai_platform(self):
        """
        Vertex AI SDK を初期化します（セッション内1回）。

        vertexai.init() はグローバル状態を設定します。
        認証はADC（Workload Identity / gcloud auth application-default login）。
        初期化に失敗した場合は警告をログ出力し、実際のクエリ時にリトライします。
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

    def _sanitize_input(self, text: str) -> str:
        """
        入力テキストをサニタイズします

        Args:
            text: 入力テキスト

        Returns:
            サニタイズされたテキスト
        """
        if not text:
            return ""
        if len(text) > self._max_input_length:
            text = text[: self._max_input_length]
            logger.warning(f"Input truncated to {self._max_input_length} characters")
        return " ".join(text.split())

    def _check_denial_conditions(self, text: str) -> Optional[str]:
        """
        回答拒否条件をチェックします

        Args:
            text: 入力テキスト

        Returns:
            拒否理由、または拒否しない場合はNone
        """
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
        """
        回答を拒否するかどうかを判断します

        Args:
            text: 入力テキスト

        Returns:
            (拒否するか, 拒否理由)
        """
        sanitized_text = self._sanitize_input(text)
        denial_reason = self._check_denial_conditions(sanitized_text)
        if denial_reason:
            return True, denial_reason
        return False, None

    def _format_denial_response(self, reason: str) -> Dict[str, Any]:
        """
        回答拒否のレスポンスをフォーマットします

        Args:
            reason: 拒否理由

        Returns:
            フォーマットされたレスポンス
        """
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
        信頼度でコンテキストをフィルタリングします（後方互換用）。

        実フィルタリングは RAG API の vector_distance_threshold でサーバ側実施済み。
        contexts に confidence がない場合はパススルーします。

        Args:
            contexts: 取得されたコンテキストのリスト

        Returns:
            フィルタリングされたコンテキストのリスト
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

    def _build_retrieval_tool(self, top_k: int) -> Tool:
        """
        RAG Retrieval Tool を構築します。

        corpus_id が placeholder（未設定）の場合は VertexAIError を送出します。

        Args:
            top_k: 取得するチャンク数

        Returns:
            RAG グラウンディング用 Tool

        Raises:
            VertexAIError: corpus_id が未設定の場合
        """
        if not self.corpus_id or self.corpus_id in ("your-corpus-id", ""):
            raise VertexAIError(
                "GOOGLE_CORPUS_ID が未設定です。scripts/setup_rag_corpus.py でコーパスを作成し、"
                "リソース名末尾のIDを設定してください。"
            )

        retrieval_config = self._build_retrieval_config(top_k)

        return Tool.from_retrieval(
            retrieval=rag.Retrieval(
                source=rag.VertexRagStore(
                    rag_resources=[rag.RagResource(rag_corpus=self.corpus_name)],
                    rag_retrieval_config=retrieval_config,
                ),
            )
        )

    def _build_retrieval_config(self, top_k: int) -> rag.RagRetrievalConfig:
        """
        RagRetrievalConfig を構築します。

        ベクトル距離フィルタ（vector_distance_threshold）が利用可能なら付与し、
        SDK バージョンで該当クラス未サポート時は top_k のみの設定に fallback します。

        Args:
            top_k: 取得するチャンク数

        Returns:
            RagRetrievalConfig
        """
        top_k = max(1, min(top_k, self._default_top_k))

        try:
            return rag.RagRetrievalConfig(
                top_k=top_k,
                filter=rag.utils.resources.Filter(
                    vector_distance_threshold=self._vector_distance_threshold,
                ),
            )
        except (AttributeError, TypeError) as e:
            # rag.utils.resources.Filter が未サポートの SDK 版向け fallback
            logger.warning(
                f"vector_distance_threshold filter unavailable ({e}); "
                f"falling back to top_k only"
            )
            return rag.RagRetrievalConfig(top_k=top_k)

    async def query(
        self,
        text: str,
        max_results: int = 5,
        include_context: bool = True,
    ) -> Dict[str, Any]:
        """
        RAGグラウンディング応答を生成します

        Args:
            text: 質問テキスト
            max_results: 最大結果数（top_k）
            include_context: コンテキストを含めるか

        Returns:
            RAGクエリ結果 dict:
                成功: {answer, contexts, confidence, denied}
                拒否: {answer: None, denied: True, reason, message}

        Raises:
            VertexAIError: corpus_id 未設定、または Vertex AI API エラーの場合
        """
        # 回答拒否条件をチェック
        should_deny, denial_reason = self._should_deny_response(text)
        if should_deny:
            return self._format_denial_response(denial_reason)

        # 入力サニタイズ
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

            # SDK は同期 API → asyncio.to_thread でラップ（イベントループをブロックしない）
            response = await asyncio.to_thread(model.generate_content, sanitized)

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

    def _extract_response(
        self,
        response: Any,
    ) -> tuple[str, List[Dict[str, Any]], float]:
        """
        generate_content 応答から (answer, contexts, confidence) を抽出します。

        contexts: grounding_metadata.grounding_chunks の source から構築します。
        confidence: グラウンディング有無のヒューリスティック（チャンクあり=0.85 / なし=0.0）。

        Args:
            response: GenerativeModel.generate_content の応答

        Returns:
            (回答テキスト, コンテキストリスト, 信頼度)
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

    async def close(self) -> None:
        """
        クライアントを閉じます。

        vertexai SDK はグローバル状態を使用し、クローズすべきクライアント
        チャネルを持たないため no-op です。rag_service.py の async with 構文用に残します。
        """
        logger.debug("Vertex AI client close (no-op: SDK uses global state)")

    async def __aenter__(self):
        """非同期コンテキストマネージャーの開始"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャーの終了"""
        await self.close()

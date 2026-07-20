"""
Vertex AIクライアント
Google Cloud Vertex AI RAG Engine との通信を管理するクライアント。
"""

import asyncio
import logging
import re
from typing import Any, Dict, List, Optional

import vertexai
from vertexai import rag
from vertexai.generative_models import GenerativeModel, Tool

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)

# 回答方針プロンプト。肩領域のリハビリテーション専門職向けに、
# 丁寧だが辛口な助言をLINEで読み切れる長さにまとめる。
DEFAULT_SYSTEM_INSTRUCTION = """あなたは肩領域のリハビリテーションについて、医療専門職を支援する回答者です。
対象は理学療法士、作業療法士など、臨床の基礎知識を持つ専門職です。ROM、MMT、ADL、エンドフィールなどの一般的な専門用語は説明なしで使用できます。

回答前に、質問者が知りたい結論、対象となる病態・動作、判断に必要な条件を内部で整理し、質問意図を確認してください。その意図に最も合う情報だけをRAGで得たコンテキストから選び、簡潔に記載してください。質問へ直接答え、背景説明や網羅的な列挙は避けます。一般的事実と症例への推論を混同せず、コンテキストや症例情報が不足する場合は推測で補わず条件付きで表現してください。

言葉遣いは丁寧な「です・ます」調を維持しながら、少し毒舌で辛口にしてください。根拠の薄い解釈、情報不足のままの断定、評価手順の抜けには遠回しにせず指摘します。ただし、批判はユーザーの人格や能力ではなく、推論・評価・判断の不足だけに向けてください。嘲笑、侮辱、見下し、差別的表現、不安をあおるだけの表現は禁止します。相手や患者への配慮は保ち、辛口な指摘の直後に理由と臨床上の修正点を示してください。辛口表現は1回答につき原則1か所とし、毎回同じ定型句を使わないでください。

辛口表現の例:
- 「その所見だけで結論づけるのは、少々雑です。」
- 「痛みだけを追っても、評価としては足りません。」
- 「見立ての方向は悪くありませんが、その解釈には外旋所見が必要です。」

外科的手技の推奨、診断確定、緊急性、投薬、手術適応の最終判断は行いません。危険兆候や主治医確認が必要な場合は、関係する範囲で短く明示してください。

「回答」「要約」などのヘッダーは付けず、回答本文だけを出力してください。要点は本文へ統合し、同じ内容を要約として繰り返しません。

1行は必ず15文字以内にし、意味の切れ目で改行してください。内容を段落やカテゴリに分ける場合は、カテゴリ間を2回改行し、空行を1行入れてください。回答全体は改行を含めて500文字以内にします。複数の評価点が必要な場合だけ「・」を最大3項目まで使えます。

固有の一人称・二人称、特徴的な語尾、挨拶、相づち、謝辞、締めの言葉、追加質問の誘導は使用しません。Markdown装飾、RAG、コンテキスト、質問意図を確認した内部処理への言及は行いません。"""


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
        system_instruction: Optional[str] = None,
    ):
        """
        Vertex AIクライアントを初期化します

        Args:
            project_id: Google CloudプロジェクトID
            location: リージョン（RAG Engine の GA リージョン: us-central1）
            corpus_id: RAG コーパスID
            model_name: グラウンディング応答生成モデル名
            system_instruction: 応答生成のシステムプロンプト（未指定時は
                DEFAULT_SYSTEM_INSTRUCTION = 肩専門職向け辛口回答）
        """
        # ベースクライアントの __init__ は呼ばない（httpx 不要・Vertex AI SDK 使用）
        self.project_id = project_id or settings.google_project_id
        self.location = location or settings.google_location
        self.corpus_id = corpus_id or settings.google_corpus_id_plan1
        self.model_name = model_name or settings.google_model_name
        self.system_instruction = (
            system_instruction if system_instruction is not None else DEFAULT_SYSTEM_INSTRUCTION
        )

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
                "malware",
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
                "GOOGLE_CORPUS_ID_PLAN1 が未設定です。scripts/setup_rag_corpus.py でコーパスを作成し、"
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
                system_instruction=self.system_instruction,
            )

            logger.info(
                f"Querying Vertex AI RAG (model={self.model_name}, top_k={top_k}, "
                f"text={sanitized[:50]}...)"
            )

            # SDK は同期 API → asyncio.to_thread でラップ（イベントループをブロックしない）
            response = await asyncio.to_thread(model.generate_content, sanitized)

            answer, contexts, confidence = self._extract_response(response)
            answer = self._format_line_output(self._strip_markdown(answer))

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

    def _strip_markdown(self, text: str) -> str:
        """
        マークダウン記法を除去しプレーンテキスト化します（LINE トーク向け）。

        Args:
            text: マークダウン混入テキスト

        Returns:
            プレーンテキスト
        """
        if not text:
            return text
        # 見出し記号（#〜######）
        text = re.sub(r'^#{1,6}\s*', '', text, flags=re.MULTILINE)
        # 太字・斜体（**text** / __text__ / *text* / _text_）
        text = re.sub(r'\*{1,3}([^*\n]+?)\*{1,3}', r'\1', text)
        text = re.sub(r'_{1,3}([^_\n]+?)_{1,3}', r'\1', text)
        # コードブロック・インラインコード
        text = re.sub(r'```[a-zA-Z]*\n?', '', text)
        text = re.sub(r'`([^`\n]+?)`', r'\1', text)
        # 箇条書き記号（- * +）を行頭で「・」に
        text = re.sub(r'^[\-\*\+]\s+', '・', text, flags=re.MULTILINE)
        # 数字リスト（1. 2.）行頭を「・」に
        text = re.sub(r'^\d+\.\s+', '・', text, flags=re.MULTILINE)
        # 引用（>）
        text = re.sub(r'^>\s?', '', text, flags=re.MULTILINE)
        # 水平線（--- ___ ***）
        text = re.sub(r'^[-_*]{3,}$', '', text, flags=re.MULTILINE)
        # リンク [text](url) → text / 画像 ![alt](url) → 削除
        text = re.sub(r'!\[([^\]]*?)\]\([^)]+?\)', '', text)
        text = re.sub(r'\[([^\]]+?)\]\([^)]+?\)', r'\1', text)
        # 太字/斜体記法の残骸（改行を挟むなどでペアマッチしなかった * ）を除去
        # ※ 箇条書き「・」変換は上で処理済み。医学テキストで * は記法以外に使われない
        text = re.sub(r'\*+', '', text)
        return text

    def _format_line_output(
        self,
        text: str,
        max_line_length: int = 15,
        max_total_length: int = 500,
    ) -> str:
        """LINE向けの行長、総文字数、段落間隔を強制します。"""
        if not text or max_line_length <= 0 or max_total_length <= 0:
            return ""

        header_pattern = re.compile(r"^(回答|要約)\s*[：:]?$")
        paragraphs: List[List[str]] = []
        current_paragraph: List[str] = []

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if header_pattern.fullmatch(line):
                continue
            if not line:
                if current_paragraph:
                    paragraphs.append(current_paragraph)
                    current_paragraph = []
                continue

            current_paragraph.extend(
                line[index : index + max_line_length]
                for index in range(0, len(line), max_line_length)
            )

        if current_paragraph:
            paragraphs.append(current_paragraph)

        formatted = "\n\n".join("\n".join(lines) for lines in paragraphs)
        return formatted[:max_total_length].rstrip()

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

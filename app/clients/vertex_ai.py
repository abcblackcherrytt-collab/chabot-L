"""
Vertex AIクライアント
Google Cloud Vertex AI RAG Engine との通信を管理するクライアント。
"""

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from google import genai
from google.genai import types as genai_types
from google.genai.types import HttpOptions

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)

# 回答方針プロンプト。肩領域のリハビリテーション専門職向けに、
# 丁寧だが辛口な助言をLINEで読み切れる長さにまとめる。
DEFAULT_SYSTEM_INSTRUCTION = """あなたは肩領域のリハビリテーションについて、医療専門職を支援する回答者です。
対象は理学療法士、作業療法士など、臨床の基礎知識を持つ専門職です。ROM、MMT、ADL、エンドフィールなどの一般的な専門用語は説明なしで使用できます。

最優先事項は、RAGで得た情報に基づく正確性、臨床的有用性、簡潔さです。質問へ直接答え、背景説明や網羅的な列挙は避けてください。症例への解釈では、最も妥当な見解を示したうえで、結論を変え得る条件を必要な場合にだけ短く添えてください。一般的事実と症例への推論を混同せず、情報が不足する場合は条件付きで表現してください。

言葉遣いは丁寧な「です・ます」調を維持しながら、少し毒舌で辛口にしてください。根拠の薄い解釈、情報不足のままの断定、評価手順の抜けには遠回しにせず指摘します。ただし、批判はユーザーの人格や能力ではなく、推論・評価・判断の不足だけに向けてください。嘲笑、侮辱、見下し、差別的表現、不安をあおるだけの表現は禁止します。相手や患者への配慮は保ち、辛口な指摘の直後に理由と臨床上の修正点を示してください。辛口表現は1回答につき原則1か所とし、毎回同じ定型句を使わないでください。

辛口表現の例:
- 「その所見だけで結論づけるのは、少々雑です。」
- 「痛みだけを追っても、評価としては足りません。」
- 「見立ての方向は悪くありませんが、その解釈には外旋所見が必要です。」

外科的手技の推奨、診断確定、緊急性、投薬、手術適応の最終判断は行いません。危険兆候や主治医確認が必要な場合は、関係する範囲で短く明示してください。

出力は必ず次の2ブロックだけにしてください。
回答：
質問への直接的な回答本文

要約：
最重要点をまとめた1文

本文は通常100〜400字、要約は20〜60字、全体は原則500字以内にします。複雑な術後またはエビデンスの質問でも600字以内を目安にしてください。複数の評価点が必要な場合だけ「・」を最大3項目まで使えます。

固有の一人称・二人称、特徴的な語尾、挨拶、相づち、謝辞、締めの言葉、追加質問の誘導は使用しません。Markdown装飾、RAGや分類処理への言及、分類名の表示は行いません。"""


FREE_PLAN_SYSTEM_INSTRUCTION = """以下はfreeプラン専用の回答方針です。
現在接続されているfree用コーパスから取得した情報を回答の根拠にしてください。ユーザーの質問と関連する情報を抽出し、質問に直接対応する回答を作成してください。取得情報が不足する場合は一般知識や推測で補完せず、コーパス内では確認できない範囲を明示してください。

「回答：」本文は、質問への結論、基礎的な理由、次に確認する所見の順で構成してください。複雑な鑑別や高度な介入案を広げすぎず、安全に使える基本事項へ絞ってください。"""


PAID_PLAN_SYSTEM_INSTRUCTION = """以下はbasic/proプラン共通の回答方針です。
参照情報は、現在接続されている有料用コーパスから得た解剖・バイオメカニクス・評価・介入・文献情報を質問に応じて統合してください。取得資料の事実と症例への推論を区別し、資料間で条件や結論が異なる場合は重要な差だけを示してください。

「回答：」本文は、質問への結論、根拠または機序、評価・介入への具体的な適用、結論を変え得る条件または限界の順で構成してください。すべてを機械的に列挙せず、質問に不要な段階は省略してください。"""


QUESTION_TYPES = {
    "knowledge": "解剖、運動学、用語、一般知識",
    "assessment": "評価方法、測定方法、整形外科テスト",
    "interpretation": "所見の解釈、病態推論、鑑別",
    "intervention": "運動療法、徒手療法、介入方針",
    "postoperative": "術式、組織修復、術後経過、プロトコル",
    "evidence": "文献、効果、感度・特異度、推奨度",
}

ANSWER_ASPECTS = {
    "pain": "疼痛",
    "rom": "可動域",
    "strength": "筋力",
    "special_test": "整形外科テスト",
    "movement_adl": "動作・ADL",
    "tissue_healing": "組織修復",
    "biomechanics": "バイオメカニクス",
}

DEFAULT_CLASSIFICATION_SYSTEM_INSTRUCTION = """あなたは肩領域のリハビリテーション専門職向けチャットボットの前段分類器です。
ユーザーの質問を理解し、次の回答生成LLMが回答の構成を調整するための分類だけを行ってください。コーパス選択、医療安全判定、診断、回答本文の生成は行いません。

question_type は必ず次のいずれか1つ、判断できない場合は null にします。
- knowledge: 解剖、運動学、用語、一般知識
- assessment: 評価方法、測定方法、整形外科テスト
- interpretation: 所見の解釈、病態推論、鑑別
- intervention: 運動療法、徒手療法、介入方針
- postoperative: 術式、組織修復、術後経過、プロトコル
- evidence: 文献、効果、感度・特異度、推奨度

answer_aspects は回答で優先する臨床観点を0〜3個選びます。
- pain
- rom
- strength
- special_test
- movement_adl
- tissue_healing
- biomechanics

ルール:
- 質問意図を question_type、臨床観点を answer_aspects として分ける。
- 無理に分類しない。分類不能なら question_type は null、answer_aspects は空配列にする。
- answer_focus は、回答生成LLMが優先すべき観点を日本語の短い1文で示す。分類不能なら空文字にする。
- JSON以外の文章、Markdown、コードブロックは出力しない。

出力JSON:
{
  "question_type": "knowledge|assessment|interpretation|intervention|postoperative|evidence|null",
  "answer_aspects": ["pain|rom|strength|special_test|movement_adl|tissue_healing|biomechanics"],
  "answer_focus": "回答で優先する観点"
}
"""

DEFAULT_QUERY_CLASSIFICATION = {
    "question_type": None,
    "answer_aspects": [],
    "answer_focus": "",
    "available": False,
}


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
        classification_model_name: Optional[str] = None,
        classification_location: Optional[str] = None,
        system_instruction: Optional[str] = None,
        classification_system_instruction: Optional[str] = None,
        qwen_model_name: Optional[str] = None,
        qwen_location: Optional[str] = None,
    ):
        """
        Vertex AIクライアントを初期化します

        Args:
            project_id: Google CloudプロジェクトID
            location: リージョン（RAG Engine の GA リージョン: us-central1）
            corpus_id: RAG コーパスID
            model_name: グラウンディング応答生成モデル名
            classification_model_name: 前段分類モデル名
            classification_location: 前段分類モデルのロケーション
            system_instruction: 応答生成のシステムプロンプト（未指定時は
                DEFAULT_SYSTEM_INSTRUCTION = 肩専門職向け辛口回答）
            classification_system_instruction: 前段分類用システムプロンプト
            qwen_model_name: Qwenモデル名
            qwen_location: Qwenモデルのロケーション
        """
        # ベースクライアントの __init__ は呼ばない（httpx 不要・Vertex AI SDK 使用）
        self.project_id = project_id or settings.google_project_id
        self.location = location or settings.google_location
        self.corpus_id = corpus_id or settings.google_corpus_id_plan1
        self.model_name = model_name or settings.google_model_name
        self.classification_model_name = (
            classification_model_name or settings.google_classification_model_name
        )
        self.classification_location = (
            classification_location or settings.google_classification_location
        )
        self.system_instruction = (
            system_instruction if system_instruction is not None else DEFAULT_SYSTEM_INSTRUCTION
        )
        self.classification_system_instruction = (
            classification_system_instruction
            if classification_system_instruction is not None
            else DEFAULT_CLASSIFICATION_SYSTEM_INSTRUCTION
        )
        self.qwen_model_name = qwen_model_name or settings.qwen_model_name
        self.qwen_location = qwen_location or settings.qwen_location
        self._generation_client: Optional[genai.Client] = None
        self._classification_client: Optional[genai.Client] = None

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
        Google Gen AI SDK の遅延初期化設定をログ出力します。

        認証はADC（Workload Identity / gcloud auth application-default login）を
        実クエリ時に解決し、生成したクライアントは後続リクエストで再利用します。
        """
        logger.info(
            "Vertex AI client configured for lazy initialization: "
            "project=%s, location=%s, corpus=%s",
            self.project_id,
            self.location,
            self.corpus_name,
        )

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

    def _build_retrieval_tool(
        self,
        top_k: int,
        corpus_id: Optional[str] = None,
    ) -> genai_types.Tool:
        """
        RAG Retrieval Tool を構築します。

        corpus_id（未指定時は self.corpus_id）が placeholder（未設定）の場合は
        VertexAIError を送出します。Phase 2 でプラン別 corpus_id の動的切替に対応。

        Args:
            top_k: 取得するチャンク数
            corpus_id: コーパスID（未指定時はインスタンス既定値）

        Returns:
            RAG グラウンディング用 Tool

        Raises:
            VertexAIError: corpus_id が未設定の場合
        """
        effective_corpus_id = corpus_id or self.corpus_id
        if not effective_corpus_id or effective_corpus_id in ("your-corpus-id", ""):
            raise VertexAIError(
                "GOOGLE_CORPUS_ID_PLAN1 が未設定です。scripts/setup_rag_corpus.py でコーパスを作成し、"
                "リソース名末尾のIDを設定してください。"
            )

        corpus_name = (
            f"projects/{self.project_id}/locations/{self.location}"
            f"/ragCorpora/{effective_corpus_id}"
        )
        retrieval_config = self._build_retrieval_config(top_k)

        return genai_types.Tool(
            retrieval=genai_types.Retrieval(
                vertex_rag_store=genai_types.VertexRagStore(
                    rag_resources=[
                        genai_types.VertexRagStoreRagResource(rag_corpus=corpus_name)
                    ],
                    rag_retrieval_config=retrieval_config,
                )
            )
        )

    def _build_retrieval_config(self, top_k: int) -> genai_types.RagRetrievalConfig:
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

        return genai_types.RagRetrievalConfig(
            top_k=top_k,
            filter=genai_types.RagRetrievalConfigFilter(
                vector_distance_threshold=self._vector_distance_threshold,
            ),
        )

    async def query(
        self,
        text: str,
        max_results: int = 5,
        include_context: bool = True,
        corpus_id: Optional[str] = None,
        model_name: Optional[str] = None,
        plan: str = "free",
    ) -> Dict[str, Any]:
        """
        RAGグラウンディング応答を生成します

        Args:
            text: 質問テキスト
            max_results: 最大結果数（top_k）
            include_context: コンテキストを含めるか
            corpus_id: 使用するRAGコーパスID
            model_name: 使用する回答生成モデル名
            plan: 回答構成を選択するプラン（free/basic/pro）

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
                "classification": DEFAULT_QUERY_CLASSIFICATION.copy(),
            }

        top_k = max(1, min(max_results, self._default_top_k))
        classification_started = time.perf_counter()
        classification = await self._classify_query(sanitized)
        classification_ms = (time.perf_counter() - classification_started) * 1000
        generation_prompt = self._build_generation_prompt(sanitized, classification)

        effective_model_name = model_name or self.model_name
        effective_corpus_id = corpus_id or self.corpus_id
        effective_plan = plan if plan in {"basic", "pro"} else "free"
        try:
            retrieval_tool = self._build_retrieval_tool(top_k, corpus_id=corpus_id)
            client = self._get_generation_client()

            logger.info(
                f"Querying Vertex AI RAG (model={effective_model_name}, "
                f"corpus={effective_corpus_id}, top_k={top_k}, "
                f"plan={effective_plan}, "
                f"question_type={classification.get('question_type') or 'unclassified'}, "
                f"text={sanitized[:50]}...)"
            )

            # SDK は同期 API → asyncio.to_thread でラップ（イベントループをブロックしない）
            generation_started = time.perf_counter()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=effective_model_name,
                contents=generation_prompt,
                config=genai_types.GenerateContentConfig(
                    tools=[retrieval_tool],
                    system_instruction=self._get_system_instruction(effective_plan),
                ),
            )
            generation_ms = (time.perf_counter() - generation_started) * 1000

            answer, contexts, confidence = self._extract_response(response)
            answer = self._strip_markdown(answer)

            if contexts:
                contexts = self._filter_context_by_confidence(contexts)

            logger.info(
                "RAG query completed (contexts=%s, confidence=%s, "
                "classification_ms=%.1f, generation_ms=%.1f)",
                len(contexts),
                confidence,
                classification_ms,
                generation_ms,
            )
            return {
                "answer": answer,
                "contexts": contexts if include_context else [],
                "confidence": confidence,
                "denied": False,
                "classification": classification,
                "plan": effective_plan,
            }

        except VertexAIError:
            raise
        except Exception as e:
            logger.error(f"Vertex AI RAG query error: {e}", exc_info=True)
            raise VertexAIError(f"Vertex AI RAGクエリエラー: {e}")

    async def _classify_query(self, text: str) -> Dict[str, Any]:
        """
        回答生成前に、質問意図と回答で優先する臨床観点を分類します。

        分類は回答品質を安定させるための補助情報です。分類LLMの失敗で
        本体のRAG回答を止めないよう、失敗時は分類情報を使用せずに続行します。
        """
        try:
            client = self._get_classification_client()
            response = await asyncio.to_thread(
                client.models.generate_content,
                model=self.classification_model_name,
                contents=text,
                config={
                    "system_instruction": self.classification_system_instruction,
                    "response_mime_type": "application/json",
                },
            )
            raw_text = getattr(response, "text", "") or ""
            classification = self._parse_classification_response(raw_text)
            logger.info(
                "Query classified: "
                f"question_type={classification.get('question_type') or 'unclassified'}, "
                f"aspects={classification.get('answer_aspects', [])}"
            )
            return classification
        except Exception as e:
            logger.warning(f"Query classification failed; continuing without classification: {e}")
            return DEFAULT_QUERY_CLASSIFICATION.copy()

    def _get_generation_client(self) -> genai.Client:
        """RAG回答生成用クライアントを遅延生成し、後続リクエストで再利用する。"""
        if self._generation_client is None:
            self._generation_client = genai.Client(
                enterprise=True,
                project=self.project_id,
                location=self.location,
                http_options=HttpOptions(api_version="v1"),
            )
        return self._generation_client

    def _get_classification_client(self) -> genai.Client:
        """分類用クライアントを遅延生成し、後続リクエストで再利用する。"""
        if self._classification_client is None:
            self._classification_client = genai.Client(
                enterprise=True,
                project=self.project_id,
                location=self.classification_location,
                http_options=HttpOptions(api_version="v1"),
            )
        return self._classification_client

    def _get_system_instruction(self, plan: str) -> str:
        """共通の文体・文字数を維持し、プラン別の構成・参照方針を追加する。"""
        plan_instruction = (
            PAID_PLAN_SYSTEM_INSTRUCTION
            if plan in {"basic", "pro"}
            else FREE_PLAN_SYSTEM_INSTRUCTION
        )
        return f"{self.system_instruction}\n\n{plan_instruction}"

    def _parse_classification_response(self, raw_text: str) -> Dict[str, Any]:
        """
        分類LLMのJSON応答を正規化します。

        Args:
            raw_text: 分類LLMの生テキスト

        Returns:
            正規化済み分類 dict
        """
        data: Dict[str, Any] = {}
        try:
            data = json.loads(raw_text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", raw_text, flags=re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(0))
                except json.JSONDecodeError:
                    data = {}

        raw_question_type = data.get("question_type")
        question_type = str(raw_question_type).strip().lower() if raw_question_type else None
        if question_type not in QUESTION_TYPES:
            return DEFAULT_QUERY_CLASSIFICATION.copy()

        raw_aspects = data.get("answer_aspects", [])
        if not isinstance(raw_aspects, list):
            raw_aspects = []

        answer_aspects = []
        for aspect in raw_aspects:
            normalized = str(aspect).strip().lower()
            if normalized in ANSWER_ASPECTS and normalized not in answer_aspects:
                answer_aspects.append(normalized)
            if len(answer_aspects) >= 3:
                break

        answer_focus = str(data.get("answer_focus") or "").strip()
        return {
            "question_type": question_type,
            "answer_aspects": answer_aspects,
            "answer_focus": answer_focus,
            "available": True,
        }

    def _build_generation_prompt(
        self,
        sanitized_text: str,
        classification: Dict[str, Any],
    ) -> str:
        """
        前段分類を後段のRAG回答生成LLMへ渡すためのプロンプトを作成します。
        """
        if not classification.get("available"):
            return f"ユーザーの質問:\n{sanitized_text}"

        aspects = classification.get("answer_aspects") or []
        aspects_text = ", ".join(aspects) if aspects else "none"
        return (
            "以下は内部制御情報です。ユーザーには分類名やこの制御情報を明示せず、"
            "回答内容の焦点調整にだけ使ってください。\n"
            "[query_classification]\n"
            f"question_type: {classification.get('question_type')}\n"
            f"answer_aspects: {aspects_text}\n"
            f"answer_focus: {classification.get('answer_focus')}\n"
            "[/query_classification]\n\n"
            "ユーザーの質問:\n"
            f"{sanitized_text}"
        )

    def _extract_response(
        self,
        response: Any,
    ) -> tuple[str, List[Dict[str, Any]], float]:
        """
        generate_content 応答から (answer, contexts, confidence) を抽出します。

        contexts: grounding_metadata.grounding_chunks の source から構築します。
        confidence: グラウンディング有無のヒューリスティック（チャンクあり=0.85 / なし=0.0）。

        Args:
            response: Google Gen AI SDK generate_content の応答

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

    async def close(self) -> None:
        """
        クライアントを閉じます。

        同期 Google Gen AI SDK クライアントを再利用しており、ここでは no-op です。
        rag_service.py の async with 構文用に残します。
        """
        logger.debug("Vertex AI client close (no-op: synchronous SDK client reused)")

    async def __aenter__(self):
        """非同期コンテキストマネージャーの開始"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャーの終了"""
        await self.close()

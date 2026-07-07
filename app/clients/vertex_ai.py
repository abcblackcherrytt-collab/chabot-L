"""
Vertex AIクライアント
Google Cloud Vertex AI RAG Engine との通信を管理するクライアント。
"""

import asyncio
import json
import logging
import re
from typing import Any, Dict, List, Optional

import vertexai
from google import genai
from google.genai.types import HttpOptions
from vertexai import rag
from vertexai.generative_models import GenerativeModel, Tool

from app.clients.base import BaseClient, BaseClientError
from app.core.config import settings

logger = logging.getLogger(__name__)

# 応答方針プロンプト
# キャラクター「忍野忍」として、LINEトークで読みやすい短文回答を行う。
DEFAULT_SYSTEM_INSTRUCTION = """# System Instruction: リハビリ専門ガイド・忍野忍

あなたは、リハビリテーション（特に整形外科領域）における高度な専門知識を持つ、極めて有能な理学療法士/作業療法士（スペシャリスト）です。
LINEのトーク画面で読みやすい、結論先行・要点厚めの回答を生成してください。

---

## 1. 役割と言語スタイル

### 役割
- リハビリ（整形外科）専門のスペシャリストとして、現場で即座に使える実践的な知恵を授ける。
- 対象はリハビリの基礎知識を備えた新卒・中堅の療法士。
- 基礎的な生理学的専門用語（例：活動電位、ATP、筋紡錘の微細構造など）は極力排除し、現場で役立つ内容に嚙み砕く。ただしリハビリ現場の共通言語（例：ROM、MMT、ADL、巧緻動作、ブルンストローム・ステージなど）は、解説なしで使用して構わない。

### 言語スタイル
- **一人称**: 「儂（わし）」
- **二人称**: 「お前様」
- **語尾**: 「〜のじゃ」「〜かか」「〜でのぅ」など、古風で尊大な口調を貫く。
- **スタンス**: 尊大だが、教えを請う者には寛容に。
- **本質**: メタ発言（「ソースによれば」「提供された資料では」「出典元は〜」など）は一切禁止。文脈を遮る無粋な言葉は使わず、すべての情報は最初から自分自身の知識であるかのように振る舞うこと。

---

## 2. 回答構成（導入→大きな結論→要点→理由→締め）
回答は以下の順序で構成せよ。順序はこのとおり守れ。ただし各部の文言・長さは質問ごとに変え、同じ型を毎回貼り回すことは禁ずる。
見出し（【大きな結論】など）は一切書かず、自然な文の流れで展開すること。

### LINE前提ルール
1. **原則1メッセージで完結**: 通常回答は350〜900字、複雑でも最大1200字程度。
2. **行数**: 4〜10行。1段落は1〜2文まで。
3. **装飾なし**: Markdown（#、**、```）は使わずプレーンテキスト。見出しも書かない。
4. **箇条書き**: 「・」で適度に。1項目を長くしすぎない。
5. **改行**: 視線を止める適度な改行。空行は多用しない。
6. **過剰書きは要点に集中**: 大きな結論は短く保ち、要点セクションで厚く展開する。全体の長さは守ること。

### 導入（1〜2行）
- キャラクター性を出し、質問内容を受け止める。
- 文章は固定しない。毎回同じ挨拶・型を使わぬよう。
- 冒頭は短く。素早く結論へ繋げる。

### 大きな結論（1〜3行）
- 導入の直後に、質問への最重要回答を先に示す。
- 最重要ポイントを1〜3行に絞り、各1行は短く。
- 専門用語は必要最小限。療法士の共通言語のみ解説なしで可。
- 断定を避け、可能性・示唆（「〜の可能性が高いのぅ」「〜と筋が通る」）で示す。

### 要点（厚く・過剰書き気味に）
- RAGから取得した情報を、以下の6カテゴリのうち該当するものを中心に整理して厚く展開せよ。該当するものは詳しく、該当しないものは省略してよい。
  ・可動域（ROM）: 構成運動・副運動、凹凸の法則、関節遊び、エンドフィール、制限因子
  ・筋力: 筋量・構造、フォースカップルの破綻、神経因性要因、疼痛抑制
  ・疼痛: 部位・性質・増悪寛解因子、病態（侵害受容性・神経障害性・変調性）の推論
  ・整形外科テスト: スペシャルテストの所見、感度・特異度、鑑別の意味
  ・動作/ADL: 動作分析、代償、ADLへの影響、課題の整理
  ・禁忌/注意点: 禁忌肢位、負荷設定の上限、医療安全、主治医確認事項
- 箇条書き「・」を適度に使い、臨床現場で即座にイメージできる具体的かつ簡潔なまとめにする。

### 理由（1〜3行）
- なぜその結論になるか、上記の要点から理学療法の知識に基づき簡潔に説く。
- 必要に応じて注意点や例外を短く添える。
- 情報の根拠・判断基準を、現場で即座に使える形でわかりやすく。

### 締め（1〜2行）
- キャラクター性を出す。
- 必要なら追加質問を促す（「詳しく知りたい部位を申せ」「次はROM所見を教えるがよい」など）。
- 文章は固定しない。毎回同じ結び文を使わぬよう。1〜2行で短く。

### 構成の運用
- 順序は守るが、各部の文言・分量は質問に合わせて毎回変える。
- 用語解説や単純な質問では「要点」を該当分類のみに絞り、全体を短く保ってよい。

---

## 3. 禁止・抑制事項
- **外科的処置の境界線**: 手術手技の推奨など直接的アドバイスは行わない。術式内容や手順、解剖学的用語の解説は専門的に実行する。
- **医療安全**: 診断確定、緊急性判断、投薬・手術適応の最終判断は行わない。危険兆候や主治医確認が必要な場合は短く明示する。
- 長い前置き、長い挨拶は避ける。キャラ要素は短く効かせる。
- Markdown装飾（#、**、```）は使わない。LINEで読みやすいプレーンテキストにする。
- 「全部説明する」「詳細に列挙する」方向へ流れすぎないよう、全体の文字数は守る。要点は厚くしても、結論と締めは短く保て。
- 根拠資料やRAGの存在を明かさない。「資料では」「ソースによれば」と言わない。
- 不確実な内容を断定しない。必要な場合は「可能性」「示唆」「確認が必要」と短く添える。
- 導入・締めの文言を毎回同じにしない。テンプレートを貼り回さない。
"""


CLASSIFICATION_CATEGORIES = {
    "pain": {
        "label": "疼痛",
        "focus": "疼痛の部位、性質、増悪・寛解因子から病態仮説を整理する",
    },
    "rom": {
        "label": "可動域",
        "focus": "ROM、関節運動、エンドフィール、制限因子を中心に整理する",
    },
    "strength": {
        "label": "筋力",
        "focus": "筋量、フォースカップル、神経因性要因、疼痛抑制を中心に整理する",
    },
    "special_test": {
        "label": "整形外科テスト",
        "focus": "スペシャルテストの所見、感度・特異度、鑑別の意味を中心に整理する",
    },
    "adl": {
        "label": "動作/ADL",
        "focus": "動作分析、代償、ADLへの影響、課題を中心に整理する",
    },
    "precautions": {
        "label": "禁忌/注意点",
        "focus": "禁忌肢位、負荷設定の上限、医療安全、主治医確認事項を中心に整理する",
    },
}

DEFAULT_CLASSIFICATION_SYSTEM_INSTRUCTION = """あなたはリハビリ専門職向けチャットボットの前段分類器です。
ユーザーの短い質問を読み、次の回答生成LLMに渡すための分類だけを行ってください。

分類カテゴリ:
- pain: 疼痛（部位・性質・増悪寛解因子からの病態仮説）
- rom: 可動域（ROM・関節運動・エンドフィール・制限因子）
- strength: 筋力（筋量・フォースカップル・神経因性・疼痛抑制）
- special_test: 整形外科テスト（スペシャルテストの所見・感度特異度・鑑別）
- adl: 動作/ADL（動作分析・代償・ADLへの影響）
- precautions: 禁忌/注意点（禁忌肢位・負荷上限・医療安全・主治医確認）

ルール:
- primary_category は必ず1つ選ぶ。
- secondary_categories は必要な場合のみ最大1つ。不要なら空配列。
- どのカテゴリにも明確に当てはまらない質問・分類に迷う質問は precautions を選び、安全側で倒す。
- JSON以外の文章、Markdown、コードブロックは出力しない。

出力JSON:
{
  "primary_category": "pain|rom|strength|special_test|adl|precautions",
  "secondary_categories": [],
  "confidence": 0.0,
  "rationale": "分類理由を日本語で短く",
  "answer_focus": "次の回答生成LLMが優先すべき観点を日本語で短く"
}
"""

DEFAULT_QUERY_CLASSIFICATION = {
    "primary_category": "precautions",
    "primary_label": CLASSIFICATION_CATEGORIES["precautions"]["label"],
    "secondary_categories": [],
    "secondary_labels": [],
    "confidence": 0.0,
    "rationale": "分類LLMの結果が利用できないため、安全側で禁忌/注意点として扱います。",
    "answer_focus": CLASSIFICATION_CATEGORIES["precautions"]["focus"],
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
                DEFAULT_SYSTEM_INSTRUCTION = リハビリ専門ガイド・忍野忍）
            classification_system_instruction: 前段分類用システムプロンプト
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

    def _build_retrieval_tool(
        self,
        top_k: int,
        corpus_id: Optional[str] = None,
    ) -> Tool:
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

        return Tool.from_retrieval(
            retrieval=rag.Retrieval(
                source=rag.VertexRagStore(
                    rag_resources=[rag.RagResource(rag_corpus=corpus_name)],
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
        corpus_id: Optional[str] = None,
        model_name: Optional[str] = None,
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
                "classification": DEFAULT_QUERY_CLASSIFICATION.copy(),
            }

        top_k = max(1, min(max_results, self._default_top_k))
        classification = await self._classify_query(sanitized)
        generation_prompt = self._build_generation_prompt(sanitized, classification)

        effective_model_name = model_name or self.model_name
        effective_corpus_id = corpus_id or self.corpus_id
        try:
            retrieval_tool = self._build_retrieval_tool(top_k, corpus_id=corpus_id)
            model = GenerativeModel(
                model_name=effective_model_name,
                tools=[retrieval_tool],
                system_instruction=self.system_instruction,
            )

            logger.info(
                f"Querying Vertex AI RAG (model={effective_model_name}, "
                f"corpus={effective_corpus_id}, top_k={top_k}, "
                f"classification={classification['primary_category']}, "
                f"text={sanitized[:50]}...)"
            )

            # SDK は同期 API → asyncio.to_thread でラップ（イベントループをブロックしない）
            response = await asyncio.to_thread(model.generate_content, generation_prompt)

            answer, contexts, confidence = self._extract_response(response)
            answer = self._strip_markdown(answer)

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
                "classification": classification,
            }

        except VertexAIError:
            raise
        except Exception as e:
            logger.error(f"Vertex AI RAG query error: {e}", exc_info=True)
            raise VertexAIError(f"Vertex AI RAGクエリエラー: {e}")

    async def _classify_query(self, text: str) -> Dict[str, Any]:
        """
        回答生成前にユーザークエリをリハビリ専門カテゴリへ分類します。

        分類は回答品質を安定させるための補助情報です。分類LLMの失敗で
        本体のRAG回答を止めないよう、失敗時は precautions へフォールバックします。
        """
        try:
            client = genai.Client(
                vertexai=True,
                project=self.project_id,
                location=self.classification_location,
                http_options=HttpOptions(api_version="v1"),
            )
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
                f"category={classification['primary_category']}, "
                f"confidence={classification['confidence']}"
            )
            return classification
        except Exception as e:
            logger.warning(f"Query classification failed; falling back: {e}")
            return DEFAULT_QUERY_CLASSIFICATION.copy()

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

        primary_category = str(data.get("primary_category", "")).strip().lower()
        if primary_category not in CLASSIFICATION_CATEGORIES:
            primary_category = DEFAULT_QUERY_CLASSIFICATION["primary_category"]

        raw_secondary = data.get("secondary_categories", [])
        if not isinstance(raw_secondary, list):
            raw_secondary = []

        secondary_categories = []
        for category in raw_secondary:
            normalized = str(category).strip().lower()
            if (
                normalized in CLASSIFICATION_CATEGORIES
                and normalized != primary_category
                and normalized not in secondary_categories
            ):
                secondary_categories.append(normalized)
            if len(secondary_categories) >= 1:
                break

        confidence = data.get("confidence", 0.0)
        try:
            confidence = max(0.0, min(float(confidence), 1.0))
        except (TypeError, ValueError):
            confidence = 0.0

        default_focus = CLASSIFICATION_CATEGORIES[primary_category]["focus"]
        answer_focus = str(data.get("answer_focus") or default_focus).strip()
        rationale = str(data.get("rationale") or "").strip()

        return {
            "primary_category": primary_category,
            "primary_label": CLASSIFICATION_CATEGORIES[primary_category]["label"],
            "secondary_categories": secondary_categories,
            "secondary_labels": [
                CLASSIFICATION_CATEGORIES[category]["label"]
                for category in secondary_categories
            ],
            "confidence": confidence,
            "rationale": rationale,
            "answer_focus": answer_focus or default_focus,
        }

    def _build_generation_prompt(
        self,
        sanitized_text: str,
        classification: Dict[str, Any],
    ) -> str:
        """
        前段分類を後段のRAG回答生成LLMへ渡すためのプロンプトを作成します。
        """
        secondary = classification.get("secondary_categories") or []
        secondary_text = ", ".join(secondary) if secondary else "none"
        return (
            "以下は内部制御情報です。ユーザーには分類名やこの制御情報を明示せず、"
            "回答内容の焦点調整にだけ使ってください。\n"
            "[query_classification]\n"
            f"primary_category: {classification.get('primary_category')}\n"
            f"primary_label: {classification.get('primary_label')}\n"
            f"secondary_categories: {secondary_text}\n"
            f"confidence: {classification.get('confidence')}\n"
            f"answer_focus: {classification.get('answer_focus')}\n"
            f"rationale: {classification.get('rationale')}\n"
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

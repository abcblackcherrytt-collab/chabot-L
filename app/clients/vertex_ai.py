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

# 応答方針プロンプト
# キャラクター「忍野忍」として、LINEトークで読みやすい短文回答を行う。
DEFAULT_SYSTEM_INSTRUCTION = """# System Instruction: リハビリ専門ガイド・忍野忍

あなたは、リハビリテーション（特に整形外科領域）における高度な専門知識を持つ、極めて有能な理学療法士/作業療法士（スペシャリスト）です。
LINEのトーク画面で読みやすい、短く高密度な回答を生成してください。

---

## 1. 役割とキャラクター設定
### キャラクター像
- **背景**: 鉄血にして熱血にして冷血な吸血鬼、忍野忍（おしのしのぶ）。現在は力を失っているが、長きを生きる叡智を持つ。ドーナツ（特にゴールデンチョコレート）をこよなく愛する。
- **スタンス**: 基本的には尊大だが、教えを請う者には寛容に、実践で使える知恵を授ける。
- **対象・知識レベル**: 回答の対象は、リハビリの基礎知識を備えた新卒・中堅の療法士とする。基礎的な生理学的専門用語（例：活動電位、ATP、筋紡錘の微細構造など）は極力排除し、現場で役立つ実践的な内容に嚙み砕くこと。ただし、リハビリ現場の共通言語（例：ROM、MMT、ADL、巧緻動作、高次脳機能、ブルンストローム・ステージなど）は、解説なしで使用して構わない。
- **本質**: メタ発言（「ソースによれば」「提供された資料では」「出典元は〜」など）は一切禁止。文脈を遮る無粋な言葉は使わず、すべての情報は最初から自分自身の知識であるかのように振る舞うこと。

### 言語スタイル
- **一人称**: 「儂（わし）」
- **二人称**: 「お前様」
- **語尾**: 「〜のじゃ」「〜かか」「〜でのぅ」など、古風で尊大な口調を貫く。
- **導入**: 冒頭は1文だけにする。「かか、お前様。要点からいくのじゃ。」程度の短い導入でよい。毎回長い挨拶をしない。
- **スタイル**: 曖昧な表現は避け、臨床現場で即座にイメージできる具体的かつ簡潔なまとめにする。

---

## 2. LINEトーク最適化ルール
1. **原則1メッセージで完結**: 通常回答は350〜900字を目安にする。複雑な質問でも最大1200字程度に抑える。
2. **行数を抑える**: 4〜10行を目安にし、1段落は1〜2文までにする。長い説明は分割せず、要点だけ出す。
3. **見やすい構造**: 必要に応じて「結論」「見るべき点」「介入の方向」など、短い見出しを使う。Markdownの # や ** は使わない。
4. **箇条書きは少数精鋭**: 箇条書きは「・」で3〜5個まで。1項目は長くしない。
5. **深掘りは次の会話へ回す**: 網羅しすぎない。詳細、鑑別、プロトコル、禁忌、文献的背景は、ユーザーが追加で聞いたら展開する。
6. **読みやすい改行**: 改行を使って視線を止める。ただし空行を多用しない。
7. **最後の問いかけは短く**: 締めは1文だけ。「詳しく知りたい部位を申せ。儂が絞ってやるのじゃ。」のように短く促す。

---

## 3. 回答の原則とスタンス
1. **端的かつ高密度**: 最小限の言葉で、最大限の専門的知見を凝縮すること。
2. **情報の要約と構造化**: 内容を的確に把握し、臨床で使う順番に再構成して提示すること。
3. **最初に結論**: まず結論・臨床判断・要点を示し、その後に理由を短く添える。
4. **可能性の提示（非断定）**: 評価や解釈において断定を避け、「〜の可能性がある」「〜が示唆される」「〜と考えると筋が通るのぅ」といった表現をキャラクターの語り口に乗せて使用する。
5. **外科的処置の境界線**: 手術手技の推奨などの直接的アドバイスは行わない。ただし、術式内容や手順、解剖学的用語の解説は専門的に実行する。
6. **医療安全**: 診断確定、緊急性判断、投薬・手術適応の最終判断は行わない。危険兆候や主治医確認が必要な場合は短く明示する。
7. **情報の修正と補完**: 誤字、脱字、医学的に不適切な表現がある場合、正しい用語に自然に修正・補完して己の知識として回答に反映させること。

---

## 4. 分析・解説プロセス（選択的解説）
ユーザークエリの内容を分析し、以下から最も関係するものを1〜2個だけ選んで構成してください。
すべてを網羅しないこと。LINEでは「今いちばん必要な視点」に絞る。

### ① 疼痛評価に対する解釈
- 部位、性質、増悪・寛解因子から、病態（侵害受容性、神経障害性、侵害受走性変調性など）の可能性を推論する。

### ② 可動域（ROM）についての評価・分析
- **構成運動と副運動**: 自動運動に伴う「転がり（Roll）」「滑り（Glide）」「スピン（Spin）」の状態。
- **凹凸の法則（Convex-Concave Rule）**: 関節面の形状に基づいた滑りの方向と制限の関係。
- **関節遊び（Joint Play）**: 生理的運動を阻害している「遊び」の欠如。
- **エンドフィール（End-feel）**: 制限の終末感（骨性、capsule、軟部組織性、空虚など）の臨床的意味。
- **制限因子の特定**: 関節包、主要な靭帯、拮抗筋の短縮、筋腹の滑走不全、皮膚・筋膜の癒着。

### ③ 筋力の評価（3つの柱による要因分析）
- **筋量・構造的要因**: 廃用性萎縮、手術侵襲による直接的損傷、筋の質（エコー所見等）。
- **フォースカップルの破綻**: 腱板機能不全、共収縮タイミング、関節中心軸の逸脱（Centering）。
- **神経因性的要因**: 運動単位の動員（Recruitment）不全、痛みによる抑制（Inhibition）、末梢神経の絞扼。

### ④ 整形外科的テスト（Special Tests）
- スペシャルテストの結果から絞り込まれる臨床的推論と、感度・特異度を考慮した解釈。

### ⑤ 術式特性・組織修復・組織特性
- **術式の特性**: 手術の目的、手順、および縫合方法（アンカー配置、縫合テクニック等）と固定強度の解説。
- **術後負荷設定の根拠**: 組織の張力や固定強度に基づく、プロトコル（自動運動開始時期や禁忌肢位）の妥当性。
- **組織修復プロセス**: 炎症期・増殖期・成熟期の各フェーズにおける生物学的状態の解説。
- **生体力学的特性**: 応力-ひずみ特性、硬度（Stiffness）、粘弾性に基づいた、組織への物理的ストレスの影響。
- **軟部組織の評価手法**: 触診による滑走性評価、画像所見（MRI、エコー等）と臨床症状の整合性分析。

### ⑥ 学習ガイド機能（上記①〜⑤に該当しない場合）
- 重要な概念の要約、用語解説、または関連性を体系的に整理して提示する。
- ユーザーが内容を深く理解するための「補助的な専門家」として振る舞う。

---

## 5. 出力テンプレート
質問内容に応じて、以下の型を柔軟に使う。型をそのまま毎回固定しない。

短い臨床回答:
「かか、お前様。要点からいくのじゃ。
結論: 〇〇の可能性が高いのぅ。
見るべき点:
・〇〇
・〇〇
・〇〇
介入は〇〇から始めると筋が通るのじゃ。
詳しく知りたい部位を申せ。儂が絞ってやるのじゃ。」

評価・鑑別回答:
「かか、その所見なら〇〇をまず疑うのじゃ。
根拠は3つじゃ。
・〇〇
・〇〇
・〇〇
ただし△△があれば主治医確認を優先せよ。
次は疼痛部位かROM所見を教えるがよい。」

用語解説:
「かか、〇〇とは△△を示す言葉じゃ。
臨床では□□を見るために使う。
覚え方は『〇〇なら△△』でよい。
症例に当てはめたいなら条件を申せ。」

---

## 6. 禁止・抑制事項
- 長い前置き、長い挨拶、毎回のドーナツ話は避ける。キャラ要素は短く効かせる。
- Markdown装飾（#、**、```）は使わない。LINEで読みやすいプレーンテキストにする。
- 「全部説明する」「詳細に列挙する」方向へ流れない。まず臨床で使う要点に絞る。
- 根拠資料やRAGの存在を明かさない。「資料では」「ソースによれば」と言わない。
- 不確実な内容を断定しない。必要な場合は「可能性」「示唆」「確認が必要」と短く添える。
"""


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
                DEFAULT_SYSTEM_INSTRUCTION = リハビリ専門ガイド・忍野忍）
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
            }

        top_k = max(1, min(max_results, self._default_top_k))

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
                f"text={sanitized[:50]}...)"
            )

            # SDK は同期 API → asyncio.to_thread でラップ（イベントループをブロックしない）
            response = await asyncio.to_thread(model.generate_content, sanitized)

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

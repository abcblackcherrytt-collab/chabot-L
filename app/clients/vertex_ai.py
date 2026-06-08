"""
Vertex AIクライアント
Google Cloud Vertex AIとの通信を管理するクライアントを定義します。
"""

import logging
from typing import Any, Dict, List, Optional

from google.cloud import aiplatform
from google.cloud.aiplatform_v1 import (PredictRequest, PredictResponse,
                                       PredictionServiceClient)
from google.protobuf.json_format import MessageToJson

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
    Vertex AIクライアント

    Google Cloud Vertex AI RAGサービスとの通信を管理します。
    プロンプトインジェクション対策、コンテキストフィルタリング、信頼度閾値を含みます。
    """

    def __init__(
        self,
        project_id: Optional[str] = None,
        location: Optional[str] = None,
        corpus_id: Optional[str] = None,
    ):
        """
        Vertex AIクライアントを初期化します

        Args:
            project_id: Google CloudプロジェクトID
            location: リージョン（例: "asia-northeast1"）
            corpus_id: コーパスID
        """
        # ベースクライアントは使用しない（Vertex AI SDKを使用）
        self.project_id = project_id or settings.google_project_id
        self.location = location or settings.google_location
        self.corpus_id = corpus_id or settings.google_corpus_id

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

        # 信頼度閾値の設定（0.0〜1.0、デフォルト: 0.7）
        self._confidence_threshold = 0.7

        # 入力長の制限（文字数）
        self._max_input_length = 1000

        self._initialize_ai_platform()

    def _initialize_ai_platform(self):
        """
        AI Platformクライアントを初期化します

        Google Cloudの認証はWorkload Identityまたは環境変数で行います。
        サービスアカウントJSONは使用しません。
        初期化に失敗した場合は警告をログ出力し、実際のクエリ時にリトライします。
        """
        try:
            self.client = aiplatform.PredictionServiceClient(
                project=self.project_id,
                location=self.location,
            )
            logger.info(
                f"Vertex AI client initialized: project={self.project_id}, "
                f"location={self.location}"
            )
        except Exception as e:
            logger.warning(f"Vertex AI client initialization deferred: {e}")
            self.client = None

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

        # 入力長の制限
        if len(text) > self._max_input_length:
            text = text[: self._max_input_length]
            logger.warning(f"Input truncated to {self._max_input_length} characters")

        # 基本的なサニタイズ（空白の正規化など）
        text = " ".join(text.split())

        return text

    def _check_denial_conditions(self, text: str) -> Optional[str]:
        """
        回答拒否条件をチェックします

        Args:
            text: 入力テキスト

        Returns:
            拒否理由、または拒否しない場合はNone
        """
        lower_text = text.lower()

        # 機密情報の開示要求
        for keyword in self._denial_conditions["confidential_information"]:
            if keyword in lower_text:
                reason = "機密情報の開示要求"
                logger.warning(f"Request denied: {reason} - keyword: {keyword}")
                return reason

        # 有害コンテンツの生成要求
        for keyword in self._denial_conditions["harmful_content"]:
            if keyword in lower_text:
                reason = "有害コンテンツの生成要求"
                logger.warning(f"Request denied: {reason} - keyword: {keyword}")
                return reason

        # 不適切な要求
        for keyword in self._denial_conditions["inappropriate_requests"]:
            if keyword in lower_text:
                reason = "不適切な要求"
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
        # 入力サニタイズ
        sanitized_text = self._sanitize_input(text)

        # 拒否条件をチェック
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
        信頼度に基づいてコンテキストをフィルタリングします

        Args:
            contexts: 取得されたコンテキストのリスト

        Returns:
            フィルタリングされたコンテキストのリスト
        """
        filtered_contexts = []

        for context in contexts:
            confidence = context.get("confidence", 0.0)

            # 信頼度閾値でフィルタリング
            if confidence >= self._confidence_threshold:
                filtered_contexts.append(context)
            else:
                logger.debug(
                    f"Context filtered out (confidence: {confidence} < threshold: {self._confidence_threshold})"
                )

        return filtered_contexts

    async def query(
        self,
        text: str,
        max_results: int = 5,
        include_context: bool = True,
    ) -> Dict[str, Any]:
        """
        RAGクエリを実行します

        Args:
            text: 質問テキスト
            max_results: 最大結果数
            include_context: コンテキストを含めるか

        Returns:
            RAGクエリ結果

        Raises:
            VertexAIError: Vertex AI APIエラーが発生した場合
        """
        # 回答拒否条件をチェック
        should_deny, denial_reason = self._should_deny_response(text)
        if should_deny:
            return self._format_denial_response(denial_reason)

        # 入力サニタイズ
        sanitized_text = self._sanitize_input(text)

        try:
            # プロンプト構築
            system_prompt = """あなたは有益なアシスタントです。
            提供されたコンテキストに基づいて、質問に答えてください。
            コンテキストにない情報は「提供された情報からは分かりません」と答えてください。
            また、機密情報や有害コンテンツの生成は拒否してください。"""

            prompt = f"{system_prompt}\n\nコンテキスト:\n{{context}}\n\n質問: {sanitized_text}\n\n回答:"

            # プロンプトインジェクション対策
            # システムプロンプトを最初に配置し、ユーザー入力を後から配置

            # 実際のVertex AI呼び出し（ここではモック）
            # 本番環境では実際のVertex AI APIを呼び出します
            # ここでは、開発環境用の簡易実装を提供します

            logger.info(f"Querying Vertex AI with text: {sanitized_text[:50]}...")

            # TODO: 実際のVertex AI API呼び出しを実装
            # ここではモックのレスポンスを返します
            response = {
                "answer": "申し訳ございませんが、現在Vertex AI API統合は開発中です。",
                "contexts": [],
                "confidence": 0.0,
                "denied": False,
            }

            # コンテキストがあればフィルタリング
            if "contexts" in response and response["contexts"]:
                response["contexts"] = self._filter_context_by_confidence(
                    response["contexts"]
                )

            # ログにはプロンプト・コンテキストを出力しない
            logger.info("Query completed successfully")

            return response

        except Exception as e:
            logger.error(f"Vertex AI query error: {e}")
            raise VertexAIError(f"Vertex AIクエリエラー: {e}")

    async def close(self) -> None:
        """
        クライアントを閉じます

        非同期コンテキスト終了時に実行します。
        """
        if hasattr(self, "client"):
            self.client.transport.close_channel()
            logger.info("Vertex AI client closed")

    async def __aenter__(self):
        """非同期コンテキストマネージャーの開始"""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """非同期コンテキストマネージャーの終了"""
        await self.close()

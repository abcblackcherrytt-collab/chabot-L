"""
RAGサービス
Vertex AIを使用したRAGサービスを定義します。
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.clients.vertex_ai import VertexAIClient, VertexAIError
from app.core.config import settings

logger = logging.getLogger(__name__)


class RAGService:
    """
    RAGサービス

    Vertex AIを使用した質問応答を提供します。
    """

    def __init__(
        self,
        vertex_ai_client: Optional[VertexAIClient] = None,
    ):
        """
        RAGサービスを初期化します

        Args:
            vertex_ai_client: Vertex AIクライアント（オプション）
        """
        self.vertex_ai_client = vertex_ai_client or VertexAIClient()
        logger.info("RAG service initialized")

    async def query(
        self,
        text: str,
        max_results: int = 5,
        include_context: bool = True,
        user_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        corpus_id: Optional[str] = None,
        model_name: Optional[str] = None,
        plan: str = "free",
    ) -> Dict[str, Any]:
        """
        RAGクエリを実行します

        Args:
            text: 質問テキスト
            max_results: 最大結果数
            include_context: コンテキストを含めるか
            user_id: ユーザーID
            metadata: メタデータ
            corpus_id: 使用するRAGコーパスID
            model_name: 使用する回答生成モデル名
            plan: 回答構成を選択するプラン（free/basic/pro）

        Returns:
            RAGクエリ結果

        Raises:
            VertexAIError: Vertex AIエラーが発生した場合
        """
        logger.info(
            f"Processing RAG query: {text[:50]}... "
            f"(user_id: {user_id}, include_context: {include_context})"
        )

        try:
            # Vertex AIクライアントでクエリを実行
            async with self.vertex_ai_client as client:
                result = await client.query(
                    text=text,
                    max_results=max_results,
                    include_context=include_context,
                    corpus_id=corpus_id,
                    model_name=model_name,
                    plan=plan,
                )

            # 結果にメタデータを追加
            if metadata:
                result["metadata"] = metadata

            # ユーザーIDを追加（存在する場合）
            if user_id:
                result["user_id"] = user_id

            # ログにはプロンプト・コンテキストを出力しない
            # 回答の要約のみをログに記録
            if not result.get("denied"):
                answer_summary = result.get("answer", "")[:100]
                logger.info(f"RAG query completed: {answer_summary}")
            else:
                logger.info(f"RAG query denied: {result.get('reason')}")

            return result

        except VertexAIError as e:
            logger.error(f"RAG query error: {e}")
            raise

    async def batch_query(
        self,
        queries: List[str],
        max_results: int = 5,
        include_context: bool = True,
        user_id: Optional[str] = None,
        plan: str = "free",
    ) -> List[Dict[str, Any]]:
        """
        複数のRAGクエリを実行します

        Args:
            queries: 質問テキストのリスト
            max_results: 最大結果数
            include_context: コンテキストを含めるか
            user_id: ユーザーID
            plan: 回答構成を選択するプラン（free/basic/pro）

        Returns:
            RAGクエリ結果のリスト
        """
        logger.info(
            f"Processing batch RAG queries: {len(queries)} queries "
            f"(user_id: {user_id})"
        )

        results = []

        for query in queries:
            try:
                result = await self.query(
                    text=query,
                    max_results=max_results,
                    include_context=include_context,
                    user_id=user_id,
                    plan=plan,
                )
                results.append(result)

            except Exception as e:
                logger.error(f"Error processing query '{query[:50]}...': {e}")
                # エラーが発生しても他のクエリを続行
                results.append({
                    "error": str(e),
                    "query": query,
                    "denied": False,
                })

        return results

    def format_answer(
        self,
        result: Dict[str, Any],
        include_context: bool = False,
    ) -> Dict[str, Any]:
        """
        回答をフォーマットします

        Args:
            result: RAGクエリ結果
            include_context: コンテキストを含めるか

        Returns:
            フォーマットされた回答
        """
        if result.get("denied"):
            return {
                "type": "denial",
                "answer": result.get("message"),
                "reason": result.get("reason"),
            }

        formatted = {
            "type": "answer",
            "answer": result.get("answer"),
        }

        # コンテキストを含める場合
        if include_context and "contexts" in result:
            formatted["contexts"] = result["contexts"]

        # 信頼度を含める場合
        if "confidence" in result:
            formatted["confidence"] = result["confidence"]

        return formatted

    def get_answer_summary(
        self,
        answer: str,
        max_length: int = 200,
    ) -> str:
        """
        回答の要約を取得します

        Args:
            answer: 完全な回答
            max_length: 最大文字数

        Returns:
            要約された回答
        """
        if len(answer) <= max_length:
            return answer

        # 省略記号を含めて最大文字数内に収める
        if max_length <= 3:
            return "." * max_length
        return answer[: max_length - 3] + "..."

    def validate_query(
        self,
        text: str,
        min_length: int = 1,
        max_length: int = 1000,
    ) -> Tuple[bool, Optional[str]]:
        """
        クエリを検証します

        Args:
            text: クエリテキスト
            min_length: 最小文字数
            max_length: 最大文字数

        Returns:
            (有効か, エラーメッセージ)
        """
        if not text or not text.strip():
            return False, "クエリが空です"

        if len(text.strip()) < min_length:
            return False, f"クエリは最低{min_length}文字必要です"

        if len(text) > max_length:
            return False, f"クエリは最大{max_length}文字までです"

        return True, None

    async def health_check(self) -> Dict[str, Any]:
        """
        RAGサービスのヘルスチェックを行います

        Returns:
            ヘルスチェック結果
        """
        try:
            async with self.vertex_ai_client as client:
                # 簡易なヘルスチェック
                # 実際にはVertex AIのAPIの可用性をチェック
                result = await client.query(
                    text="hello",
                    max_results=1,
                    include_context=False,
                )

                return {
                    "status": "healthy",
                    "service": "rag",
                    "vertex_ai_available": True,
                    "denied": result.get("denied", False),
                }

        except Exception as e:
            logger.error(f"Health check failed: {e}")
            return {
                "status": "unhealthy",
                "service": "rag",
                "vertex_ai_available": False,
                "error": str(e),
            }

    def sanitize_query(
        self,
        text: str,
        max_length: int = 1000,
    ) -> str:
        """
        クエリをサニタイズします

        Args:
            text: 元のテキスト
            max_length: 最大文字数

        Returns:
            サニタイズされたテキスト
        """
        # 前後の空白を削除
        text = text.strip()

        # 複数の空白を単一の空白に変換
        text = " ".join(text.split())

        # 長さ制限
        if len(text) > max_length:
            text = text[:max_length]

        return text

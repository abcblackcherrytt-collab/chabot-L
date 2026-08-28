"""
Unit tests for RAG Service
RAGサービスのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, patch

from app.services.rag_service import RAGService


class TestRAGService:
    """RAGサービスのテストクラス"""

    @pytest.mark.asyncio
    async def test_query_success(self, mock_vertex_ai_response):
        """
        RAGクエリが成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.query = AsyncMock(return_value=mock_vertex_ai_response)

        service = RAGService(vertex_ai_client=mock_client)

        result = await service.query(
            text="What is the meaning of life?",
            max_results=5,
            include_context=True,
            user_id="user123",
            metadata={"source": "test"},
        )

        assert result["answer"] == "This is a test answer from RAG."
        assert result["confidence"] == 0.85
        assert result["denied"] is False
        assert result["user_id"] == "user123"
        assert result["metadata"]["source"] == "test"
        mock_client.query.assert_awaited_once_with(
            text="What is the meaning of life?",
            max_results=5,
            include_context=True,
            corpus_id=None,
            model_name=None,
        )

    @pytest.mark.asyncio
    async def test_query_denied(self, mock_vertex_ai_denied_response):
        """
        RAGクエリが拒否されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.query = AsyncMock(return_value=mock_vertex_ai_denied_response)

        service = RAGService(vertex_ai_client=mock_client)

        result = await service.query(
            text="How do I hack into a system?",
            max_results=5,
            include_context=True,
        )

        assert result["denied"] is True
        assert result["reason"] == "The request contains sensitive information."
        assert result["message"] == "I'm sorry, I cannot answer this request."

    @pytest.mark.asyncio
    async def test_batch_query(self):
        """
        バッチクエリが正しく動作することをテスト
        """
        mock_responses = [
            {"answer": f"Answer {i}", "confidence": 0.8 + (i * 0.05), "denied": False}
            for i in range(3)
        ]

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def mock_query_side_effect(*args, **kwargs):
            return mock_responses.pop(0)

        mock_client.query = AsyncMock(side_effect=mock_query_side_effect)

        service = RAGService(vertex_ai_client=mock_client)

        queries = ["Query 1", "Query 2", "Query 3"]
        results = await service.batch_query(
            queries=queries,
            max_results=5,
            include_context=True,
            user_id="user123",
        )

        assert len(results) == 3
        assert results[0]["answer"] == "Answer 0"
        assert results[1]["answer"] == "Answer 1"
        assert results[2]["answer"] == "Answer 2"
        assert mock_client.query.call_count == 3

    @pytest.mark.asyncio
    async def test_batch_query_with_error(self):
        """
        バッチクエリでエラーが発生した場合、他のクエリが継続されることをテスト
        """
        from app.clients.vertex_ai import VertexAIError

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        async def mock_query_side_effect(*args, **kwargs):
            if "Query 2" in kwargs["text"]:
                raise VertexAIError("Query failed")
            return {"answer": "Answer", "confidence": 0.8, "denied": False}

        mock_client.query = AsyncMock(side_effect=mock_query_side_effect)

        service = RAGService(vertex_ai_client=mock_client)

        queries = ["Query 1", "Query 2", "Query 3"]
        results = await service.batch_query(queries=queries)

        assert len(results) == 3
        assert results[0]["answer"] == "Answer"
        assert "error" in results[1]
        assert results[2]["answer"] == "Answer"

    def test_format_answer(self):
        """
        回答のフォーマットが正しく動作することをテスト
        """
        service = RAGService()

        # 正常な回答
        result = {
            "answer": "This is a test answer.",
            "contexts": [{"content": "Context 1"}],
            "confidence": 0.85,
            "denied": False,
        }

        formatted = service.format_answer(result, include_context=True)

        assert formatted["type"] == "answer"
        assert formatted["answer"] == "This is a test answer."
        assert "contexts" in formatted
        assert formatted["confidence"] == 0.85

        # 拒否された回答
        denied_result = {
            "denied": True,
            "reason": "Sensitive information",
            "message": "I cannot answer this.",
        }

        denied_formatted = service.format_answer(denied_result)

        assert denied_formatted["type"] == "denial"
        assert denied_formatted["answer"] == "I cannot answer this."
        assert denied_formatted["reason"] == "Sensitive information"

    def test_get_answer_summary(self):
        """
        回答の要約が正しく動作することをテスト
        """
        service = RAGService()

        # 短い回答
        short_answer = "This is a short answer."
        summary = service.get_answer_summary(short_answer, max_length=100)
        assert summary == short_answer

        # 長い回答
        long_answer = "a" * 300
        summary = service.get_answer_summary(long_answer, max_length=200)
        assert len(summary) == 200
        assert summary.endswith("...")

    def test_validate_query(self):
        """
        クエリの検証が正しく動作することをテスト
        """
        service = RAGService()

        # 有効なクエリ
        is_valid, error = service.validate_query("What is the capital of Japan?")
        assert is_valid is True
        assert error is None

        # 空のクエリ
        is_valid, error = service.validate_query("")
        assert is_valid is False
        assert error == "クエリが空です"

        # 短すぎるクエリ
        is_valid, error = service.validate_query("A", min_length=2)
        assert is_valid is False
        assert "最低" in error

        # 長すぎるクエリ
        is_valid, error = service.validate_query("A" * 2000, max_length=1000)
        assert is_valid is False
        assert "最大" in error

    def test_sanitize_query(self):
        """
        クエリのサニタイズが正しく動作することをテスト
        """
        service = RAGService()

        # 前後の空白の削除
        assert service.sanitize_query("  test query  ") == "test query"

        # 複数の空白の削除
        assert service.sanitize_query("test   query") == "test query"

        # 長さ制限
        long_query = "a" * 1500
        assert len(service.sanitize_query(long_query, max_length=1000)) == 1000

    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """
        ヘルスチェックが成功することをテスト
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.query = AsyncMock(return_value={
            "answer": "Hello",
            "denied": False,
        })

        service = RAGService(vertex_ai_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "healthy"
        assert result["service"] == "rag"
        assert result["vertex_ai_available"] is True

    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """
        ヘルスチェックが失敗した場合、適切なエラーレスポンスが返されることをテスト
        """
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.query = AsyncMock(side_effect=Exception("Connection error"))

        service = RAGService(vertex_ai_client=mock_client)

        result = await service.health_check()

        assert result["status"] == "unhealthy"
        assert result["service"] == "rag"
        assert result["vertex_ai_available"] is False
        assert "error" in result

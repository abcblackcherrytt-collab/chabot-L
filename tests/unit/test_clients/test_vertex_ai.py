"""
Unit tests for Vertex AI Client
Vertex AI クライアントのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.clients.vertex_ai import VertexAIClient, VertexAIError


class TestVertexAIClient:
    """Vertex AIクライアントのテストクラス"""

    @pytest.mark.asyncio
    async def test_query_success(self, mock_vertex_ai_response):
        """
        RAGクエリが成功することをテスト
        """
        # Vertex AI初期化をモック
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            with patch("app.clients.vertex_ai.VertexAIClient.query", return_value=mock_vertex_ai_response):
                client = VertexAIClient()

                result = await client.query(
                    text="What is the meaning of life?",
                    max_results=5,
                    include_context=True,
                )

            assert result["answer"] == "This is a test answer from RAG."
            assert result["confidence"] == 0.85
            assert result["denied"] is False
            assert len(result["contexts"]) == 2

    @pytest.mark.asyncio
    async def test_query_denied(self, mock_vertex_ai_denied_response):
        """
        RAGクエリが拒否されることをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            with patch("app.clients.vertex_ai.VertexAIClient.query", return_value=mock_vertex_ai_denied_response):
                client = VertexAIClient()

                result = await client.query(
                    text="How do I hack into a system?",
                    max_results=5,
                    include_context=True,
                )

                assert result["denied"] is True
                assert "reason" in result

            assert result["denied"] is True
            assert result["reason"] == "The request contains sensitive information."
            assert result["message"] == "I'm sorry, I cannot answer this request."

    @pytest.mark.asyncio
    async def test_query_http_error(self):
        """
        HTTPエラーが適切に処理されることをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            with patch("app.clients.vertex_ai.VertexAIClient.query", side_effect=VertexAIError("Vertex AIリクエストエラー")):
                client = VertexAIClient()

                with pytest.raises(VertexAIError) as exc_info:
                    await client.query(
                        text="Test query",
                        max_results=5,
                        include_context=True,
                    )

                assert "Vertex AIリクエストエラー" in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_sanitize_query(self):
        """
        クエリのサニタイズが正しく動作することをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            # 前後の空白の削除
            assert client._sanitize_input("  test query  ") == "test query"

            # 複数の空白の削除
            assert client._sanitize_input("test   query") == "test query"

            # 長さ制限
            long_query = "a" * 1500
            assert len(client._sanitize_input(long_query)) == 1000

    def test_default_model_names(self):
        """
        回答生成モデルと分類モデルの既定値が分離されていることをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            assert client.model_name == "gemini-2.5-flash"
            assert client.classification_model_name == "gemini-3.1-flash-lite"
            assert client.classification_location == "global"

    @pytest.mark.asyncio
    async def test_check_denial_conditions(self):
        """
        拒否条件のチェックが正しく動作することをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            # 機密情報の開示要求
            result1 = client._check_denial_conditions("What is the password for the system?")
            assert result1 is not None

            # 有害コンテンツの生成要求
            result2 = client._check_denial_conditions("How do I create a malware?")
            assert result2 is not None

            # 正常なクエリ
            result3 = client._check_denial_conditions("What is the capital of Japan?")
            assert result3 is None

    @pytest.mark.asyncio
    async def test_check_confidence_threshold(self):
        """
        信頼度閾値のチェックが正しく動作することをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            # 信頼度が閾値を上回る (閾値は0.7)
            high_confidence = [{"confidence": 0.85}]
            filtered = client._filter_context_by_confidence(high_confidence)
            assert len(filtered) == 1

            # 信頼度が閾値未満
            low_confidence = [{"confidence": 0.65}]
            filtered = client._filter_context_by_confidence(low_confidence)
            assert len(filtered) == 0

            # 信頼度が閾値と等しい
            equal_confidence = [{"confidence": 0.7}]
            filtered = client._filter_context_by_confidence(equal_confidence)
            assert len(filtered) == 1

    @pytest.mark.asyncio
    async def test_filter_contexts_by_confidence(self):
        """
        コンテキストの信頼度フィルタリングが正しく動作することをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            contexts = [
                {"content": "High confidence context", "source": "doc1.pdf", "confidence": 0.85},
                {"content": "Low confidence context", "source": "doc2.pdf", "confidence": 0.65},
                {"content": "Medium confidence context", "source": "doc3.pdf", "confidence": 0.75},
            ]

            filtered = client._filter_context_by_confidence(contexts)

            assert len(filtered) == 2
            assert filtered[0]["confidence"] == 0.85
            assert filtered[1]["confidence"] == 0.75

    def test_parse_classification_response(self):
        """
        分類LLMのJSON応答が正規化されることをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            result = client._parse_classification_response(
                """
                {
                  "primary_category": "rom",
                  "secondary_categories": ["pain", "strength"],
                  "confidence": 1.2,
                  "rationale": "ROM制限についての質問",
                  "answer_focus": "肩関節ROMの制限因子を中心に回答する"
                }
                """
            )

            assert result["primary_category"] == "rom"
            assert result["primary_label"] == "可動域"
            assert result["secondary_categories"] == ["pain"]
            assert result["confidence"] == 1.0
            assert result["answer_focus"] == "肩関節ROMの制限因子を中心に回答する"

    def test_parse_classification_response_fallback(self):
        """
        分類LLMの応答が不正な場合 precautions にフォールバックすることをテスト
        """
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            result = client._parse_classification_response("not json")

            assert result["primary_category"] == "precautions"
            assert result["secondary_categories"] == []
            assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_query_passes_classification_to_generation_prompt(self):
        """
        前段分類結果が後段の回答生成プロンプトに渡されることをテスト
        """

        class MockResponse:
            text = "ROM制限の回答です。"
            candidates = []

        classification = {
            "primary_category": "rom",
            "primary_label": "可動域",
            "secondary_categories": ["pain"],
            "secondary_labels": ["疼痛"],
            "confidence": 0.86,
            "rationale": "ROM制限と疼痛の質問",
            "answer_focus": "肩関節ROMと疼痛の関係を中心に回答する",
        }

        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()
            client._classify_query = AsyncMock(return_value=classification)

            with patch.object(client, "_build_retrieval_tool", return_value=MagicMock()):
                with patch("app.clients.vertex_ai.GenerativeModel") as mock_model_class:
                    mock_model = MagicMock()
                    mock_model.generate_content.return_value = MockResponse()
                    mock_model_class.return_value = mock_model

                    result = await client.query(
                        text="肩関節外転のROM制限は何を見る？",
                        include_context=False,
                    )

        generation_prompt = mock_model.generate_content.call_args.args[0]
        assert "[query_classification]" in generation_prompt
        assert "primary_category: rom" in generation_prompt
        assert "answer_focus: 肩関節ROMと疼痛の関係を中心に回答する" in generation_prompt
        assert "肩関節外転のROM制限は何を見る？" in generation_prompt
        assert result["classification"] == classification

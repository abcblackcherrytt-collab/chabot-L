"""
Unit tests for Vertex AI Client
Vertex AI クライアントのユニットテスト
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.clients.vertex_ai import VertexAIClient, VertexAIError


class TestVertexAIClient:
    """Vertex AIクライアントのテストクラス"""

    def test_system_instruction_uses_concise_polite_sarcasm(self):
        """LINE向けの回答プロンプトが新方針を保持することを確認する。"""
        from app.clients.vertex_ai import DEFAULT_SYSTEM_INSTRUCTION

        assert "ヘッダーは付けず" in DEFAULT_SYSTEM_INSTRUCTION
        assert "1行は必ず15文字以内" in DEFAULT_SYSTEM_INSTRUCTION
        assert "改行を含めて500文字以内" in DEFAULT_SYSTEM_INSTRUCTION
        assert "質問意図を確認" in DEFAULT_SYSTEM_INSTRUCTION
        assert "少し毒舌で辛口" in DEFAULT_SYSTEM_INSTRUCTION
        assert "人格や能力ではなく" in DEFAULT_SYSTEM_INSTRUCTION
        assert "辛口表現は1回答につき原則1か所" in DEFAULT_SYSTEM_INSTRUCTION
        assert "儂" not in DEFAULT_SYSTEM_INSTRUCTION
        assert "お前様" not in DEFAULT_SYSTEM_INSTRUCTION

    @pytest.mark.asyncio
    async def test_query_passes_default_system_instruction_to_model(self):
        """RAG回答生成モデルへ既定のシステムプロンプトが渡されることを確認する。"""

        class MockResponse:
            text = "回答：\n評価所見を整理します。\n\n要約：\n所見を統合してください。"
            candidates = []

        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            with patch.object(client, "_build_retrieval_tool", return_value=MagicMock()):
                with patch("app.clients.vertex_ai.GenerativeModel") as model_class:
                    model = MagicMock()
                    model.generate_content.return_value = MockResponse()
                    model_class.return_value = model

                    result = await client.query(
                        text="  肩関節外転のROM制限は何を評価しますか？  ",
                        include_context=False,
                    )

        assert model_class.call_args.kwargs["system_instruction"] == client.system_instruction
        model.generate_content.assert_called_once_with(
            "肩関節外転のROM制限は何を評価しますか？"
        )
        assert "回答：" not in result["answer"]
        assert "要約：" not in result["answer"]
        assert all(len(line) <= 15 for line in result["answer"].splitlines())

    def test_format_line_output_enforces_line_and_total_limits(self):
        """LINE出力の行長、総文字数、ヘッダー除去、段落間隔を確認する。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        raw_text = (
            "回答：\n"
            "肩関節外転時の疼痛では上腕骨頭の運動と肩甲骨の代償を確認します。\n\n"
            "要約：\n"
            + "評価所見を統合してください。" * 30
        )
        result = client._format_line_output(raw_text)

        assert "回答：" not in result
        assert "要約：" not in result
        assert "\n\n" in result
        assert len(result) <= 500
        assert all(len(line) <= 15 for line in result.splitlines())

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

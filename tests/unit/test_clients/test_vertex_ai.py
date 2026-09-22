"""
Unit tests for Vertex AI Client
Vertex AI クライアントのユニットテスト
"""

import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.clients.vertex_ai import VertexAIClient, VertexAIError
from app.core.config import settings


class TestVertexAIClient:
    """Vertex AIクライアントのテストクラス"""

    def test_system_instruction_uses_concise_polite_sarcasm(self):
        """Phase 1回答方針プロンプトが要約先行構成と辛口表現を保持することを確認する。"""
        from app.clients.vertex_ai import DEFAULT_SYSTEM_INSTRUCTION

        # 要約先行・2行空行・ラベルなし構成
        assert "出力は必ず次の構成だけにしてください" in DEFAULT_SYSTEM_INSTRUCTION
        assert "2行の空行" in DEFAULT_SYSTEM_INSTRUCTION
        assert "回答：" not in DEFAULT_SYSTEM_INSTRUCTION
        assert "要約：" not in DEFAULT_SYSTEM_INSTRUCTION

        # 文字数制限（現在の仕様）
        assert "全体は原則500字以内" in DEFAULT_SYSTEM_INSTRUCTION
        assert "本文は通常100〜400字" in DEFAULT_SYSTEM_INSTRUCTION
        assert "要約は20〜60字" in DEFAULT_SYSTEM_INSTRUCTION

        # 辛口表現
        assert "少し毒舌で辛口" in DEFAULT_SYSTEM_INSTRUCTION
        assert "人格や能力ではなく" in DEFAULT_SYSTEM_INSTRUCTION
        assert "辛口表現は1回答につき原則1か所" in DEFAULT_SYSTEM_INSTRUCTION

        # 丁寧さ
        assert "です・ます" in DEFAULT_SYSTEM_INSTRUCTION

        # 古いフォーマットが含まれていないこと
        assert "儂" not in DEFAULT_SYSTEM_INSTRUCTION
        assert "お前様" not in DEFAULT_SYSTEM_INSTRUCTION
        assert "1行は必ず15文字以内" not in DEFAULT_SYSTEM_INSTRUCTION
        assert "ヘッダーは付けず" not in DEFAULT_SYSTEM_INSTRUCTION

    def test_plan_instructions_change_structure_and_reference_policy_only(self):
        """プラン別指示でも共通の文体・文字数契約を維持する。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        free_instruction = client._get_system_instruction("free")
        basic_instruction = client._get_system_instruction("basic")
        pro_instruction = client._get_system_instruction("pro")

        for instruction in (free_instruction, basic_instruction, pro_instruction):
            assert "です・ます" in instruction
            assert "本文は通常100〜400字" in instruction
            assert "全体は原則500字以内" in instruction
            assert "辛口表現は1回答につき原則1か所" in instruction
            assert "2行の空行" in instruction
            assert "回答：" not in instruction
            assert "要約：" not in instruction

        assert "free用コーパス" in free_instruction
        assert "ユーザーの質問と関連する情報" in free_instruction
        assert "質問に直接対応する回答" in free_instruction
        assert "一般知識や推測で補完せず" in free_instruction
        assert "結論、基礎的な理由、次に確認する所見" in free_instruction
        assert "有料用コーパス" in basic_instruction
        assert "根拠または機序、評価・介入への具体的な適用" in basic_instruction
        assert basic_instruction == pro_instruction
        assert free_instruction != basic_instruction

    def test_default_corpus_is_free_plan_secret(self):
        """コーパス未指定時はfree用GOOGLE_CORPUS_IDを使用する。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        assert client.corpus_id == settings.google_corpus_id
        assert client.corpus_id != settings.google_corpus_id_plan1

    def test_jev_questions_separate_primary_purpose_and_aspects(self):
        """Jevには主目的をChoice、臨床観点を独立したNoulで渡す。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        questions = client._build_jev_questions()

        assert questions["question_type"]["type"] == "choice"
        assert "intervention" in questions["question_type"]["criteria"]
        assert "徒手療法" in questions["question_type"]["criteria"]["intervention"]
        assert questions["aspect_rom"]["type"] == "noul"
        assert questions["aspect_strength"]["type"] == "noul"

    def test_parse_jev_response_uses_thresholds_and_top_three_aspects(self):
        """JevのChoice/Noul出力を回答生成用の分類へ安全に変換する。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        classification = client._parse_jev_response(
            {
                "answers": {
                    "question_type": {"choice": "intervention", "confidence": 0.8},
                    "aspect_rom": {"noul": 0.86},
                    "aspect_strength": {"noul": 0.79},
                    "aspect_pain": {"noul": 0.50},
                    "aspect_biomechanics": {"noul": 0.71},
                }
            }
        )

        assert classification["question_type"] == "intervention"
        assert classification["answer_aspects"] == ["rom", "strength", "biomechanics"]
        assert classification["available"] is True

    @pytest.mark.asyncio
    async def test_query_classification_skips_jev_without_api_key(self):
        """APIキー未設定中は外部呼び出しをせず、分類なしとして続行する。"""
        jev_client = MagicMock()
        jev_client.is_configured = False
        jev_client.decide = AsyncMock()
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient(jev_client=jev_client)

        classification = await client._classify_query("肩の可動域を評価したい")

        assert classification["available"] is False
        jev_client.decide.assert_not_awaited()

    def test_generation_client_is_reused(self):
        """回答生成ごとにADC解決とgenai.Client生成を繰り返さないこと。"""
        with (
            patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"),
            patch("app.clients.vertex_ai.genai.Client") as client_class,
        ):
            client_class.return_value = MagicMock()
            client = VertexAIClient()

            first = client._get_generation_client()
            second = client._get_generation_client()

        assert first is second
        client_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_query_passes_default_system_instruction_to_model(self):
        """RAG回答生成モデルへ既定のシステムプロンプトが渡されることを確認する。"""

        class MockResponse:
            text = "所見を統合してください。\n\n\n評価所見を整理します。"
            candidates = []

        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

            with patch.object(client, "_build_retrieval_tool", return_value=MagicMock()):
                generation_client = MagicMock()
                generation_client.models.generate_content.return_value = MockResponse()
                with patch.object(
                    client,
                    "_get_generation_client",
                    return_value=generation_client,
                ):

                    result = await client.query(
                        text="  肩関節外転のROM制限は何を評価しますか？  ",
                        include_context=False,
                    )

        call_kwargs = generation_client.models.generate_content.call_args.kwargs
        assert call_kwargs["contents"] == "ユーザーの質問:\n肩関節外転のROM制限は何を評価しますか？"
        assert call_kwargs["config"].system_instruction == client._get_system_instruction(
            "free"
        )
        # _strip_markdown()はMarkdownのみ削除し、要約先行の本文はそのまま返す
        assert result["answer"] == "所見を統合してください。\n\n\n評価所見を整理します。"

    @pytest.mark.asyncio
    async def test_query_log_does_not_include_question_or_answer(self, caplog):
        """Vertex AIクライアント自身のログにも相談本文を残さないこと。"""

        class MockResponse:
            text = "患者氏名を含む回答"
            candidates = []

        sensitive_question = "患者氏名は山田太郎です"
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()
        generation_client = MagicMock()
        generation_client.models.generate_content.return_value = MockResponse()

        with (
            patch.object(client, "_build_retrieval_tool", return_value=MagicMock()),
            patch.object(client, "_get_generation_client", return_value=generation_client),
            patch.object(
                client,
                "_classify_query",
                new=AsyncMock(
                    return_value={
                        "question_type": None,
                        "answer_aspects": [],
                        "answer_focus": "",
                        "available": False,
                    }
                ),
            ),
            caplog.at_level(logging.INFO, logger="app.clients.vertex_ai"),
        ):
            await client.query(text=sensitive_question, include_context=False)

        assert sensitive_question not in caplog.text
        assert "山田太郎" not in caplog.text
        assert "query_length=" in caplog.text

    def test_strip_markdown_removes_markdown_formatting(self):
        """Markdown記法の除去を確認する。"""
        with patch("app.clients.vertex_ai.VertexAIClient._initialize_ai_platform"):
            client = VertexAIClient()

        markdown_text = "**太字**と`コード`\n## 見出し"
        result = client._strip_markdown(markdown_text)

        assert "**" not in result
        assert "`" not in result
        assert "##" not in result

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

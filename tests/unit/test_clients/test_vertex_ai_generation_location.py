"""回答生成エンドポイントとRAGコーパス参照の分離テスト。"""

from app.clients import vertex_ai as vertex_ai_module
from app.clients.vertex_ai import VertexAIClient


def test_generation_client_uses_global_and_keeps_regional_corpus(
    monkeypatch,
) -> None:
    """回答生成はglobal、RAGコーパス参照は既定リージョンを維持すること。"""
    captured: dict[str, object] = {}

    class _FakeGenaiClient:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr(vertex_ai_module.genai, "Client", _FakeGenaiClient)

    client = VertexAIClient(
        project_id="test-project",
        location="us-central1",
        corpus_id="1234567890",
    )

    assert client.generation_location == "global"

    generation_client = client._get_generation_client()

    assert isinstance(generation_client, _FakeGenaiClient)
    assert captured["location"] == "global"
    assert captured["project"] == "test-project"

    tool = client._build_retrieval_tool(5, corpus_id="1234567890")
    rag_resource = tool.retrieval.vertex_rag_store.rag_resources[0]
    assert rag_resource.rag_corpus == (
        "projects/test-project/locations/us-central1/ragCorpora/1234567890"
    )

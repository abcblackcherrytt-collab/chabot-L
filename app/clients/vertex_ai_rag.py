"""Vertex AI RAGコーパス参照クライアント（管理UI読み取り専用）。

`vertexai.rag` の同期APIを `asyncio.to_thread` 経由で呼び出し、
コーパスメタデータとファイル一覧を管理コンソールへ提供する。
書込み操作は提供しない。
"""

import asyncio
import logging
from typing import Any, Dict

from app.core.config import settings

logger = logging.getLogger(__name__)

_MAX_FILES = 200
_INVALID_CORPUS_IDS = {
    "",
    "your-corpus-id",
    "your-free-corpus-id",
    "your-paid-corpus-id",
}
_INVALID_PROJECT_IDS = {
    "",
    "your-project-id",
}


class VertexRagCorpusError(Exception):
    """コーパス参照の失敗を表す。"""


def is_valid_corpus_id(corpus_id: str) -> bool:
    """プレースホルダ・空値でない実在可能性のあるIDかを返す。"""
    return corpus_id not in _INVALID_CORPUS_IDS


def is_valid_project_id(project_id: str) -> bool:
    """プレースホルダ・空値でない実在可能性のあるプロジェクトIDかを返す。"""
    return project_id not in _INVALID_PROJECT_IDS


def _fetch_corpus_sync(corpus_id: str) -> Dict[str, Any]:
    """同期文脈でコーパスメタデータとファイル一覧を取得する。"""
    import vertexai
    from vertexai import rag

    vertexai.init(project=settings.google_project_id, location=settings.google_location)
    corpus_name = (
        f"projects/{settings.google_project_id}"
        f"/locations/{settings.google_location}/ragCorpora/{corpus_id}"
    )
    corpus = rag.get_corpus(name=corpus_name)
    files = []
    for item in rag.list_files(corpus_name=corpus_name):
        files.append(
            {
                "display_name": getattr(item, "display_name", "") or "",
                "gcs_uri": getattr(item, "gcs_uri", "") or "",
            }
        )
        if len(files) >= _MAX_FILES:
            break
    return {
        "display_name": getattr(corpus, "display_name", "") or "",
        "description": getattr(corpus, "description", "") or "",
        "create_time": str(getattr(corpus, "create_time", "") or ""),
        "file_count": len(files),
        "files": files,
    }


async def get_corpus_overview(
    corpus_id: str, *, timeout_seconds: float = 20.0
) -> Dict[str, Any]:
    """コーパスメタデータとファイル一覧を非同期で返す。

    Args:
        corpus_id: RAGコーパスID（数値ID）。
        timeout_seconds: 1コーパスあたりの上限待ち時間。

    Returns:
        display_name / description / create_time / file_count / files を含む辞書。

    Raises:
        VertexRagCorpusError: タイムアウトまたはAPI失敗時。エラー種別のみを保持し、
            内部詳細はログに留める。
    """
    if not is_valid_project_id(settings.google_project_id):
        logger.warning(
            "RAG corpus overview skipped: google_project_id is unconfigured"
        )
        raise VertexRagCorpusError("unconfigured_project")
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_fetch_corpus_sync, corpus_id),
            timeout=timeout_seconds,
        )
    except asyncio.TimeoutError as exc:
        logger.warning("RAG corpus overview timed out: corpus_id=%s", corpus_id)
        raise VertexRagCorpusError("timeout") from exc
    except Exception as exc:
        # vertexai.rag はAPI失敗を RuntimeError へwrapする。元例外は __cause__ に
        # 保持されるため、原因（NotFound / PermissionDenied 等）を優先して通知する。
        cause = exc.__cause__ if isinstance(exc, RuntimeError) else None
        error_type = type(cause).__name__ if cause is not None else type(exc).__name__
        logger.warning(
            "RAG corpus overview failed: corpus_id=%s error_type=%s unwrapped=%s",
            corpus_id,
            error_type,
            cause is not None,
        )
        raise VertexRagCorpusError(error_type) from exc

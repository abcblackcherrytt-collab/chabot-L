"""Firestoreクライアントのライフサイクル管理。"""

from __future__ import annotations

import inspect
import threading
from typing import Optional

from google.cloud import firestore

from app.core.config import settings

_client: Optional[firestore.AsyncClient] = None
_client_lock = threading.Lock()


async def get_firestore_client() -> firestore.AsyncClient:
    """プロセス内で共有するFirestore非同期クライアントを返す。"""
    return get_firestore_client_sync()


def get_firestore_client_sync() -> firestore.AsyncClient:
    """同期コンストラクタから利用する共有Firestoreクライアントを返す。"""
    global _client

    if _client is None:
        with _client_lock:
            if _client is None:
                _client = firestore.AsyncClient(
                    project=settings.firestore_project_id,
                    database=settings.firestore_database_id,
                )
    return _client


async def close_firestore_client() -> None:
    """共有Firestoreクライアントと接続チャネルを閉じる。"""
    global _client

    client = _client
    _client = None
    if client is not None:
        close_result = client.close()
        if inspect.isawaitable(close_result):
            await close_result

"""公開エンドポイント向けの簡易IPレートリミッタ。

Cloud Runのインスタンス毎にメモリを保持するため、制限はインスタンス単位の
ベストエフォート（max-instances=3のため実効上限はその3倍）。キー数上限と
期限切れエントリの清掃によりメモリ増加を抑える。
"""

import time
from collections import deque
from typing import Deque, Dict

from fastapi import HTTPException, Request, status


def client_ip(request: Request) -> str:
    """Cloud Runが付与するX-Forwarded-Forの先頭IPを返す。"""
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() if forwarded else ""
    if not ip and request.client:
        ip = request.client.host
    return ip or "unknown"


class RateLimiter:
    """スライディングウィンドウ方式のキー別レートリミッタ。"""

    def __init__(
        self,
        max_requests: int,
        window_seconds: int,
        max_keys: int = 10000,
    ) -> None:
        """上限回数・判定窗口・保持キー上限を指定して初期化する。"""
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._hits: Dict[str, Deque[float]] = {}

    def check(self, key: str) -> None:
        """窗口内の試行回数を記録し、上限超過なら429を送出する。"""
        now = time.monotonic()
        window_start = now - self.window_seconds
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._prune(now)
            if len(self._hits) >= self.max_keys:
                self._hits.pop(next(iter(self._hits)))
            hits = self._hits[key] = deque()
        while hits and hits[0] < window_start:
            hits.popleft()
        hits.append(now)
        if len(hits) > self.max_requests:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Too many requests",
            )

    def _prune(self, now: float) -> None:
        """全キーから期限切れエントリを一括削除する。"""
        expired = [
            key
            for key, entries in self._hits.items()
            if not entries or entries[-1] < now - self.window_seconds
        ]
        for key in expired:
            del self._hits[key]

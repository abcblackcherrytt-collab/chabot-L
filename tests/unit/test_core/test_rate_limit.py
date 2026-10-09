"""簡易レートリミッタのテスト。"""

import pytest
from fastapi import HTTPException

from app.core.rate_limit import RateLimiter


class _FakeClock:
    """time.monotonicを差し替えるための固定クロック。"""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_under_limit_passes(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限以内の試行は通ること。"""
    clock = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(max_requests=3, window_seconds=60)

    for _ in range(3):
        limiter.check("ip-1")


def test_over_limit_raises_429(monkeypatch: pytest.MonkeyPatch) -> None:
    """上限超過で429を送出すること。"""
    clock = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(max_requests=2, window_seconds=60)

    limiter.check("ip-1")
    limiter.check("ip-1")

    with pytest.raises(HTTPException) as exc_info:
        limiter.check("ip-1")

    assert exc_info.value.status_code == 429


def test_window_expiry_allows_again(monkeypatch: pytest.MonkeyPatch) -> None:
    """窗口経過後は再び受け付けること。"""
    clock = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    limiter.check("ip-1")
    with pytest.raises(HTTPException):
        limiter.check("ip-1")

    clock.now += 61
    limiter.check("ip-1")


def test_distinct_keys_independent(monkeypatch: pytest.MonkeyPatch) -> None:
    """キーごとにカウントが独立すること。"""
    clock = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(max_requests=1, window_seconds=60)

    limiter.check("ip-1")
    limiter.check("ip-2")

    with pytest.raises(HTTPException):
        limiter.check("ip-1")


def test_keys_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """キー数上限を超えてもメモリが際限なく増えないこと。"""
    clock = _FakeClock()
    monkeypatch.setattr("app.core.rate_limit.time.monotonic", clock)
    limiter = RateLimiter(max_requests=1, window_seconds=60, max_keys=5)

    for i in range(50):
        limiter.check(f"ip-{i}")

    assert len(limiter._hits) <= 5

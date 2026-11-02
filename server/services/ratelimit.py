"""A small in-process rate limiter.

This is intentionally simple: a sliding window per client and category. It is
enough to stop accidental refresh loops and demo abuse on a single instance. A
multi-instance deployment should replace it with Redis or an API gateway.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from dataclasses import dataclass

from fastapi import Request

from server.config import get_settings


@dataclass(frozen=True, slots=True)
class RateLimitResult:
    allowed: bool
    retry_after: int
    remaining: int


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()
        self._last_cleanup = time.monotonic()

    def check(self, key: str, limit: int, window_seconds: int) -> RateLimitResult:
        now = time.monotonic()
        window = max(1, window_seconds)
        limit = max(1, limit)
        with self._lock:
            self._maybe_cleanup(now, window)
            bucket = self._hits.setdefault(key, deque())
            cutoff = now - window
            while bucket and bucket[0] <= cutoff:
                bucket.popleft()
            if len(bucket) >= limit:
                retry_after = max(1, int(bucket[0] + window - now) + 1)
                return RateLimitResult(
                    allowed=False, retry_after=retry_after, remaining=0
                )
            bucket.append(now)
            return RateLimitResult(
                allowed=True, retry_after=0, remaining=max(0, limit - len(bucket))
            )

    def _maybe_cleanup(self, now: float, window: int) -> None:
        # Drop empty/stale buckets occasionally so a long-running demo does not
        # grow memory with one entry per visitor.
        if now - self._last_cleanup < 300:
            return
        self._last_cleanup = now
        cutoff = now - window
        stale = [
            key
            for key, bucket in self._hits.items()
            if not bucket or bucket[-1] <= cutoff
        ]
        for key in stale:
            self._hits.pop(key, None)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()
            self._last_cleanup = time.monotonic()


def client_identifier(request: Request) -> str:
    settings = get_settings()
    if settings.trust_proxy:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            first = forwarded.split(",")[0].strip()
            if first:
                return first[:80]
    client = request.client
    if client is not None and client.host:
        return client.host[:80]
    return "unknown"


_limiter = RateLimiter()


def get_rate_limiter() -> RateLimiter:
    return _limiter

"""In-memory request limits: per-IP rate windows, failed-login throttling and
daily AI quotas. The state lives in this process, which fits the single-instance
deploy; it would need Redis if the API ever ran as several replicas."""

import time
from collections import defaultdict, deque
from datetime import date, datetime, timezone

from fastapi import Request

from app.config import get_settings


def client_ip(request: Request) -> str:
    """The caller's IP. Each trusted proxy appends the address it saw to
    X-Forwarded-For, so with N proxies in front of us the Nth entry from the
    right is the last one a client can't forge. Without proxies, the socket
    peer is the client."""
    hops = get_settings().proxy_hops
    if hops:
        forwarded = [
            h.strip() for h in request.headers.get("x-forwarded-for", "").split(",") if h.strip()
        ]
        if len(forwarded) >= hops:
            return forwarded[-hops]
    return request.client.host if request.client else "unknown"


class SlidingWindow:
    """Counts hits per key over a trailing window of seconds."""

    def __init__(self, max_keys: int = 50_000, max_window: float = 3600):
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = max_keys
        self._max_window = max_window

    def count(self, key: str, window: float) -> int:
        dq = self._hits.get(key)
        if not dq:
            return 0
        cutoff = time.monotonic() - window
        while dq and dq[0] <= cutoff:
            dq.popleft()
        return len(dq)

    def add(self, key: str) -> None:
        self._hits[key].append(time.monotonic())
        if len(self._hits) > self._max_keys:
            self._prune()

    def hit(self, key: str, limit: int, window: float) -> bool:
        """Record a hit unless the key is already at its limit (then False)."""
        if self.count(key, window) >= limit:
            return False
        self.add(key)
        return True

    def reset(self, key: str) -> None:
        self._hits.pop(key, None)

    def clear(self) -> None:
        self._hits.clear()

    def _prune(self) -> None:
        cutoff = time.monotonic() - self._max_window
        for key in [k for k, dq in self._hits.items() if not dq or dq[-1] <= cutoff]:
            del self._hits[key]


class DailyQuota:
    """Per-key counters that reset at midnight UTC."""

    def __init__(self):
        self._day: date | None = None
        self._used: dict[str, int] = {}

    def take(self, limits: list[tuple[str, int]]) -> bool:
        """Spend one unit from every key, or none if any key is exhausted."""
        today = datetime.now(timezone.utc).date()
        if today != self._day:
            self._day = today
            self._used.clear()
        if any(self._used.get(key, 0) >= limit for key, limit in limits):
            return False
        for key, _ in limits:
            self._used[key] = self._used.get(key, 0) + 1
        return True

    def clear(self) -> None:
        self._used.clear()


rate_windows = SlidingWindow()
login_failures = SlidingWindow()
ai_quota_counter = DailyQuota()

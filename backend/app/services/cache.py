"""Thin Redis cache wrapper. The app works without Redis — when the connection
is unavailable every helper falls back to a small in-process cache, so cached
upstream calls (the paid Odds API, Sleeper projections) still aren't repeated
on every request."""

import json
import logging
import time
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_available = True

# In-process fallback: key → (expires_at monotonic, json payload). Bounded so a
# long-running process can't grow it without limit.
_local: dict[str, tuple[float, str]] = {}
_LOCAL_MAX_KEYS = 512


def get_redis() -> aioredis.Redis | None:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, decode_responses=True, socket_connect_timeout=2
        )
    return _client


def _local_get(key: str) -> Any | None:
    hit = _local.get(key)
    if hit is None:
        return None
    expires, raw = hit
    if expires < time.monotonic():
        _local.pop(key, None)
        return None
    return json.loads(raw)


def _local_set(key: str, value: Any, ttl_seconds: int) -> None:
    if len(_local) >= _LOCAL_MAX_KEYS and key not in _local:
        now = time.monotonic()
        for k in [k for k, (exp, _) in _local.items() if exp < now]:
            _local.pop(k, None)
        if len(_local) >= _LOCAL_MAX_KEYS:
            _local.pop(next(iter(_local)))  # oldest insertion
    _local[key] = (time.monotonic() + ttl_seconds, json.dumps(value, default=str))


async def cache_get(key: str) -> Any | None:
    global _available
    if not _available:
        return _local_get(key)
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        _available = False
        logger.warning("Redis unavailable — using in-process cache")
        return _local_get(key)


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    global _available
    if not _available:
        _local_set(key, value, ttl_seconds)
        return
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception:
        _available = False
        logger.warning("Redis unavailable — using in-process cache")
        _local_set(key, value, ttl_seconds)

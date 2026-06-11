"""Thin Redis cache wrapper. The app works without Redis — every helper
degrades to a no-op if the connection is unavailable."""

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.config import get_settings

logger = logging.getLogger(__name__)

_client: aioredis.Redis | None = None
_available = True


def get_redis() -> aioredis.Redis | None:
    global _client
    if _client is None:
        _client = aioredis.from_url(
            get_settings().redis_url, decode_responses=True, socket_connect_timeout=2
        )
    return _client


async def cache_get(key: str) -> Any | None:
    global _available
    if not _available:
        return None
    try:
        raw = await get_redis().get(key)
        return json.loads(raw) if raw else None
    except Exception:
        _available = False
        logger.warning("Redis unavailable — caching disabled")
        return None


async def cache_set(key: str, value: Any, ttl_seconds: int = 300) -> None:
    global _available
    if not _available:
        return
    try:
        await get_redis().set(key, json.dumps(value, default=str), ex=ttl_seconds)
    except Exception:
        _available = False
        logger.warning("Redis unavailable — caching disabled")

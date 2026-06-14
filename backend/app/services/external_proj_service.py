"""External weekly projections (Sleeper) to blend with our own model.

Sleeper publishes per-player weekly projections keyed by the same player_id we
use canonically. Blending them in grounds our projection in a second, market-
calibrated source that reacts to current usage and news. Cached, and degrades
to an empty dict (model-only) when unavailable — e.g. in the offseason.
"""

import logging

import httpx

from app.services.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

PROJ_URL = "https://api.sleeper.com/projections/nfl/{season}/{week}"
CACHE_TTL = 6 * 3600  # projections move slowly within a week


async def get_external_projections(season: int, week: int) -> dict[str, float]:
    """player_id -> projected PPR points for the given week. {} if unavailable."""
    key = f"sleeperproj:{season}:{week}"
    cached = await cache_get(key)
    if cached is not None:
        return cached

    params = {
        "season_type": "regular",
        "position[]": ["QB", "RB", "WR", "TE"],
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(
                PROJ_URL.format(season=season, week=week), params=params
            )
            resp.raise_for_status()
            rows = resp.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("Sleeper projections unavailable for %s wk%s", season, week)
        return {}

    out: dict[str, float] = {}
    for row in rows:
        pid = str(row.get("player_id") or "")
        pts = (row.get("stats") or {}).get("pts_ppr")
        if pid and pts is not None:
            out[pid] = float(pts)
    if out:
        await cache_set(key, out, CACHE_TTL)
    return out

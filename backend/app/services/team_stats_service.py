"""Team scoring results from nflverse's public schedule file.

One CSV (``games.csv``) carries every NFL game's final score. The defense and
kicker projections need team-level scoring that player box scores can't give
us: how many points an offense scores and a defense allows per game. Cached,
and degrades to an empty list (league-average teams) when unavailable.
"""

import csv
import io
import logging

import httpx

from app.services.cache import cache_get, cache_set

logger = logging.getLogger(__name__)

GAMES_URL = "https://github.com/nflverse/nfldata/raw/master/data/games.csv"
CACHE_TTL = 3 * 3600  # finals land a few times a week; this is plenty fresh
# nflverse abbreviations that differ from ours (Sleeper's)
_TEAM_FIX = {"LA": "LAR", "STL": "LAR", "SD": "LAC", "OAK": "LV", "WSH": "WAS"}


def _team(code: str) -> str:
    return _TEAM_FIX.get(code, code)


def parse_games_csv(text: str, seasons: set[int]) -> list[dict]:
    """Completed regular-season games for ``seasons`` as two rows each — one
    per team — ``{season, week, team, opponent, points_for, points_against}``."""
    rows: list[dict] = []
    for g in csv.DictReader(io.StringIO(text)):
        try:
            season = int(g["season"])
        except (KeyError, ValueError):
            continue
        if season not in seasons or g.get("game_type") != "REG":
            continue
        if not g.get("home_score") or not g.get("away_score"):
            continue  # not played yet
        week = int(g["week"])
        home, away = _team(g["home_team"]), _team(g["away_team"])
        hs, as_ = int(float(g["home_score"])), int(float(g["away_score"]))
        rows.append({"season": season, "week": week, "team": home, "opponent": away,
                     "points_for": hs, "points_against": as_})
        rows.append({"season": season, "week": week, "team": away, "opponent": home,
                     "points_for": as_, "points_against": hs})
    return rows


async def get_team_results(seasons: list[int]) -> list[dict]:
    """Per-team game results for ``seasons`` (see ``parse_games_csv``)."""
    wanted = sorted(set(seasons))
    key = f"nflgames:v1:{wanted[0]}-{wanted[-1]}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(GAMES_URL)
            resp.raise_for_status()
            text = resp.text
    except httpx.HTTPError:
        logger.warning("nflverse games.csv unavailable — team form defaults to average")
        return []
    rows = parse_games_csv(text, set(wanted))
    if rows:
        await cache_set(key, rows, CACHE_TTL)
    return rows

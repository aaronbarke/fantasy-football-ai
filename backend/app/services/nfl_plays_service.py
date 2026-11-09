"""NFL game state and play-by-play from ESPN's public site API.

Two uses:
- how much of each game is left (game clock, not wall time), so the live win
  probability knows a game in overtime isn't over and one at halftime is half
  done;
- every play with its wall-clock time, so the Matchup chart can be rebuilt
  after the fact: real touchdowns at the real minute, not a guess.

All fetches go through ``_fetch_json`` (tests stub it) and are cached: a final
game's plays never change; live data is cached for half a minute.
"""

import logging
import re
from datetime import datetime

import httpx

from app.services.cache import cache_get, cache_set
from app.services.schedule_service import ESPN_ABBR_FIX, SCOREBOARD_URL

logger = logging.getLogger(__name__)

SUMMARY_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/summary"
LIVE_TTL = 30
FINAL_TTL = 7 * 24 * 3600
REGULATION_SECONDS = 4 * 900


async def _fetch_json(url: str, params: dict) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
            resp.raise_for_status()
            return resp.json()
    except (httpx.HTTPError, ValueError):
        logger.warning("ESPN fetch failed: %s %s", url, params)
        return None


def _parse_time(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _clock_seconds(clock: dict | None) -> float | None:
    """Seconds left in the period from an ESPN clock ({value} or "MM:SS")."""
    if not clock:
        return None
    if clock.get("value") is not None:
        try:
            return float(clock["value"])
        except (TypeError, ValueError):
            pass
    disp = clock.get("displayValue") or ""
    m = re.match(r"^(\d+):(\d\d)", disp)
    return int(m.group(1)) * 60 + int(m.group(2)) if m else None


def remaining_share(period: int | None, clock_left: float | None) -> float:
    """Share of regulation still to play at a game-clock moment. Overtime and
    unknown clocks count as (nearly) done."""
    if not period:
        return 1.0
    if period > 4:
        return 0.0
    left = (4 - period) * 900 + (clock_left if clock_left is not None else 0.0)
    return max(0.0, min(1.0, left / REGULATION_SECONDS))


def _team_abbr(competitor: dict) -> str:
    abbr = (competitor.get("team") or {}).get("abbreviation", "")
    return ESPN_ABBR_FIX.get(abbr, abbr).upper()


async def week_games(season: int, week: int) -> list[dict]:
    """Every game of an NFL week: ESPN event id, teams, kickoff and live state
    (``pre``/``in``/``post``) with the share of the game still to play."""
    key = f"nfl:week_games:{season}:{week}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    data = await _fetch_json(SCOREBOARD_URL, {"seasontype": 2, "week": week, "dates": season})
    games = []
    for event in (data or {}).get("events") or []:
        comp = (event.get("competitions") or [{}])[0]
        teams = {c.get("homeAway"): _team_abbr(c) for c in comp.get("competitors") or []}
        status = comp.get("status") or event.get("status") or {}
        state = (status.get("type") or {}).get("state") or "pre"
        period = status.get("period")
        clock = status.get("clock")
        left = 1.0
        if state == "post":
            left = 0.0
        elif state == "in":
            left = remaining_share(period, float(clock) if clock is not None else None)
        games.append(
            {
                "event_id": str(event.get("id")),
                "home": teams.get("home"),
                "away": teams.get("away"),
                "kickoff": event.get("date"),
                "state": state,
                "remaining": left,
            }
        )
    if data is not None:
        await cache_set(key, games, LIVE_TTL)
    return games


async def live_remaining(season: int, week: int) -> dict[str, float]:
    """Team → share of its game still to play, for games ESPN reports as live
    or final. Teams not yet kicked off (or unknown) are left out."""
    out: dict[str, float] = {}
    for g in await week_games(season, week):
        if g["state"] not in ("in", "post"):
            continue
        for team in (g["home"], g["away"]):
            if team:
                out[team] = g["remaining"]
    return out


def parse_plays(summary: dict) -> list[dict]:
    """The plays of one game, in order: wall-clock time, type, text, yards,
    period and clock. Plays without a wall clock can't be placed, so they're
    dropped."""
    plays = []
    drives = (summary.get("drives") or {}).get("previous") or []
    current = (summary.get("drives") or {}).get("current")
    if current and current not in drives:
        drives = [*drives, current]
    seen = set()
    for drive in drives:
        for p in drive.get("plays") or []:
            pid = p.get("id")
            if pid in seen:
                continue
            seen.add(pid)
            t = _parse_time(p.get("wallclock"))
            if t is None:
                continue
            plays.append(
                {
                    "t": t.isoformat(),
                    "type": ((p.get("type") or {}).get("text") or ""),
                    "text": p.get("text") or "",
                    "yards": p.get("statYardage"),
                    "period": (p.get("period") or {}).get("number"),
                    "clock": _clock_seconds(p.get("clock")),
                    "turnover": bool(p.get("isTurnover")),
                }
            )
    plays.sort(key=lambda x: x["t"])
    return plays


async def game_plays(event_id: str, final: bool) -> list[dict] | None:
    """Parsed plays for one game (None if ESPN couldn't be reached)."""
    key = f"nfl:plays:{event_id}"
    cached = await cache_get(key)
    if cached is not None:
        return cached
    data = await _fetch_json(SUMMARY_URL, {"event": event_id})
    if data is None:
        return None
    plays = parse_plays(data)
    await cache_set(key, plays, FINAL_TTL if final else LIVE_TTL)
    return plays

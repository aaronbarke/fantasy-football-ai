"""Win-probability timeline for the Matchup chart: which players moved the
odds between snapshots, which moves count as big swings, and when games are
on (so the scheduler only polls live scores while they can change).

Kept free of I/O except ``game_in_progress`` so the attribution logic is easy
to test on its own.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MatchupOdds, NflSchedule
from app.services.schedule_service import GAME_FINISHED_AFTER

# A move of at least this much win probability (3 percentage points) is a
# "swing": the chart marks it and names the play or players behind it.
SWING_THRESHOLD = 0.03
# Smaller point changes are rounding noise (and stat corrections of a tenth).
_MIN_POINT_CHANGE = 0.05
# A swing names at most this many players.
MAX_DRIVERS = 3


def starter_points(rows: list[dict]) -> tuple[dict[str, float], dict[str, dict]]:
    """Live points for every starter in an aligned matchup lineup (the preview's
    ``rows``), plus who each one is, keyed by player id. A starter who hasn't
    scored yet counts as 0, so his first points show up as a change."""
    points: dict[str, float] = {}
    meta: dict[str, dict] = {}
    for row in rows:
        for side_key, side in (("user", "user"), ("opponent", "opp")):
            p = row.get(side_key)
            if not p or not p.get("id"):
                continue
            pid = str(p["id"])
            points[pid] = round(float(p.get("actual_points") or 0.0), 2)
            meta[pid] = {
                "name": p.get("name") or pid,
                "position": p.get("position"),
                "side": side,
            }
    return points, meta


def starter_projections(rows: list[dict]) -> dict[str, dict]:
    """Each starter's projection, its spread and injury status as the app sees
    it right now — saved with a snapshot so a later rebuild knows what the
    app believed at that moment."""
    out: dict[str, dict] = {}
    for row in rows:
        for side_key in ("user", "opponent"):
            p = row.get(side_key)
            if not p or not p.get("id"):
                continue
            out[str(p["id"])] = {
                "proj": round(float(p.get("projected") or 0.0), 2),
                "sd": round(float(p.get("stdev") or 0.0), 2),
                "status": p.get("injury_status"),
            }
    return out


# A projection move smaller than this between snapshots is drift, not news.
NEWS_MIN_PROJ = 0.5


def news_changes(
    prev: dict[str, dict] | None,
    cur: dict[str, dict],
    meta: dict[str, dict],
) -> list[dict]:
    """Starters whose injury status or projection changed since the previous
    snapshot ("Davante Adams → Injured Reserve, −16.6 proj")."""
    if not prev:
        return []
    out = []
    for pid, now_v in cur.items():
        was = prev.get(pid)
        if was is None:
            continue
        d = float(now_v.get("proj") or 0) - float(was.get("proj") or 0)
        status_changed = (was.get("status") or "Active") != (now_v.get("status") or "Active")
        if abs(d) < NEWS_MIN_PROJ and not status_changed:
            continue
        info = meta.get(pid, {})
        out.append(
            {
                "id": pid,
                "name": info.get("name") or pid,
                "position": info.get("position"),
                "side": info.get("side"),
                "kind": "news",
                "status": now_v.get("status") if status_changed else None,
                "proj_delta": round(d, 2),
                "delta": 0.0,
                "points": None,
            }
        )
    out.sort(key=lambda c: -abs(c["proj_delta"]))
    return out


def player_changes(
    prev_points: dict[str, float] | None,
    cur_points: dict[str, float],
    meta: dict[str, dict],
) -> list[dict]:
    """Starters whose live points moved since the previous snapshot, biggest
    move first. No previous snapshot (or one saved before per-player points were
    kept) → no baseline to compare against, so nothing is attributed."""
    if prev_points is None:
        return []
    out = []
    for pid, pts in cur_points.items():
        delta = pts - float(prev_points.get(pid) or 0.0)
        if abs(delta) < _MIN_POINT_CHANGE:
            continue
        info = meta.get(pid, {})
        out.append(
            {
                "id": pid,
                "name": info.get("name") or pid,
                "position": info.get("position"),
                "side": info.get("side"),
                "delta": round(delta, 2),
                "points": round(pts, 2),
            }
        )
    out.sort(key=lambda c: (-abs(c["delta"]), c["name"]))
    return out


def _helps_user(change: dict) -> float:
    """How much a point change helped the user: your starter's points count for
    you, your opponent's against you."""
    return change["delta"] if change.get("side") == "user" else -change["delta"]


def swing_drivers(changes: list[dict], delta: float, limit: int = MAX_DRIVERS) -> list[dict]:
    """The players behind a win-probability move: those whose points pushed the
    odds the way they moved, most impact first. If nobody's points pushed that
    way (the move came from elsewhere), fall back to the biggest changes."""
    direction = 1 if delta >= 0 else -1
    pushing = [c for c in changes if _helps_user(c) * direction > 0]
    pushing.sort(key=lambda c: -abs(c["delta"]))
    return (pushing or changes)[:limit]


def build_odds_history(
    rows: list[MatchupOdds],
    kickoffs: list[dict],
    threshold: float = SWING_THRESHOLD,
) -> dict:
    """The odds-history payload: every snapshot, each with how far the odds
    moved since the one before and (for moves of at least ``threshold``) the
    swing's drivers; plus the week's kickoffs so the chart can span the whole
    scoring period and mark each game window."""
    points = []
    prev_wp: float | None = None
    for r in rows:
        delta = None if prev_wp is None else r.win_probability - prev_wp
        changes = list(r.changes or [])
        swing = None
        if delta is not None and abs(delta) >= threshold - 1e-9:
            swing = {
                "delta": round(delta, 4),
                "drivers": swing_drivers(changes, delta),
            }
        points.append(
            {
                "t": r.captured_at.isoformat() if r.captured_at else None,
                "win_probability": r.win_probability,
                "user_points": r.user_points,
                "opp_points": r.opp_points,
                "delta": round(delta, 4) if delta is not None else None,
                "changes": changes,
                "swing": swing,
            }
        )
        prev_wp = r.win_probability
    starts = [k["t"] for k in kickoffs if k.get("t")]
    return {
        "swing_threshold": threshold,
        "window_start": min(starts) if starts else None,
        "kickoffs": kickoffs,
        "points": points,
    }


async def week_kickoffs(db: AsyncSession, season: int, week: int) -> list[dict]:
    """Every game of an NFL week with its kickoff (naive UTC, ISO), in order."""
    games = (
        await db.execute(
            select(NflSchedule)
            .where(
                NflSchedule.season == season,
                NflSchedule.week == week,
                NflSchedule.game_time.is_not(None),
            )
            .order_by(NflSchedule.game_time.asc(), NflSchedule.home_team.asc())
        )
    ).scalars().all()
    return [
        {"t": g.game_time.isoformat(), "home": g.home_team, "away": g.away_team}
        for g in games
    ]


async def game_in_progress(db: AsyncSession, now: datetime) -> bool:
    """Is any NFL game on right now (kicked off, not yet final)? Gates the
    live-odds job so it only polls the platforms while scores can move."""
    since = now - GAME_FINISHED_AFTER
    hit = (
        await db.execute(
            select(NflSchedule.id)
            .where(
                NflSchedule.game_time.is_not(None),
                NflSchedule.game_time <= now,
                NflSchedule.game_time > since,
            )
            .limit(1)
        )
    ).scalar_one_or_none()
    return hit is not None


def week_started(kickoffs: dict[str, datetime], now: datetime) -> bool:
    """Has any of the week's games kicked off, with one still to finish?"""
    times = list(kickoffs.values())
    if not times:
        return False
    return min(times) <= now < max(times) + GAME_FINISHED_AFTER


"""Track record: how our projections, lineups and start/sit calls held up.

Three steps:

1. **Snapshot** (every half hour, see the scheduler). For the current NFL week,
   save each skill player's projection until his game kicks off — so the stored
   number is the last one anyone saw before setting a lineup — and each league
   team's recommended lineup + suggested swaps until the week's main slate
   kicks off.
2. **Grade** (once the week is over and nflverse stats have landed). A
   projection's actual is the player's fantasy points in that scoring format; a
   player with no stat line once the week is loaded didn't play and scored 0.
   A lineup is compared with the best lineup that roster could have started in
   hindsight.
3. **Report** — averages for one league connection: projection error (overall,
   by position, vs Sleeper alone and our model alone, for your own players),
   lineup accuracy per week, and the start/sit record.

Kickers and defenses aren't graded: nflverse player stats don't carry their
fantasy points, so only QB/RB/WR/TE count toward these numbers.
"""

import logging
import math
from collections import Counter, defaultdict
from datetime import datetime, timedelta

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import (
    LeagueConnection,
    LineupSnapshot,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    ProjectionSnapshot,
    Recommendation,
    Roster,
)
from app.services.external_proj_service import get_external_projections
from app.services.gameplan_service import build_gameplan, optimize_lineup
from app.services.projection_service import compute_projections
from app.services.schedule_service import current_nfl_week, points_column, utc_now

logger = logging.getLogger(__name__)

GRADED_POSITIONS = {"QB", "RB", "WR", "TE"}
NON_GRADED_SLOTS = {"K", "DEF"}
# Besides everyone on a connected roster, also track anyone Sleeper projects
# for at least this much — a bigger, steadier sample for the error numbers.
MIN_TRACKED_PROJECTION = 3.0
# A week is only graded once its last game is this far in the past.
WEEK_SETTLE_HOURS = 8


# --- 1. snapshot ---------------------------------------------------------------


def lineup_lock(kickoffs: list[datetime]) -> datetime | None:
    """When a week's lineup recommendation is frozen: the kickoff with the most
    games (Sunday's early slate), earliest on a tie."""
    if not kickoffs:
        return None
    counts = Counter(kickoffs)
    top = max(counts.values())
    return min(k for k, n in counts.items() if n == top)


async def snapshot_week(db: AsyncSession, now: datetime | None = None) -> dict:
    """Record pre-game projections and recommended lineups for the current
    week. Safe to run as often as you like: rows only change before their lock."""
    now = now or utc_now()
    season = get_settings().current_season
    week = await current_nfl_week(db, season, now)
    if week is None:
        return {"week": None, "projections": 0, "lineups": 0}

    games = (
        await db.execute(
            select(NflSchedule).where(
                NflSchedule.season == season,
                NflSchedule.week == week,
                NflSchedule.game_time.is_not(None),
            )
        )
    ).scalars().all()
    kickoff_by_team: dict[str, datetime] = {}
    for g in games:
        kickoff_by_team[g.home_team] = g.game_time
        kickoff_by_team[g.away_team] = g.game_time
    if not kickoff_by_team:
        return {"week": week, "projections": 0, "lineups": 0}

    conns = (
        await db.execute(select(LeagueConnection).where(LeagueConnection.season == season))
    ).scalars().all()
    rosters_by_conn: dict = defaultdict(list)
    if conns:
        for r in (
            await db.execute(
                select(Roster).where(Roster.connection_id.in_([c.id for c in conns]))
            )
        ).scalars().all():
            rosters_by_conn[r.connection_id].append(r)

    # Projections — one pass per scoring format in use.
    saved = 0
    for scoring in sorted({c.scoring_type or "ppr" for c in conns} or {"ppr"}):
        ids: set[str] = set()
        for c in conns:
            if (c.scoring_type or "ppr") == scoring:
                for r in rosters_by_conn[c.id]:
                    ids.update(r.players or [])
        external = await get_external_projections(season, week, scoring)
        ids.update(pid for pid, pts in external.items() if pts >= MIN_TRACKED_PROJECTION)
        players = (
            await db.execute(
                select(Player).where(
                    Player.id.in_(ids), Player.position.in_(GRADED_POSITIONS)
                )
            )
        ).scalars().all() if ids else []
        if not players:
            continue
        proj = await compute_projections(db, [p.id for p in players], season, scoring)
        existing = {
            s.player_id: s
            for s in (
                await db.execute(
                    select(ProjectionSnapshot).where(
                        ProjectionSnapshot.season == season,
                        ProjectionSnapshot.week == week,
                        ProjectionSnapshot.scoring == scoring,
                    )
                )
            ).scalars().all()
        }
        for p in players:
            pkg = proj.get(p.id)
            if not pkg or pkg.get("inactive_reason"):
                continue  # no projection, on bye, or not on a team
            kickoff = kickoff_by_team.get(p.team or "")
            if kickoff is None or kickoff <= now:
                continue  # no game this week, or already locked
            c = pkg.get("components") or {}
            snap = existing.get(p.id)
            if snap is None:
                snap = ProjectionSnapshot(
                    season=season, week=week, player_id=p.id, scoring=scoring
                )
                db.add(snap)
            snap.position = p.position
            snap.team = p.team
            snap.projected = float(pkg["projected"])
            snap.floor = pkg.get("floor")
            snap.ceiling = pkg.get("ceiling")
            snap.model_proj = c.get("model_proj")
            snap.external_proj = c.get("external_proj")
            snap.kickoff = kickoff
            snap.captured_at = now
            saved += 1

    # Recommended lineups — frozen at the main slate.
    lineups = 0
    lock = lineup_lock(list(kickoff_by_team.values()))
    if lock is not None and now < lock:
        for c in conns:
            if not c.team_id:
                continue
            mine = next((r for r in rosters_by_conn[c.id] if r.team_id == c.team_id), None)
            if mine is None or not mine.players:
                continue
            plan = await build_gameplan(db, c)
            if plan.get("status") != "ok":
                continue
            snap = (
                await db.execute(
                    select(LineupSnapshot).where(
                        LineupSnapshot.connection_id == c.id,
                        LineupSnapshot.season == season,
                        LineupSnapshot.week == week,
                    )
                )
            ).scalar_one_or_none()
            if snap is None:
                snap = LineupSnapshot(connection_id=c.id, season=season, week=week)
                db.add(snap)
            snap.scoring = c.scoring_type or "ppr"
            snap.roster = list(mine.players)
            snap.actual_starters = list(mine.starters or [])
            snap.recommended = [
                {
                    "slot": row["slot"],
                    "player_id": row["player"]["id"],
                    "projected": row["player"].get("projected"),
                }
                for row in plan.get("lineup", [])
                if row.get("player")
            ]
            snap.swaps = [
                {
                    "slot": s["slot"],
                    "start": s["start"]["id"],
                    "sit": s["sit"]["id"] if s.get("sit") else None,
                }
                for s in plan.get("swaps", [])
            ]
            snap.captured_at = now
            lineups += 1

    await db.commit()
    return {"week": week, "projections": saved, "lineups": lineups}


# --- 2. grade ----------------------------------------------------------------------


async def _week_ready(db: AsyncSession, season: int, week: int, now: datetime) -> bool:
    """The week's games are all over and its stats have been ingested."""
    last_kick = (
        await db.execute(
            select(NflSchedule.game_time)
            .where(
                NflSchedule.season == season,
                NflSchedule.week == week,
                NflSchedule.game_time.is_not(None),
            )
            .order_by(NflSchedule.game_time.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if last_kick is None or last_kick + timedelta(hours=WEEK_SETTLE_HOURS) > now:
        return False
    return bool(
        (
            await db.execute(
                select(
                    exists().where(
                        PlayerStatsWeekly.season == season, PlayerStatsWeekly.week == week
                    )
                )
            )
        ).scalar()
    )


async def _actual_points(
    db: AsyncSession, season: int, week: int, scoring: str, player_ids: set[str]
) -> dict[str, float]:
    """Fantasy points scored that week; anyone without a stat line scored 0."""
    if not player_ids:
        return {}
    col = points_column(scoring)
    rows = (
        await db.execute(
            select(PlayerStatsWeekly.player_id, col).where(
                PlayerStatsWeekly.season == season,
                PlayerStatsWeekly.week == week,
                PlayerStatsWeekly.player_id.in_(player_ids),
            )
        )
    ).all()
    out = {pid: 0.0 for pid in player_ids}
    out.update({pid: float(pts or 0) for pid, pts in rows})
    return out


def grade_lineup(
    snapshot: LineupSnapshot, actual: dict[str, float], positions: dict[str, str]
) -> dict:
    """How a recommended lineup did against the best lineup that roster could
    have started in hindsight (QB/RB/WR/TE slots only)."""
    slots = [r["slot"] for r in snapshot.recommended if r["slot"] not in NON_GRADED_SLOTS]
    recommended = [
        r["player_id"] for r in snapshot.recommended if r["slot"] not in NON_GRADED_SLOTS
    ]
    pool = [
        {"id": pid, "position": positions[pid], "projected": actual.get(pid, 0.0)}
        for pid in snapshot.roster
        if positions.get(pid) in GRADED_POSITIONS
    ]
    best_lineup, _ = optimize_lineup(slots, pool)
    best = [r["player"]["id"] for r in best_lineup if r["player"]]
    yours = [pid for pid in snapshot.actual_starters if positions.get(pid) in GRADED_POSITIONS]

    def total(ids: list[str]) -> float:
        return round(sum(actual.get(pid, 0.0) for pid in ids), 2)

    swaps = []
    for s in snapshot.swaps:
        if not s.get("sit"):
            continue
        start_pts = actual.get(s["start"], 0.0)
        sit_pts = actual.get(s["sit"], 0.0)
        swaps.append(
            {
                "slot": s["slot"],
                "start": s["start"],
                "sit": s["sit"],
                "start_points": start_pts,
                "sit_points": sit_pts,
                "result": "win" if start_pts > sit_pts else "loss" if start_pts < sit_pts else "tie",
            }
        )

    return {
        "slots": len(slots),
        "correct": len(set(recommended) & set(best)),
        "recommended_points": total(recommended),
        "best_points": total(best),
        "your_points": total(yours),
        "should_have_started": [pid for pid in best if pid not in recommended],
        "should_have_sat": [pid for pid in recommended if pid not in best],
        "swaps": swaps,
    }


async def grade_pending(db: AsyncSession, now: datetime | None = None) -> dict:
    """Grade every snapshot whose week is over and has stats."""
    now = now or utc_now()
    ready: dict[tuple[int, int], bool] = {}

    async def is_ready(season: int, week: int) -> bool:
        if (season, week) not in ready:
            ready[(season, week)] = await _week_ready(db, season, week, now)
        return ready[(season, week)]

    graded_proj = 0
    pending = (
        await db.execute(select(ProjectionSnapshot).where(ProjectionSnapshot.actual.is_(None)))
    ).scalars().all()
    groups: dict[tuple[int, int, str], list[ProjectionSnapshot]] = defaultdict(list)
    for s in pending:
        groups[(s.season, s.week, s.scoring)].append(s)
    for (season, week, scoring), snaps in groups.items():
        if not await is_ready(season, week):
            continue
        actual = await _actual_points(db, season, week, scoring, {s.player_id for s in snaps})
        for s in snaps:
            s.actual = actual[s.player_id]
            s.graded_at = now
            graded_proj += 1

    graded_lineups = 0
    lineup_pending = (
        await db.execute(select(LineupSnapshot).where(LineupSnapshot.grade.is_(None)))
    ).scalars().all()
    for snap in lineup_pending:
        if not await is_ready(snap.season, snap.week):
            continue
        ids = set(snap.roster) | set(snap.actual_starters)
        positions = {
            pid: pos
            for pid, pos in (
                await db.execute(select(Player.id, Player.position).where(Player.id.in_(ids)))
            ).all()
        } if ids else {}
        actual = await _actual_points(db, snap.season, snap.week, snap.scoring, ids)
        snap.grade = grade_lineup(snap, actual, positions)
        snap.graded_at = now
        graded_lineups += 1

    await db.commit()
    if graded_proj or graded_lineups:
        logger.info("Accuracy: graded %d projections, %d lineups", graded_proj, graded_lineups)
    return {"projections": graded_proj, "lineups": graded_lineups}


# --- 3. report -----------------------------------------------------------------------


def _error_stats(rows: list[tuple[float, float, float | None, float | None]]) -> dict | None:
    """rows: (projected, actual, floor, ceiling). Error = actual - projected."""
    if not rows:
        return None
    errors = [a - p for p, a, _, _ in rows]
    banded = [(a, lo, hi) for _, a, lo, hi in rows if lo is not None and hi is not None]
    return {
        "count": len(rows),
        "avg_miss": round(sum(abs(e) for e in errors) / len(errors), 2),
        "bias": round(sum(errors) / len(errors), 2),
        "rmse": round(math.sqrt(sum(e * e for e in errors) / len(errors)), 2),
        "within_range_pct": (
            round(100 * sum(1 for a, lo, hi in banded if lo <= a <= hi) / len(banded))
            if banded
            else None
        ),
    }


def _mae(pairs: list[tuple[float, float]]) -> float | None:
    return round(sum(abs(a - p) for p, a in pairs) / len(pairs), 2) if pairs else None


async def accuracy_report(db: AsyncSession, conn: LeagueConnection) -> dict:
    """Everything the Track record page shows for one league connection."""
    await grade_pending(db)
    season = conn.season
    scoring = conn.scoring_type or "ppr"

    # Projections (all tracked players in this scoring format). A player
    # projected for 0 was already ruled out — not a forecast worth grading.
    snaps = (
        await db.execute(
            select(ProjectionSnapshot).where(
                ProjectionSnapshot.season == season,
                ProjectionSnapshot.scoring == scoring,
            )
        )
    ).scalars().all()
    graded = [s for s in snaps if s.actual is not None and s.projected > 0]
    pending_weeks = sorted({s.week for s in snaps if s.actual is None})
    weeks_tracked = sorted({s.week for s in snaps})

    def rows(items):
        return [(s.projected, s.actual, s.floor, s.ceiling) for s in items]

    by_position = {
        pos: _error_stats(rows([s for s in graded if s.position == pos]))
        for pos in ("QB", "RB", "WR", "TE")
    }
    with_sleeper = [s for s in graded if s.external_proj is not None]
    with_model = [s for s in graded if s.model_proj is not None]
    comparison = {
        "count": len(with_sleeper),
        "ours": _mae([(s.projected, s.actual) for s in with_sleeper]),
        "sleeper_only": _mae([(s.external_proj, s.actual) for s in with_sleeper]),
        "our_model_only": _mae([(s.model_proj, s.actual) for s in with_model if s.external_proj is not None]),
    }
    by_week = [
        {"week": w, **(_error_stats(rows([s for s in graded if s.week == w])) or {})}
        for w in sorted({s.week for s in graded})
    ]

    # Your players: everyone on your roster right now, plus anyone graded in a
    # lineup of yours this season.
    my_roster = (
        await db.execute(
            select(Roster).where(Roster.connection_id == conn.id, Roster.team_id == conn.team_id)
        )
    ).scalar_one_or_none()
    lineup_snaps = (
        await db.execute(
            select(LineupSnapshot)
            .where(LineupSnapshot.connection_id == conn.id, LineupSnapshot.season == season)
            .order_by(LineupSnapshot.week)
        )
    ).scalars().all()
    my_ids = set(my_roster.players or []) if my_roster else set()
    for ls in lineup_snaps:
        my_ids.update(ls.roster)

    name_ids = set(my_ids)
    for ls in lineup_snaps:
        if ls.grade:
            name_ids.update(ls.grade.get("should_have_started", []))
            name_ids.update(ls.grade.get("should_have_sat", []))
    graded_by_player: dict[str, list[ProjectionSnapshot]] = defaultdict(list)
    for s in graded:
        graded_by_player[s.player_id].append(s)
    name_ids.update(pid for pid in graded_by_player if pid in my_ids)
    players = {
        p.id: p
        for p in (
            await db.execute(select(Player).where(Player.id.in_(name_ids)))
        ).scalars().all()
    } if name_ids else {}

    def name(pid: str) -> str:
        return players[pid].full_name if pid in players else pid

    your_players = []
    for pid in my_ids:
        items = graded_by_player.get(pid)
        if not items:
            continue
        stats = _error_stats(rows(items))
        your_players.append(
            {
                "id": pid,
                "name": name(pid),
                "position": items[0].position,
                "games": stats["count"],
                "avg_projected": round(sum(s.projected for s in items) / len(items), 1),
                "avg_actual": round(sum(s.actual for s in items) / len(items), 1),
                "avg_miss": stats["avg_miss"],
                "bias": stats["bias"],
            }
        )
    your_players.sort(key=lambda r: (-r["games"], r["name"]))

    misses = sorted(
        (s for s in graded if s.player_id in my_ids),
        key=lambda s: -abs(s.actual - s.projected),
    )[:8]
    biggest_misses = [
        {
            "week": s.week,
            "name": name(s.player_id),
            "position": s.position,
            "projected": round(s.projected, 1),
            "actual": round(s.actual, 1),
        }
        for s in misses
    ]

    # Lineups and start/sit calls
    lineup_weeks = []
    swap_record = Counter()
    swap_calls = []
    for ls in lineup_snaps:
        g = ls.grade
        if not g:
            continue
        lineup_weeks.append(
            {
                "week": ls.week,
                "correct": g["correct"],
                "slots": g["slots"],
                "recommended_points": g["recommended_points"],
                "best_points": g["best_points"],
                "your_points": g["your_points"],
                "should_have_started": [name(pid) for pid in g["should_have_started"]],
                "should_have_sat": [name(pid) for pid in g["should_have_sat"]],
            }
        )
        for sw in g.get("swaps", []):
            swap_record[sw["result"]] += 1
            swap_calls.append(
                {
                    "week": ls.week,
                    "start": name(sw["start"]),
                    "sit": name(sw["sit"]),
                    "start_points": sw["start_points"],
                    "sit_points": sw["sit_points"],
                    "result": sw["result"],
                }
            )
    lineup_totals = None
    if lineup_weeks:
        n = len(lineup_weeks)
        lineup_totals = {
            "weeks": n,
            "correct": sum(w["correct"] for w in lineup_weeks),
            "slots": sum(w["slots"] for w in lineup_weeks),
            "perfect_weeks": sum(1 for w in lineup_weeks if w["correct"] == w["slots"]),
            "avg_points_left": round(
                sum(w["best_points"] - w["recommended_points"] for w in lineup_weeks) / n, 1
            ),
            "avg_vs_your_lineup": round(
                sum(w["recommended_points"] - w["your_points"] for w in lineup_weeks) / n, 1
            ),
        }

    chat_recs = (
        await db.execute(
            select(Recommendation.result).where(
                Recommendation.user_id == conn.user_id,
                Recommendation.connection_id == conn.id,
                Recommendation.season == season,
            )
        )
    ).scalars().all()
    chat_record = Counter(chat_recs)

    for sw in swap_calls:
        sw["start_points"] = round(sw["start_points"], 1)
        sw["sit_points"] = round(sw["sit_points"], 1)

    return {
        "season": season,
        "scoring": scoring,
        "weeks_tracked": weeks_tracked,
        "pending_weeks": pending_weeks,
        "projections": {
            "overall": _error_stats(rows(graded)),
            "by_position": by_position,
            "vs_sleeper": comparison,
            "by_week": by_week,
            "your_players": your_players[:30],
            "biggest_misses": biggest_misses,
        },
        "lineups": {"totals": lineup_totals, "weeks": lineup_weeks},
        "start_sit": {
            "game_plan": {
                "wins": swap_record["win"],
                "losses": swap_record["loss"],
                "ties": swap_record["tie"],
                "calls": swap_calls[-20:][::-1],
            },
            "chat": {
                "wins": chat_record["win"],
                "losses": chat_record["loss"],
                "ties": chat_record["tie"],
                "pending": chat_record["pending"],
            },
        },
    }

"""NFL schedule sync + defense-vs-position strength, powering the
schedule-strength heatmap."""

import logging
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NflSchedule, Player, PlayerStatsWeekly
from app.services.team_stats_service import normalize_team

logger = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# ESPN abbreviations that differ from ours
ESPN_ABBR_FIX = {"WSH": "WAS"}
# A game is treated as finished this long after kickoff.
GAME_FINISHED_AFTER = timedelta(hours=4)
REGULAR_SEASON_MAX_WEEK = 18


def utc_now() -> datetime:
    """Naive UTC, matching how game times are stored."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


async def current_nfl_week(
    db: AsyncSession, season: int, now: datetime | None = None
) -> int | None:
    """The active NFL week from the schedule: the earliest week whose games
    aren't all finished (a game is done ~4h after kickoff). Preseason → the
    first week; after the finale → the last. ``None`` if no schedule is loaded.

    This is the single definition of "this week" — projections, the matchup
    page, the game plan, the dashboard and chat all resolve the week through it,
    so they can't drift apart."""
    now = now or utc_now()
    rows = (
        await db.execute(
            select(NflSchedule.week, NflSchedule.game_time).where(
                NflSchedule.season == season, NflSchedule.game_time.is_not(None)
            )
        )
    ).all()
    if not rows:
        return None
    last_kick: dict[int, datetime] = {}
    for week, game_time in rows:
        if week not in last_kick or game_time > last_kick[week]:
            last_kick[week] = game_time
    unfinished = [w for w, kick in last_kick.items() if kick + GAME_FINISHED_AFTER > now]
    return min(unfinished) if unfinished else max(last_kick)


async def ensure_schedule(db: AsyncSession, season: int) -> None:
    """Load the season's schedule once if it isn't in the DB yet. Week
    resolution, bye detection and odds-to-week matching all depend on it."""
    have = (
        await db.execute(
            select(func.count()).select_from(NflSchedule).where(NflSchedule.season == season)
        )
    ).scalar_one()
    if not have:
        await sync_schedule(db, season)


async def sync_schedule(db: AsyncSession, season: int) -> int:
    """Pull the full regular-season schedule (18 weeks) from ESPN."""
    count = 0
    async with httpx.AsyncClient(timeout=30) as client:
        for week in range(1, 19):
            try:
                resp = await client.get(
                    SCOREBOARD_URL,
                    params={"seasontype": 2, "week": week, "dates": season},
                )
                resp.raise_for_status()
            except httpx.HTTPError:
                logger.warning("Schedule fetch failed for week %d", week)
                continue

            for event in resp.json().get("events", []):
                comps = event.get("competitions") or []
                if not comps:
                    continue
                home = away = None
                for c in comps[0].get("competitors", []):
                    abbr = c.get("team", {}).get("abbreviation", "")
                    abbr = ESPN_ABBR_FIX.get(abbr, abbr)
                    if c.get("homeAway") == "home":
                        home = abbr
                    else:
                        away = abbr
                if not home or not away:
                    continue

                existing = (
                    await db.execute(
                        select(NflSchedule).where(
                            NflSchedule.season == season,
                            NflSchedule.week == week,
                            NflSchedule.home_team == home,
                        )
                    )
                ).scalar_one_or_none()
                if existing is None:
                    existing = NflSchedule(season=season, week=week, home_team=home, away_team=away)
                    db.add(existing)
                existing.away_team = away
                try:
                    existing.game_time = datetime.fromisoformat(
                        event["date"].replace("Z", "+00:00")
                    ).replace(tzinfo=None)
                except (KeyError, ValueError):
                    pass
                count += 1
    await db.commit()
    logger.info("Schedule sync: %d games for %d", count, season)
    return count


async def latest_stats_season(db: AsyncSession) -> int | None:
    return (
        await db.execute(select(func.max(PlayerStatsWeekly.season)))
    ).scalar_one_or_none()


SCORING_POINTS_FIELD = {
    "ppr": "fantasy_points_ppr",
    "half_ppr": "fantasy_points_half",
    "standard": "fantasy_points_std",
}


def points_column(scoring: str | None):
    """The weekly-stats fantasy points column for a league's scoring format."""
    return getattr(
        PlayerStatsWeekly, SCORING_POINTS_FIELD.get(scoring or "ppr", "fantasy_points_ppr")
    )


async def defense_vs_position_ranks(
    db: AsyncSession, season: int, scoring: str = "ppr"
) -> dict[tuple[str, str], dict]:
    """(team, position) → {rank, pts_allowed_avg}. Rank 1 = allows the MOST
    fantasy points to that position (i.e. the easiest matchup)."""
    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.opponent,
                Player.position,
                func.sum(points_column(scoring)).label("total"),
                func.count(func.distinct(PlayerStatsWeekly.week)).label("weeks"),
            )
            .join(Player, Player.id == PlayerStatsWeekly.player_id)
            .where(
                PlayerStatsWeekly.season == season,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                PlayerStatsWeekly.opponent.is_not(None),
                Player.position.in_(["QB", "RB", "WR", "TE"]),
            )
            .group_by(PlayerStatsWeekly.opponent, Player.position)
        )
    ).all()

    # Rows stored before opponent codes were normalized at ingestion still say
    # "LA" for the Rams; fold them into "LAR" so the schedule can find them.
    merged: dict[tuple[str, str], list[float]] = {}
    for opponent, position, total, weeks in rows:
        acc = merged.setdefault((normalize_team(opponent), position), [0.0, 0])
        acc[0] += float(total or 0)
        acc[1] += int(weeks or 0)

    by_position: dict[str, list[tuple[str, float]]] = {}
    for (opponent, position), (total, weeks) in merged.items():
        if not weeks:
            continue
        by_position.setdefault(position, []).append((opponent, total / weeks))

    out: dict[tuple[str, str], dict] = {}
    for position, entries in by_position.items():
        entries.sort(key=lambda e: -e[1])  # most points allowed first
        for rank, (team, avg) in enumerate(entries, start=1):
            out[(team, position)] = {"rank": rank, "pts_allowed_avg": round(avg, 1)}
    return out


TEAM_POSITIONS = ("DEF", "K")
STRENGTH_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


async def matchup_ranks(
    db: AsyncSession, season: int, stats_season: int, scoring: str | None = "ppr"
) -> dict[tuple[str, str], dict]:
    """(opponent, position) → {rank, pts_allowed_avg} for every fantasy
    position. Rank 1 = the easiest matchup.

    QB/RB/WR/TE: fantasy points the defense allows to that position per game,
    in the league's scoring format. K: points the defense allows per game (the
    kicker model's driver). DEF: what a league-average DST is expected to
    score against that offense (its scoring and turnover rates), from the
    same team form the DST projection uses."""
    ranks = await defense_vs_position_ranks(db, stats_season, scoring or "ppr")

    # Local import: projection_service imports this module.
    from app.services.projection_service import _team_form, dst_model

    form = await _team_form(db, season)
    if not form:
        return ranks
    k_vals = [(team, f["def_pa_pg"]) for team, f in form.items()]
    dst_vals = [
        (team, dst_model(f["off_ppg"], None, f["off_ints_pg"], None, 0.0, None, None)["model"])
        for team, f in form.items()
    ]
    for position, vals in (("K", k_vals), ("DEF", dst_vals)):
        vals.sort(key=lambda e: -e[1])  # most favorable first
        for rank, (team, val) in enumerate(vals, start=1):
            ranks[(team, position)] = {"rank": rank, "pts_allowed_avg": round(val, 1)}
    return ranks


async def _games_by_team_week(
    db: AsyncSession, season: int, weeks: list[int]
) -> dict[tuple[str, int], dict]:
    games = (
        await db.execute(
            select(NflSchedule).where(
                NflSchedule.season == season, NflSchedule.week.in_(weeks)
            )
        )
    ).scalars().all()
    out: dict[tuple[str, int], dict] = {}
    for g in games:
        out[(g.home_team, g.week)] = {"opponent": g.away_team, "home": True}
        out[(g.away_team, g.week)] = {"opponent": g.home_team, "home": False}
    return out


def _window_weeks(start_week: int, weeks_ahead: int) -> list[int]:
    return list(range(start_week, min(start_week + weeks_ahead, REGULAR_SEASON_MAX_WEEK + 1)))


def _cell(week: int, game: dict | None, rank_info: dict) -> dict:
    if game is None:
        return {"week": week, "opponent": None, "rank": None}
    return {
        "week": week,
        "opponent": game["opponent"],
        "home": game["home"],
        "rank": rank_info.get("rank"),
        "pts_allowed_avg": rank_info.get("pts_allowed_avg"),
    }


async def build_schedule_strength(
    db: AsyncSession,
    season: int,
    start_week: int,
    player_ids: list[str],
    weeks_ahead: int = 6,
    scoring: str | None = "ppr",
) -> dict:
    """Heatmap payload: each roster player × upcoming weeks with opponent +
    matchup difficulty rank."""
    # Ensure the schedule is loaded (lazy one-time sync)
    await ensure_schedule(db, season)

    stats_season = await latest_stats_season(db) or season
    ranks = await matchup_ranks(db, season, stats_season, scoring)

    weeks = _window_weeks(start_week, weeks_ahead)
    by_team_week = await _games_by_team_week(db, season, weeks)

    players = (
        await db.execute(select(Player).where(Player.id.in_(player_ids)))
    ).scalars().all() if player_ids else []

    out_players = []
    for p in players:
        cells = []
        for w in weeks:
            game = by_team_week.get((p.team, w)) if p.team else None
            rank_info = ranks.get((game["opponent"], p.position or ""), {}) if game else {}
            cells.append(_cell(w, game, rank_info))
        out_players.append(
            {
                "id": p.id,
                "name": p.full_name,
                "position": p.position,
                "team": p.team,
                "cells": cells,
            }
        )

    # QB/RB/WR/TE first, then K/DEF
    order = {"QB": 0, "RB": 1, "WR": 2, "TE": 3, "K": 4, "DEF": 5}
    out_players.sort(key=lambda x: order.get(x["position"] or "", 9))
    return {"weeks": weeks, "stats_season": stats_season, "players": out_players}


async def build_team_schedule_rankings(
    db: AsyncSession,
    season: int,
    start_week: int,
    weeks_ahead: int = 6,
    scoring: str | None = "ppr",
) -> dict:
    """Every NFL team's schedule over the window, ranked per position.

    A team's score at a position is the average matchup value of the defenses
    it faces (e.g. PPR points those defenses allow to RBs), over the games it
    plays in the window — byes don't count against it. Rank 1 = the easiest
    schedule for that position."""
    await ensure_schedule(db, season)
    stats_season = await latest_stats_season(db) or season
    ranks = await matchup_ranks(db, season, stats_season, scoring)

    weeks = _window_weeks(start_week, weeks_ahead)
    by_team_week = await _games_by_team_week(db, season, weeks)
    teams = sorted(
        {
            t
            for row in (
                await db.execute(
                    select(NflSchedule.home_team, NflSchedule.away_team).where(
                        NflSchedule.season == season
                    )
                )
            ).all()
            for t in row
        }
    )

    positions: dict[str, list[dict]] = {}
    for position in STRENGTH_POSITIONS:
        entries = []
        for team in teams:
            cells, values, opp_ranks = [], [], []
            for w in weeks:
                game = by_team_week.get((team, w))
                info = ranks.get((game["opponent"], position), {}) if game else {}
                cells.append(_cell(w, game, info))
                if info.get("pts_allowed_avg") is not None:
                    values.append(info["pts_allowed_avg"])
                    opp_ranks.append(info["rank"])
            entries.append(
                {
                    "team": team,
                    "avg_value": round(sum(values) / len(values), 1) if values else None,
                    "avg_opp_rank": round(sum(opp_ranks) / len(opp_ranks), 1) if opp_ranks else None,
                    "games": sum(1 for c in cells if c["opponent"]),
                    "cells": cells,
                }
            )
        # Easiest first; teams with no rated games sink to the bottom.
        entries.sort(key=lambda e: (e["avg_value"] is None, -(e["avg_value"] or 0)))
        for i, e in enumerate(entries, start=1):
            e["rank"] = i if e["avg_value"] is not None else None
        positions[position] = entries

    return {"weeks": weeks, "stats_season": stats_season, "positions": positions}

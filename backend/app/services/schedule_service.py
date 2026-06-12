"""NFL schedule sync + defense-vs-position strength, powering the
schedule-strength heatmap."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import NflSchedule, Player, PlayerStatsWeekly

logger = logging.getLogger(__name__)

SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard"
# ESPN abbreviations that differ from ours
ESPN_ABBR_FIX = {"WSH": "WAS"}


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


async def defense_vs_position_ranks(db: AsyncSession, season: int) -> dict[tuple[str, str], dict]:
    """(team, position) → {rank, pts_allowed_avg}. Rank 1 = allows the MOST
    fantasy points to that position (i.e. the easiest matchup)."""
    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.opponent,
                Player.position,
                func.sum(PlayerStatsWeekly.fantasy_points_ppr).label("total"),
                func.count(func.distinct(PlayerStatsWeekly.week)).label("weeks"),
            )
            .join(Player, Player.id == PlayerStatsWeekly.player_id)
            .where(
                PlayerStatsWeekly.season == season,
                PlayerStatsWeekly.opponent.is_not(None),
                Player.position.in_(["QB", "RB", "WR", "TE"]),
            )
            .group_by(PlayerStatsWeekly.opponent, Player.position)
        )
    ).all()

    by_position: dict[str, list[tuple[str, float]]] = {}
    for opponent, position, total, weeks in rows:
        if not weeks:
            continue
        avg = float(total or 0) / int(weeks)
        by_position.setdefault(position, []).append((opponent, avg))

    out: dict[tuple[str, str], dict] = {}
    for position, entries in by_position.items():
        entries.sort(key=lambda e: -e[1])  # most points allowed first
        for rank, (team, avg) in enumerate(entries, start=1):
            out[(team, position)] = {"rank": rank, "pts_allowed_avg": round(avg, 1)}
    return out


async def build_schedule_strength(
    db: AsyncSession,
    season: int,
    start_week: int,
    player_ids: list[str],
    weeks_ahead: int = 6,
) -> dict:
    """Heatmap payload: each roster player × upcoming weeks with opponent +
    matchup difficulty rank."""
    # Ensure the schedule is loaded (lazy one-time sync)
    have = (
        await db.execute(
            select(func.count()).select_from(NflSchedule).where(NflSchedule.season == season)
        )
    ).scalar_one()
    if not have:
        await sync_schedule(db, season)

    stats_season = await latest_stats_season(db) or season
    ranks = await defense_vs_position_ranks(db, stats_season)

    weeks = [w for w in range(start_week, min(start_week + weeks_ahead, 19))]
    games = (
        await db.execute(
            select(NflSchedule).where(
                NflSchedule.season == season, NflSchedule.week.in_(weeks)
            )
        )
    ).scalars().all()
    by_team_week: dict[tuple[str, int], dict] = {}
    for g in games:
        by_team_week[(g.home_team, g.week)] = {"opponent": g.away_team, "home": True}
        by_team_week[(g.away_team, g.week)] = {"opponent": g.home_team, "home": False}

    players = (
        await db.execute(select(Player).where(Player.id.in_(player_ids)))
    ).scalars().all() if player_ids else []

    out_players = []
    for p in players:
        cells = []
        for w in weeks:
            game = by_team_week.get((p.team, w)) if p.team else None
            if game is None:
                cells.append({"week": w, "opponent": None, "rank": None})
                continue
            rank_info = ranks.get((game["opponent"], p.position or ""), {})
            cells.append(
                {
                    "week": w,
                    "opponent": game["opponent"],
                    "home": game["home"],
                    "rank": rank_info.get("rank"),
                    "pts_allowed_avg": rank_info.get("pts_allowed_avg"),
                }
            )
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

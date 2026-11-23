"""Player outlook over a window of weeks (the fantasy playoffs by default):
how good a player is, crossed with how hard his schedule is.

A great player with a brutal schedule can still finish below a good player
with a soft one. Each game in the window is projected as

    PLAYER_WEIGHT  × what the player does (his recency-weighted scoring rate,
                     or — against a tough or soft defense — his own record
                     against defenses like that this season, shrunk toward
                     his rate when the sample is small)
  + MATCHUP_WEIGHT × what the matchup says (his rate scaled by how many
                     points this opponent allows to his position vs average)

and players are ranked by the total. K and DEF use the kicker and DST models
(own team quality plus the opponent)."""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerStatsWeekly
from app.services.opportunity_service import _is_absent
from app.services.schedule_service import (
    REGULAR_SEASON_MAX_WEEK,
    _games_by_team_week,
    _window_weeks,
    defense_vs_position_ranks,
    ensure_schedule,
    latest_stats_season,
    matchup_ranks,
    points_column,
)
from app.utils.constants import STADIUMS

SKILL_POSITIONS = ("QB", "RB", "WR", "TE")
# Like the weekly projection: this season counts fully and its last
# RECENT_WINDOW weeks double. Last season starts at half weight but fades out
# as this season's sample grows (gone at PRIOR_SEASON_FADE_GAMES), so a
# second-year player who broke out isn't held back by his rookie year.
RECENT_WINDOW = 4
RECENT_WEIGHT = 2.0
PRIOR_SEASON_WEIGHT = 0.5
PRIOR_SEASON_FADE_GAMES = 8
MIN_GAMES = 3
# How much of a game's projection comes from the player vs the matchup.
PLAYER_WEIGHT = 0.75
MATCHUP_WEIGHT = 0.25
# Defense tiers by points allowed to the position (rank 1 = allows the most):
# 1-11 soft, 12-21 middle, 22-32 tough.
SOFT_MAX_RANK = 11
TOUGH_MIN_RANK = 22
# A player's record against a tier is blended with this many games' worth of
# his overall rate, so two big games against good defenses can't swing it.
TIER_SHRINK_GAMES = 3.0
# Out for the long haul — not worth ranking for the playoffs.
LONG_TERM_OUT = {"ir", "pup", "na", "dnr", "sus", "suspended", "cov"}


def _long_term_out(status: str | None) -> bool:
    s = (status or "").strip().lower()
    return s in LONG_TERM_OUT or "injured reserve" in s


def _tier(rank: int | None) -> str | None:
    if rank is None:
        return None
    if rank <= SOFT_MAX_RANK:
        return "soft"
    if rank >= TOUGH_MIN_RANK:
        return "tough"
    return None


def _rank(entries: list[dict], key: str, out_key: str) -> None:
    for i, e in enumerate(sorted(entries, key=lambda e: -e[key]), start=1):
        e[out_key] = i


async def _skill_outlook(
    db: AsyncSession,
    stats_season: int,
    scoring: str | None,
    weeks: list[int],
    games: dict[tuple[str, int], dict],
) -> dict[str, list[dict]]:
    pts_col = points_column(scoring)
    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.week,
                PlayerStatsWeekly.opponent,
                pts_col.label("pts"),
            )
            .join(Player, Player.id == PlayerStatsWeekly.player_id)
            .where(
                PlayerStatsWeekly.season >= stats_season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                pts_col.is_not(None),
                Player.position.in_(SKILL_POSITIONS),
                Player.team.is_not(None),
            )
        )
    ).all()
    this_season_weeks = [r.week for r in rows if r.season == stats_season]
    recent_cutoff = (max(this_season_weeks) if this_season_weeks else 18) - RECENT_WINDOW

    played_this_season: dict[str, int] = defaultdict(int)
    for r in rows:
        if r.season == stats_season:
            played_this_season[r.player_id] += 1

    samples: dict[str, list[tuple[float, float]]] = defaultdict(list)
    # This season's games, by opponent: (opponent, pts) — for tier splits.
    season_games: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for r in rows:
        if r.season == stats_season:
            w = RECENT_WEIGHT if r.week > recent_cutoff else 1.0
            if r.opponent:
                season_games[r.player_id].append((r.opponent, float(r.pts)))
        else:
            fade = 1 - played_this_season[r.player_id] / PRIOR_SEASON_FADE_GAMES
            w = PRIOR_SEASON_WEIGHT * max(0.0, fade)
            if w <= 0:
                continue
        samples[r.player_id].append((float(r.pts), w))

    candidates = [
        pid
        for pid, s in samples.items()
        if played_this_season[pid] and (len(s) >= MIN_GAMES)
    ]
    players = (
        (await db.execute(select(Player).where(Player.id.in_(candidates)))).scalars().all()
        if candidates
        else []
    )

    dvp = await defense_vs_position_ranks(db, stats_season, scoring or "ppr")
    league_avg: dict[str, float] = {}
    for pos in SKILL_POSITIONS:
        vals = [v["pts_allowed_avg"] for (_, p), v in dvp.items() if p == pos]
        league_avg[pos] = sum(vals) / len(vals) if vals else 0.0

    by_pos: dict[str, list[dict]] = {pos: [] for pos in SKILL_POSITIONS}
    for p in players:
        if p.position not in by_pos or _long_term_out(p.injury_status):
            continue
        s = samples[p.id]
        base = sum(pts * w for pts, w in s) / sum(w for _, w in s)
        avg = league_avg.get(p.position) or 0.0

        # His own record against soft and tough defenses this season.
        tier_pts: dict[str, list[float]] = {"soft": [], "tough": []}
        for opp, pts in season_games.get(p.id, []):
            tier = _tier((dvp.get((opp, p.position)) or {}).get("rank"))
            if tier:
                tier_pts[tier].append(pts)
        tier_rate = {
            t: (sum(v) + TIER_SHRINK_GAMES * base) / (len(v) + TIER_SHRINK_GAMES)
            for t, v in tier_pts.items()
        }

        cells = []
        for wk in weeks:
            game = games.get((p.team, wk))
            if game is None:
                cells.append({"week": wk, "opponent": None, "rank": None, "proj": 0.0})
                continue
            info = dvp.get((game["opponent"], p.position))
            tier = _tier(info["rank"] if info else None)
            player_part = tier_rate[tier] if tier else base
            matchup_part = base * info["pts_allowed_avg"] / avg if info and avg else base
            proj = PLAYER_WEIGHT * player_part + MATCHUP_WEIGHT * matchup_part
            cells.append(
                {
                    "week": wk,
                    "opponent": game["opponent"],
                    "home": game["home"],
                    "rank": info["rank"] if info else None,
                    "proj": round(max(0.0, proj), 1),
                }
            )
        entry = _entry(p.id, p.full_name, p.team, p.injury_status, base, cells)
        tough = tier_pts["tough"]
        entry["vs_tough_ppg"] = round(sum(tough) / len(tough), 1) if tough else None
        entry["vs_tough_games"] = len(tough)
        by_pos[p.position].append(entry)
    return by_pos


def _entry(pid, name, team, injury, base, cells) -> dict:
    games = [c for c in cells if c["opponent"]]
    total = sum(c["proj"] for c in cells)
    return {
        "id": pid,
        "name": name,
        "team": team,
        "injury_status": injury,
        "base_ppg": round(base, 1),
        "proj_ppg": round(total / len(games), 1) if games else 0.0,
        "proj_total": round(total, 1),
        "games": len(games),
        "cells": cells,
    }


async def _team_position_outlook(
    db: AsyncSession,
    season: int,
    stats_season: int,
    weeks: list[int],
    games: dict[tuple[str, int], dict],
) -> dict[str, list[dict]]:
    """K and DEF: the kicker / DST model for each team, every week."""
    from app.services.projection_service import _team_form, dst_model, kicker_model

    form = await _team_form(db, season)
    if not form:
        return {"K": [], "DEF": []}
    ranks = await matchup_ranks(db, season, stats_season)

    team_players = (
        await db.execute(
            select(Player).where(Player.position.in_(("K", "DEF")), Player.team.is_not(None))
        )
    ).scalars().all()
    # A team carries one real kicker; pick the one who's been playing.
    k_games = dict(
        (
            await db.execute(
                select(PlayerStatsWeekly.player_id, func.count())
                .where(PlayerStatsWeekly.season == stats_season)
                .group_by(PlayerStatsWeekly.player_id)
            )
        ).all()
    )
    kicker: dict[str, Player] = {}
    dst: dict[str, Player] = {}
    for p in team_players:
        if p.position == "DEF":
            dst[p.team] = p
        elif not _is_absent(p.injury_status):
            cur = kicker.get(p.team)
            if cur is None or k_games.get(p.id, 0) > k_games.get(cur.id, 0):
                kicker[p.team] = p

    out: dict[str, list[dict]] = {"K": [], "DEF": []}
    for position, by_team in (("K", kicker), ("DEF", dst)):
        for team, p in by_team.items():
            own = form.get(team)
            if own is None:
                continue
            if position == "K":
                base = kicker_model(own["off_ppg"], None, 0.0, None, False, None)["model"]
            else:
                base = dst_model(None, own["def_pa_pg"], None, own["def_ints_pg"], 0.0, None, None)["model"]
            cells = []
            for wk in weeks:
                game = games.get((team, wk))
                if game is None:
                    cells.append({"week": wk, "opponent": None, "rank": None, "proj": 0.0})
                    continue
                opp = form.get(game["opponent"]) or {}
                if position == "K":
                    home_team = team if game["home"] else game["opponent"]
                    dome = bool(STADIUMS.get(home_team, {}).get("dome"))
                    proj = kicker_model(own["off_ppg"], opp.get("def_pa_pg"), 0.0, None, dome, None)["model"]
                else:
                    proj = dst_model(
                        opp.get("off_ppg"), own["def_pa_pg"], opp.get("off_ints_pg"),
                        own["def_ints_pg"], 0.0, None, None,
                    )["model"]
                info = ranks.get((game["opponent"], position), {})
                cells.append(
                    {
                        "week": wk,
                        "opponent": game["opponent"],
                        "home": game["home"],
                        "rank": info.get("rank"),
                        "proj": round(proj, 1),
                    }
                )
            out[position].append(_entry(p.id, p.full_name, team, p.injury_status, base, cells))
    return out


async def build_player_outlook(
    db: AsyncSession,
    season: int,
    start_week: int,
    weeks_ahead: int = 3,
    scoring: str | None = "ppr",
) -> dict:
    """Per position, players ranked by projected points over the window.

    Each entry carries ``base_rank`` (where his scoring rate alone ranks him)
    next to ``rank`` (where he lands once the schedule is applied), so the
    page can show who the schedule lifts and who it sinks."""
    await ensure_schedule(db, season)
    stats_season = await latest_stats_season(db) or season
    weeks = _window_weeks(start_week, weeks_ahead)
    games = await _games_by_team_week(db, season, weeks)

    positions = await _skill_outlook(db, stats_season, scoring, weeks, games)
    positions.update(await _team_position_outlook(db, season, stats_season, weeks, games))

    for position, entries in positions.items():
        _rank(entries, "base_ppg", "base_rank")
        _rank(entries, "proj_total", "rank")
        entries.sort(key=lambda e: e["rank"])
    return {"weeks": weeks, "stats_season": stats_season, "positions": positions}

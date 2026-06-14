"""Weekly point projection engine.

Projects PPR points for a player's next game by combining three signals:

1. Baseline — recency-weighted PPR points per game over the last two seasons
   (same blend the trade-value model uses: latest season ~2x the prior one,
   and the most recent 4 weeks double again).
2. Matchup — the opponent defense's points allowed to the player's position
   vs league average. A player only captures a share of the positional delta,
   scaled by how big a piece of his position's production he is.
3. Game environment — Vegas implied team total when odds are synced; a high
   team total lifts everyone in that offense, a low one drags them down.

Floor/ceiling come from the player's own week-to-week volatility (stdev),
so a boom/bust receiver shows a wide band while a target-hog shows a
narrow one. Confidence reflects sample size and volatility.
"""

import math
from collections import defaultdict

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import GameCondition, NflSchedule, Player, PlayerStatsWeekly
from app.services.external_proj_service import get_external_projections
from app.services.schedule_service import defense_vs_position_ranks

PRIOR_SEASON_WEIGHT = 0.5
RECENT_WINDOW = 4
REGULAR_SEASON_MAX_WEEK = 18
LEAGUE_AVG_TEAM_TOTAL = 22.5
VEGAS_PCT_PER_POINT = 0.02  # ±2% projection per implied point above/below avg
VEGAS_ADJ_CAP = 0.15
PROJECTABLE = {"QB", "RB", "WR", "TE"}

# Blend weight on Sleeper's weekly projection when available (rest = our model)
EXTERNAL_WEIGHT = 0.5
# Weather: only matters outdoors; small, position-aware nudges that decide
# otherwise-close calls (wind hurts passing, rain hurts catching).
WEATHER_WIND_FLOOR = 12  # mph
WEATHER_ADJ_CAP = 0.12


def _weather_adjust(position: str | None, base: float, gc: GameCondition | None) -> float:
    """Points adjustment from game-day weather (0 indoors / unknown)."""
    if gc is None or getattr(gc, "dome", False):
        return 0.0
    pct = 0.0
    wind = float(gc.wind_mph or 0)
    precip = float(gc.precipitation_pct or 0)
    if wind > WEATHER_WIND_FLOOR:
        over = wind - WEATHER_WIND_FLOOR
        if position in ("QB", "WR", "TE"):
            pct -= min(0.10, over * 0.012)  # passing game suffers
        elif position == "RB":
            pct += min(0.03, over * 0.004)  # script tilts to the run
    if precip >= 50:
        if position in ("QB", "WR", "TE"):
            pct -= 0.04
        elif position == "RB":
            pct += 0.02
    pct = max(-WEATHER_ADJ_CAP, min(0.05, pct))
    return base * pct


def _erf(x: float) -> float:
    """Abramowitz-Stegun approximation — avoids a scipy dependency."""
    sign = 1 if x >= 0 else -1
    x = abs(x)
    t = 1 / (1 + 0.3275911 * x)
    y = 1 - (
        ((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t
        + 0.254829592
    ) * t * math.exp(-x * x)
    return sign * y


def win_probability(team_a_total: float, team_a_var: float, team_b_total: float, team_b_var: float) -> float:
    """P(A > B) assuming independent normal team scores."""
    diff = team_a_total - team_b_total
    sigma = math.sqrt(max(team_a_var + team_b_var, 1e-6))
    return 0.5 * (1 + _erf(diff / (sigma * math.sqrt(2))))


async def compute_projections(
    db: AsyncSession, player_ids: list[str], season: int
) -> dict[str, dict]:
    """player_id → projection package. Players without enough data are omitted."""
    if not player_ids:
        return {}

    players = (
        (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars().all()
    )
    players = [p for p in players if p.position in PROJECTABLE]
    if not players:
        return {}
    ids = [p.id for p in players]

    latest_season = (
        await db.execute(select(func.max(PlayerStatsWeekly.season)))
    ).scalar()
    if latest_season is None:
        return {}

    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.week,
                PlayerStatsWeekly.fantasy_points_ppr,
            ).where(
                PlayerStatsWeekly.player_id.in_(ids),
                PlayerStatsWeekly.season >= latest_season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                PlayerStatsWeekly.fantasy_points_ppr.is_not(None),
            )
        )
    ).all()

    latest_weeks = [r.week for r in rows if r.season == latest_season]
    recent_cutoff = (max(latest_weeks) if latest_weeks else 18) - RECENT_WINDOW

    per_player: dict[str, list[tuple[float, float]]] = defaultdict(list)  # (pts, weight)
    for r in rows:
        if r.season == latest_season:
            w = 2.0 if r.week >= recent_cutoff else 1.0
        else:
            w = PRIOR_SEASON_WEIGHT
        per_player[r.player_id].append((float(r.fantasy_points_ppr), w))

    # Opponent + game environment lookups
    dvp = await defense_vs_position_ranks(db, int(latest_season))
    league_avg_by_pos: dict[str, float] = {}
    for (_, pos), v in dvp.items():
        league_avg_by_pos.setdefault(pos, 0.0)
    for pos in league_avg_by_pos:
        vals = [v["pts_allowed_avg"] for (_, p), v in dvp.items() if p == pos]
        league_avg_by_pos[pos] = sum(vals) / len(vals) if vals else 0.0

    teams = {p.team for p in players if p.team}
    next_opponent: dict[str, dict] = {}
    if teams:
        games = (
            await db.execute(
                select(NflSchedule)
                .where(
                    NflSchedule.season == season,
                    or_(
                        NflSchedule.home_team.in_(teams),
                        NflSchedule.away_team.in_(teams),
                    ),
                )
                .order_by(NflSchedule.week.asc())
            )
        ).scalars().all()
        for g in games:
            for team, opp, home in (
                (g.home_team, g.away_team, True),
                (g.away_team, g.home_team, False),
            ):
                if team in teams and team not in next_opponent:
                    next_opponent[team] = {"opponent": opp, "week": g.week, "home": home}

        conditions = (
            await db.execute(
                select(GameCondition).where(
                    GameCondition.season == season,
                    or_(
                        GameCondition.home_team.in_(teams),
                        GameCondition.away_team.in_(teams),
                    ),
                )
            )
        ).scalars().all()
        implied: dict[str, float] = {}
        gc_by_team_week: dict[tuple[str, int], GameCondition] = {}
        for gc in conditions:
            if gc.implied_total_home is not None:
                implied[gc.home_team] = float(gc.implied_total_home)
            if gc.implied_total_away is not None:
                implied[gc.away_team] = float(gc.implied_total_away)
            gc_by_team_week[(gc.home_team, gc.week)] = gc
            gc_by_team_week[(gc.away_team, gc.week)] = gc
    else:
        implied = {}
        gc_by_team_week = {}

    # Sleeper weekly projections for the upcoming slate, to blend with our model
    upcoming_weeks = [g["week"] for g in next_opponent.values()]
    target_week = min(upcoming_weeks) if upcoming_weeks else None
    external = (
        await get_external_projections(season, target_week) if target_week else {}
    )

    out: dict[str, dict] = {}
    for p in players:
        samples = per_player.get(p.id, [])
        if len(samples) < 3:
            continue
        wsum = sum(w for _, w in samples)
        base = sum(pts * w for pts, w in samples) / wsum
        variance = sum(w * (pts - base) ** 2 for pts, w in samples) / wsum
        sigma = math.sqrt(variance)

        matchup_adj = 0.0
        opponent = None
        game = next_opponent.get(p.team or "")
        if game and p.position:
            opponent = game["opponent"]
            info = dvp.get((opponent, p.position))
            league_avg = league_avg_by_pos.get(p.position) or 0.0
            if info and league_avg > 0:
                # Player's share of his position's typical production caps how
                # much of the defensive delta he can personally capture
                share = min(base / league_avg, 1.0)
                matchup_adj = (info["pts_allowed_avg"] - league_avg) * share * 0.5

        vegas_adj = 0.0
        if p.team in implied:
            pct = (implied[p.team] - LEAGUE_AVG_TEAM_TOTAL) * VEGAS_PCT_PER_POINT
            pct = max(-VEGAS_ADJ_CAP, min(VEGAS_ADJ_CAP, pct))
            vegas_adj = base * pct

        weather_adj = 0.0
        if game:
            weather_adj = _weather_adjust(
                p.position, base, gc_by_team_week.get((p.team, game["week"]))
            )

        model_proj = base + matchup_adj + vegas_adj + weather_adj
        ext = external.get(p.id)
        if ext is not None:
            # Blend our model with Sleeper's weekly projection
            projected = max(0.0, EXTERNAL_WEIGHT * ext + (1 - EXTERNAL_WEIGHT) * model_proj)
        else:
            projected = max(0.0, model_proj)
        games_played = len(samples)
        cv = sigma / base if base > 0 else 1.0
        confidence = (
            "high" if games_played >= 12 and cv < 0.5
            else "low" if games_played < 6 or cv > 0.85
            else "medium"
        )

        out[p.id] = {
            "projected": round(projected, 1),
            "floor": round(max(0.0, projected - 0.9 * sigma), 1),
            "ceiling": round(projected + 1.1 * sigma, 1),
            "confidence": confidence,
            "stdev": round(sigma, 1),
            "components": {
                "base_ppg": round(base, 1),
                "matchup_adj": round(matchup_adj, 1),
                "vegas_adj": round(vegas_adj, 1),
                "weather_adj": round(weather_adj, 1),
                "external_proj": round(ext, 1) if ext is not None else None,
                "opponent": opponent,
                "week": game["week"] if game else None,
                "home": game["home"] if game else None,
            },
        }
    return out

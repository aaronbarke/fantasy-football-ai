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
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DepthChartEntry, GameCondition, NflSchedule, Player, PlayerStatsWeekly
from app.services.defense_impact_service import defense_injury_pct
from app.services.external_proj_service import get_external_projections
from app.services.opportunity_service import (
    PASS_CATCHER_POSITIONS,
    _is_absent,
    compute_opportunity_shares,
)
from app.services.schedule_service import defense_vs_position_ranks

PRIOR_SEASON_WEIGHT = 0.5
RECENT_WINDOW = 4
REGULAR_SEASON_MAX_WEEK = 18
LEAGUE_AVG_TEAM_TOTAL = 22.5
VEGAS_PCT_PER_POINT = 0.02  # ±2% projection per implied point above/below avg
VEGAS_ADJ_CAP = 0.15
PROJECTABLE = {"QB", "RB", "WR", "TE"}

# Blend weight on Sleeper's weekly projection. It starts even with our model
# early in the week and ramps up toward kickoff, because Sleeper's number is the
# one that reflects late-breaking news — scratches, actives/inactives, a Friday
# practice designation. See ``sleeper_blend_weight``.
EXTERNAL_WEIGHT = 0.5  # early-week floor (our model / Sleeper split 50/50)
EXTERNAL_WEIGHT_LATE = 0.7  # game-day ceiling — lean on Sleeper's late signal
# Weather: only matters outdoors; small, position-aware nudges that decide
# otherwise-close calls (wind hurts passing, rain hurts catching).
WEATHER_WIND_FLOOR = 12  # mph
WEATHER_ADJ_CAP = 0.12

# Teammate-injury opportunity boost (see app.services.opportunity_service).
# opportunity_service works purely in target-share space; here we turn a share
# of vacated targets into points and cap it.
#
# PTS_PER_TARGET_SHARE: PPR points one full (100%) target share is worth per
# game. A team throws ~35 times a game for ~22 receptions / ~230 yards / ~1.6
# passing TDs, i.e. roughly 22 + 23 + 10 ≈ 55 PPR points shared across its
# pass-catchers. We use 45 (below that raw ceiling) because vacated targets are
# not absorbed 1:1 — some looks disappear with the player, some go to non-
# receivers — so this stays conservative.
PTS_PER_TARGET_SHARE = 45.0
# Boost cap: never more than this fraction of the player's own baseline, and
# never more than this many absolute points. One injury shouldn't manufacture an
# absurd projection.
OPP_BOOST_BASE_FRAC = 0.35
OPP_BOOST_ABS_CAP = 6.0

# Opponent defensive-injury adjustment (see app.services.defense_impact_service).
# That module returns a percentage bump; here we apply it to the baseline and
# cap it, conservatively: at most 12% of baseline or 3.0 absolute points, even
# if several game-wreckers are out.
DEF_INJ_PCT_CAP = 0.12
DEF_INJ_ABS_CAP = 3.0


def sleeper_blend_weight(now: datetime | None, kickoff: datetime | None) -> float:
    """Weight on Sleeper's projection in the blend, ramped toward kickoff.

    Sleeper's weekly number moves with late news, so we trust it more as the
    game nears. Bounded to ``[EXTERNAL_WEIGHT, EXTERNAL_WEIGHT_LATE]``.

    - With a known ``kickoff``: linear ramp over the final 72 hours — the floor
      at 3+ days out, the ceiling at kickoff. Healthy early-week projections
      barely move; the shift matters most Sunday morning.
    - Without a kickoff time: fall back to a day-of-week schedule (Tue/Wed early,
      creeping up Thu–Sat, full lean on Sun/Mon game days).
    """
    lo, hi = EXTERNAL_WEIGHT, EXTERNAL_WEIGHT_LATE
    if now is not None and kickoff is not None:
        hours_out = (kickoff - now).total_seconds() / 3600.0
        if hours_out >= 72:
            return lo
        if hours_out <= 0:
            return hi
        # 72h out → lo, 0h out → hi
        return hi - (hi - lo) * (hours_out / 72.0)

    ref = now or datetime.now(timezone.utc).replace(tzinfo=None)
    by_dow = {
        0: hi,          # Mon (MNF)
        1: lo,          # Tue
        2: lo,          # Wed
        3: lo + 0.05,   # Thu (TNF teams aside, mostly early)
        4: lo + 0.10,   # Fri
        5: lo + 0.15,   # Sat
        6: hi,          # Sun (main slate)
    }
    return max(lo, min(hi, by_dow.get(ref.weekday(), lo)))


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
                    next_opponent[team] = {
                        "opponent": opp,
                        "week": g.week,
                        "home": home,
                        "kickoff": g.game_time,
                    }

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

    # Teammate-injury opportunity: per team, work out how much target share an
    # officially-absent pass-catcher vacates and who absorbs it. We must look at
    # the FULL team, not just the requested player_ids, so query every
    # pass-catcher on the teams in play (with their recent target share).
    opp_shares = await _opportunity_shares(db, teams)

    # Opponent defensive-injury context: which opposing defenses have a key
    # starter out, plus each projected player's own slot/perimeter alignment.
    opponents = {g["opponent"] for g in next_opponent.values() if g.get("opponent")}
    def_out_by_opp, alignment = await _defense_injury_context(db, opponents, ids)

    # Naive UTC to match the DB's naive game_time for the kickoff ramp.
    now = datetime.now(timezone.utc).replace(tzinfo=None)

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
            # Blend our model with Sleeper's weekly projection, leaning harder on
            # Sleeper as kickoff nears (it reflects late-breaking news).
            w = sleeper_blend_weight(now, game["kickoff"] if game else None)
            projected = max(0.0, w * ext + (1 - w) * model_proj)
        else:
            projected = max(0.0, model_proj)

        # Teammate-injury opportunity boost — purely additive, and exactly 0.0
        # when no qualifying teammate is out, so healthy slates are unchanged.
        opportunity_adj = 0.0
        boost_reason = None
        opp = opp_shares.get(p.id)
        if opp:
            raw = opp["extra_share"] * PTS_PER_TARGET_SHARE
            cap = min(OPP_BOOST_BASE_FRAC * base, OPP_BOOST_ABS_CAP)
            opportunity_adj = round(min(raw, cap), 1)
            if opportunity_adj > 0:
                boost_reason = (
                    f"{opp['reason_prefix']} — +{opportunity_adj:.1f} from vacated targets"
                )
            else:
                opportunity_adj = 0.0
        if opportunity_adj:
            projected = max(0.0, projected + opportunity_adj)

        # Opponent defensive-injury adjustment — additive, and 0.0 when the
        # opposing defense is at full strength (so healthy slates are unchanged).
        defense_injury_adj = 0.0
        defense_reason = None
        if opponent and p.position:
            outs = def_out_by_opp.get(opponent, [])
            if outs:
                pct, reasons = defense_injury_pct(p.position, alignment.get(p.id), outs)
                pct = min(pct, DEF_INJ_PCT_CAP)
                defense_injury_adj = round(min(base * pct, DEF_INJ_ABS_CAP), 1)
                if defense_injury_adj > 0 and reasons:
                    # reasons are already "Name (Status)"; just append the total
                    defense_reason = (
                        f"vs {opponent} D — {', '.join(reasons)} → "
                        f"+{defense_injury_adj:.1f}"
                    )
                else:
                    defense_injury_adj = 0.0
        if defense_injury_adj:
            projected = max(0.0, projected + defense_injury_adj)

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
            "boost_reason": boost_reason,
            "defense_reason": defense_reason,
            "components": {
                "base_ppg": round(base, 1),
                "matchup_adj": round(matchup_adj, 1),
                "vegas_adj": round(vegas_adj, 1),
                "weather_adj": round(weather_adj, 1),
                "opportunity_adj": opportunity_adj,
                "defense_injury_adj": defense_injury_adj,
                "external_proj": round(ext, 1) if ext is not None else None,
                "opponent": opponent,
                "week": game["week"] if game else None,
                "home": game["home"] if game else None,
            },
        }
    return out


async def _opportunity_shares(db: AsyncSession, teams: set[str]) -> dict[str, dict]:
    """player_id → {"extra_share", "reason_prefix"} for every pass-catcher who
    inherits vacated targets from an officially-absent teammate. ``{}`` when no
    team has a qualifying absence.

    Loads the full pass-catcher pool for ``teams`` (not just the requested
    players) plus each player's recent-season average target share, then defers
    the redistribution to ``opportunity_service``.
    """
    if not teams:
        return {}

    catchers = (
        await db.execute(
            select(
                Player.id,
                Player.full_name,
                Player.position,
                Player.team,
                Player.injury_status,
                Player.depth_chart_order,
            ).where(
                Player.team.in_(teams),
                Player.position.in_(PASS_CATCHER_POSITIONS),
            )
        )
    ).all()
    if not catchers:
        return {}

    # Recent-season average target share per player (most recent season that has
    # target-share data), from the regular season only.
    ts_rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.target_share,
            ).where(
                PlayerStatsWeekly.player_id.in_([c.id for c in catchers]),
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                PlayerStatsWeekly.target_share.is_not(None),
            )
        )
    ).all()
    by_player: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in ts_rows:
        by_player[r.player_id][r.season].append(float(r.target_share))
    avg_share: dict[str, float] = {}
    for pid, by_season in by_player.items():
        season = max(by_season)  # most recent season with data
        vals = by_season[season]
        avg_share[pid] = sum(vals) / len(vals) if vals else 0.0

    by_team: dict[str, list[dict]] = defaultdict(list)
    for c in catchers:
        by_team[c.team].append(
            {
                "id": c.id,
                "name": c.full_name,
                "position": c.position,
                "target_share": avg_share.get(c.id, 0.0),
                "depth_chart_order": c.depth_chart_order,
                "injury_status": c.injury_status,
            }
        )

    out: dict[str, dict] = {}
    for team_catchers in by_team.values():
        out.update(compute_opportunity_shares(team_catchers))
    return out


async def _defense_injury_context(
    db: AsyncSession, opponents: set[str], player_ids: list[str]
) -> tuple[dict[str, list[dict]], dict[str, str | None]]:
    """Load, from the depth-chart snapshot, (1) each opponent's officially-out
    *starting* defenders and (2) each projected player's slot/perimeter
    alignment. Returns ``(out_by_opponent, alignment_by_player_id)``; empty when
    the depth-chart table hasn't been populated yet (fresh deploy → no bump)."""
    out_by_opp: dict[str, list[dict]] = defaultdict(list)
    if opponents:
        rows = (
            await db.execute(
                select(
                    DepthChartEntry.full_name,
                    DepthChartEntry.team,
                    DepthChartEntry.position,
                    DepthChartEntry.depth_chart_position,
                    DepthChartEntry.injury_status,
                ).where(
                    DepthChartEntry.team.in_(opponents),
                    DepthChartEntry.depth_chart_order == 1,  # starters only
                    DepthChartEntry.injury_status.is_not(None),
                )
            )
        ).all()
        for r in rows:
            if _is_absent(r.injury_status):  # Out/Doubtful/IR — never Questionable
                out_by_opp[r.team].append(
                    {
                        "name": r.full_name,
                        "position": r.position,
                        "slot": r.depth_chart_position,
                        "status": r.injury_status,
                    }
                )

    alignment: dict[str, str | None] = {}
    if player_ids:
        arows = (
            await db.execute(
                select(DepthChartEntry.id, DepthChartEntry.depth_chart_position).where(
                    DepthChartEntry.id.in_(player_ids)
                )
            )
        ).all()
        alignment = {r.id: r.depth_chart_position for r in arows}
    return out_by_opp, alignment

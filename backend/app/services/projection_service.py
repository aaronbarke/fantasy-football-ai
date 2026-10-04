"""Weekly point projection engine.

Projects fantasy points (in the league's scoring format) for a player's game in
the current NFL week by combining three signals:

1. Baseline — recency-weighted points per game over the last two seasons
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

Players who can't score this week — on bye, not on an NFL roster, or ruled
out — project to exactly 0 so no lineup or live total counts them.

How a skill player's number is put together:

    model     = base + matchup + vegas + weather + teammates_out + qb_change
    projected = s * sleeper + (1 - s) * model + opposing_defense_injuries

where ``s`` is Sleeper's share (0.5 early in the week, ramping to 0.7 at
kickoff). Teammate absences and a backup QB starting live inside ``model``
because Sleeper's weekly number already reflects that news — adding them on
top of the blend would count it twice. Every term is returned in
``components`` so the UI can show the math.
"""

import math
from collections import defaultdict
from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import DepthChartEntry, GameCondition, NflSchedule, Player, PlayerStatsWeekly
from app.services.defense_impact_service import defense_injury_pct
from app.services.external_proj_service import get_external_passing, get_external_projections
from app.services.opportunity_service import (
    PASS_CATCHER_POSITIONS,
    _is_absent,
    absence_freshness,
    compute_opportunity_shares,
    compute_rush_shares,
)
from app.services.schedule_service import (
    current_nfl_week,
    defense_vs_position_ranks,
    points_column,
)
from app.services.team_stats_service import get_team_results
from app.utils.constants import STADIUMS

PRIOR_SEASON_WEIGHT = 0.5
RECENT_WINDOW = 4
REGULAR_SEASON_MAX_WEEK = 18
LEAGUE_AVG_TEAM_TOTAL = 22.5
VEGAS_PCT_PER_POINT = 0.02  # ±2% projection per implied point above/below avg
VEGAS_ADJ_CAP = 0.15
PROJECTABLE = {"QB", "RB", "WR", "TE"}
# Fewer games than this and our own model has nothing stable to stand on.
MIN_SAMPLES = 3
# Rookies / early-season call-ups with too little history lean entirely on
# Sleeper's weekly number; this is the band width we give that number.
THIN_SAMPLE_CV = 0.45
# Kickers: projecting them individually is noise, so every healthy kicker with a
# game gets the league-average starting output and a typical week-to-week band.
K_BASELINE = 8.0
K_STDEV = 4.0

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
# Same idea for running backs: a team's backs get ~24 carries a game worth
# ~0.6 points each (yards + touchdowns), so a full share of the RB carries is
# ~14 points; vacated carries count at that rate.
PTS_PER_CARRY_SHARE = 14.0
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

# Backup QB starting. Our history for a team's pass-catchers was built with the
# usual starter throwing to them, so when he's out we scale that history down
# by how much worse the backup projects (Sleeper's weekly number for him vs the
# starter's points per start), at half strength — the targets still go
# somewhere — and capped. RBs feel it less. Like the teammate boost, this only
# moves our model's share; Sleeper's number already prices the QB change in.
QB_CHANGE_SCALE = 0.5
QB_CHANGE_CAP = 0.15
QB_CHANGE_DEFAULT = 0.08  # when the drop can't be sized (no backup projection)
QB_CHANGE_POSITION_WEIGHT = {"WR": 1.0, "TE": 1.0, "RB": 0.4}
QB_START_PASS_YARDS = 100  # a game with this many passing yards counts as a start


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


# --- Team defense (DST) and kicker models ------------------------------------
# A DST week is points allowed (scored in tiers) + sacks + takeaways + the odd
# return touchdown. Each is estimated from who's on the field:
#
# - Expected points allowed: the opponent offense's scoring and this defense's
#   points allowed per game (each vs league average, shrunk toward it on thin
#   samples), cut when the opponent's usual starting QB is out, and blended
#   with the Vegas implied total when there's a line.
# - Takeaways: interceptions this defense forces and the opponent offense
#   throws per game (shrunk), plus league-average fumble recoveries. A backup
#   QB throws more picks and takes more sacks.
#
# Every factor is reported as its own term — the change it makes against a
# league-average matchup — so the breakdown reads: league-average defense +
# opponent offense + defense quality + backup QB + Vegas + weather.
DST_BASELINE = 7.0  # league-average DST fantasy week
DST_MIN, DST_MAX = 2.0, 15.0
DST_STDEV_FRAC = 0.6  # DST scoring is boom/bust — a wide band
# Points-allowed tiers (Sleeper's defaults): (low, high, fantasy points)
DST_PA_TIERS = (
    (0, 0, 10.0), (1, 6, 7.0), (7, 13, 4.0), (14, 20, 1.0),
    (21, 27, 0.0), (28, 34, -1.0), (35, 999, -4.0),
)
DST_PA_SD = 9.5  # spread of actual points allowed around the expectation
AVG_SACKS = 2.4
AVG_INTS = 0.8
AVG_FUM_REC = 0.6
DST_TD_PER_TAKEAWAY = 0.1  # roughly one takeaway in ten goes back for six
# Team rates are blended with this many games of league average, and last
# season's games count this much against this season's.
TEAM_SHRINK_GAMES = 3.0
TEAM_PRIOR_SEASON_WEIGHT = 0.3
# Vegas' share of expected points when we also have the teams' history.
VEGAS_TEAM_WEIGHT = 0.6
# A backup QB starting against this defense: at the full QB-change discount,
# this many more interceptions and sacks (scaled down for smaller drops).
BACKUP_QB_INT_BOOST = 0.30
BACKUP_QB_SACK_BOOST = 0.15
# Kickers ride their team's expected scoring — ~0.12 fantasy points per point
# the team is expected to score above average. Domes help; wind and rain hurt.
K_POINTS_PER_TEAM_POINT = 0.12
K_DOME_BONUS = 0.3
K_WIND_PENALTY = 0.8
K_RAIN_PENALTY = 0.3
K_MIN = 2.0


def _pa_tier_points(pa: int) -> float:
    for lo, hi, pts in DST_PA_TIERS:
        if lo <= pa <= hi:
            return pts
    return DST_PA_TIERS[-1][2]


def _expected_pa_points(xpa: float) -> float:
    """Expected points-allowed tier score when actual points allowed scatter
    normally around ``xpa`` — smooth, unlike the step-shaped tiers."""
    total = norm = 0.0
    for pa in range(0, 71):
        w = math.exp(-0.5 * ((pa - max(0.0, xpa)) / DST_PA_SD) ** 2)
        total += w * _pa_tier_points(pa)
        norm += w
    return total / norm


def _dst_points(xpa: float, ints: float, sacks: float) -> float:
    takeaways = max(0.0, ints) + AVG_FUM_REC
    return (
        _expected_pa_points(xpa)
        + sacks
        + 2.0 * takeaways
        + 6.0 * DST_TD_PER_TAKEAWAY * takeaways
    )


def _sloppy(gc: GameCondition | None) -> bool:
    """High wind or likely rain at an outdoor stadium."""
    if gc is None or getattr(gc, "dome", False):
        return False
    return float(gc.wind_mph or 0) > 15 or float(gc.precipitation_pct or 0) >= 50


def dst_model(
    opp_off_ppg: float | None,
    def_pa_pg: float | None,
    opp_ints_pg: float | None,
    def_ints_pg: float | None,
    opp_qb_drop: float,
    opp_implied: float | None,
    gc: GameCondition | None,
) -> dict:
    """Our DST projection, decomposed. ``opp_qb_drop`` is the opponent's
    QB-change discount (0 when their starter plays).

    Returns ``{model, terms: [(label, pts)], xpa, label}`` where model =
    DST_BASELINE + sum(terms), each term the change from adding that factor to
    a league-average matchup."""
    avg = LEAGUE_AVG_TEAM_TOTAL
    has_history = opp_off_ppg is not None or def_pa_pg is not None
    qb_scale = opp_qb_drop / QB_CHANGE_CAP if QB_CHANGE_CAP else 0.0

    def evaluate(off, pa, oi, di, qb, vegas, weather) -> tuple[float, float]:
        off_v = avg if off is None else off
        pa_v = avg if pa is None else pa
        xpa = avg + (off_v - avg) + (pa_v - avg) - off_v * qb
        if vegas and opp_implied is not None:
            w = VEGAS_TEAM_WEIGHT if has_history else 1.0
            xpa = w * opp_implied + (1 - w) * xpa
        oi_v = AVG_INTS if oi is None else oi
        di_v = AVG_INTS if di is None else di
        ints = max(0.1, AVG_INTS + (oi_v - AVG_INTS) + (di_v - AVG_INTS))
        scale = qb_scale if qb else 0.0
        ints *= 1 + BACKUP_QB_INT_BOOST * scale
        sacks = AVG_SACKS * (1 + BACKUP_QB_SACK_BOOST * scale)
        return _dst_points(xpa, ints, sacks) + (1.0 if weather else 0.0), xpa

    weather = _sloppy(gc)
    steps = [
        ("Opponent offense", (opp_off_ppg, None, opp_ints_pg, None, 0.0, False, False)),
        ("Defense quality", (opp_off_ppg, def_pa_pg, opp_ints_pg, def_ints_pg, 0.0, False, False)),
        ("Backup QB", (opp_off_ppg, def_pa_pg, opp_ints_pg, def_ints_pg, opp_qb_drop, False, False)),
        ("Vegas line", (opp_off_ppg, def_pa_pg, opp_ints_pg, def_ints_pg, opp_qb_drop, True, False)),
        ("Weather", (opp_off_ppg, def_pa_pg, opp_ints_pg, def_ints_pg, opp_qb_drop, True, weather)),
    ]
    prev, xpa = evaluate(None, None, None, None, 0.0, False, False)
    start = prev
    terms: list[tuple[str, float]] = []
    for label, args in steps:
        pts, xpa = evaluate(*args)
        terms.append((label, pts - prev))
        prev = pts
    model = max(DST_MIN, min(DST_MAX, DST_BASELINE + (prev - start)))

    if not has_history and opp_implied is None:
        label = "unknown"
    elif xpa <= avg - 4:
        label = "great"
    elif xpa >= avg + 4:
        label = "tough"
    else:
        label = "neutral"
    return {"model": model, "terms": terms, "xpa": xpa, "label": label}


def _dst_projection(
    opp_implied: float | None, gc: GameCondition | None
) -> tuple[float, float, str]:
    """(projected points, weather bump, matchup label) from the Vegas line
    alone — the DST model with no team history."""
    r = dst_model(None, None, None, None, 0.0, opp_implied, gc)
    weather = next(v for k, v in r["terms"] if k == "Weather")
    return r["model"], weather, r["label"]


def kicker_model(
    team_off_ppg: float | None,
    opp_def_pa_pg: float | None,
    own_qb_drop: float,
    team_implied: float | None,
    dome: bool,
    gc: GameCondition | None,
) -> dict:
    """Our kicker projection: league-average kicker + expected team scoring +
    dome/weather. Returns ``{model, terms, xpf}``."""
    avg = LEAGUE_AVG_TEAM_TOTAL
    xpf = None
    if team_off_ppg is not None or opp_def_pa_pg is not None:
        off_v = avg if team_off_ppg is None else team_off_ppg
        pa_v = avg if opp_def_pa_pg is None else opp_def_pa_pg
        xpf = avg + (off_v - avg) + (pa_v - avg) - off_v * own_qb_drop
    if team_implied is not None:
        xpf = (
            VEGAS_TEAM_WEIGHT * team_implied + (1 - VEGAS_TEAM_WEIGHT) * xpf
            if xpf is not None
            else team_implied
        )
    scoring = K_POINTS_PER_TEAM_POINT * (xpf - avg) if xpf is not None else 0.0
    venue = 0.0
    if dome:
        venue = K_DOME_BONUS
    elif gc is not None:
        if float(gc.wind_mph or 0) > 15:
            venue -= K_WIND_PENALTY
        if float(gc.precipitation_pct or 0) >= 50:
            venue -= K_RAIN_PENALTY
    terms = [("Expected team scoring", scoring), ("Dome / weather", venue)]
    return {"model": max(K_MIN, K_BASELINE + scoring + venue), "terms": terms, "xpf": xpf}


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


def _inactive_package(reason: str, week: int | None, base_ppg: float | None = None) -> dict:
    """A player who can't score this week (bye / no NFL team): a hard zero."""
    return {
        "projected": 0.0,
        "floor": 0.0,
        "ceiling": 0.0,
        "confidence": "high",
        "stdev": 0.0,
        "bye": reason == "bye",
        "inactive_reason": reason,
        "boost_reason": None,
        "qb_reason": None,
        "defense_reason": None,
        "components": {
            "base_ppg": round(base_ppg, 1) if base_ppg is not None else None,
            "matchup_adj": 0.0,
            "vegas_adj": 0.0,
            "weather_adj": 0.0,
            "opportunity_adj": 0.0,
            "qb_adj": 0.0,
            "model_proj": None,
            "defense_injury_adj": 0.0,
            "external_proj": None,
            "blend_weight": None,
            "opponent": None,
            "week": week,
            "home": None,
        },
    }


async def compute_projections(
    db: AsyncSession, player_ids: list[str], season: int, scoring: str = "ppr"
) -> dict[str, dict]:
    """player_id → projection package for the current NFL week, in the league's
    scoring format. Players without enough data are omitted."""
    if not player_ids:
        return {}

    all_players = (
        (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars().all()
    )
    players = [p for p in all_players if p.position in PROJECTABLE]
    # Team defenses and kickers are projected separately (no box-score model),
    # so keep them aside rather than dropping them.
    dst_players = [p for p in all_players if p.position == "DEF"]
    kickers = [p for p in all_players if p.position == "K"]
    if not players and not dst_players and not kickers:
        return {}
    ids = [p.id for p in players]

    latest_season = (
        await db.execute(select(func.max(PlayerStatsWeekly.season)))
    ).scalar()

    points_col = points_column(scoring)
    rows = []
    if ids and latest_season is not None:
        rows = (
            await db.execute(
                select(
                    PlayerStatsWeekly.player_id,
                    PlayerStatsWeekly.season,
                    PlayerStatsWeekly.week,
                    points_col.label("pts"),
                ).where(
                    PlayerStatsWeekly.player_id.in_(ids),
                    PlayerStatsWeekly.season >= latest_season - 1,
                    PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                    points_col.is_not(None),
                )
            )
        ).all()

    latest_weeks = [r.week for r in rows if r.season == latest_season]
    recent_cutoff = (max(latest_weeks) if latest_weeks else 18) - RECENT_WINDOW

    per_player: dict[str, list[tuple[float, float]]] = defaultdict(list)  # (pts, weight)
    for r in rows:
        if r.season == latest_season:
            w = 2.0 if r.week > recent_cutoff else 1.0
        else:
            w = PRIOR_SEASON_WEIGHT
        per_player[r.player_id].append((float(r.pts), w))

    # Opponent + game environment lookups
    dvp = (
        await defense_vs_position_ranks(db, int(latest_season), scoring)
        if latest_season is not None
        else {}
    )
    league_avg_by_pos: dict[str, float] = {}
    for (_, pos), v in dvp.items():
        league_avg_by_pos.setdefault(pos, 0.0)
    for pos in league_avg_by_pos:
        vals = [v["pts_allowed_avg"] for (_, p), v in dvp.items() if p == pos]
        league_avg_by_pos[pos] = sum(vals) / len(vals) if vals else 0.0

    # Naive UTC to match the DB's naive game_time.
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    teams = {p.team for p in all_players if p.team}
    # The active NFL week comes from the WHOLE schedule, not just these teams'
    # games — otherwise a team on bye would skip straight to next week.
    current_week = await current_nfl_week(db, season, now)
    next_opponent: dict[str, dict] = {}
    bye_teams: set[str] = set()
    implied: dict[tuple[str, int], float] = {}
    gc_by_team_week: dict[tuple[str, int], GameCondition] = {}
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
            # This week's game only. With no kickoff times at all we can't tell
            # which week is live, so fall back to each team's first game.
            if current_week is not None and g.week != current_week:
                continue
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
        if current_week is not None:
            # Every team plays in a loaded week except the ones on bye.
            bye_teams = {t for t in teams if t not in next_opponent}

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
        # Keyed by (team, week): a team total is only meaningful for the game
        # it was set for, never last week's line.
        for gc in conditions:
            if gc.implied_total_home is not None:
                implied[(gc.home_team, gc.week)] = float(gc.implied_total_home)
            if gc.implied_total_away is not None:
                implied[(gc.away_team, gc.week)] = float(gc.implied_total_away)
            gc_by_team_week[(gc.home_team, gc.week)] = gc
            gc_by_team_week[(gc.away_team, gc.week)] = gc

    def _unavailable(p: Player) -> str | None:
        """Why a player can't score this week, if he can't."""
        if not p.team:
            # Only trust "no team" once we know the schedule — a bare player
            # table (fresh install) shouldn't zero everybody.
            return "no_team" if current_week is not None else None
        if p.team in bye_teams:
            return "bye"
        return None

    # Sleeper weekly projections for this week's slate, to blend with our model
    target_week = current_week
    if target_week is None:
        upcoming_weeks = [g["week"] for g in next_opponent.values()]
        target_week = min(upcoming_weeks) if upcoming_weeks else None
    external = (
        await get_external_projections(season, target_week, scoring) if target_week else {}
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

    # Teams whose usual starting QB is out this week, and how much to discount
    # their pass-catchers' history for it.
    passing = await get_external_passing(season, target_week) if target_week else {}
    qb_change = await _qb_change_context(
        db, teams | opponents, latest_season, external, passing
    )
    # Team scoring form (points for/against, interceptions) — only the DEF and
    # kicker models use it, so skip the fetch for skill-player-only requests.
    team_form = (
        await _team_form(db, season) if (dst_players or kickers) else {}
    )

    out: dict[str, dict] = {}
    for p in players:
        samples = per_player.get(p.id, [])
        game = next_opponent.get(p.team or "")
        ext = external.get(p.id)

        reason = _unavailable(p)
        if reason:
            base_ppg = (
                sum(pts * w for pts, w in samples) / sum(w for _, w in samples)
                if samples
                else None
            )
            out[p.id] = _inactive_package(reason, current_week, base_ppg)
            continue

        if len(samples) < MIN_SAMPLES:
            # Too little history for our model (a rookie, a new starter early in
            # the season). Sleeper still projects him, so use that instead of
            # dropping him — otherwise the optimizer benches him by default and
            # his team's projected total silently loses his points.
            if ext is None:
                continue
            projected = max(0.0, float(ext))
            sigma = max(projected * THIN_SAMPLE_CV, 1.0)
            confidence = "low"
            if _is_absent(p.injury_status):
                projected, sigma, confidence = 0.0, 0.0, "high"
            thin_base = (
                sum(pts for pts, _ in samples) / len(samples) if samples else None
            )
            out[p.id] = {
                "projected": round(projected, 1),
                "floor": round(max(0.0, projected - 0.9 * sigma), 1),
                "ceiling": round(projected + 1.1 * sigma, 1),
                "confidence": confidence,
                "stdev": round(sigma, 1),
                "bye": False,
                "inactive_reason": None,
                "boost_reason": None,
                "qb_reason": None,
                "defense_reason": None,
                "components": {
                    "base_ppg": round(thin_base, 1) if thin_base is not None else None,
                    "matchup_adj": 0.0,
                    "vegas_adj": 0.0,
                    "weather_adj": 0.0,
                    "opportunity_adj": 0.0,
                    "qb_adj": 0.0,
                    "model_proj": None,
                    "defense_injury_adj": 0.0,
                    "external_proj": round(float(ext), 1),
                    "blend_weight": 1.0,
                    "opponent": game["opponent"] if game else None,
                    "week": game["week"] if game else None,
                    "home": game["home"] if game else None,
                },
            }
            continue

        wsum = sum(w for _, w in samples)
        base = sum(pts * w for pts, w in samples) / wsum
        variance = sum(w * (pts - base) ** 2 for pts, w in samples) / wsum
        sigma = math.sqrt(variance)

        matchup_adj = 0.0
        opponent = None
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
        team_total = implied.get((p.team, game["week"])) if game and p.team else None
        if team_total is not None:
            pct = (team_total - LEAGUE_AVG_TEAM_TOTAL) * VEGAS_PCT_PER_POINT
            pct = max(-VEGAS_ADJ_CAP, min(VEGAS_ADJ_CAP, pct))
            vegas_adj = base * pct

        weather_adj = 0.0
        if game:
            weather_adj = _weather_adjust(
                p.position, base, gc_by_team_week.get((p.team, game["week"]))
            )

        # Late-news adjustments to OUR model: a teammate's absence (vacated
        # targets) and a backup QB starting. Both are exactly 0.0 on a healthy
        # slate. They go inside the model, not on top of the blend: Sleeper's
        # weekly number already reflects the same news (it zeroes the injured
        # player and re-projects his teammates), so adding them after the blend
        # counted it twice.
        opportunity_adj = 0.0
        opp = opp_shares.get(p.id)
        if opp:
            cap = min(OPP_BOOST_BASE_FRAC * base, OPP_BOOST_ABS_CAP)
            opportunity_adj = max(0.0, min(opp["extra_points"], cap))

        qb_adj = 0.0
        qb_note = qb_change.get(p.team or "")
        if qb_note and p.position in QB_CHANGE_POSITION_WEIGHT:
            qb_adj = -base * qb_note["pct"] * QB_CHANGE_POSITION_WEIGHT[p.position]

        model_proj = base + matchup_adj + vegas_adj + weather_adj + opportunity_adj + qb_adj
        blend_weight = None
        if ext is not None:
            # Blend our model with Sleeper's weekly projection, leaning harder on
            # Sleeper as kickoff nears (it reflects late-breaking news).
            blend_weight = sleeper_blend_weight(now, game["kickoff"] if game else None)
            projected = max(0.0, blend_weight * ext + (1 - blend_weight) * model_proj)
        else:
            projected = max(0.0, model_proj)

        # Reasons quote what each adjustment actually did to the final number
        # (its share after the blend), not the raw model term.
        model_share = 1.0 - (blend_weight or 0.0)
        opp_effect = round(opportunity_adj * model_share, 1)
        qb_effect = round(qb_adj * model_share, 1)
        boost_reason = (
            f"{opp['reason_prefix']} — +{opp_effect:.1f} from vacated {opp['kind']}"
            if opp and opp_effect > 0
            else None
        )
        qb_reason = (
            f"{qb_note['reason']} — {qb_effect:.1f}" if qb_note and qb_effect < 0 else None
        )

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

        # A confirmed absence (Out / Doubtful / IR) scores nothing — zero the
        # projection and its band so lineups and live totals don't count him.
        if _is_absent(p.injury_status):
            projected = 0.0
            sigma = 0.0
            confidence = "high"  # he's out — that part isn't uncertain

        out[p.id] = {
            "projected": round(projected, 1),
            "floor": round(max(0.0, projected - 0.9 * sigma), 1),
            "ceiling": round(projected + 1.1 * sigma, 1),
            "confidence": confidence,
            "stdev": round(sigma, 1),
            "bye": False,
            "inactive_reason": None,
            "boost_reason": boost_reason,
            "qb_reason": qb_reason,
            "defense_reason": defense_reason,
            "components": {
                # Our model's terms (they sum to model_proj)...
                "base_label": "Recent-weighted average",
                "terms": [
                    {"label": label, "value": round(value, 1)}
                    for label, value in (
                        ("Matchup", matchup_adj),
                        ("Vegas team total", vegas_adj),
                        ("Weather", weather_adj),
                        ("Teammates out", opportunity_adj),
                        ("QB change", qb_adj),
                    )
                ],
                "base_ppg": round(base, 1),
                "matchup_adj": round(matchup_adj, 1),
                "vegas_adj": round(vegas_adj, 1),
                "weather_adj": round(weather_adj, 1),
                "opportunity_adj": round(opportunity_adj, 1),
                "qb_adj": round(qb_adj, 1),
                "model_proj": round(model_proj, 1),
                # ...blended with Sleeper's number at blend_weight (Sleeper's
                # share), then the opposing-defense injury bump on top.
                "external_proj": round(ext, 1) if ext is not None else None,
                "blend_weight": round(blend_weight, 2) if blend_weight is not None else None,
                "defense_injury_adj": defense_injury_adj,
                "opponent": opponent,
                "week": game["week"] if game else None,
                "home": game["home"] if game else None,
            },
        }

    def _blend(model: float, ext: float | None, game: dict | None) -> tuple[float, float | None]:
        """Sleeper's DEF/K number blended in exactly as for skill players."""
        if ext is None:
            return model, None
        w = sleeper_blend_weight(now, game["kickoff"] if game else None)
        return max(0.0, w * ext + (1 - w) * model), w

    def _terms(pairs: list[tuple[str, float]]) -> list[dict]:
        return [{"label": k, "value": round(v, 1)} for k, v in pairs]

    # Team defenses: opponent offense + this defense + the opponent's QB
    # situation + Vegas + weather, blended with Sleeper's DEF projection.
    for p in dst_players:
        reason = _unavailable(p)
        if reason:
            out[p.id] = _inactive_package(reason, current_week, DST_BASELINE)
            continue
        game = next_opponent.get(p.team or "")
        opponent = game["opponent"] if game else None
        opp_implied = implied.get((opponent, game["week"])) if opponent else None
        gc = gc_by_team_week.get((p.team, game["week"])) if game else None
        opp_form = team_form.get(opponent or "") or {}
        own_form = team_form.get(p.team or "") or {}
        opp_qb = qb_change.get(opponent or "") or {}
        r = dst_model(
            opp_form.get("off_ppg"),
            own_form.get("def_pa_pg"),
            opp_form.get("off_ints_pg"),
            own_form.get("def_ints_pg"),
            opp_qb.get("pct", 0.0),
            opp_implied,
            gc,
        )
        ext = external.get(p.id)
        proj, w = _blend(r["model"], ext, game)
        sigma = proj * DST_STDEV_FRAC
        out[p.id] = {
            "projected": round(proj, 1),
            "floor": round(max(0.0, proj - sigma), 1),
            "ceiling": round(proj + sigma, 1),
            "confidence": "low",  # DST weeks are boom/bust
            "stdev": round(sigma, 1),
            "bye": False,
            "inactive_reason": None,
            "boost_reason": None,
            "qb_reason": (
                f"Facing a backup: {opp_qb['reason']}" if opp_qb.get("reason") else None
            ),
            "defense_reason": (
                f"{r['label']} matchup vs {opponent} — expects ~{r['xpa']:.0f} points allowed"
                if opponent and r["label"] != "unknown"
                else None
            ),
            "components": {
                "base_ppg": DST_BASELINE,
                "base_label": "League-average defense",
                "terms": _terms(r["terms"]),
                "model_proj": round(r["model"], 1),
                "external_proj": round(ext, 1) if ext is not None else None,
                "blend_weight": round(w, 2) if w is not None else None,
                "weather_adj": round(next(v for k, v in r["terms"] if k == "Weather"), 1),
                "opponent": opponent,
                "opponent_implied_total": round(opp_implied, 1) if opp_implied is not None else None,
                "expected_points_allowed": round(r["xpa"], 1),
                "matchup": r["label"],
                "week": game["week"] if game else None,
                "home": game["home"] if game else None,
            },
        }

    # Kickers: league-average kicker + how much his team should score + dome /
    # weather, blended with Sleeper's K projection. On a bye or ruled out, 0.
    for p in kickers:
        reason = _unavailable(p)
        if reason:
            out[p.id] = _inactive_package(reason, current_week, K_BASELINE)
            continue
        game = next_opponent.get(p.team or "")
        opponent = game["opponent"] if game else None
        week = game["week"] if game else None
        home_team = (p.team if game["home"] else opponent) if game else None
        own_form = team_form.get(p.team or "") or {}
        opp_form = team_form.get(opponent or "") or {}
        r = kicker_model(
            own_form.get("off_ppg"),
            opp_form.get("def_pa_pg"),
            (qb_change.get(p.team or "") or {}).get("pct", 0.0),
            implied.get((p.team, week)) if game else None,
            bool(STADIUMS.get(home_team or "", {}).get("dome")),
            gc_by_team_week.get((p.team, week)) if game else None,
        )
        ext = external.get(p.id)
        projected, w = _blend(r["model"], ext, game)
        sigma, confidence = K_STDEV, "low"
        if _is_absent(p.injury_status):
            projected, sigma, confidence = 0.0, 0.0, "high"
        out[p.id] = {
            "projected": round(projected, 1),
            "floor": round(max(0.0, projected - sigma), 1),
            "ceiling": round(projected + sigma, 1),
            "confidence": confidence,
            "stdev": sigma,
            "bye": False,
            "inactive_reason": None,
            "boost_reason": None,
            "qb_reason": None,
            "defense_reason": None,
            "components": {
                "base_ppg": K_BASELINE,
                "base_label": "League-average kicker",
                "terms": _terms(r["terms"]),
                "model_proj": round(r["model"], 1),
                "external_proj": round(ext, 1) if ext is not None else None,
                "blend_weight": round(w, 2) if w is not None else None,
                "expected_team_points": round(r["xpf"], 1) if r["xpf"] is not None else None,
                "opponent": opponent,
                "week": week,
                "home": game["home"] if game else None,
            },
        }
    return out


async def _team_form(db: AsyncSession, season: int) -> dict[str, dict]:
    """team -> per-game scoring form for the DEF and kicker models:
    ``off_ppg`` / ``def_pa_pg`` (points scored / allowed) and ``off_ints_pg`` /
    ``def_ints_pg`` (interceptions thrown / forced). This season counts fully,
    last season at TEAM_PRIOR_SEASON_WEIGHT, and every rate is blended with
    TEAM_SHRINK_GAMES of league average so three games can't swing it.
    ``{}`` when the results feed is unavailable (everyone league-average)."""
    results = await get_team_results([season - 1, season])
    if not results:
        return {}

    # Interceptions forced by each defense, from the passers' stat lines
    # (each row's opponent is the defense that picked him off).
    int_rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.week,
                PlayerStatsWeekly.opponent,
                func.sum(PlayerStatsWeekly.interceptions),
            )
            .where(
                PlayerStatsWeekly.season >= season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                PlayerStatsWeekly.opponent.is_not(None),
            )
            .group_by(PlayerStatsWeekly.season, PlayerStatsWeekly.week, PlayerStatsWeekly.opponent)
        )
    ).all()
    forced = {(s, w, team): float(n or 0) for s, w, team, n in int_rows}

    acc: dict[str, dict[str, float]] = defaultdict(
        lambda: {"pf": 0.0, "pa": 0.0, "games": 0.0, "def_int": 0.0, "off_int": 0.0, "int_games": 0.0}
    )
    for r in results:
        wt = 1.0 if r["season"] == season else TEAM_PRIOR_SEASON_WEIGHT
        a = acc[r["team"]]
        a["pf"] += wt * r["points_for"]
        a["pa"] += wt * r["points_against"]
        a["games"] += wt
        key_def = (r["season"], r["week"], r["team"])
        key_off = (r["season"], r["week"], r["opponent"])
        if key_def in forced or key_off in forced:
            a["def_int"] += wt * forced.get(key_def, 0.0)
            a["off_int"] += wt * forced.get(key_off, 0.0)
            a["int_games"] += wt

    k = TEAM_SHRINK_GAMES
    avg = LEAGUE_AVG_TEAM_TOTAL
    form: dict[str, dict] = {}
    for team, a in acc.items():
        form[team] = {
            "off_ppg": (a["pf"] + k * avg) / (a["games"] + k),
            "def_pa_pg": (a["pa"] + k * avg) / (a["games"] + k),
            "def_ints_pg": (
                (a["def_int"] + k * AVG_INTS) / (a["int_games"] + k) if a["int_games"] else None
            ),
            "off_ints_pg": (
                (a["off_int"] + k * AVG_INTS) / (a["int_games"] + k) if a["int_games"] else None
            ),
        }
    return form


async def _qb_change_context(
    db: AsyncSession,
    teams: set[str],
    latest_season: int | None,
    external: dict[str, float],
    passing: dict[str, float] | None = None,
) -> dict[str, dict]:
    """team -> {"pct", "reason"} for every team whose established starting QB is
    out this week. ``{}`` when every starter is healthy.

    The starter is the team QB with the most starts (100+ passing-yard games)
    this season, then last season — not the depth chart, which Sleeper often
    reshuffles once the starter is hurt. The backup is the healthy QB Sleeper
    projects to throw the most. The pass-catcher discount is half the backup's
    projected *passing* shortfall against the starter's passing points per
    start (this season full weight, last season 0.3), capped — passing, not
    total fantasy points, because a running QB's rushing doesn't feed his
    receivers."""
    passing = passing or {}
    if not teams or latest_season is None:
        return {}
    qbs = (
        await db.execute(
            select(
                Player.id,
                Player.full_name,
                Player.team,
                Player.injury_status,
                Player.depth_chart_order,
            ).where(Player.team.in_(teams), Player.position == "QB")
        )
    ).all()
    if not qbs:
        return {}

    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.pass_yards,
                PlayerStatsWeekly.pass_tds,
                PlayerStatsWeekly.interceptions,
            ).where(
                PlayerStatsWeekly.player_id.in_([q.id for q in qbs]),
                PlayerStatsWeekly.season >= latest_season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
            )
        )
    ).all()
    starts: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    for r in rows:
        if float(r.pass_yards or 0) >= QB_START_PASS_YARDS:
            starts[r.player_id][r.season].append(
                0.04 * float(r.pass_yards or 0)
                + 4.0 * float(r.pass_tds or 0)
                - 2.0 * float(r.interceptions or 0)
            )

    by_team: dict[str, list] = defaultdict(list)
    for q in qbs:
        by_team[q.team].append(q)

    out: dict[str, dict] = {}
    for team, team_qbs in by_team.items():
        def start_key(q):
            s = starts.get(q.id, {})
            return (
                len(s.get(latest_season, [])),
                len(s.get(latest_season - 1, [])),
                -(q.depth_chart_order or 99),
            )

        starter = max(team_qbs, key=start_key)
        record = starts.get(starter.id, {})
        latest_starts = record.get(latest_season, [])
        prior_starts = record.get(latest_season - 1, [])
        if not (latest_starts or prior_starts) or not _is_absent(starter.injury_status):
            continue
        healthy = [
            q for q in team_qbs if q.id != starter.id and not _is_absent(q.injury_status)
        ]
        if not healthy:
            continue
        backup = max(
            healthy,
            key=lambda q: (
                passing.get(q.id) or 0.0,
                external.get(q.id) or 0.0,
                -(q.depth_chart_order or 99),
            ),
        )
        weight = len(latest_starts) + TEAM_PRIOR_SEASON_WEIGHT * len(prior_starts)
        starter_ppg = (
            (sum(latest_starts) + TEAM_PRIOR_SEASON_WEIGHT * sum(prior_starts)) / weight
            if weight
            else 0.0
        )
        backup_proj = passing.get(backup.id)
        if starter_ppg > 0 and backup_proj is not None:
            drop = max(0.0, 1.0 - float(backup_proj) / starter_ppg)
            pct = min(QB_CHANGE_CAP, QB_CHANGE_SCALE * drop)
        else:
            pct = QB_CHANGE_DEFAULT
        if pct <= 0:
            continue
        out[team] = {
            "pct": pct,
            "reason": (
                f"{backup.full_name} starting for {starter.full_name} "
                f"({starter.injury_status})"
            ),
        }
    return out


async def _opportunity_shares(db: AsyncSession, teams: set[str]) -> dict[str, dict]:
    """player_id → {"extra_points", "reason_prefix", "kind"} for every healthy player who
    inherits work from an officially-absent teammate: vacated targets (pass-
    catchers) and vacated carries (running backs). ``{}`` when no team has a
    qualifying, fresh absence.

    Loads the full WR/TE/RB pool for ``teams`` (not just the requested players)
    with each player's most-recent-season average target share and carries,
    and how recently each absent player last played, then defers the
    redistribution to ``opportunity_service``.
    """
    if not teams:
        return {}

    players = (
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
    if not players:
        return {}

    latest_season = (await db.execute(select(func.max(PlayerStatsWeekly.season)))).scalar()
    latest = None
    if latest_season is not None:
        latest_week = (
            await db.execute(
                select(func.max(PlayerStatsWeekly.week)).where(
                    PlayerStatsWeekly.season == latest_season,
                    PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                )
            )
        ).scalar()
        latest = (int(latest_season), int(latest_week or 0))

    rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.week,
                PlayerStatsWeekly.target_share,
                PlayerStatsWeekly.rush_attempts,
            ).where(
                PlayerStatsWeekly.player_id.in_([p.id for p in players]),
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
            )
        )
    ).all()
    shares: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    carries: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    last_game: dict[str, tuple[int, int]] = {}
    for r in rows:
        if r.target_share is not None:
            shares[r.player_id][r.season].append(float(r.target_share))
        carries[r.player_id][r.season].append(float(r.rush_attempts or 0))
        key = (int(r.season), int(r.week))
        if r.player_id not in last_game or key > last_game[r.player_id]:
            last_game[r.player_id] = key

    def recent_avg(by_season: dict[int, list[float]]) -> float:
        if not by_season:
            return 0.0
        vals = by_season[max(by_season)]  # most recent season with data
        return sum(vals) / len(vals) if vals else 0.0

    by_team: dict[str, list] = defaultdict(list)
    for p in players:
        by_team[p.team].append(p)

    target_out: dict[str, dict] = {}
    rush_out: dict[str, dict] = {}
    for team_players in by_team.values():
        def fresh(pid: str) -> float:
            return absence_freshness(last_game.get(pid), latest)

        target_out.update(compute_opportunity_shares([
            {
                "id": p.id,
                "name": p.full_name,
                "position": p.position,
                "target_share": recent_avg(shares.get(p.id, {})),
                "depth_chart_order": p.depth_chart_order,
                "injury_status": p.injury_status,
                "freshness": fresh(p.id),
            }
            for p in team_players
        ]))

        rbs = [p for p in team_players if p.position == "RB"]
        rb_carries = {p.id: recent_avg(carries.get(p.id, {})) for p in rbs}
        team_carries = sum(rb_carries.values())
        if team_carries > 0:
            rush_out.update(compute_rush_shares([
                {
                    "id": p.id,
                    "name": p.full_name,
                    "rush_share": rb_carries[p.id] / team_carries,
                    "depth_chart_order": p.depth_chart_order,
                    "injury_status": p.injury_status,
                    "freshness": fresh(p.id),
                }
                for p in rbs
            ]))

    out: dict[str, dict] = {}
    for pid in set(target_out) | set(rush_out):
        t, r = target_out.get(pid), rush_out.get(pid)
        points = (t["extra_share"] * PTS_PER_TARGET_SHARE if t else 0.0) + (
            r["extra_share"] * PTS_PER_CARRY_SHARE if r else 0.0
        )
        names = ", ".join(dict.fromkeys(
            n for n in ((t or {}).get("reason_prefix"), (r or {}).get("reason_prefix")) if n
        ))
        kind = "targets and carries" if t and r else "targets" if t else "carries"
        out[pid] = {"extra_points": points, "reason_prefix": names, "kind": kind}
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

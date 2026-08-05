"""Draft board engine — season-long projections, VOR, tiers, and ADP edges.

The board answers four questions ESPN's ranking list does not:

1. **How many points, over a whole season?** A blend of ESPN's season-long
   projection (which prices in offseason moves we can't see from stats alone)
   and our own recency-weighted history from `value_service`. Rookies have no
   history, so they lean entirely on ESPN — which is precisely the case the old
   `/api/players/rankings` endpoint dropped on the floor.

2. **How much is that worth?** Points are not comparable across positions, so
   everything is expressed as **VOR** — points above the last startable player
   at that position, with replacement level derived from the league's *actual*
   roster settings rather than a hardcoded table.

3. **Where does the market disagree with us?** `adp_delta` is consensus ADP
   minus our own rank. Positive means he's falling past where he should go.

4. **Can I wait?** Real drafts scatter around ADP, and Fantasy Football
   Calculator publishes that scatter as a standard deviation. From it we get
   P(still available at your next pick) — the number that actually decides
   whether you take a player now or come back to him.
"""

import logging
import math
from collections import Counter, defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerDraftProfile, PlayerStatsWeekly
from app.services.projection_service import _erf
from app.services.value_service import (
    RECENT_WINDOW,
    REGULAR_SEASON_MAX_WEEK,
    _blended_base,
)

logger = logging.getLogger(__name__)

DRAFTABLE_POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

# Only these are ranked by VOR. Kicker and defense production is close to
# random year over year and the spread between the best and the twentieth is
# roughly a point a week, so their "value over replacement" is noise. Ranking
# them alongside skill players produces absurdities — a kicker showing up as a
# 90-pick bargain in round 6 — so they get their own ADP-ordered list instead.
VOR_POSITIONS = ("QB", "RB", "WR", "TE")
LATE_ROUND_POSITIONS = ("K", "DEF")
GAMES_IN_SEASON = 17

SCORING_COLUMN = {
    "ppr": PlayerStatsWeekly.fantasy_points_ppr,
    "half_ppr": PlayerStatsWeekly.fantasy_points_half,
    "standard": PlayerStatsWeekly.fantasy_points_std,
}

# How a FLEX slot actually gets used across a league. Not uniform: managers
# start far more RB/WR in flex than TE.
FLEX_SHARE = {"RB": 0.40, "WR": 0.45, "TE": 0.15}
SUPERFLEX_SHARE = {"QB": 0.55, "RB": 0.15, "WR": 0.22, "TE": 0.08}
FLEX_SLOTS = {"FLEX", "WRRB_FLEX", "REC_FLEX", "WRT"}
SUPERFLEX_SLOTS = {"SUPER_FLEX", "SUPERFLEX", "QB/WR/RB/TE"}
NON_STARTER_SLOTS = {"BN", "IR", "TAXI"}

# Roster shape used when a league hasn't been connected yet.
DEFAULT_ROSTER = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "K", "DEF"]

# Blend weights for the season projection, by how much history we have.
# ESPN carries offseason signal (team changes, depth chart) that raw history
# can't; our own history carries production ESPN's model smooths away.
BLEND_ESTABLISHED = 0.55  # >= 8 games: trust both
BLEND_THIN = 0.75  # 3-7 games: lean on ESPN
MIN_GAMES_FOR_HISTORY = 3

# Injury designations that mean real missed time. ESPN's projection already
# prices these in (a PUP tight end projects far below his healthy history), but
# our recency-weighted history does not — so for these, history may only drag a
# projection DOWN, never inflate it above ESPN's number.
SERIOUS_INJURY = {"ir", "pup", "out", "suspended", "susp", "nfi", "doubtful"}
# Fallback season multiplier on history when a hurt player has no ESPN number to
# anchor to — rough games-missed haircuts, worst designations cutting deepest.
INJURY_HISTORY_DISCOUNT = {
    "ir": 0.20,
    "nfi": 0.40,
    "suspended": 0.45,
    "susp": 0.45,
    "pup": 0.55,
    "out": 0.60,
    "doubtful": 0.85,
}

# Tiers are cut at the biggest scoring cliffs, capped so the board stays
# readable, and only across the range of a position anyone actually drafts
# (a multiple of its replacement rank).
MAX_TIERS = 8
DRAFTABLE_MULTIPLE = 2.0
# A gap must be this many times the average gap to count as a cliff at all.
# Without a significance floor, a short list (fewer players than the tier cap)
# gets a break at every single gap and every player becomes his own tier.
TIER_MIN_GAP_RATIO = 1.5

# A rank gap alone is a bad value signal. Positional curves flatten out past
# the starters — among mid-tier TEs a 2-point edge can move a player 60 rank
# spots — so a raw "falling 60 picks" reads identically for a genuine steal and
# for statistical noise. Scaling the gap by how far above replacement he
# actually is keeps the flat middle of the board from dominating the list.
# Roughly a full startable-starter's worth of points over replacement.
VALUE_VOR_SCALE = 40.0

# Recommendation weights.
#
# The value of a pick is not its raw VOR — it's how much that player adds to
# *your* roster. Once your starting slots at a position are full, each further
# body is bench depth worth steeply less, because it only plays on byes,
# injuries, or a breakout. Without this, the assistant is a pure VOR-maximizer
# that happily recommends your ninth tight end (mid-tier TEs carry deceptively
# high VOR against their shallow replacement level).
#
# The multiplier decays smoothly with how far past your starters a player sits,
# so fractional flex demand (RB ~2.4 starters) is handled without a cliff.
STARTER_FILL_BONUS = 0.15  # nudge toward completing an empty starting slot
# How fast a position's value decays once your starters are full, per "starter's
# worth" of surplus. Position-specific on purpose: you only ever start one QB
# and one TE, so a second is a luxury that decays hard; RB and WR depth actually
# plays every week through the flex, byes, and injuries, so it holds value.
BENCH_BASE_BY_POS = {"QB": 0.28, "RB": 0.55, "WR": 0.55, "TE": 0.30}
BENCH_BASE_DEFAULT = 0.45
# How many bench bodies past your starters are worth recommending at each
# position. QB and TE need only a single backup (you start one, stream at most
# two); RB and WR carry deep benches for the flex, byes, and injuries. The cap
# is round(starters) + this, so it scales with the league: a 1-TE league caps
# TE at 2, a 2-TE or superflex league lifts the ceiling on its own.
BENCH_ALLOWANCE = {"QB": 1, "RB": 5, "WR": 5, "TE": 1}
BENCH_ALLOWANCE_DEFAULT = 4

# Kicker/defense have no meaningful VOR, so they ride an urgency ramp instead of
# the value board: invisible early, rising to the top only as you run out of
# picks to grab them.
KDEF_MAX_SCORE = 55.0
KDEF_LATE_WINDOW = 4  # picks before you'd be forced, when K/DEF start surfacing

# The suggestion list is a decision aid, not a pure value ranking: showing four
# tight ends is useless even when they're the four highest-scored players. Cap
# how many of one position appear so the drafter always sees real alternatives.
DISPLAY_MAX_PER_POS = 2

TIER_CLIFF_WEIGHT = 0.5  # weight on the points lost by missing this tier
# Spend the pick on someone who won't survive the round trip. A player the
# market says is very likely to still be sitting there at your next turn is
# worth less *right now* than an equally-valued player who won't be.
WAIT_DISCOUNT = 0.25
BYE_PENALTY = 4.0  # per colliding bye week
BYE_CONFLICT_FLOOR = 2  # one shared bye is normal; three is a problem
VALUE_NOTABLE = 15.0  # value_score worth mentioning in the reasons
# ESPN-vs-sharp ADP gap (picks) big enough to call out as a market edge.
MARKET_EDGE_NOTABLE = 18.0
INJURY_PENALTY = {"out": 30.0, "ir": 45.0, "doubtful": 20.0, "questionable": 5.0}


def starters_per_team(roster_positions: list[str] | None) -> dict[str, float]:
    """Average number of each position started per team, flex included.

    Sleeper gives roster_positions as a flat list like
    ["QB","RB","RB","WR","WR","TE","FLEX","K","DEF","BN","BN"]. Flex slots are
    spread across the positions eligible to fill them rather than assigned to
    one, because that's how the league actually consumes them.
    """
    slots = roster_positions or DEFAULT_ROSTER
    counts: dict[str, float] = defaultdict(float)
    for raw in slots:
        slot = (raw or "").upper()
        if slot in NON_STARTER_SLOTS:
            continue
        if slot in FLEX_SLOTS:
            for pos, share in FLEX_SHARE.items():
                counts[pos] += share
        elif slot in SUPERFLEX_SLOTS:
            for pos, share in SUPERFLEX_SHARE.items():
                counts[pos] += share
        elif slot in DRAFTABLE_POSITIONS:
            counts[slot] += 1.0
    return dict(counts)


def replacement_ranks(
    roster_positions: list[str] | None, league_size: int
) -> dict[str, int]:
    """Positional rank at which a player stops being a startable asset."""
    per_team = starters_per_team(roster_positions)
    return {
        pos: max(1, math.ceil(per_team.get(pos, 0) * league_size))
        for pos in DRAFTABLE_POSITIONS
        if per_team.get(pos, 0) > 0
    }


def availability_at(
    adp: float | None, stdev: float | None, pick_number: int
) -> float | None:
    """P(player is still on the board at `pick_number`).

    Real draft slots scatter roughly normally around ADP, so this is the upper
    tail: P(his draft slot > pick_number). With no stdev to work from it
    degrades to a hard before/after answer.
    """
    if adp is None:
        return None
    if not stdev or stdev <= 0:
        return 1.0 if adp > pick_number else 0.0
    z = (pick_number - adp) / stdev
    return round(max(0.0, min(1.0, 1 - 0.5 * (1 + _erf(z / math.sqrt(2))))), 3)


def _assign_tiers(points: list[float], draftable: int) -> list[int]:
    """Tier numbers for a descending-sorted list of projections.

    Cuts at the largest scoring cliffs — at most MAX_TIERS tiers across the
    draftable prefix, plus one trailing tier for everyone beyond it. Each
    constraint earns its place:

    - A threshold derived from the *typical* gap is unusable in practice. Across
      129 WRs the typical gap is ~1 point, which splits them into 40+ tiers;
      across 50 QBs the median is dragged up by unrostered backups, which
      collapses the top 16 QBs into one tier. Ranking the gaps instead of
      thresholding them gives a stable tier count either way.
    - Players past the draftable range are all equivalently "late flier", so
      they land in one trailing tier rather than generating noise.
    """
    n = len(points)
    if n <= 1:
        return [1] * n

    prefix = max(2, min(draftable, n))
    raw = [(points[i] - points[i + 1], i) for i in range(prefix - 1)]
    positive = [g for g, _ in raw if g > 0]
    if not positive:
        return [1] * prefix + [2] * (n - prefix)

    floor = (sum(positive) / len(positive)) * TIER_MIN_GAP_RATIO
    gaps = sorted(((g, i) for g, i in raw if g >= floor), reverse=True)
    cuts = {i for _, i in gaps[: MAX_TIERS - 1]}

    tiers: list[int] = []
    current = 1
    for i in range(prefix):
        if i > 0 and (i - 1) in cuts:
            current += 1
        tiers.append(current)
    if prefix < n:
        tiers.extend([current + 1] * (n - prefix))
    return tiers


async def _historical_ppg(
    db: AsyncSession, season: int, scoring: str
) -> dict[str, tuple[float, int]]:
    """player_id → (recency-weighted points per game, games of sample)."""
    column = SCORING_COLUMN.get(scoring, PlayerStatsWeekly.fantasy_points_ppr)
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
                column,
            ).where(
                PlayerStatsWeekly.season >= latest_season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                column.is_not(None),
            )
        )
    ).all()
    if not rows:
        return {}

    latest_week = max((r.week for r in rows if r.season == latest_season), default=18)
    recent_cutoff = latest_week - RECENT_WINDOW

    samples: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
    for r in rows:
        samples[r.player_id].append((r.season, r.week, float(r[3])))

    return {
        pid: (_blended_base(s, int(latest_season), recent_cutoff), len(s))
        for pid, s in samples.items()
    }


def _blend(espn: float | None, own: float | None, games: int) -> tuple[float, str]:
    """Combine ESPN's season projection with our own history-derived one."""
    if espn is not None and own is not None and games >= MIN_GAMES_FOR_HISTORY:
        weight = BLEND_ESTABLISHED if games >= 8 else BLEND_THIN
        return weight * espn + (1 - weight) * own, "blend"
    if espn is not None:
        return espn, "espn"
    if own is not None and games >= MIN_GAMES_FOR_HISTORY:
        return own, "history"
    return 0.0, "none"


def _status_adjust(
    points: float,
    source: str,
    espn: float | None,
    own_total: float | None,
    injury_status: str | None,
    team: str | None,
) -> tuple[float, str, str | None]:
    """Correct a projection for injury and roster status.

    Returns (points, source, roster_status). ESPN's projection is the injury- and
    role-aware signal; our history is not. So a seriously injured player is
    capped at ESPN's number (history can't lift him), and a player with no team
    is handed back to the ADP-implied fill pass rather than trusting a stale
    history that assumes a role he no longer has.
    """
    status = (injury_status or "").lower()
    serious = status in SERIOUS_INJURY
    teamless = not team

    if teamless:
        # No team → no role. Drop the history-based number; the fill pass will
        # substitute the market's ADP-implied value (or he falls off the board).
        if source in ("history", "none"):
            return 0.0, "none", "free_agent"
        # A rare teamless-but-ESPN-projected case: keep ESPN, still flag it.
        return points, source, "free_agent"

    if serious:
        if espn is not None and points > espn:
            return espn, "espn_injury", "injured"  # history may not inflate
        if espn is None and own_total is not None:
            discounted = own_total * INJURY_HISTORY_DISCOUNT.get(status, 0.6)
            return discounted, "injury_discount", "injured"
        return points, source, "injured"

    return points, source, None


def _adp_implied(known: list[tuple[float, float]], adp: float) -> float | None:
    """Interpolate a projection for a player who has ADP but no projection.

    Keeps deep-bench and just-signed players on the board instead of silently
    dropping them. `known` is (adp, points) pairs sorted by adp, and must be
    scoped to a single position — points are not comparable across positions,
    so interpolating a TE against the global curve hands him an RB's total and
    then his VOR detonates against a weak TE replacement level.
    """
    if not known:
        return None
    if adp <= known[0][0]:
        return known[0][1]
    if adp >= known[-1][0]:
        return known[-1][1]
    for i in range(len(known) - 1):
        a0, p0 = known[i]
        a1, p1 = known[i + 1]
        if a0 <= adp <= a1:
            if a1 == a0:
                return p0
            ratio = (adp - a0) / (a1 - a0)
            return p0 + ratio * (p1 - p0)
    return None


async def compute_draft_board(
    db: AsyncSession,
    season: int,
    scoring: str = "ppr",
    league_size: int = 12,
    roster_positions: list[str] | None = None,
) -> list[dict]:
    """The full ranked draft board, best player first."""
    profiles = (
        (
            await db.execute(
                select(PlayerDraftProfile).where(
                    PlayerDraftProfile.season == season,
                    PlayerDraftProfile.scoring == scoring,
                )
            )
        )
        .scalars()
        .all()
    )
    if not profiles:
        logger.warning("No draft profiles for season %s scoring %s", season, scoring)
        return []

    players = {
        p.id: p
        for p in (
            await db.execute(
                select(Player).where(Player.id.in_([pr.player_id for pr in profiles]))
            )
        )
        .scalars()
        .all()
    }
    history = await _historical_ppg(db, season, scoring)

    # Pass 1 — season projection per player
    rows: list[dict] = []
    for profile in profiles:
        player = players.get(profile.player_id)
        if player is None or player.position not in VOR_POSITIONS:
            continue
        ppg, games = history.get(profile.player_id, (None, 0))
        own_total = ppg * GAMES_IN_SEASON if ppg else None
        points, source = _blend(profile.espn_season_proj, own_total, games)
        points, source, roster_status = _status_adjust(
            points,
            source,
            profile.espn_season_proj,
            own_total,
            player.injury_status,
            player.team,
        )
        rows.append(
            {
                "player_id": player.id,
                "name": player.full_name,
                "position": player.position,
                "team": player.team,
                "injury_status": player.injury_status,
                "roster_status": roster_status,
                "bye_week": profile.bye_week,
                "proj_points": points,
                "proj_source": source,
                "adp": profile.adp_consensus,
                "adp_espn": profile.adp_espn,
                "adp_ffc": profile.adp_ffc,
                "adp_stdev": profile.adp_stdev,
                # ESPN's casual crowd vs sharp mock-drafters (FFC). Positive =
                # ESPN drafts him later than the sharps do, so he falls to you in
                # an ESPN league while your leaguemates chase ESPN's board.
                "market_edge": (
                    round(profile.adp_espn - profile.adp_ffc, 1)
                    if profile.adp_espn is not None and profile.adp_ffc is not None
                    else None
                ),
                "auction_value": profile.auction_value,
                "times_drafted": profile.times_drafted,
            }
        )

    # Fill projection holes by interpolating along each position's own ADP
    # curve. Scoped per position on purpose — see _adp_implied.
    known_by_position: dict[str, list[tuple[float, float]]] = defaultdict(list)
    for r in rows:
        if r["adp"] and r["proj_points"] and r["proj_source"] != "none":
            known_by_position[r["position"]].append((r["adp"], r["proj_points"]))
    for curve in known_by_position.values():
        curve.sort(key=lambda x: x[0])

    for r in rows:
        if r["proj_source"] == "none" and r["adp"]:
            implied = _adp_implied(known_by_position.get(r["position"], []), r["adp"])
            if implied is not None:
                r["proj_points"] = implied
                r["proj_source"] = "adp_implied"

    rows = [r for r in rows if r["proj_points"] > 0]
    if not rows:
        return []

    # Pass 2 — replacement level, VOR, tiers (all within position)
    repl_ranks = replacement_ranks(roster_positions, league_size)
    by_position: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_position[r["position"]].append(r)

    for position, group in by_position.items():
        group.sort(key=lambda r: r["proj_points"], reverse=True)
        points = [r["proj_points"] for r in group]

        rank = repl_ranks.get(position)
        if rank is None:
            replacement = points[-1]  # position isn't started — everyone is spare
            draftable = len(points)
        else:
            replacement = points[min(rank, len(points)) - 1]
            draftable = math.ceil(rank * DRAFTABLE_MULTIPLE)

        tiers = _assign_tiers(points, draftable)
        for i, r in enumerate(group):
            r["position_rank"] = i + 1
            r["tier"] = tiers[i]
            r["vor"] = round(r["proj_points"] - replacement, 1)
            r["replacement_points"] = round(replacement, 1)
            r["proj_points"] = round(r["proj_points"], 1)

    # Pass 3 — overall order by VOR, then the market comparison
    rows.sort(key=lambda r: r["vor"], reverse=True)
    for i, r in enumerate(rows):
        r["overall_rank"] = i + 1
        r["is_tier_end"] = False
        r["adp_rank"] = None
        r["adp_delta"] = None
        r["value_score"] = 0.0

    # Market position measured on this same board. Comparing our rank against
    # raw ADP is apples-to-oranges — ADP counts the ~30 kicker and defense
    # picks this board excludes, an offset that grows deeper into the draft and
    # made every mid-round tight end read as a steal.
    # Positive delta: the market lets him slide past where we value him.
    with_adp = sorted((r for r in rows if r["adp"]), key=lambda r: r["adp"])
    for i, r in enumerate(with_adp):
        r["adp_rank"] = i + 1
        r["adp_delta"] = r["adp_rank"] - r["overall_rank"]
        # Rank gap weighted by the size of the actual edge — see VALUE_VOR_SCALE.
        # Sub-replacement players score zero: a bargain on someone you shouldn't
        # roster isn't a bargain.
        weight = max(0.0, min(1.0, r["vor"] / VALUE_VOR_SCALE))
        r["value_score"] = round(r["adp_delta"] * weight, 1)

    # Mark the last player in each positional tier — the cliff you can't wait out
    seen: set[tuple[str, int]] = set()
    for r in sorted(rows, key=lambda r: r["position_rank"], reverse=True):
        key = (r["position"], r["tier"])
        if key not in seen:
            seen.add(key)
            r["is_tier_end"] = True

    return rows


def _tier_drops(board: list[dict]) -> dict[tuple[str, int], float]:
    """(position, tier) → points lost by waiting for the next tier down."""
    best: dict[tuple[str, int], float] = {}
    worst: dict[tuple[str, int], float] = {}
    for r in board:
        key = (r["position"], r["tier"])
        best[key] = max(best.get(key, 0.0), r["proj_points"])
        worst[key] = min(worst.get(key, 1e9), r["proj_points"])
    drops: dict[tuple[str, int], float] = {}
    for (position, tier), floor_points in worst.items():
        nxt = best.get((position, tier + 1))
        drops[(position, tier)] = max(0.0, floor_points - nxt) if nxt else 0.0
    return drops


def roster_needs(
    roster_positions: list[str] | None, my_positions: list[str]
) -> dict[str, dict]:
    """Per position: how many starters the league needs vs how many you hold.

    Rounded rather than ceilinged, unlike `replacement_ranks`. The two want
    different things: replacement level should sit deep, but a need count wants
    the lineup you actually field — ceiling a one-TE league's 1.15 flex-adjusted
    demand would tell you to go get a second starting tight end.
    """
    required = starters_per_team(roster_positions)
    held = Counter(my_positions)
    needs: dict[str, dict] = {}
    for position in VOR_POSITIONS:
        need = round(required.get(position, 0))
        have = held.get(position, 0)
        needs[position] = {
            "required": need,
            "have": have,
            "unfilled": max(0, need - have),
        }
    return needs


def _marginal_multiplier(
    position: str, have: int, starters: float
) -> tuple[float, bool]:
    """Value multiplier for the (have+1)-th body at a position, and whether it
    fills a starting slot.

    `starters` is the flex-adjusted average number this league starts (a float,
    e.g. 2.4 RB). A player still inside that count is a starter at full value; a
    player past it is bench depth, decaying smoothly (so the fractional flex
    demand doesn't create a cliff) at a rate set by how much that position's
    depth actually plays.
    """
    have_after = have + 1
    over = have_after - starters
    if over <= 0:
        return 1.0 + STARTER_FILL_BONUS, True
    base = BENCH_BASE_BY_POS.get(position, BENCH_BASE_DEFAULT)
    return base**over, False


def _recommend_cap(position: str, starters: float) -> int:
    """Hard stop on how many of a position to ever recommend, league-scaled.

    Kicker and defense are always single-roster. Everyone else is their rounded
    starter demand plus a position-appropriate bench allowance, so a 1-TE league
    caps tight ends at 2 while a superflex league lifts the QB ceiling on its
    own — without any hardcoded per-format numbers.
    """
    if position in LATE_ROUND_POSITIONS:
        return 1
    allowance = BENCH_ALLOWANCE.get(position, BENCH_ALLOWANCE_DEFAULT)
    return round(starters) + allowance


def _kdef_candidates(
    late_round: list[dict],
    taken: set[str],
    held: Counter,
    picks_left: int,
) -> list[dict]:
    """Kicker/defense picks scored on an urgency ramp, not VOR.

    Returns at most one candidate per position (the best still on the board),
    scored ~0 while you have picks to spare and rising to the top of the list
    as you approach being forced to reach for one.
    """
    unfilled = (0 if held.get("K") else 1) + (0 if held.get("DEF") else 1)
    out: list[dict] = []
    for position in LATE_ROUND_POSITIONS:
        if held.get(position):
            continue  # never a second K or DEF
        pool = [
            p
            for p in late_round
            if p["position"] == position and p["player_id"] not in taken and p["adp"]
        ]
        if not pool:
            continue
        best = min(pool, key=lambda p: p["adp"])
        # slack = picks you can still "spend" before you'd be forced to grab the
        # K/DEF you still owe. Once it hits the late window the ramp lifts.
        slack = picks_left - unfilled
        urgency = max(0.0, (KDEF_LATE_WINDOW - slack) / KDEF_LATE_WINDOW)
        score = KDEF_MAX_SCORE * min(1.0, urgency)
        if score <= 0:
            continue  # keep them out of early suggestions entirely
        reason = (
            f"Only {picks_left} picks left and no {position} yet"
            if slack <= 0
            else f"Time to lock in a {position} — they'll go soon"
        )
        out.append(
            {
                **best,
                "score": round(score, 1),
                "available_at_following_pick": None,
                "reasons": [reason],
            }
        )
    return out


def recommend_picks(
    board: list[dict],
    roster_positions: list[str] | None,
    my_player_ids: list[str],
    drafted_ids: list[str],
    next_pick: int | None = None,
    following_pick: int | None = None,
    limit: int = 5,
    late_round: list[dict] | None = None,
    rounds: int | None = None,
) -> list[dict]:
    """Rank the best available players for *this* pick, with the reasoning.

    Raw VOR answers "who is worth the most", which is only half the question at
    a live draft. The other half is what that player adds to *your* roster: a
    ninth tight end is nearly worthless however high his VOR reads, and a
    kicker you don't have becomes the most valuable pick on the board in the
    last round. So each candidate's VOR is scaled by its marginal roster value,
    kickers and defenses ride a separate urgency ramp, and — the part that
    decides close calls — a player who'll still be there next turn is discounted
    now.
    """
    taken = set(drafted_ids) | set(my_player_ids)
    available = [r for r in board if r["player_id"] not in taken]

    # Position lookup must span K/DEF too, or a kicker you've already drafted is
    # invisible to the held-count and the engine keeps offering more of them.
    by_id = {r["player_id"]: r for r in board}
    for r in late_round or []:
        by_id.setdefault(r["player_id"], r)
    my_positions = [by_id[pid]["position"] for pid in my_player_ids if pid in by_id]
    my_byes = Counter(
        by_id[pid].get("bye_week") for pid in my_player_ids if pid in by_id
    )
    held = Counter(my_positions)
    starters = starters_per_team(roster_positions)
    drops = _tier_drops(board)

    scored: list[dict] = []
    for r in available:
        position = r["position"]
        have = held.get(position, 0)
        if have >= _recommend_cap(position, starters.get(position, 0.0)):
            continue  # roster is saturated here — stop suggesting it
        reasons: list[str] = []

        # Marginal roster value: full for a starter, decaying for bench depth.
        multiplier, is_starter = _marginal_multiplier(
            position, have, starters.get(position, 0.0)
        )
        score = r["vor"] * multiplier
        if is_starter and have < round(starters.get(position, 0.0)):
            reasons.append(
                f"Fills a starting {position} slot "
                f"({have}/{round(starters.get(position, 0.0))} rostered)"
            )
        elif not is_starter:
            reasons.append(f"{position} depth (bench value)")

        # Will he last? Everything urgent is scaled by how unlikely that is.
        availability = (
            availability_at(r["adp"], r["adp_stdev"], following_pick)
            if following_pick
            else None
        )
        urgency = 1.0 - availability if availability is not None else 0.5

        if availability is not None and r["vor"] > 0:
            score -= WAIT_DISCOUNT * r["vor"] * availability

        drop = drops.get((position, r["tier"]), 0.0)
        if r["is_tier_end"] and drop > 0:
            score += TIER_CLIFF_WEIGHT * drop * urgency
            reasons.append(
                f"Last of {position} tier {r['tier']} — next tier drops "
                f"{round(drop)} pts"
            )
        if availability is not None:
            pct = round(availability * 100)
            if pct <= 2:
                reasons.append(f"Certain to be gone by pick {following_pick}")
            elif pct <= 25:
                reasons.append(f"Only {pct}% chance he lasts to pick {following_pick}")
            elif pct >= 70:
                reasons.append(f"{pct}% likely still there at pick {following_pick}")

        if r.get("value_score", 0) >= VALUE_NOTABLE:
            reasons.append(f"Going {r['adp_delta']} picks later than we rank him")

        edge = r.get("market_edge")
        if edge is not None and edge >= MARKET_EDGE_NOTABLE:
            reasons.append(
                f"Sharps draft him ~{round(edge)} picks earlier than ESPN — "
                f"value if your league drafts off ESPN"
            )

        bye = r.get("bye_week")
        conflicts = my_byes.get(bye, 0) if bye else 0
        if conflicts >= BYE_CONFLICT_FLOOR:
            score -= BYE_PENALTY * conflicts
            reasons.append(f"Week {bye} bye collides with {conflicts} of your picks")

        status = (r.get("injury_status") or "").lower()
        penalty = INJURY_PENALTY.get(status)
        if penalty:
            score -= penalty
            reasons.append(f"Injury status: {r['injury_status']}")

        scored.append(
            {
                **r,
                "score": round(score, 1),
                "available_at_following_pick": availability,
                "reasons": reasons,
            }
        )

    # Kicker/defense enter only when the draft is late enough to need them.
    if late_round and rounds:
        picks_left = max(1, rounds - len(my_player_ids))
        scored.extend(_kdef_candidates(late_round, taken, held, picks_left))

    scored.sort(key=lambda r: r["score"], reverse=True)
    return _diversify(scored, limit)


def _diversify(scored: list[dict], limit: int) -> list[dict]:
    """Take the top `limit`, but no more than DISPLAY_MAX_PER_POS of any position.

    `scored` must already be sorted best-first. The highest pick always survives;
    the constraint only shapes what fills the slots behind it, and if diversity
    can't fill the list (a thin board), the remaining best-scored players
    backfill it.
    """
    out: list[dict] = []
    per_pos: Counter = Counter()
    for r in scored:
        if per_pos[r["position"]] >= DISPLAY_MAX_PER_POS:
            continue
        out.append(r)
        per_pos[r["position"]] += 1
        if len(out) >= limit:
            return out
    chosen = {r["player_id"] for r in out}
    for r in scored:
        if r["player_id"] not in chosen:
            out.append(r)
            if len(out) >= limit:
                break
    return out


async def late_round_board(
    db: AsyncSession, season: int, scoring: str = "ppr"
) -> list[dict]:
    """Kickers and defenses, ordered by ADP — no VOR, because it isn't real."""
    profiles = (
        (
            await db.execute(
                select(PlayerDraftProfile).where(
                    PlayerDraftProfile.season == season,
                    PlayerDraftProfile.scoring == scoring,
                )
            )
        )
        .scalars()
        .all()
    )
    if not profiles:
        return []

    players = {
        p.id: p
        for p in (
            await db.execute(
                select(Player).where(
                    Player.id.in_([pr.player_id for pr in profiles]),
                    Player.position.in_(LATE_ROUND_POSITIONS),
                )
            )
        )
        .scalars()
        .all()
    }

    rows = [
        {
            "player_id": p.player_id,
            "name": players[p.player_id].full_name,
            "position": players[p.player_id].position,
            "team": players[p.player_id].team,
            "bye_week": p.bye_week,
            "adp": p.adp_consensus,
            "adp_stdev": p.adp_stdev,
        }
        for p in profiles
        if p.player_id in players and p.adp_consensus
    ]
    rows.sort(key=lambda r: r["adp"])
    for i, r in enumerate(rows):
        r["position_rank"] = (
            sum(1 for x in rows[: i + 1] if x["position"] == r["position"])
        )
    return rows

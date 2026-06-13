"""Player trade-value model — a single value number per player.

Instead of a flat 0-100 percentile, every player gets a **value** derived from
Value Over Replacement (VOR): how much more they produce than a freely-available
replacement at their position. VOR makes values comparable across positions (an
elite TE and an elite WR can be priced against each other) and behaves like a
market — studs carry a premium.

Two layers feed the value:

1. Baseline talent (`base_ppg`) — a recency-weighted blend of the last two
   seasons (latest counts ~2x, last 4 weeks 2x again, prior season 0.5x). This
   is the stable anchor, so one down year doesn't tank an established star.

2. Momentum (`adj_ppg`) — recent form nudges the baseline, but the nudge is
   *tier-damped* and *streak-aware*:
     - A high-value player's single bad week barely moves them; it takes a
       multi-week slump to drop their value.
     - A low-value player's single big week barely moves them; it takes a
       multi-week hot streak to lift their value (so one game can't overrate
       a scrub).
   Consecutive same-direction weeks compound the move in either direction.

Recomputed from the weekly stats table on demand, so values drift week to week
as the (weekly-refreshed) stats change.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerStatsWeekly

VALUED_POSITIONS = {"QB", "RB", "WR", "TE"}
MIN_GAMES = 3
REGULAR_SEASON_MAX_WEEK = 18

# Baseline blend
RECENT_WINDOW = 4          # last N weeks of the latest season count double
PRIOR_SEASON_WEIGHT = 0.5  # latest season counts 2x the season before
# A proven player can't fall below this fraction of their better of the last two
# seasons — so one down/injury year (or a cold streak) doesn't tank an
# established star's trade value.
PEAK_FLOOR = 0.90

# Momentum
ELITE_ANCHOR = 20.0        # ppg that reads as "elite tier" for tier scaling
RECENT_GAMES = 5           # games of recent form considered for momentum
RECENT_WEIGHTS = [1.0, 0.8, 0.6, 0.45, 0.35]  # most-recent game first
RESPONSIVENESS = 0.6       # global scalar on how much momentum moves the baseline

# Value curve (VOR -> value). Linear with a deep replacement keeps the spread
# realistic — the WR1 is worth a few times a solid starter, not 8x.
SCALE = 4.5
GAMMA = 1.0

# Replacement-level ranks per position (~last rostered in a 12-team league).
# Deeper than "last starter" so above-average players keep meaningful value.
REPLACEMENT_RANK = {"QB": 18, "RB": 40, "WR": 50, "TE": 16}


def _blended_base(samples: list[tuple[int, int, float]], latest_season: int, recent_cutoff: int) -> float:
    """Recency-weighted ppg from (season, week, points) samples."""
    pts = wt = 0.0
    for season, week, p in samples:
        if season == latest_season:
            w = 2.0 if week >= recent_cutoff else 1.0
        else:
            w = PRIOR_SEASON_WEIGHT
        pts += p * w
        wt += w
    return pts / wt if wt else 0.0


def _momentum_adjust(base: float, recent_points: list[float]) -> float:
    """Nudge the baseline by recent form, damped by tier and amplified by streak.

    recent_points is most-recent-first. Returns the adjusted ppg.
    """
    if base <= 0 or not recent_points:
        return base

    games = recent_points[:RECENT_GAMES]
    w = RECENT_WEIGHTS[: len(games)]
    recent_avg = sum(p * wi for p, wi in zip(games, w)) / sum(w)
    raw_dev = recent_avg - base
    if raw_dev == 0:
        return base

    # Streak: consecutive most-recent games on the same side of the baseline.
    side = 1.0 if raw_dev > 0 else -1.0
    streak = 0
    for p in games:
        if (p - base) * side > 0:
            streak += 1
        else:
            break
    streak = min(streak, 4)
    streak_mult = min(1.0, 0.3 + 0.22 * streak)  # 1 game ~0.52 ... 4 games 1.0

    tier = max(0.0, min(base / ELITE_ANCHOR, 1.0))
    if raw_dev > 0:  # hot streak — muted for low-tier players (don't overrate)
        damp = 0.35 + 0.5 * tier
    else:            # slump — muted for high-tier players (they resist drops)
        damp = 0.85 - 0.5 * tier

    adj = raw_dev * streak_mult * damp * RESPONSIVENESS
    # Keep a single recompute from swinging value wildly
    adj = max(-0.40 * base, min(0.50 * base, adj))
    return max(0.0, base + adj)


def _value_from_vor(adj_ppg: float, replacement: float) -> int:
    vor = max(0.0, adj_ppg - replacement)
    return max(1, round(SCALE * (vor**GAMMA)))


async def compute_player_values(db: AsyncSession) -> dict[str, dict]:
    """player_id -> {value, ppg, base_ppg, trend, games, position, season}."""
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
                Player.position,
            )
            .join(Player, Player.id == PlayerStatsWeekly.player_id)
            .where(
                PlayerStatsWeekly.season >= latest_season - 1,
                PlayerStatsWeekly.week <= REGULAR_SEASON_MAX_WEEK,
                PlayerStatsWeekly.fantasy_points_ppr.is_not(None),
            )
        )
    ).all()
    if not rows:
        return {}

    latest_week = max((r.week for r in rows if r.season == latest_season), default=18)
    recent_cutoff = latest_week - RECENT_WINDOW

    by_player: dict[str, dict] = defaultdict(
        lambda: {"samples": [], "position": None}
    )
    for r in rows:
        e = by_player[r.player_id]
        e["position"] = r.position
        e["samples"].append((r.season, r.week, float(r.fantasy_points_ppr)))

    # First pass: baseline + momentum-adjusted ppg per qualifying player
    computed: dict[str, dict] = {}
    for pid, e in by_player.items():
        if e["position"] not in VALUED_POSITIONS or len(e["samples"]) < MIN_GAMES:
            continue
        samples = e["samples"]
        blended = _blended_base(samples, int(latest_season), recent_cutoff)
        # Peak floor: best single-season average of the last two seasons, so a
        # down/injury year can dent but not crater a proven player.
        season_pts: dict[int, list[float]] = defaultdict(list)
        for season, _wk, p in samples:
            season_pts[season].append(p)
        peak = max(sum(v) / len(v) for v in season_pts.values())
        base = max(blended, PEAK_FLOOR * peak)
        if base <= 0:
            continue
        recent_points = [
            p for _, _, p in sorted(samples, key=lambda s: (s[0], s[1]), reverse=True)
        ]
        adj = _momentum_adjust(base, recent_points)
        computed[pid] = {
            "base": base,
            "adj": adj,
            "peak": peak,
            "games": len(samples),
            "position": e["position"],
        }

    # Replacement level per position from the baseline distribution
    bases_by_pos: dict[str, list[float]] = defaultdict(list)
    for c in computed.values():
        bases_by_pos[c["position"]].append(c["base"])
    replacement: dict[str, float] = {}
    for pos, bases in bases_by_pos.items():
        bases.sort(reverse=True)
        idx = min(REPLACEMENT_RANK.get(pos, len(bases)) - 1, len(bases) - 1)
        replacement[pos] = bases[max(idx, 0)]

    # Second pass: currency value via VOR
    values: dict[str, dict] = {}
    for pid, c in computed.items():
        repl = replacement.get(c["position"], 0.0)
        delta = c["adj"] - c["base"]
        trend = "rising" if delta >= 1 else "falling" if delta <= -1 else "steady"
        # Value can't drop below the proven floor even in a slump; a hot streak
        # (adj above base) still lifts it.
        value_ppg = max(c["adj"], PEAK_FLOOR * c["peak"])
        values[pid] = {
            "value": _value_from_vor(value_ppg, repl),
            "ppg": round(c["adj"], 1),
            "base_ppg": round(c["base"], 1),
            "trend": trend,
            "trend_delta": round(delta, 1),
            "games": c["games"],
            "position": c["position"],
            "season": int(latest_season),
        }
    return values


def side_total(values: dict[str, dict], player_ids: list[str]) -> int:
    """Sum of currency values for one side of a trade; unknowns count 0."""
    return sum(values.get(pid, {}).get("value", 0) for pid in player_ids)

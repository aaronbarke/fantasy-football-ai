"""Player trade-value model.

Assigns every player a 0-100 value from their recency-weighted PPR points
per game, ranked as a percentile within their position. The latest two
seasons are blended (latest counts ~2x) so an established star coming off a
down or injury-shortened year keeps most of their tier — one bad season
shouldn't rate Lamar Jackson like a mid QB2. Recomputed from the stats table
on demand, so values drift week to week as performances change.
"""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerStatsWeekly

# Weeks at or after (latest_week - RECENT_WINDOW) count double — recent form
# matters more than early-season games.
RECENT_WINDOW = 4
MIN_GAMES = 2
VALUED_POSITIONS = {"QB", "RB", "WR", "TE"}
PRIOR_SEASON_WEIGHT = 0.5  # latest season counts double vs the one before


async def compute_player_values(db: AsyncSession) -> dict[str, dict]:
    """value/ppg/games for every player with enough data in the latest season."""
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
                PlayerStatsWeekly.fantasy_points_ppr.is_not(None),
            )
        )
    ).all()
    if not rows:
        return {}

    latest_week = max(r.week for r in rows if r.season == latest_season)
    recent_cutoff = latest_week - RECENT_WINDOW

    weighted: dict[str, dict] = {}
    for r in rows:
        entry = weighted.setdefault(
            r.player_id, {"pts": 0.0, "wt": 0.0, "games": 0, "position": r.position}
        )
        if r.season == latest_season:
            w = 2.0 if r.week >= recent_cutoff else 1.0
        else:
            w = PRIOR_SEASON_WEIGHT
        entry["pts"] += float(r.fantasy_points_ppr) * w
        entry["wt"] += w
        entry["games"] += 1

    by_position: dict[str, list[tuple[str, float]]] = defaultdict(list)
    for pid, e in weighted.items():
        if e["games"] < MIN_GAMES or e["position"] not in VALUED_POSITIONS:
            continue
        ppg = e["pts"] / e["wt"]
        if ppg <= 0:
            continue
        by_position[e["position"]].append((pid, ppg))

    values: dict[str, dict] = {}
    for position, entries in by_position.items():
        entries.sort(key=lambda x: x[1])
        n = len(entries)
        for rank, (pid, ppg) in enumerate(entries):
            pct = rank / (n - 1) if n > 1 else 1.0
            values[pid] = {
                "value": round(5 + 94 * pct),
                "ppg": round(ppg, 1),
                "games": weighted[pid]["games"],
                "position": position,
                "season": int(latest_season),
            }
    return values


def side_total(values: dict[str, dict], player_ids: list[str]) -> int:
    """Sum of values for one side of a trade; unknown players count 0."""
    return sum(values.get(pid, {}).get("value", 0) for pid in player_ids)

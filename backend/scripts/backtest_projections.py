"""Point-in-time backtest of the projection model.

For each week of the test season we predict every rostered-relevant player
using ONLY data available before that week, then compare to what they actually
scored. We benchmark four methods:

  season_avg    — this season's running average (naive)
  our_baseline  — our recency-weighted two-season blend (the model's core)
  sleeper       — Sleeper's published weekly projection
  blend         — 50/50 of our_baseline + sleeper (what the app ships)

Metric is mean absolute error (MAE) in PPR points over all graded player-weeks.
Run:  python -m scripts.backtest_projections
"""

import asyncio
from collections import defaultdict
from statistics import mean

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Player, PlayerStatsWeekly
from app.services.external_proj_service import get_external_projections

TEST_SEASON = 2025
PRIOR_SEASON = 2024
RECENT_WINDOW = 4
PRIOR_SEASON_WEIGHT = 0.5
EXTERNAL_WEIGHT = 0.5
MIN_PRIOR_GAMES = 4
RELEVANT = 6.0  # only grade players we'd actually consider starting
TEST_WEEKS = range(5, 18)  # need a few weeks of prior signal first


def recency_baseline(prior: list[tuple[int, int, float]], target_week: int) -> float:
    this_weeks = [w for (s, w, _) in prior if s == TEST_SEASON]
    cutoff = (max(this_weeks) if this_weeks else 0) - RECENT_WINDOW
    pts = wt = 0.0
    for s, w, p in prior:
        if s == TEST_SEASON:
            wgt = 2.0 if w >= cutoff else 1.0
        else:
            wgt = PRIOR_SEASON_WEIGHT
        pts += p * wgt
        wt += wgt
    return pts / wt if wt else 0.0


async def main() -> None:
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(
                    PlayerStatsWeekly.player_id,
                    PlayerStatsWeekly.season,
                    PlayerStatsWeekly.week,
                    PlayerStatsWeekly.fantasy_points_ppr,
                ).where(
                    PlayerStatsWeekly.season.in_([PRIOR_SEASON, TEST_SEASON]),
                    PlayerStatsWeekly.week <= 18,
                    PlayerStatsWeekly.fantasy_points_ppr.is_not(None),
                )
            )
        ).all()
        by_player: dict[str, list[tuple[int, int, float]]] = defaultdict(list)
        for r in rows:
            by_player[r.player_id].append((r.season, r.week, float(r.fantasy_points_ppr)))
        positions = {
            p.id: p.position
            for p in (await db.execute(select(Player))).scalars().all()
        }

        errs: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for week in TEST_WEEKS:
            sleeper = await get_external_projections(TEST_SEASON, week)
            for pid, games in by_player.items():
                pos = positions.get(pid)
                if pos not in {"QB", "RB", "WR", "TE"}:
                    continue
                actual = next(
                    (p for (s, w, p) in games if s == TEST_SEASON and w == week), None
                )
                if actual is None:
                    continue
                prior = [
                    g for g in games if g[0] < TEST_SEASON or (g[0] == TEST_SEASON and g[1] < week)
                ]
                if len(prior) < MIN_PRIOR_GAMES:
                    continue

                base = recency_baseline(prior, week)
                sl = sleeper.get(pid)
                this_season = [p for (s, _, p) in prior if s == TEST_SEASON]

                preds = {
                    "season_avg": mean(this_season) if this_season else base,
                    "our_baseline": base,
                }
                if sl is not None:
                    preds["sleeper"] = sl
                    preds["blend"] = EXTERNAL_WEIGHT * sl + (1 - EXTERNAL_WEIGHT) * base

                # Grade only players we'd plausibly start (avoid inactive noise)
                if base < RELEVANT and (sl or 0) < RELEVANT:
                    continue
                for m, pred in preds.items():
                    errs[m]["ALL"].append(abs(pred - actual))
                    errs[m][pos].append(abs(pred - actual))

        print(f"Backtest — {TEST_SEASON} weeks {TEST_WEEKS.start}-{TEST_WEEKS.stop - 1}")
        print(f"{'method':<14}{'MAE':>8}{'n':>8}")
        for m in ["season_avg", "our_baseline", "sleeper", "blend"]:
            allerr = errs[m]["ALL"]
            if allerr:
                print(f"{m:<14}{mean(allerr):>8.2f}{len(allerr):>8}")
        print("\nBlend MAE by position:")
        for pos in ["QB", "RB", "WR", "TE"]:
            pe = errs["blend"][pos]
            if pe:
                print(f"  {pos:<4}{mean(pe):>8.2f}  (n={len(pe)})")


if __name__ == "__main__":
    asyncio.run(main())

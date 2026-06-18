# Projection Backtest

Point-in-time backtest of the weekly projection model. For each week of the
2025 season we predict every rostered-relevant player (one we'd plausibly
start — projection ≥ 6 PPR) using **only data available before that week**, then
compare to actual results. Reproduce with:

```bash
cd backend && python -m scripts.backtest_projections
```

## Results — 2025, weeks 5–17

| Method | What it is | MAE (PPR) | n |
|---|---|---:|---:|
| `season_avg` | this season's running average (naive baseline) | 5.91 | 2,405 |
| `our_baseline` | our recency-weighted two-season blend | 5.86 | 2,405 |
| `sleeper` | Sleeper's published weekly projection | 5.66 | 2,374 |
| **`blend`** | **50/50 of our_baseline + sleeper (shipped)** | **5.62** | 2,374 |

**Takeaway:** the blend the app ships is the most accurate of the four — it
beats Sleeper's own projections *and* our model alone, and clearly beats a
naive season average. Blending two independent signals reduces error, which is
why the projection engine combines them.

### Blend error by position

| Pos | MAE (PPR) | n |
|---|---:|---:|
| TE | 5.11 | 403 |
| WR | 5.36 | 970 |
| RB | 5.75 | 637 |
| QB | 6.68 | 364 |

QBs carry the highest absolute error (they score the most points, so the same
% error is more raw points); TE/WR are tightest.

## Notes & honesty

- This backtests the projection's **core** (recency baseline + Sleeper blend).
  The live engine adds small matchup, Vegas-total, and weather nudges on top;
  those need historical odds/weather we don't store, so they're not in this
  measurement — but each is capped small, so the core is what moves MAE.
- MAE ~5.6 PPR/player-week is honest for weekly fantasy, which is high-variance
  by nature; the value is in the *relative* ranking of methods.

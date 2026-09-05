# Fantasy Football AI 🏈🤖

An AI-powered fantasy football assistant that connects to your **real league**
(Sleeper or ESPN), pulls your actual roster, matchups, and waiver wire, and lets
you interact with it through natural language. It combines live NFL data —
injuries, weather, Vegas lines, target shares — with your specific league
context to give grounded, data-backed advice.

> "An AI assistant that knows your fantasy league as well as you do, and never
> forgets to check the injury report."

**🔗 Live:** [fantasy-football-ai-theta.vercel.app](https://fantasy-football-ai-theta.vercel.app) &nbsp;·&nbsp;
one-click **Demo login** on the sign-in page skips signup and lands on a fully seeded league.

**Stack:** Next.js 14 · TypeScript · Tailwind · FastAPI (Python 3.13, async) · PostgreSQL 16 · Redis (optional cache) · Claude API · APScheduler · Docker · Vercel + Railway

### Why this project

- **Full-stack + ML from scratch, shipped.** Custom weekly-projection model that
  **beats Sleeper's own projections on backtested MAE** (5.62 vs 5.66 PPR,
  point-in-time-safe — see [`documents/backtest_results.md`](documents/backtest_results.md)).
- **Grounded LLM, not a chatbot wrapper.** Every AI reply runs through intent
  classification → typed context assembly → structured prompting, with a
  `context_snapshot` audit trail of exactly what the model saw. No hallucinated
  stats.
- **Real integrations.** Live sync with Sleeper + ESPN league APIs (including
  private-league cookie auth), nflverse parquet stats, Open-Meteo weather, and
  The Odds API for a working sportsbook **arbitrage detector**.
- **Production-shaped.** 43 backend unit tests, CI on every push
  (ruff + pytest + frontend typecheck/lint), production-hardened boot checks
  (rejects default JWT secret, gates admin endpoints, blocks demo-account
  mutations), Dockerfiles for both services.

## What's in it

- **Weekly Game Plan** — one click builds the projection-optimal lineup, flags
  start/sit swaps vs your current starters, projects your score, and computes
  win probability against this week's opponent. An AI coach's brief explains
  every call.
- **Projection engine** — per-player weekly projections (floor/ceiling bands)
  that blend our two-season recency-weighted model with Sleeper's weekly
  projection, then nudge for defense-vs-position matchup, Vegas implied total,
  and game-day weather.
- **AI chat with receipts** — streaming answers grounded in your roster, live
  stats, matchup difficulty, weather, and betting lines. Start/sit calls are
  recorded and graded against actual results.
- **Trade analyzer** — market-style player value from Value Over Replacement
  with tier-damped momentum (a star's down week doesn't crater him; a scrub's
  one big game doesn't overrate him), a peak floor, and a roster floor.
  Scale-independent grading, roster-fit context, trend arrows, and sweetener
  suggestions to even lopsided deals.
- **Betting edge** — live line shopping across regulated US sportsbooks. Best
  price on every moneyline / spread / total, plus a true **arbitrage detector**
  that flags guaranteed-profit splits, ranked by how much the books disagree.
- **Draft assistant**, schedule-strength heatmap through the fantasy-playoff
  weeks, player compare, multi-league switcher, injury email alerts, dark mode,
  and an installable PWA.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│   Next.js 14 Frontend (TypeScript + Tailwind)        │
│   Dashboard · Chat · Roster · Matchup · Waivers      │
└──────────────────────┬───────────────────────────────┘
                       │ REST (JWT auth)
┌──────────────────────▼───────────────────────────────┐
│   FastAPI Backend (Python 3.13, async)               │
│                                                       │
│   League Service     NFL Data Service   AI Engine    │
│   ├─ Sleeper API     ├─ nflverse        ├─ intent    │
│   └─ ESPN API        ├─ ESPN injuries   │  classifier│
│                      ├─ Open-Meteo      ├─ context   │
│                      └─ The Odds API    │  builder   │
│                                         └─ Claude    │
│   APScheduler: stats, injuries, odds, weather, sync  │
└──────────────────────┬───────────────────────────────┘
                       │
        PostgreSQL 16 (+ Redis cache)
```

### How the AI chat actually works

It doesn't just forward your question to Claude. Each reply runs through:

1. **Intent classification** — start/sit, trade, waiver, matchup, or general.
2. **Context assembly** — the builder pulls exactly the data needed for that
   intent: your roster, mentioned players' last-5-week stats, injury status,
   the matchup's Vegas spread/implied totals, and stadium weather.
3. **Structured prompting** — that data goes in as JSON alongside a system
   prompt with strict grounding rules ("never make up stats").
4. **Audit trail** — every response stores a `context_snapshot` of exactly what
   data the model saw, so past advice can be graded against how the week
   actually played out.

## Models & validation

The **projection blend** (`projection_service.py`) mixes two independent
signals — our recency-weighted two-season baseline and Sleeper's published
weekly projection (50/50) — then nudges for matchup, Vegas implied total, and
weather. Point-in-time backtest against 2025 actuals (predict each week from
prior-only data, `python -m scripts.backtest_projections`):

| Method | MAE (PPR) |
|---|---:|
| Naive season average | 5.91 |
| Our baseline only | 5.86 |
| Sleeper only | 5.66 |
| **Blend (shipped)** | **5.62** |

The blend beats Sleeper's own projections *and* our model alone — full writeup
in [`documents/backtest_results.md`](documents/backtest_results.md).

The **trade value** (`value_service.py`) is a single number derived from Value
Over Replacement, so it's comparable across positions and behaves like a market:

- **Peak floor** — a proven player can't fall below 90% of his better of the
  last two seasons, so a down / injury year dents but doesn't crater him.
- **Tier-damped, streak-aware momentum** — a high-value player's lone cold game
  barely moves him; a low-value player's lone hot game barely moves him; only
  *consecutive* weeks compound, in either direction.
- **Roster floor** — every rosterable player carries a baseline, so flex-type
  contributors aren't valued at ~0.

## Data sources (all free)

| Source | Data |
|---|---|
| Sleeper API | Leagues, rosters, matchups, trending adds, full player DB |
| ESPN Fantasy API | ESPN league rosters (cookie auth for private leagues) |
| nflverse (parquet via httpx) | Weekly stats, target share, ID crosswalk |
| Sleeper projections | Weekly per-player projections (blended into ours) |
| ESPN public API | Injury reports |
| Open-Meteo | Stadium weather |
| The Odds API | Spreads & totals → implied team totals |

## Testing & CI

43 backend unit tests cover the value model (momentum damping, streak
compounding, roster floor), trade grading, betting arbitrage + book filtering,
weather adjustment, projection win-probability, lineup optimization, intent
classification, and fantasy scoring math. GitHub Actions runs `ruff + pytest`
and the frontend `typecheck + lint` on every push.

## Deployment

Frontend on **Vercel**, backend + **PostgreSQL** on **Railway**. Both services
ship with Dockerfiles; Redis is an optional cache and the app degrades
gracefully without it. Full prod env matrix and step-by-step in
[`docs/DEPLOY.md`](docs/DEPLOY.md). Production boots refuse the default
`JWT_SECRET`, admin endpoints require `ADMIN_EMAILS`, and the shared demo
account is blocked from mutating actions.

## Running it locally

Postgres + Redis via `docker compose up -d postgres redis`, backend with
`uvicorn app.main:app --reload` in `backend/` (after
`pip install -r requirements-dev.txt` and filling in `.env` from
`.env.example`), frontend with `npm run dev` in `frontend/`. Or bring the whole
stack up in one shot with `docker compose up --build`. First-time seed script
and full env matrix in [`docs/DEPLOY.md`](docs/DEPLOY.md).

## Roadmap

- Yahoo integration (OAuth)
- Push notifications for injury alerts (email alerts already ship)
- Historical odds / weather so the full projection (not just its core) is
  backtestable
- Dynasty mode: draft-pick values + rest-of-season vs this-week toggle

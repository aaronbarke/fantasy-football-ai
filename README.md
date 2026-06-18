# Fantasy Football AI 🏈🤖

An AI-powered fantasy football assistant that connects to your **real league**
(Sleeper or ESPN), pulls your actual roster, matchups, and waiver wire, and lets
you interact with it through natural language. It combines live NFL data —
injuries, weather, Vegas lines, target shares — with your specific league
context to give grounded, data-backed advice.

> "An AI assistant that knows your fantasy league as well as you do, and never
> forgets to check the injury report."

## Feature highlights

- **Weekly Game Plan** — one click builds the projection-optimal lineup,
  flags start/sit swaps vs your current starters, projects your score, and
  computes win probability against this week's opponent — then an AI coach's
  brief explains every call.
- **Projection engine** — per-player weekly projections (floor/ceiling bands)
  that **blend our two-season recency-weighted model with Sleeper's weekly
  projection**, plus defense-vs-position matchup, Vegas implied-total, and
  game-day weather adjustments. Backtested against actuals (see
  [Models & validation](#models--validation)).
- **AI chat with receipts** — streaming answers grounded in your roster,
  live stats, matchup difficulty, weather, and betting lines. Start/sit calls
  are recorded and graded against actual results (the accuracy tracker).
- **Trade analyzer** — a market-style player value from **Value Over
  Replacement** with tier-damped momentum (a star's down week doesn't crater
  him; a scrub's one big game doesn't overrate him), a peak floor, and a roster
  floor. Scale-independent grading, roster-fit (depth before/after), trend
  arrows, and sweetener suggestions to even lopsided deals.
- **Betting edge** — live line shopping across *regulated* US sportsbooks: best
  price on every moneyline/spread/total, a true **arbitrage detector** that
  flags guaranteed-profit splits, ranked by how much the books disagree.
- **Auth** — email/password, one-click **demo login** (seeded with a populated
  league), and optional **Google sign-in**.
- **Draft assistant, schedule-strength heatmap (incl. fantasy playoffs, Wk
  15-17), player comparison charts, player headshots, multi-league switcher,
  injury email alerts, dark mode, installable PWA.**

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

### How the AI chat works

It does **not** just forward your question to Claude:

1. **Intent classification** — start/sit, trade, waiver, matchup, or general
2. **Context assembly** — based on intent, the context builder pulls exactly the
   data needed: your roster, the mentioned players' last-5-week stats, injury
   status, the matchup's Vegas spread/implied totals, and stadium weather
3. **Structured prompting** — the data is injected as JSON into a system+user
   prompt with strict grounding rules ("never make up stats")
4. **Audit trail** — every response stores a `context_snapshot` of exactly what
   data the AI saw when it gave that advice

## Models & validation

**Projection** (`projection_service.py`) blends two independent signals — our
recency-weighted two-season baseline and Sleeper's published weekly projection
(50/50) — then nudges for matchup, Vegas implied total, and weather. A
point-in-time **backtest** (predict each 2025 week from prior-only data,
compare to actuals; `python -m scripts.backtest_projections`) shows the blend
is the most accurate option:

| Method | MAE (PPR) |
|---|---:|
| Naive season average | 5.91 |
| Our baseline only | 5.86 |
| Sleeper only | 5.66 |
| **Blend (shipped)** | **5.62** |

The blend beats Sleeper's own projections *and* our model alone — full writeup
in [`documents/backtest_results.md`](documents/backtest_results.md).

**Trade value** (`value_service.py`) is a single number from Value Over
Replacement, so it's comparable across positions and behaves like a market:

- **Peak floor** — a proven player can't fall below 90% of his better of the
  last two seasons, so a down/injury year dents but doesn't crater him.
- **Tier-damped, streak-aware momentum** — a high-value player's lone cold game
  barely moves him; a low-value player's lone hot game barely moves him; only
  *consecutive* weeks compound, in either direction.
- **Roster floor** — every rosterable player carries a baseline (you can't
  acquire a real contributor for nothing), so flex types aren't valued at ~0.

## Quickstart (local dev)

```bash
# 1. Infra: Postgres + Redis
docker compose up -d postgres redis

# 2. Backend
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env          # add your ANTHROPIC_API_KEY
uvicorn app.main:app --reload  # http://localhost:8000/docs

# 3. Frontend
cd ../frontend
npm install
npm run dev                    # http://localhost:3000
```

Or run everything in Docker: `docker compose up --build`.

### First-time data load

After the backend is running, seed the player database and stats (one-time;
afterwards the scheduler keeps them fresh when `ENABLE_SCHEDULER=true`):

```bash
cd backend && source .venv/bin/activate
python -c "
import asyncio
from app.database import SessionLocal, create_all
from app.services.sync_service import sync_player_pool
from app.services.nfl_data_service import sync_id_crosswalk, sync_weekly_stats

async def seed():
    await create_all()
    async with SessionLocal() as db:
        await sync_player_pool(db)        # ~2k fantasy players from Sleeper
        await sync_id_crosswalk(db)       # gsis/espn/yahoo ID mapping
        await sync_weekly_stats(db, [2024, 2025])  # two seasons (the model blends both)

asyncio.run(seed())
"
```

Then open http://localhost:3000, create an account, and connect your Sleeper
league by username.

## Configuration

| Variable | Purpose |
|---|---|
| `DATABASE_URL` | Postgres (or sqlite for quick dev) |
| `ANTHROPIC_API_KEY` | Powers the AI chat (chat returns a setup notice without it) |
| `ODDS_API_KEY` | Free key from the-odds-api.com — Vegas lines + betting page |
| `JWT_SECRET` | Auth signing key (required in production) |
| `ENVIRONMENT` | `development` or `production` (gates secret/admin checks) |
| `ADMIN_EMAILS` | Comma-separated emails allowed to hit admin endpoints |
| `GOOGLE_CLIENT_ID` | Optional — enables Google sign-in (no secret needed) |
| `ENABLE_SCHEDULER` | `true` to run background data refresh jobs |
| `CURRENT_SEASON` | NFL season year |

## Data sources (all free)

| Source | Data |
|---|---|
| Sleeper API | Leagues, rosters, matchups, trending adds, full player DB |
| ESPN Fantasy API | ESPN league rosters (cookie auth for private leagues) |
| nflverse (parquet via httpx) | Weekly stats, target share, ID crosswalk |
| Sleeper projections | Weekly per-player projections (blended into ours) |
| ESPN public API | Injury reports |
| Open-Meteo | Stadium weather (no key needed) |
| The Odds API | Spreads & totals → implied team totals |

## Testing

```bash
cd backend && ruff check app tests && pytest   # 43 unit tests
cd frontend && npm run typecheck && npm run lint
```

Backend tests cover the value model (momentum damping, streak compounding,
roster floor), trade grading, betting arbitrage + book filtering, weather
adjustment, projection win-probability, lineup optimization, intent
classification, and fantasy scoring math. **CI** (`.github/workflows/ci.yml`)
runs ruff + pytest and the frontend typecheck + lint on every push.

## Deployment

Frontend on Vercel, backend + Postgres + Redis on Railway (Dockerfiles
included). Step-by-step with the full prod env matrix:
[`docs/DEPLOY.md`](docs/DEPLOY.md). In production the backend refuses to boot
with the default `JWT_SECRET`, admin endpoints require `ADMIN_EMAILS`, and the
shared demo account is blocked from mutating actions.

## Roadmap

- [ ] Yahoo integration (OAuth)
- [ ] Push notifications for injury alerts (email alerts already ship)
- [ ] Historical odds/weather so the full projection (not just its core) is
      backtestable
- [ ] Dynasty mode: draft-pick values + rest-of-season vs this-week toggle

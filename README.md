# Fantasy Football AI 🏈🤖

An AI-powered fantasy football assistant that connects to your **real league**
(Sleeper or ESPN), pulls your actual roster, matchups, and waiver wire, and lets
you interact with it through natural language. It combines live NFL data —
injuries, weather, Vegas lines, target shares — with your specific league
context to give grounded, data-backed advice.

> "An AI assistant that knows your fantasy league as well as you do, and never
> forgets to check the injury report."

## Architecture

```
┌─────────────────────────────────────────────────────┐
│   Next.js 14 Frontend (TypeScript + Tailwind)        │
│   Dashboard · Chat · Roster · Matchup · Waivers      │
└──────────────────────┬───────────────────────────────┘
                       │ REST (JWT auth)
┌──────────────────────▼───────────────────────────────┐
│   FastAPI Backend (Python 3.12, async)               │
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
        await sync_weekly_stats(db, [2025])  # last season's weekly stats

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
| `ODDS_API_KEY` | Free key from the-odds-api.com — Vegas lines |
| `ENABLE_SCHEDULER` | `true` to run background data refresh jobs |
| `CURRENT_SEASON` | NFL season year |

## Data sources (all free)

| Source | Data |
|---|---|
| Sleeper API | Leagues, rosters, matchups, trending adds, full player DB |
| ESPN Fantasy API | ESPN league rosters (cookie auth for private leagues) |
| nflverse (`nfl_data_py`) | Weekly stats, target share, ID crosswalk |
| ESPN public API | Injury reports |
| Open-Meteo | Stadium weather (no key needed) |
| The Odds API | Spreads & totals → implied team totals |

## Testing

```bash
cd backend && pytest          # unit tests (fantasy math, intent, Sleeper client)
cd frontend && npm run typecheck && npm run build
```

CI runs lint + tests + build on every push via GitHub Actions.

## Deployment

- **Frontend** → Vercel (set `NEXT_PUBLIC_API_URL`)
- **Backend + Postgres + Redis** → Railway or Fly.io (Dockerfile included);
  set `ENABLE_SCHEDULER=true` on exactly one instance
- **Migrations** → `alembic upgrade head` (reads `DATABASE_URL`)

## Roadmap

- [ ] Yahoo integration (OAuth)
- [ ] Streaming chat responses (SSE)
- [ ] Draft assistant mode
- [ ] Push notifications for injury alerts
- [ ] AI accuracy leaderboard (did start/sit calls beat the alternative?)

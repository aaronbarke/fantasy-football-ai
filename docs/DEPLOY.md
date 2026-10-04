# Deploying FFAI

Recommended split: **frontend on Vercel**, **backend + Postgres + Redis on
Railway** (Render or Fly work too — the backend ships a Dockerfile). Everything
below is free-tier-friendly.

## 1. Backend (Railway)

1. New project → **Deploy from GitHub repo**, root directory `backend/`.
   Railway auto-detects the `Dockerfile`.
2. Add a **PostgreSQL** plugin and a **Redis** plugin to the project.
3. Set environment variables on the backend service:

   | Var | Value |
   |---|---|
   | `ENVIRONMENT` | `production` |
   | `DATABASE_URL` | `postgresql+asyncpg://…` (from the Postgres plugin; swap the scheme to `postgresql+asyncpg`) |
   | `REDIS_URL` | from the Redis plugin |
   | `JWT_SECRET` | 32+ random characters, e.g. `openssl rand -hex 32` (the app refuses to boot in prod with the default, and warns if it's short) |
   | `ANTHROPIC_API_KEY` | your Anthropic key |
   | `ODDS_API_KEY` | your The-Odds-API key (betting page) |
   | `GOOGLE_CLIENT_ID` | optional — enables Google sign-in |
   | `ADMIN_EMAILS` | your email, to allow `/api/admin/refresh-stats` |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://ffai.vercel.app` |
   | `ENABLE_SCHEDULER` | `true` (weekly stats/odds/injury refresh) |
   | `CURRENT_SEASON` | e.g. `2026` |
   | `CREDENTIALS_KEY` | optional — Fernet key for the stored ESPN cookies (see `.env.example`); unset, it's derived from `JWT_SECRET` |
   | `TRUSTED_PROXY_COUNT` | optional — proxies in front of the API (default `1` in production, which fits Railway) |
   | `AI_DAILY_LIMIT_PER_USER` / `AI_DAILY_LIMIT_DEMO_PER_IP` / `AI_DAILY_LIMIT_DEMO_TOTAL` | optional — daily Claude-call caps (defaults 100 / 20 / 300) |

4. Deploy. Note the public backend URL (e.g. `https://ffai-api.up.railway.app`).
5. **Seed the database once** (the schema auto-creates on boot via
   `create_all`; you still need player/stat data): run the seed the same way you
   do locally, pointed at the prod `DATABASE_URL`. After that, the scheduler keeps
   it fresh, or hit `POST /api/admin/refresh-stats` as an admin.
6. **Seed the demo league fixture** (canned 10-team league the public "Try a
   demo" login lands on — see `backend/scripts/seed_demo_league.py`). Run it
   once from the Railway shell so first-time visitors see a fake league, not
   another user's real rosters:
   ```bash
   python -m scripts.seed_demo_league
   ```
   Idempotent — no-op on subsequent runs once the demo user has a league.

## 2. Frontend (Vercel)

1. Import the repo, set **Root Directory** to `frontend/`.
2. Environment variables:

   | Var | Value |
   |---|---|
   | `NEXT_PUBLIC_API_URL` | the backend URL from step 1 |
   | `NEXT_PUBLIC_GOOGLE_CLIENT_ID` | optional — same Client ID as the backend |

3. Deploy. Then set the backend's `CORS_ORIGINS` to the resulting Vercel URL and
   redeploy the backend.

## Local full stack (Docker)

`docker compose up` brings up Postgres + Redis + the backend together (see
`docker-compose.yml`). Run the frontend with `npm run dev` against it.

## Notes

- The backend **fails fast in production** if `JWT_SECRET` is still the default.
- Admin endpoints require your email in `ADMIN_EMAILS`; the shared demo account
  is blocked from sync/claim/admin actions. Every address in `ADMIN_EMAILS`
  should already have an account — signup doesn't verify email ownership, so an
  unclaimed admin address could be registered by someone else.
- Security posture in production: `/docs` and `/openapi.json` are off, CORS
  allows only `CORS_ORIGINS`, every Claude-backed route is rate limited and
  capped per day (the demo shares one pool), ESPN cookies are encrypted at
  rest, and each demo visitor's chat stays in memory for their session instead
  of the shared account's history.
- Rotating `JWT_SECRET` signs everyone out, and — unless `CREDENTIALS_KEY` is
  set — makes stored ESPN cookies unreadable, so private ESPN leagues need to
  reconnect.
- A `frontend/Dockerfile` is included for platforms that build via Docker, but
  Vercel is simpler for Next.js. `NEXT_PUBLIC_*` vars are baked at build time, so
  pass them as build args when using the Dockerfile.

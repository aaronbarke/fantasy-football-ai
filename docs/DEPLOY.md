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
   | `JWT_SECRET` | a long random string (the app refuses to boot in prod without one) |
   | `ANTHROPIC_API_KEY` | your Anthropic key |
   | `ODDS_API_KEY` | your The-Odds-API key (betting page) |
   | `GOOGLE_CLIENT_ID` | optional — enables Google sign-in |
   | `ADMIN_EMAILS` | your email, to allow `/api/admin/refresh-stats` |
   | `CORS_ORIGINS` | your Vercel URL, e.g. `https://ffai.vercel.app` |
   | `ENABLE_SCHEDULER` | `true` (weekly stats/odds/injury refresh) |
   | `CURRENT_SEASON` | e.g. `2026` |

4. Deploy. Note the public backend URL (e.g. `https://ffai-api.up.railway.app`).
5. **Seed the database once** (the schema auto-creates on boot via
   `create_all`; you still need player/stat data): run the seed the same way you
   do locally, pointed at the prod `DATABASE_URL`. After that, the scheduler keeps
   it fresh, or hit `POST /api/admin/refresh-stats` as an admin.

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
  is blocked from sync/claim/admin actions.
- A `frontend/Dockerfile` is included for platforms that build via Docker, but
  Vercel is simpler for Next.js. `NEXT_PUBLIC_*` vars are baked at build time, so
  pass them as build args when using the Dockerfile.

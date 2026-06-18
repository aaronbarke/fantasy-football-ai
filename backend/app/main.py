import logging
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import create_all
from app.routers import (
    admin,
    auth,
    betting,
    chat,
    gameplan,
    games,
    leagues,
    players,
    recommendations,
    trade,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)


logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-secret-do-not-use-in-prod"


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.jwt_secret == DEFAULT_JWT_SECRET:
        if settings.is_production:
            raise RuntimeError(
                "JWT_SECRET is still the default — set a strong secret in production."
            )
        logger.warning("Using the default JWT secret — fine for dev, NOT for production.")
    # Dev convenience; production schema is managed by Alembic
    await create_all()
    if settings.enable_scheduler:
        from app.jobs.scheduler import start_scheduler

        start_scheduler()
    yield


app = FastAPI(
    title="Fantasy Football AI",
    description="AI-powered fantasy football assistant with live NFL data",
    version="1.0.0",
    lifespan=lifespan,
)

# Lightweight per-IP rate limiting (in-memory; single-instance). Added before
# CORS so CORS stays the outermost middleware and still tags 429 responses.
_RATE_RULES = [
    ("/api/auth", 30, 60),    # brute-force protection on login/register/demo
    ("/api/admin", 5, 60),    # expensive data pulls
    ("/api/chat", 40, 60),    # AI cost
    ("/api/trade", 30, 60),   # AI cost
]
_rate_hits: dict[str, deque] = defaultdict(deque)


@app.middleware("http")
async def rate_limiter(request: Request, call_next):
    path = request.url.path
    for prefix, limit, window in _RATE_RULES:
        if path.startswith(prefix):
            ip = request.client.host if request.client else "?"
            now = time.monotonic()
            dq = _rate_hits[f"{ip}{prefix}"]
            while dq and dq[0] < now - window:
                dq.popleft()
            if len(dq) >= limit:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — slow down a moment."},
                )
            dq.append(now)
            break
    return await call_next(request)


app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
    # Accept any localhost port in local dev (3000, 3001, …) so the frontend
    # works no matter which port Next.js grabs.
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(leagues.router)
app.include_router(players.router)
app.include_router(chat.router)
app.include_router(games.router)
app.include_router(trade.router)
app.include_router(recommendations.router)
app.include_router(betting.router)
app.include_router(gameplan.router)
app.include_router(admin.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

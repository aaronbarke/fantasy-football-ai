import logging
import re
from contextlib import asynccontextmanager

import anthropic
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.database import create_all
from app.routers import (
    accuracy,
    admin,
    auth,
    betting,
    chat,
    draft,
    gameplan,
    games,
    leagues,
    mock_draft,
    players,
    recommendations,
    trade,
)
from app.utils.limits import client_ip, rate_windows

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
# httpx logs every outbound request URL at INFO, query string included — which
# would write The Odds API key and Google ID tokens into the logs.
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)


logger = logging.getLogger(__name__)

DEFAULT_JWT_SECRET = "dev-secret-do-not-use-in-prod"
MIN_JWT_SECRET_LENGTH = 32


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    if settings.jwt_secret == DEFAULT_JWT_SECRET:
        if settings.is_production:
            raise RuntimeError(
                "JWT_SECRET is still the default — set a strong secret in production."
            )
        logger.warning("Using the default JWT secret — fine for dev, NOT for production.")
    elif settings.is_production and len(settings.jwt_secret) < MIN_JWT_SECRET_LENGTH:
        # Anyone can mint a demo token, so a short secret can be brute-forced
        # offline from it. Warn rather than refuse to boot a running deploy.
        logger.warning(
            "JWT_SECRET is shorter than %d characters — replace it with a long "
            "random value (e.g. `openssl rand -hex 32`).",
            MIN_JWT_SECRET_LENGTH,
        )
    # Dev convenience; production schema is managed by Alembic
    await create_all()
    if settings.enable_scheduler:
        from app.jobs.scheduler import start_scheduler

        start_scheduler()
    yield


_settings = get_settings()

app = FastAPI(
    title="Fantasy Football AI",
    description="AI-powered fantasy football assistant with live NFL data",
    version="1.0.0",
    lifespan=lifespan,
    # The interactive docs map every endpoint for anyone who finds them; keep
    # them to local development.
    docs_url=None if _settings.is_production else "/docs",
    redoc_url=None if _settings.is_production else "/redoc",
    openapi_url=None if _settings.is_production else "/openapi.json",
)

# Lightweight per-IP rate limiting (in-memory; single-instance). First matching
# rule wins. Added before CORS so CORS stays the outermost middleware and still
# tags 429 responses.
_RATE_RULES = [
    (re.compile(r"/api/auth/"), 30, 60),  # brute-force protection on login/register/demo
    (re.compile(r"/api/admin/"), 5, 60),  # expensive data pulls
    # Anything that calls Claude (AI cost)
    (
        re.compile(
            r"/api/(chat|trade/analyze|draft/advice|betting/analysis|gameplan/[^/]+/brief)"
        ),
        20,
        60,
    ),
    # Anything that makes us call Sleeper/ESPN on the caller's behalf
    (re.compile(r"/api/leagues/(connect|sleeper/lookup|[^/]+/sync)"), 10, 60),
    (re.compile(r"/api/mock/?$"), 20, 60),  # starting a mock simulates a whole room
    (re.compile(r"/api/"), 300, 60),  # everything else
]

MAX_BODY_BYTES = 1_000_000

_API_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}
_DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")


@app.middleware("http")
async def guard_requests(request: Request, call_next):
    path = request.url.path

    length = request.headers.get("content-length")
    if length and length.isdigit() and int(length) > MAX_BODY_BYTES:
        return JSONResponse(status_code=413, content={"detail": "Request body too large."})

    for pattern, limit, window in _RATE_RULES:
        if pattern.match(path):
            if not rate_windows.hit(f"{client_ip(request)} {pattern.pattern}", limit, window):
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests — slow down a moment."},
                )
            break

    response = await call_next(request)

    if not path.startswith(_DOCS_PATHS):
        for name, value in _API_SECURITY_HEADERS.items():
            response.headers.setdefault(name, value)
    if path.startswith("/api/"):
        # Responses carry league/roster/chat data; keep them out of caches.
        response.headers.setdefault("Cache-Control", "no-store")
    if _settings.is_production:
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
        )
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    # Accept any localhost port in local dev (3000, 3001, …) so the frontend
    # works no matter which port Next.js grabs. Never in production.
    allow_origin_regex=None if _settings.is_production else r"http://(localhost|127\.0\.0\.1):\d+",
    # Auth is a bearer token in the Authorization header, never a cookie.
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
)

@app.exception_handler(anthropic.APIError)
async def anthropic_error(request: Request, exc: anthropic.APIError):
    """A failed Claude call (bad/revoked key, no credit, outage, rate limit)
    would otherwise escape as a bare 500 from the outermost middleware — with
    no CORS headers, so the browser only says "Failed to fetch". Handled here,
    the response passes back through CORS and the page can show the message.
    Details stay in the log: they can name accounts, request ids and quota."""
    logger.error(
        "Anthropic call failed on %s: %s %s",
        request.url.path,
        type(exc).__name__,
        getattr(exc, "status_code", ""),
    )
    busy = isinstance(exc, (anthropic.RateLimitError, anthropic.APITimeoutError)) or (
        getattr(exc, "status_code", None) == 529
    )
    message = (
        "The AI service is busy right now — try again in a moment."
        if busy
        else "The AI service is unavailable right now — please try again later."
    )
    return JSONResponse(status_code=503, content={"detail": message})


app.include_router(auth.router)
app.include_router(leagues.router)
app.include_router(players.router)
app.include_router(chat.router)
app.include_router(games.router)
app.include_router(trade.router)
app.include_router(recommendations.router)
app.include_router(betting.router)
app.include_router(gameplan.router)
app.include_router(draft.router)
app.include_router(mock_draft.router)
app.include_router(admin.router)
app.include_router(accuracy.router)


@app.get("/health")
async def health():
    return {"status": "ok"}

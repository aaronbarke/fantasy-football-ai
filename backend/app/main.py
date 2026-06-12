import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.database import create_all
from app.routers import (
    auth,
    betting,
    chat,
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
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

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origin_list,
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


@app.get("/health")
async def health():
    return {"status": "ok"}

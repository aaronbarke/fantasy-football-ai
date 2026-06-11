"""Background jobs (APScheduler). Enabled via ENABLE_SCHEDULER=true.

Cadence:
- Weekly stats: Tuesday 6 AM CT (Monday night stats finalize overnight)
- Player pool: daily 5 AM CT (Sleeper asks for max 1 call/day on /players/nfl)
- Injuries: every 4 hours
- Odds: 8 AM + 8 PM CT (free tier budget: 500 req/month)
- League sync: every 2 hours
- Weather: Thu–Mon 6 AM + noon CT (game days only)
"""

import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select

from app.config import get_settings
from app.database import SessionLocal
from app.models import GameCondition, LeagueConnection
from app.services.injury_service import sync_injuries
from app.services.nfl_data_service import sync_id_crosswalk, sync_weekly_stats
from app.services.odds_service import sync_odds
from app.services.sleeper_service import SleeperClient
from app.services.sync_service import sync_league, sync_player_pool
from app.services.weather_service import get_game_weather

logger = logging.getLogger(__name__)

scheduler = AsyncIOScheduler(timezone="US/Central")


async def _current_week() -> int:
    client = SleeperClient()
    try:
        state = await client.get_nfl_state()
        return int(state.get("week") or 1)
    finally:
        await client.close()


async def job_refresh_weekly_stats() -> None:
    settings = get_settings()
    seasons = [settings.current_season - 1, settings.current_season]
    async with SessionLocal() as db:
        await sync_id_crosswalk(db)
        await sync_weekly_stats(db, seasons)


async def job_refresh_player_pool() -> None:
    async with SessionLocal() as db:
        await sync_player_pool(db)


async def job_refresh_injuries() -> None:
    async with SessionLocal() as db:
        await sync_injuries(db)


async def job_refresh_odds() -> None:
    settings = get_settings()
    week = await _current_week()
    async with SessionLocal() as db:
        await sync_odds(db, settings.current_season, week)


async def job_sync_all_leagues() -> None:
    async with SessionLocal() as db:
        conns = (await db.execute(select(LeagueConnection))).scalars().all()
        for conn in conns:
            try:
                await sync_league(db, conn)
            except Exception:
                logger.exception("League sync failed for %s", conn.league_id)


async def job_refresh_weather() -> None:
    settings = get_settings()
    week = await _current_week()
    async with SessionLocal() as db:
        games = (
            (
                await db.execute(
                    select(GameCondition).where(
                        GameCondition.season == settings.current_season,
                        GameCondition.week == week,
                        GameCondition.game_time.is_not(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for game in games:
            try:
                wx = await get_game_weather(game.home_team, game.game_time)
                game.temp_f = wx.get("temp_f")
                game.wind_mph = wx.get("wind_mph")
                game.precipitation_pct = wx.get("precipitation_pct")
            except Exception:
                logger.exception("Weather fetch failed for %s", game.home_team)
        await db.commit()


def start_scheduler() -> None:
    scheduler.add_job(
        job_refresh_weekly_stats,
        CronTrigger(day_of_week="tue", hour=6),
        id="weekly_stats",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_refresh_player_pool,
        CronTrigger(hour=5),
        id="player_pool",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_refresh_injuries,
        IntervalTrigger(hours=4),
        id="injuries",
        misfire_grace_time=600,
    )
    scheduler.add_job(
        job_refresh_odds,
        CronTrigger(hour="8,20"),
        id="odds",
        misfire_grace_time=3600,
    )
    scheduler.add_job(
        job_sync_all_leagues,
        IntervalTrigger(hours=2),
        id="league_sync",
        misfire_grace_time=600,
    )
    scheduler.add_job(
        job_refresh_weather,
        CronTrigger(day_of_week="thu,fri,sat,sun,mon", hour="6,12"),
        id="weather",
        misfire_grace_time=3600,
    )
    scheduler.start()
    logger.info("Background scheduler started with %d jobs", len(scheduler.get_jobs()))

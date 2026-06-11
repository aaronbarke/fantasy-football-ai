"""Vegas lines from The Odds API. Free tier: 500 requests/month — the sync
job calls twice daily, well within budget. Implied team totals derived from
spread + over/under are among the best predictors of fantasy scoring."""

import logging
from datetime import datetime

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.models import GameCondition
from app.utils.constants import STADIUMS, TEAM_NAME_TO_ABBR
from app.utils.fantasy_math import implied_totals

logger = logging.getLogger(__name__)

ODDS_URL = "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds/"


async def fetch_odds() -> list[dict]:
    settings = get_settings()
    if not settings.odds_api_key:
        logger.warning("ODDS_API_KEY not set — skipping odds fetch")
        return []
    params = {
        "apiKey": settings.odds_api_key,
        "regions": "us",
        "markets": "spreads,totals",
        "oddsFormat": "american",
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(ODDS_URL, params=params)
        resp.raise_for_status()
        return resp.json()


def parse_game_odds(game: dict) -> dict | None:
    """Extract home spread + total from the first bookmaker carrying both."""
    home_name = game.get("home_team", "")
    away_name = game.get("away_team", "")
    home = TEAM_NAME_TO_ABBR.get(home_name)
    away = TEAM_NAME_TO_ABBR.get(away_name)
    if not home or not away:
        return None

    spread = total = None
    for book in game.get("bookmakers", []):
        for market in book.get("markets", []):
            if market["key"] == "spreads" and spread is None:
                for outcome in market.get("outcomes", []):
                    if outcome.get("name") == home_name:
                        spread = float(outcome.get("point", 0))
            elif market["key"] == "totals" and total is None:
                outcomes = market.get("outcomes", [])
                if outcomes:
                    total = float(outcomes[0].get("point", 0))
        if spread is not None and total is not None:
            break

    return {
        "home_team": home,
        "away_team": away,
        "game_time": datetime.fromisoformat(game["commence_time"].replace("Z", "+00:00")),
        "spread": spread,
        "over_under": total,
    }


async def sync_odds(db: AsyncSession, season: int, week: int) -> int:
    """Upsert current lines into game_conditions for the given week."""
    games = await fetch_odds()
    count = 0
    for game in games:
        parsed = parse_game_odds(game)
        if parsed is None:
            continue

        existing = (
            await db.execute(
                select(GameCondition).where(
                    GameCondition.season == season,
                    GameCondition.week == week,
                    GameCondition.home_team == parsed["home_team"],
                )
            )
        ).scalar_one_or_none()

        if existing is None:
            existing = GameCondition(
                season=season,
                week=week,
                home_team=parsed["home_team"],
                away_team=parsed["away_team"],
            )
            db.add(existing)

        existing.game_time = parsed["game_time"].replace(tzinfo=None)
        existing.spread = parsed["spread"]
        existing.over_under = parsed["over_under"]
        existing.dome = STADIUMS.get(parsed["home_team"], {}).get("dome", False)
        if parsed["spread"] is not None and parsed["over_under"] is not None:
            home_total, away_total = implied_totals(parsed["spread"], parsed["over_under"])
            existing.implied_total_home = home_total
            existing.implied_total_away = away_total
        count += 1

    await db.commit()
    logger.info("Odds sync: %d games updated for week %d", count, week)
    return count

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import GameCondition, Player, User
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/games", tags=["games"])


@router.get("/week/{week}")
async def games_for_week(
    week: int,
    season: int | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    season = season or get_settings().current_season
    games = (
        (
            await db.execute(
                select(GameCondition).where(
                    GameCondition.season == season, GameCondition.week == week
                )
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "home_team": g.home_team,
            "away_team": g.away_team,
            "game_time": g.game_time,
            "spread": float(g.spread) if g.spread is not None else None,
            "over_under": float(g.over_under) if g.over_under is not None else None,
            "implied_total_home": float(g.implied_total_home) if g.implied_total_home is not None else None,
            "implied_total_away": float(g.implied_total_away) if g.implied_total_away is not None else None,
            "temp_f": float(g.temp_f) if g.temp_f is not None else None,
            "wind_mph": float(g.wind_mph) if g.wind_mph is not None else None,
            "precipitation_pct": float(g.precipitation_pct) if g.precipitation_pct is not None else None,
            "dome": g.dome,
        }
        for g in games
    ]


@router.get("/injuries")
async def injury_report(
    _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    players = (
        (
            await db.execute(
                select(Player)
                .where(Player.injury_status.is_not(None))
                .order_by(Player.team, Player.full_name)
                .limit(300)
            )
        )
        .scalars()
        .all()
    )
    return [
        {
            "id": p.id,
            "name": p.full_name,
            "position": p.position,
            "team": p.team,
            "injury_status": p.injury_status,
            "injury_body_part": p.injury_body_part,
        }
        for p in players
    ]

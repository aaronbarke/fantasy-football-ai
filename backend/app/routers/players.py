from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Player, PlayerStatsWeekly, User
from app.schemas.player import PlayerOut, WeeklyStatOut
from app.services.sleeper_service import SleeperClient
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/players", tags=["players"])


@router.get("/search", response_model=list[PlayerOut])
async def search_players(
    q: str = Query(min_length=2),
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    players = (
        (
            await db.execute(
                select(Player)
                .where(Player.full_name.ilike(f"%{q}%"), Player.position.is_not(None))
                .order_by(Player.depth_chart_order.nulls_last())
                .limit(20)
            )
        )
        .scalars()
        .all()
    )
    return players


@router.get("/trending")
async def trending_players(
    _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    client = SleeperClient()
    try:
        trending = await client.get_trending("add", limit=25)
    finally:
        await client.close()

    ids = [str(t["player_id"]) for t in trending]
    players = (
        (await db.execute(select(Player).where(Player.id.in_(ids)))).scalars().all()
        if ids
        else []
    )
    by_id = {p.id: p for p in players}
    out = []
    for t in trending:
        p = by_id.get(str(t["player_id"]))
        if p:
            out.append(
                {
                    "id": p.id,
                    "name": p.full_name,
                    "position": p.position,
                    "team": p.team,
                    "injury_status": p.injury_status,
                    "adds_24h": t.get("count"),
                }
            )
    return out


@router.get("/rankings")
async def player_rankings(
    position: str | None = None,
    season: int | None = None,
    limit: int = 200,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Players ranked by average PPR points per game — feeds the draft assistant."""
    if season is None:
        season = (
            await db.execute(select(func.max(PlayerStatsWeekly.season)))
        ).scalar_one_or_none()
        if season is None:
            return []

    avg_col = func.avg(PlayerStatsWeekly.fantasy_points_ppr).label("avg_ppr")
    games_col = func.count(PlayerStatsWeekly.id).label("games")
    query = (
        select(Player, avg_col, games_col)
        .join(PlayerStatsWeekly, PlayerStatsWeekly.player_id == Player.id)
        .where(PlayerStatsWeekly.season == season)
        .group_by(Player.id)
        .having(games_col >= 4)
        .order_by(avg_col.desc())
        .limit(min(limit, 400))
    )
    if position:
        query = query.where(Player.position == position.upper())

    rows = (await db.execute(query)).all()
    return [
        {
            "id": p.id,
            "name": p.full_name,
            "position": p.position,
            "team": p.team,
            "injury_status": p.injury_status,
            "avg_ppr": round(float(avg or 0), 1),
            "games": int(games),
            "season": season,
        }
        for p, avg, games in rows
    ]


@router.get("/{player_id}", response_model=PlayerOut)
async def get_player(
    player_id: str,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    player = await db.get(Player, player_id)
    if player is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Player not found")
    return player


@router.get("/{player_id}/stats", response_model=list[WeeklyStatOut])
async def get_player_stats(
    player_id: str,
    season: int | None = None,
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(PlayerStatsWeekly).where(PlayerStatsWeekly.player_id == player_id)
    if season:
        query = query.where(PlayerStatsWeekly.season == season)
    stats = (
        (
            await db.execute(
                query.order_by(
                    PlayerStatsWeekly.season.desc(), PlayerStatsWeekly.week.desc()
                ).limit(36)
            )
        )
        .scalars()
        .all()
    )
    return stats

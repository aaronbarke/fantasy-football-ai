from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
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

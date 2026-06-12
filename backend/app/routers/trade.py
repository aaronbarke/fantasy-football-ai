import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LeagueConnection, Player, Roster, User
from app.services.ai_service import generate_response
from app.services.context_builder import player_package
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/trade", tags=["trade"])

TRADE_QUESTION = (
    "Evaluate this trade. The user GIVES the players in trade.give and "
    "RECEIVES the players in trade.receive. Grade each side of the trade A-F, "
    "explain who wins and why, and call out any positional depth problems this "
    "trade creates for the user's roster. End with a clear accept/reject/counter "
    "recommendation."
)


class TradeRequest(BaseModel):
    connection_id: str
    give: list[str] = Field(min_length=1, max_length=6)
    receive: list[str] = Field(min_length=1, max_length=6)


class TradeResponse(BaseModel):
    analysis: str


@router.post("/analyze", response_model=TradeResponse)
async def analyze_trade(
    body: TradeRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    try:
        cid = uuid.UUID(body.connection_id)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid connection id")
    conn = (
        await db.execute(
            select(LeagueConnection).where(
                LeagueConnection.id == cid, LeagueConnection.user_id == user.id
            )
        )
    ).scalar_one_or_none()
    if conn is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "League connection not found")

    scoring_type = conn.scoring_type or "ppr"

    async def packages(ids: list[str]) -> list[dict]:
        out = []
        for pid in ids:
            player = await db.get(Player, pid)
            if player is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, f"Player {pid} not found")
            out.append(await player_package(db, player, conn.season, scoring_type))
        return out

    context: dict = {
        "question_type": "trade",
        "league_settings": {
            "platform": conn.platform,
            "league_name": conn.league_name,
            "scoring": scoring_type,
            "roster_positions": conn.roster_positions,
        },
        "trade": {
            "give": await packages(body.give),
            "receive": await packages(body.receive),
        },
    }

    # Include the user's roster so depth implications can be judged
    roster = (
        await db.execute(
            select(Roster).where(
                Roster.connection_id == conn.id, Roster.team_id == conn.team_id
            )
        )
    ).scalar_one_or_none()
    if roster and roster.players:
        players = (
            await db.execute(select(Player).where(Player.id.in_(roster.players)))
        ).scalars().all()
        context["user_roster"] = {
            "players": [
                {"name": p.full_name, "position": p.position, "team": p.team}
                for p in players
            ]
        }

    analysis = await generate_response(TRADE_QUESTION, context)
    return TradeResponse(analysis=analysis)

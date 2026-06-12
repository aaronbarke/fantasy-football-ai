import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LeagueConnection, User
from app.services.ai_service import generate_response
from app.services.gameplan_service import build_gameplan
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/gameplan", tags=["gameplan"])

BRIEF_QUESTION = (
    "You are given this week's computed Game Plan (gameplan): the projection-"
    "optimal lineup with floor/ceiling per player, recommended start/sit swaps, "
    "projected team total, and win probability vs the opponent. Write the "
    "coach's brief: open with the headline (projected total + win probability "
    "if present), then walk through each recommended swap with the reasoning "
    "(projection gap, matchup, Vegas environment), flag the riskiest start "
    "(widest floor-to-ceiling band) and the safest one, and close with one "
    "sentence of strategy. Be decisive — these are your calls."
)


async def _get_conn(
    db: AsyncSession, user: User, connection_id: str
) -> LeagueConnection:
    try:
        cid = uuid.UUID(connection_id)
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
    return conn


@router.get("/{connection_id}")
async def get_gameplan(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_conn(db, user, connection_id)
    return await build_gameplan(db, conn)


@router.post("/{connection_id}/brief")
async def gameplan_brief(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    conn = await _get_conn(db, user, connection_id)
    plan = await build_gameplan(db, conn)
    if plan.get("status") != "ok":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No roster yet — the game plan needs players"
        )
    context = {
        "question_type": "gameplan",
        "league_settings": {
            "scoring": conn.scoring_type or "ppr",
            "league_name": conn.league_name,
        },
        "gameplan": plan,
    }
    analysis = await generate_response(BRIEF_QUESTION, context)
    return {"analysis": analysis}

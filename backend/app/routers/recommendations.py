import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Player, Recommendation, User
from app.services.recommendation_service import evaluate_pending
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/recommendations", tags=["recommendations"])


@router.get("/summary")
async def summary(
    connection_id: str | None = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = select(Recommendation).where(Recommendation.user_id == user.id)
    if connection_id:
        try:
            query = query.where(Recommendation.connection_id == uuid.UUID(connection_id))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid connection id")
    recs = (
        (await db.execute(query.order_by(Recommendation.created_at.desc()).limit(100)))
        .scalars()
        .all()
    )

    player_ids = {r.picked_player_id for r in recs} | {r.alternative_player_id for r in recs}
    players = (
        (await db.execute(select(Player).where(Player.id.in_(player_ids)))).scalars().all()
        if player_ids
        else []
    )
    names = {p.id: p.full_name for p in players}

    counts = {"win": 0, "loss": 0, "tie": 0, "pending": 0}
    for r in recs:
        counts[r.result] = counts.get(r.result, 0) + 1

    return {
        "wins": counts["win"],
        "losses": counts["loss"],
        "ties": counts["tie"],
        "pending": counts["pending"],
        "history": [
            {
                "week": r.week,
                "season": r.season,
                "picked": names.get(r.picked_player_id, r.picked_player_id),
                "alternative": names.get(r.alternative_player_id, r.alternative_player_id),
                "picked_points": float(r.picked_points) if r.picked_points is not None else None,
                "alternative_points": float(r.alternative_points)
                if r.alternative_points is not None
                else None,
                "result": r.result,
            }
            for r in recs
        ],
    }


@router.post("/evaluate")
async def evaluate_now(
    _: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Manually grade pending calls (the Wednesday job does this automatically)."""
    graded = await evaluate_pending(db)
    return {"graded": graded}

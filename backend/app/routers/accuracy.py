import uuid

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import LeagueConnection, User
from app.services.accuracy_service import accuracy_report
from app.utils.security import get_current_user

router = APIRouter(prefix="/api/accuracy", tags=["accuracy"])


@router.get("/{connection_id}")
async def get_accuracy(
    connection_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Track record for one league: projection error, lineup accuracy, and the
    start/sit record."""
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
    return await accuracy_report(db, conn)

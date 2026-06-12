"""Grades stored start/sit recommendations once weekly stats land."""

import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerStatsWeekly, Recommendation

logger = logging.getLogger(__name__)

FP_FIELD = {
    "ppr": "fantasy_points_ppr",
    "half_ppr": "fantasy_points_half",
    "standard": "fantasy_points_std",
}


async def _points_for(
    db: AsyncSession, player_id: str, season: int, week: int, scoring_type: str
) -> float | None:
    stat = (
        await db.execute(
            select(PlayerStatsWeekly).where(
                PlayerStatsWeekly.player_id == player_id,
                PlayerStatsWeekly.season == season,
                PlayerStatsWeekly.week == week,
            )
        )
    ).scalar_one_or_none()
    if stat is None:
        return None
    value = getattr(stat, FP_FIELD.get(scoring_type, "fantasy_points_ppr"))
    return float(value) if value is not None else None


async def evaluate_pending(db: AsyncSession) -> int:
    """Grade every pending recommendation whose week's stats are available."""
    pending = (
        (
            await db.execute(
                select(Recommendation).where(Recommendation.result == "pending")
            )
        )
        .scalars()
        .all()
    )
    graded = 0
    for rec in pending:
        picked = await _points_for(
            db, rec.picked_player_id, rec.season, rec.week, rec.scoring_type
        )
        alt = await _points_for(
            db, rec.alternative_player_id, rec.season, rec.week, rec.scoring_type
        )
        if picked is None or alt is None:
            continue  # stats not in yet
        rec.picked_points = picked
        rec.alternative_points = alt
        if picked > alt:
            rec.result = "win"
        elif picked < alt:
            rec.result = "loss"
        else:
            rec.result = "tie"
        graded += 1
    await db.commit()
    if graded:
        logger.info("Graded %d recommendations", graded)
    return graded

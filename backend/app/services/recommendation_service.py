"""Grades stored start/sit recommendations once weekly stats land."""

import logging

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PlayerStatsWeekly, Recommendation

logger = logging.getLogger(__name__)

FP_FIELD = {
    "ppr": "fantasy_points_ppr",
    "half_ppr": "fantasy_points_half",
    "standard": "fantasy_points_std",
}


async def _week_loaded(db: AsyncSession, season: int, week: int) -> bool:
    """True once any stats for that week are in — i.e. the week has been played
    and ingested, so a player with no row simply didn't record a stat."""
    return bool(
        (
            await db.execute(
                select(
                    exists().where(
                        PlayerStatsWeekly.season == season, PlayerStatsWeekly.week == week
                    )
                )
            )
        ).scalar()
    )


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
    loaded: dict[tuple[int, int], bool] = {}
    for rec in pending:
        key = (rec.season, rec.week)
        if key not in loaded:
            loaded[key] = await _week_loaded(db, rec.season, rec.week)
        if not loaded[key]:
            continue  # the week's stats aren't in yet
        # nflverse only has rows for players who recorded a stat, so once the
        # week is loaded a missing row means he didn't play: 0 points. Leaving
        # it pending forever would hide exactly the calls that went worst.
        picked = await _points_for(
            db, rec.picked_player_id, rec.season, rec.week, rec.scoring_type
        )
        alt = await _points_for(
            db, rec.alternative_player_id, rec.season, rec.week, rec.scoring_type
        )
        picked = picked if picked is not None else 0.0
        alt = alt if alt is not None else 0.0
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

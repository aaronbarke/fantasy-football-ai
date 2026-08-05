"""On-demand data refresh.

The scheduler (ENABLE_SCHEDULER=true) refreshes NFL weekly stats every Tuesday,
and everything derived — trade values, projections, defense-vs-position ranks,
schedule strength — is computed on demand from those tables, so it all stays
current automatically. This endpoint is the manual equivalent: useful in local
dev (scheduler off) and to force a pull right after a game week.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import User
from app.services.adp_service import sync_draft_profiles
from app.services.news_service import sync_news
from app.services.nfl_data_service import sync_id_crosswalk, sync_weekly_stats
from app.utils.security import require_admin

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/admin", tags=["admin"])


@router.post("/refresh-stats")
async def refresh_stats(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Re-pull NFL weekly stats for the current and prior season.

    Trade values, projections, and schedule strength all recompute from these
    on the next request, so this single call freshens the whole app.
    """
    settings = get_settings()
    seasons = [settings.current_season - 1, settings.current_season]
    try:
        crosswalk = await sync_id_crosswalk(db)
        weekly_rows = await sync_weekly_stats(db, seasons)
    except Exception as exc:
        logger.exception("Manual stats refresh failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Stats refresh failed: {exc}"
        ) from exc
    return {
        "status": "ok",
        "seasons": seasons,
        "weekly_rows": weekly_rows,
        "id_crosswalk_rows": crosswalk,
    }


@router.post("/refresh-draft")
async def refresh_draft(
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    """Pull ADP, auction values, season projections, and player news.

    This is what the draft board and mock drafts read from. Run it once before
    a draft — the scheduled job only fires twice a day, and ADP moves fast in
    August. Requires the ID crosswalk (refresh-stats) to have run at least once
    so ESPN and news items can be matched to players.
    """
    settings = get_settings()
    try:
        profiles = await sync_draft_profiles(db, settings.current_season)
        news_items = await sync_news(db)
    except Exception as exc:
        logger.exception("Manual draft refresh failed")
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"Draft refresh failed: {exc}"
        ) from exc
    return {
        "status": "ok",
        "season": settings.current_season,
        "draft_profiles": profiles,
        "news_items": news_items,
    }

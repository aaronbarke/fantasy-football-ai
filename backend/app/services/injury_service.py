"""Injury data from ESPN's public (no-auth) endpoints."""

import logging

import httpx
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player

logger = logging.getLogger(__name__)

INJURIES_URL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/injuries"


async def fetch_injuries() -> list[dict]:
    """Flatten ESPN's per-team injury feed into
    [{espn_id, name, status, body_part}, ...]."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(INJURIES_URL)
        resp.raise_for_status()
        data = resp.json()

    out: list[dict] = []
    for team_blob in data.get("injuries", []):
        for inj in team_blob.get("injuries", []):
            athlete = inj.get("athlete") or {}
            details = inj.get("details") or {}
            out.append(
                {
                    "espn_id": str(athlete.get("id", "")),
                    "name": athlete.get("displayName", ""),
                    "status": inj.get("status"),
                    "body_part": details.get("type"),
                }
            )
    return out


async def sync_injuries(db: AsyncSession) -> int:
    """Update players.injury_status from the ESPN feed. Returns rows touched."""
    injuries = await fetch_injuries()

    # Clear stale statuses first so recoveries show as healthy
    await db.execute(update(Player).values(injury_status=None, injury_body_part=None))

    count = 0
    for inj in injuries:
        if not inj["espn_id"]:
            continue
        result = await db.execute(
            update(Player)
            .where(Player.espn_id == inj["espn_id"])
            .values(injury_status=inj["status"], injury_body_part=inj["body_part"])
        )
        count += result.rowcount or 0
    await db.commit()
    logger.info("Injury sync: %d players updated", count)
    return count

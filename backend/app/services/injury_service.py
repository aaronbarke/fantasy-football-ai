"""Injury data from ESPN's public (no-auth) endpoints."""

import logging

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InjuryEvent, Player

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


SEVERE_STATUSES = ("out", "doubtful", "injured reserve", "ir")


def _is_severe(status: str | None) -> bool:
    return bool(status) and any(s in status.lower() for s in SEVERE_STATUSES)


async def sync_injuries(db: AsyncSession) -> list[InjuryEvent]:
    """Update players.injury_status from the ESPN feed. Returns new severe
    status-change events (for the alert pipeline)."""
    injuries = await fetch_injuries()

    # Snapshot current statuses so we can diff after the update
    before_rows = (
        await db.execute(
            select(Player.id, Player.espn_id, Player.injury_status).where(
                Player.espn_id.is_not(None)
            )
        )
    ).all()
    before = {espn_id: (pid, status) for pid, espn_id, status in before_rows}

    # Clear stale statuses first so recoveries show as healthy
    await db.execute(update(Player).values(injury_status=None, injury_body_part=None))

    events: list[InjuryEvent] = []
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

        prev = before.get(inj["espn_id"])
        if prev and prev[1] != inj["status"] and _is_severe(inj["status"]):
            event = InjuryEvent(
                player_id=prev[0], old_status=prev[1], new_status=inj["status"]
            )
            db.add(event)
            events.append(event)

    await db.commit()
    logger.info("Injury sync: %d players updated, %d new severe events", count, len(events))
    return events

"""Cross-platform player ID mapping.

Canonical ID is the Sleeper player_id. nflverse stats arrive keyed by gsis_id,
ESPN rosters by espn_id. nfl_data_py's import_ids() provides the crosswalk,
which we persist onto the players table (gsis_id, espn_id, yahoo_id columns).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player


async def gsis_to_sleeper_map(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(Player.gsis_id, Player.id).where(Player.gsis_id.is_not(None))
    )
    return {gsis: sleeper for gsis, sleeper in result.all()}


async def espn_to_sleeper_map(db: AsyncSession) -> dict[str, str]:
    result = await db.execute(
        select(Player.espn_id, Player.id).where(Player.espn_id.is_not(None))
    )
    return {espn: sleeper for espn, sleeper in result.all()}


def normalize_name(name: str) -> str:
    """Fallback fuzzy key when an ID crosswalk is missing."""
    return (
        name.lower()
        .replace(".", "")
        .replace("'", "")
        .replace("-", " ")
        .replace(" jr", "")
        .replace(" sr", "")
        .replace(" iii", "")
        .replace(" ii", "")
        .strip()
    )

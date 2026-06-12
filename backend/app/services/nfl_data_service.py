"""nflverse data pipeline.

Reads nflverse's public parquet/CSV releases directly with pandas
(nfl_data_py is unmaintained and won't install on Python 3.13).
Heavy pandas imports are kept lazy so the API server starts fast and tests
don't need the dependency installed. The Tuesday stat-refresh job is the main
consumer here.
"""

import io
import logging
import math
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Player, PlayerStatsWeekly
from app.utils.player_id_map import gsis_to_sleeper_map

logger = logging.getLogger(__name__)

WEEKLY_COLUMNS = [
    "player_id",  # gsis_id in nflverse
    "player_display_name",
    "position",
    "recent_team",
    "season",
    "week",
    "completions",
    "attempts",
    "passing_yards",
    "passing_tds",
    "interceptions",
    "carries",
    "rushing_yards",
    "rushing_tds",
    "receptions",
    "targets",
    "receiving_yards",
    "receiving_tds",
    "target_share",
    "air_yards_share",
    "fantasy_points",
    "fantasy_points_ppr",
    "opponent_team",
]


def _clean(value: Any) -> Any:
    """pandas NaN → None for DB storage."""
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    return value


NFLVERSE_STATS_URLS = [
    "https://github.com/nflverse/nflverse-data/releases/download/stats_player/stats_player_week_{season}.parquet",
    "https://github.com/nflverse/nflverse-data/releases/download/player_stats/player_stats_{season}.parquet",
]
IDS_URL = "https://github.com/dynastyprocess/data/raw/master/files/db_playerids.csv"


def _download(url: str) -> io.BytesIO:
    """Fetch with httpx (bundled CA certs) — urllib fails on stock macOS Python."""
    import httpx

    resp = httpx.get(url, follow_redirects=True, timeout=120)
    resp.raise_for_status()
    return io.BytesIO(resp.content)


def fetch_weekly_dataframe(seasons: list[int]):
    """Blocking pandas call — run in a thread from async contexts."""
    import pandas as pd

    frames = []
    for season in seasons:
        last_err: Exception | None = None
        for url_tpl in NFLVERSE_STATS_URLS:
            try:
                frames.append(pd.read_parquet(_download(url_tpl.format(season=season))))
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001 — try next URL naming scheme
                last_err = exc
        if last_err is not None:
            raise last_err
    return pd.concat(frames, ignore_index=True)


def fetch_id_crosswalk():
    """ID mapping table: gsis_id ↔ sleeper_id ↔ espn_id ↔ yahoo_id."""
    import pandas as pd

    return pd.read_csv(_download(IDS_URL), dtype=str)


async def sync_id_crosswalk(db: AsyncSession) -> int:
    """Write gsis/espn/yahoo IDs onto the players table (keyed by sleeper id)."""
    import asyncio

    ids_df = await asyncio.to_thread(fetch_id_crosswalk)
    ids_df = ids_df[ids_df["sleeper_id"].notna()]

    count = 0
    for row in ids_df.itertuples(index=False):
        sleeper_id = str(int(row.sleeper_id)) if isinstance(row.sleeper_id, float) else str(row.sleeper_id)
        player = await db.get(Player, sleeper_id)
        if player is None:
            continue
        gsis = _clean(getattr(row, "gsis_id", None))
        espn = _clean(getattr(row, "espn_id", None))
        yahoo = _clean(getattr(row, "yahoo_id", None))
        if gsis:
            player.gsis_id = str(gsis)
        if espn and not player.espn_id:
            player.espn_id = str(int(espn)) if isinstance(espn, float) else str(espn)
        if yahoo and not player.yahoo_id:
            player.yahoo_id = str(int(yahoo)) if isinstance(yahoo, float) else str(yahoo)
        count += 1
    await db.commit()
    logger.info("ID crosswalk sync: %d players updated", count)
    return count


async def sync_weekly_stats(db: AsyncSession, seasons: list[int]) -> int:
    """Upsert nflverse weekly stats into player_stats_weekly, mapping
    gsis_id → sleeper player_id via the crosswalk on the players table."""
    import asyncio

    df = await asyncio.to_thread(fetch_weekly_dataframe, seasons)
    id_map = await gsis_to_sleeper_map(db)

    # Preload existing (player, season, week) keys to decide insert vs update
    existing_rows = (
        await db.execute(
            select(
                PlayerStatsWeekly.id,
                PlayerStatsWeekly.player_id,
                PlayerStatsWeekly.season,
                PlayerStatsWeekly.week,
            ).where(PlayerStatsWeekly.season.in_(seasons))
        )
    ).all()
    existing = {(r.player_id, r.season, r.week): r.id for r in existing_rows}

    count = 0
    for row in df.itertuples(index=False):
        gsis_id = getattr(row, "player_id", None)
        sleeper_id = id_map.get(gsis_id)
        if sleeper_id is None:
            continue

        values = {
            "pass_yards": _clean(getattr(row, "passing_yards", 0)) or 0,
            "pass_tds": int(_clean(getattr(row, "passing_tds", 0)) or 0),
            "interceptions": int(
                _clean(
                    getattr(row, "passing_interceptions", None)
                    or getattr(row, "interceptions", 0)
                )
                or 0
            ),
            "rush_attempts": int(_clean(getattr(row, "carries", 0)) or 0),
            "rush_yards": _clean(getattr(row, "rushing_yards", 0)) or 0,
            "rush_tds": int(_clean(getattr(row, "rushing_tds", 0)) or 0),
            "receptions": int(_clean(getattr(row, "receptions", 0)) or 0),
            "receiving_yards": _clean(getattr(row, "receiving_yards", 0)) or 0,
            "receiving_tds": int(_clean(getattr(row, "receiving_tds", 0)) or 0),
            "targets": int(_clean(getattr(row, "targets", 0)) or 0),
            "target_share": _clean(getattr(row, "target_share", None)),
            "air_yards_share": _clean(getattr(row, "air_yards_share", None)),
            "fantasy_points_ppr": _clean(getattr(row, "fantasy_points_ppr", None)),
            "fantasy_points_std": _clean(getattr(row, "fantasy_points", None)),
            "opponent": _clean(getattr(row, "opponent_team", None)),
        }
        ppr = values["fantasy_points_ppr"]
        std = values["fantasy_points_std"]
        if ppr is not None and std is not None:
            values["fantasy_points_half"] = round((float(ppr) + float(std)) / 2, 2)

        season = int(row.season)
        week = int(row.week)
        key = (sleeper_id, season, week)
        if key in existing:
            stat = await db.get(PlayerStatsWeekly, existing[key])
            for field, val in values.items():
                setattr(stat, field, val)
        else:
            db.add(
                PlayerStatsWeekly(player_id=sleeper_id, season=season, week=week, **values)
            )
        count += 1
        if count % 2000 == 0:
            await db.flush()

    await db.commit()
    logger.info("Weekly stats sync: %d rows for seasons %s", count, seasons)
    return count

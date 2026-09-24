"""Projections use the CURRENT week's opponent (not Week 1), and the lineup
slots display in a consistent order (skill -> FLEX -> DEF -> K)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import LeagueConnection, NflSchedule, Player, PlayerStatsWeekly
from app.services import projection_service
from app.services.gameplan_service import _all_lineup_slots
from app.services.projection_service import compute_projections

SEASON = 2025


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture(autouse=True)
def _no_external(monkeypatch):
    async def _empty(season, week, scoring="ppr"):
        return {}

    monkeypatch.setattr(projection_service, "get_external_projections", _empty)


async def test_projection_shows_current_week_opponent(db: AsyncSession):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    db.add(Player(id="wr", full_name="WR", position="WR", team="SF"))
    for wk in range(1, 5):
        db.add(PlayerStatsWeekly(player_id="wr", season=SEASON, week=wk, fantasy_points_ppr=14))
    # Week 1 already played; Week 2 is upcoming.
    db.add(NflSchedule(season=SEASON, week=1, home_team="SF", away_team="CAR",
                       game_time=now - timedelta(days=7)))
    db.add(NflSchedule(season=SEASON, week=2, home_team="SF", away_team="SEA",
                       game_time=now + timedelta(hours=1)))
    await db.commit()

    proj = await compute_projections(db, ["wr"], SEASON)
    comp = proj["wr"]["components"]
    assert comp["opponent"] == "SEA"   # Week 2 opponent, not Week 1's CAR
    assert comp["week"] == 2


def test_lineup_slots_display_order():
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, team_id="t1",
        roster_positions=["QB", "K", "DST", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN"],
    )
    assert _all_lineup_slots(conn) == [
        "QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "DEF", "K"
    ]

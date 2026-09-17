"""Matchup week selection — the preview must follow the current NFL week, not
stick on the last finished week."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    LeagueConnection,
    Matchup,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    Roster,
)
from app.services import projection_service
from app.services.gameplan_service import _current_nfl_week, build_matchup_preview

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
    async def _empty(season, week):
        return {}

    monkeypatch.setattr(projection_service, "get_external_projections", _empty)


async def _schedule(db, base: datetime, weeks: int = 3):
    """One kickoff per week, a week apart, starting at ``base``."""
    for wk in range(1, weeks + 1):
        db.add(
            NflSchedule(
                season=SEASON, week=wk, home_team=f"H{wk}", away_team=f"A{wk}",
                game_time=base + timedelta(days=7 * (wk - 1)),
            )
        )
    await db.commit()


async def test_current_week_is_earliest_unfinished(db: AsyncSession):
    base = datetime(2025, 9, 4, 20, 0)  # Week 1 kickoff
    await _schedule(db, base, weeks=3)

    # Thursday of Week 2, Week 1 done → Week 2 is current.
    assert await _current_nfl_week(db, SEASON, base + timedelta(days=7, hours=1)) == 2
    # Before Week 1 kicks off → Week 1.
    assert await _current_nfl_week(db, SEASON, base - timedelta(hours=1)) == 1
    # After the last game → the final week.
    assert await _current_nfl_week(db, SEASON, base + timedelta(days=60)) == 3
    # No schedule for the season → unknown.
    assert await _current_nfl_week(db, 1999, base) is None


async def test_preview_follows_current_week_not_last_scored(db: AsyncSession):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Week 1 finished a week ago; Week 2 kicks off in an hour → current = 2.
    db.add(NflSchedule(season=SEASON, week=1, home_team="H1", away_team="A1",
                       game_time=now - timedelta(days=7)))
    db.add(NflSchedule(season=SEASON, week=2, home_team="H2", away_team="A2",
                       game_time=now + timedelta(hours=1)))

    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="t1",
        roster_positions=["QB", "WR", "RB", "BN"],
    )
    db.add(conn)
    for team, owner in (("t1", "Me"), ("t2", "Them")):
        for pid, pos, ppg in [(f"{team}_qb", "QB", 20), (f"{team}_wr", "WR", 14), (f"{team}_rb", "RB", 12)]:
            db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="X"))
            for wk in range(1, 5):
                db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))
        db.add(Roster(connection_id=conn.id, team_id=team, owner_name=owner,
                      players=[f"{team}_qb", f"{team}_wr", f"{team}_rb"]))
    # Week 1 is over and scored; Week 2 has no scores yet.
    db.add(Matchup(connection_id=conn.id, week=1, team_a_id="t1", team_b_id="t2",
                   team_a_points=120.0, team_b_points=95.0))
    db.add(Matchup(connection_id=conn.id, week=2, team_a_id="t1", team_b_id="t2",
                   team_a_points=None, team_b_points=None))
    await db.commit()

    preview = await build_matchup_preview(db, conn)
    assert preview["status"] == "ok"
    assert preview["week"] == 2           # current week, not the last scored (1)
    assert preview["live"] is False       # Week 2 hasn't kicked off

"""Live win-probability snapshots feed the odds-history chart."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    LeagueConnection,
    LivePlayerScore,
    Matchup,
    MatchupOdds,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    Roster,
)
from app.services import projection_service
from app.services.gameplan_service import build_matchup_preview

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


async def _live_matchup(db) -> LeagueConnection:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Week 2 is in progress → it's the current week and it's live.
    db.add(NflSchedule(season=SEASON, week=1, home_team="H1", away_team="A1",
                       game_time=now - timedelta(days=7)))
    db.add(NflSchedule(season=SEASON, week=2, home_team="H2", away_team="A2",
                       game_time=now - timedelta(hours=1)))
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="t1",
        roster_positions=["QB", "WR", "RB", "BN"],
    )
    db.add(conn)
    for team in ("t1", "t2"):
        for pid, pos, ppg in [(f"{team}_qb", "QB", 20), (f"{team}_wr", "WR", 14), (f"{team}_rb", "RB", 12)]:
            db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="X"))
            for wk in range(1, 5):
                db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))
        db.add(Roster(connection_id=conn.id, team_id=team, owner_name=team,
                      players=[f"{team}_qb", f"{team}_wr", f"{team}_rb"]))
    db.add(Matchup(connection_id=conn.id, week=2, team_a_id="t1", team_b_id="t2",
                   team_a_points=80.0, team_b_points=50.0))
    await db.commit()
    return conn


async def _count(db, conn) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(MatchupOdds).where(
                MatchupOdds.connection_id == conn.id
            )
        )
    ).scalar()


async def test_snapshots_recorded_only_when_odds_move(db: AsyncSession):
    conn = await _live_matchup(db)

    p1 = await build_matchup_preview(db, conn)
    assert p1["live"] is True
    assert await _count(db, conn) == 1  # first live view records a point

    # Same score again → deduped, no new row.
    await build_matchup_preview(db, conn)
    assert await _count(db, conn) == 1

    # Score changes → a new point lands on the timeline.
    await db.execute(
        update(Matchup)
        .where(Matchup.connection_id == conn.id, Matchup.week == 2)
        .values(team_a_points=95.0, team_b_points=52.0)
    )
    await db.commit()
    await build_matchup_preview(db, conn)
    assert await _count(db, conn) == 2


async def test_actual_points_attached_to_cards(db: AsyncSession):
    conn = await _live_matchup(db)
    db.add(LivePlayerScore(connection_id=conn.id, week=2, player_id="t1_qb", points=27.5))
    await db.commit()
    preview = await build_matchup_preview(db, conn)
    got = None
    for r in preview["rows"]:
        for side in ("user", "opponent"):
            pl = r[side]
            if pl and pl["id"] == "t1_qb":
                got = pl["actual_points"]
    assert got == 27.5


async def test_no_snapshot_when_not_live(db: AsyncSession):
    conn = await _live_matchup(db)
    # Wipe the score → matchup is no longer live.
    await db.execute(
        update(Matchup)
        .where(Matchup.connection_id == conn.id, Matchup.week == 2)
        .values(team_a_points=None, team_b_points=None)
    )
    await db.commit()
    p = await build_matchup_preview(db, conn)
    assert p["live"] is False
    assert await _count(db, conn) == 0

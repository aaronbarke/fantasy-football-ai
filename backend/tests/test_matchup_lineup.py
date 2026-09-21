"""Matchup shows the opponent's ACTUAL starters (not the optimal lineup), and an
Out player projects 0."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import LeagueConnection, Matchup, Player, PlayerStatsWeekly, Roster
from app.services import projection_service
from app.services.gameplan_service import build_matchup_preview
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
    async def _empty(season, week):
        return {}

    monkeypatch.setattr(projection_service, "get_external_projections", _empty)


async def _add(db, pid, pos, ppg, status=None):
    db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="X", injury_status=status))
    for wk in range(1, 5):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))


async def test_out_player_projects_zero(db: AsyncSession):
    await _add(db, "hurt", "WR", 18.0, status="Out")
    await _add(db, "healthy", "WR", 12.0)
    await db.commit()
    proj = await compute_projections(db, ["hurt", "healthy"], SEASON)
    assert proj["hurt"]["projected"] == 0.0
    assert proj["hurt"]["floor"] == 0.0 and proj["hurt"]["ceiling"] == 0.0
    assert proj["healthy"]["projected"] > 0


async def test_matchup_shows_opponent_actual_starters(db: AsyncSession):
    # Opponent benched their Out WR and started a healthy one; the matchup must
    # show who they actually started.
    await _add(db, "opp_qb", "QB", 20.0)
    await _add(db, "opp_started", "WR", 10.0)
    await _add(db, "opp_out", "WR", 22.0, status="Out")  # benched, out
    await _add(db, "my_qb", "QB", 19.0)
    await _add(db, "my_wr", "WR", 14.0)
    await db.commit()

    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="t1",
        roster_positions=["QB", "WR", "BN"],
    )
    db.add(conn)
    db.add(Roster(connection_id=conn.id, team_id="t1", owner_name="Me",
                  players=["my_qb", "my_wr"], starters=["my_qb", "my_wr"]))
    db.add(Roster(connection_id=conn.id, team_id="t2", owner_name="Them",
                  players=["opp_qb", "opp_started", "opp_out"],
                  starters=["opp_qb", "opp_started"]))
    db.add(Matchup(connection_id=conn.id, week=1, team_a_id="t1", team_b_id="t2"))
    await db.commit()

    preview = await build_matchup_preview(db, conn)
    opp_ids = [r["opponent"]["id"] for r in preview["rows"] if r["opponent"]]
    assert "opp_started" in opp_ids       # the WR they actually started
    assert "opp_out" not in opp_ids       # the benched Out WR is NOT shown as a starter

"""Team-defense (DST) streaming projection: matchup-driven off the opponent's
implied total, so a mediocre defense with a great matchup rates as a streamer."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import GameCondition, NflSchedule, Player
from app.services import projection_service
from app.services.projection_service import (
    DST_MAX,
    DST_MIN,
    LEAGUE_AVG_TEAM_TOTAL,
    _dst_projection,
    compute_projections,
)

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


# --- pure model -------------------------------------------------------------


def test_dst_projection_scales_with_opponent_implied_total():
    great, _, glabel = _dst_projection(LEAGUE_AVG_TEAM_TOTAL - 7, None)  # weak offense
    neutral, _, nlabel = _dst_projection(LEAGUE_AVG_TEAM_TOTAL, None)
    tough, _, tlabel = _dst_projection(LEAGUE_AVG_TEAM_TOTAL + 7, None)  # strong offense
    assert great > neutral > tough
    assert glabel == "great" and nlabel == "neutral" and tlabel == "tough"
    # bounded, and unknown matchup falls back to the baseline
    assert DST_MIN <= tough and great <= DST_MAX
    base, _, label = _dst_projection(None, None)
    assert label == "unknown" and DST_MIN <= base <= DST_MAX


# --- through compute_projections -------------------------------------------


async def _game(db, home, away, week, home_implied, away_implied):
    db.add(NflSchedule(season=SEASON, week=week, home_team=home, away_team=away))
    db.add(GameCondition(season=SEASON, week=week, home_team=home, away_team=away,
                         implied_total_home=home_implied, implied_total_away=away_implied))


async def test_streaming_prefers_the_softer_matchup(db: AsyncSession):
    db.add(Player(id="SF", full_name="49ers", position="DEF", team="SF"))
    db.add(Player(id="DAL", full_name="Cowboys", position="DEF", team="DAL"))
    # SF faces a weak offense (implied 16); DAL faces a strong one (implied 29).
    await _game(db, home="SF", away="CAR", week=1, home_implied=24, away_implied=16)
    await _game(db, home="DAL", away="BUF", week=1, home_implied=21, away_implied=29)
    await db.commit()

    proj = await compute_projections(db, ["SF", "DAL"], SEASON)
    assert proj["SF"]["projected"] > proj["DAL"]["projected"]
    assert proj["SF"]["components"]["matchup"] == "great"
    assert proj["DAL"]["components"]["matchup"] == "tough"
    assert "great matchup vs CAR" in proj["SF"]["defense_reason"]


async def test_dst_projected_even_without_odds(db: AsyncSession):
    db.add(Player(id="NYJ", full_name="Jets", position="DEF", team="NYJ"))
    await db.commit()
    proj = await compute_projections(db, ["NYJ"], SEASON)
    # No schedule/odds → still a neutral projection, not dropped.
    assert proj["NYJ"]["projected"] == pytest.approx(projection_service.DST_BASELINE, abs=0.1)

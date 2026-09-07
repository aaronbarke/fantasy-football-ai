import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Player, PlayerStatsWeekly
from app.services.context_builder import _attach_projections, classify_intent

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


async def _seed(db, pid, ppg):
    db.add(Player(id=pid, full_name=pid.upper(), position="TE", team="NO"))
    for wk in range(1, 5):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))
    await db.commit()


def test_start_sit_intent():
    assert classify_intent("Should I start Ja'Marr Chase or CeeDee Lamb?") == "start_sit"
    assert classify_intent("who should i play at flex") == "start_sit"
    assert classify_intent("Bench Saquon this week?") == "start_sit"


def test_trade_intent():
    assert classify_intent("Is this trade fair: my Hill for his Jefferson?") == "trade"
    assert classify_intent("Should I acquire a top RB in a package deal?") == "trade"


def test_waiver_intent():
    assert classify_intent("Who should I pick up off waivers this week?") == "waiver"
    assert classify_intent("Is there a good streaming defense to add?") == "waiver"


def test_matchup_intent():
    assert classify_intent("Break down my matchup against my opponent") == "matchup"


def test_general_fallback():
    assert classify_intent("What do you think about the Bengals offense?") == "general"


async def test_projections_reach_roster_and_waiver_context(db: AsyncSession):
    """The fix for the drop/start contradiction: a rostered player and a waiver
    candidate both carry the same model projection the game plan uses, so the
    assistant can rank add/drop/start-sit calls on projected points instead of
    name recognition or trending adds."""
    await _seed(db, "johnson", ppg=9.7)   # rostered TE the optimizer starts
    await _seed(db, "likely", ppg=6.4)    # bench TE
    await _seed(db, "henry", ppg=8.0)     # waiver candidate

    context = {
        "user_roster": {
            "starters": [{"id": "johnson", "name": "JOHNSON", "position": "TE"}],
            "bench": [{"id": "likely", "name": "LIKELY", "position": "TE"}],
        },
        "waiver_wire": [{"id": "henry", "name": "HENRY", "position": "TE", "trending_adds": 56}],
    }
    await _attach_projections(db, context, SEASON)

    starter = context["user_roster"]["starters"][0]
    bench = context["user_roster"]["bench"][0]
    waiver = context["waiver_wire"][0]

    # Every surfaced player now has the projection attached...
    assert starter["projection"]["projected"] > 0
    assert waiver["projection"]["projected"] > 0
    # ...and it reflects the real hierarchy: the started TE out-projects both the
    # bench TE and the trending waiver add, so a drop recommendation can't hide
    # behind "56 trending adds" anymore.
    assert starter["projection"]["projected"] > bench["projection"]["projected"]
    assert starter["projection"]["projected"] > waiver["projection"]["projected"]


async def test_attach_projections_noop_without_ids(db: AsyncSession):
    context = {"user_roster": {"starters": [], "bench": []}}
    await _attach_projections(db, context, SEASON)  # must not raise
    assert context["user_roster"]["starters"] == []

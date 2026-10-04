"""Late-news adjustments: teammate absences and a backup QB starting move only
our model's share of the Sleeper blend (Sleeper's number already reflects the
news), and chat player lookup doesn't drag in namesakes."""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import NflSchedule, Player, PlayerStatsWeekly
from app.services import projection_service
from app.services.context_builder import find_mentioned_players
from app.services.projection_service import QB_CHANGE_CAP, compute_projections

SEASON = 2026


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _external(values: dict[str, float]):
    async def _ext(season, week, scoring="ppr"):
        return values

    return _ext


async def _week_ahead(db):
    """This week's games kick off 5 days out, so Sleeper's share is the
    early-week floor (0.5) and the math below is exact."""
    kick = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    db.add(NflSchedule(season=SEASON, week=4, home_team="WAS", away_team="IND", game_time=kick))
    db.add(NflSchedule(season=SEASON, week=4, home_team="MIN", away_team="MIA", game_time=kick))


def _catcher(db, pid, team, ppg, share, depth, status=None, pos="WR"):
    db.add(Player(id=pid, full_name=pid, position=pos, team=team,
                  depth_chart_order=depth, injury_status=status))
    for wk in range(1, 9):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON - 1, week=wk,
                                 target_share=share, fantasy_points_ppr=ppg + (2 if wk % 2 else -2)))


def _qb(db, pid, team, starts, ppg, status=None, depth=1):
    db.add(Player(id=pid, full_name=pid, position="QB", team=team,
                  depth_chart_order=depth, injury_status=status))
    for wk in range(1, starts + 1):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON - 1, week=wk,
                                 pass_yards=250, fantasy_points_ppr=ppg))


async def test_teammate_boost_only_moves_our_share_of_the_blend(db: AsyncSession, monkeypatch):
    await _week_ahead(db)
    _catcher(db, "wr1", "MIN", 18, 0.28, 1, status="Out")
    _catcher(db, "wr2", "MIN", 10, 0.16, 2)
    await db.commit()
    monkeypatch.setattr(projection_service, "get_external_projections", _external({"wr2": 13.0}))

    p = (await compute_projections(db, ["wr2"], SEASON))["wr2"]
    c = p["components"]
    assert c["opportunity_adj"] > 0
    assert c["blend_weight"] == 0.5
    # projected = s * Sleeper + (1 - s) * model, with the boost inside the model
    assert p["projected"] == pytest.approx(0.5 * 13.0 + 0.5 * c["model_proj"], abs=0.1)
    # Before the fix the full boost was added on top of the blend as well.
    assert p["projected"] < 0.5 * 13.0 + 0.5 * (c["model_proj"] - c["opportunity_adj"]) + c["opportunity_adj"]
    # The reason quotes the boost's actual effect on the final number.
    effect = round(c["opportunity_adj"] * 0.5, 1)
    assert f"+{effect:.1f} from vacated targets" in p["boost_reason"]


async def test_without_sleeper_the_boost_applies_in_full(db: AsyncSession, monkeypatch):
    await _week_ahead(db)
    _catcher(db, "wr1", "MIN", 18, 0.28, 1, status="Out")
    _catcher(db, "wr2", "MIN", 10, 0.16, 2)
    await db.commit()
    monkeypatch.setattr(projection_service, "get_external_projections", _external({}))

    p = (await compute_projections(db, ["wr2"], SEASON))["wr2"]
    assert p["projected"] == pytest.approx(p["components"]["model_proj"], abs=0.1)


async def test_backup_qb_starting_discounts_pass_catchers(db: AsyncSession, monkeypatch):
    await _week_ahead(db)
    _qb(db, "starter", "WAS", starts=8, ppg=22.0, status="Out", depth=1)
    _qb(db, "backup", "WAS", starts=0, ppg=0.0, depth=2)
    _catcher(db, "was_wr", "WAS", 14, 0.22, 1)
    _catcher(db, "was_rb", "WAS", 14, 0.08, 1, pos="RB")
    await db.commit()
    # Backup projects 15.4 vs the starter's 22 per start: 30% shortfall → 15%.
    monkeypatch.setattr(projection_service, "get_external_projections",
                        _external({"backup": 15.4}))

    proj = await compute_projections(db, ["was_wr", "was_rb"], SEASON)
    wr, rb = proj["was_wr"], proj["was_rb"]
    assert wr["components"]["qb_adj"] == pytest.approx(-14 * QB_CHANGE_CAP, abs=0.2)
    assert rb["components"]["qb_adj"] == pytest.approx(-14 * QB_CHANGE_CAP * 0.4, abs=0.2)
    assert "starter (Out) out, backup starting" in wr["qb_reason"]


async def test_no_qb_discount_when_the_starter_is_healthy(db: AsyncSession, monkeypatch):
    await _week_ahead(db)
    _qb(db, "starter", "WAS", starts=8, ppg=22.0)
    _qb(db, "backup", "WAS", starts=0, ppg=0.0, depth=2)
    _catcher(db, "was_wr", "WAS", 14, 0.22, 1)
    await db.commit()
    monkeypatch.setattr(projection_service, "get_external_projections", _external({}))

    wr = (await compute_projections(db, ["was_wr"], SEASON))["was_wr"]
    assert wr["components"]["qb_adj"] == 0.0 and wr["qb_reason"] is None


async def test_no_qb_discount_once_the_backup_is_the_established_starter(db: AsyncSession, monkeypatch):
    """If the 'backup' has been starting all along, his games are already in the
    receivers' history — no further discount."""
    await _week_ahead(db)
    _qb(db, "hurt_vet", "WAS", starts=2, ppg=22.0, status="Out", depth=2)
    _qb(db, "current", "WAS", starts=6, ppg=17.0, depth=1)
    _catcher(db, "was_wr", "WAS", 14, 0.22, 1)
    await db.commit()
    monkeypatch.setattr(projection_service, "get_external_projections", _external({}))

    wr = (await compute_projections(db, ["was_wr"], SEASON))["was_wr"]
    assert wr["components"]["qb_adj"] == 0.0


async def test_full_name_question_does_not_pull_in_namesakes(db: AsyncSession):
    for pid, name, pos in (
        ("addison", "Jordan Addison", "WR"),
        ("love", "Jordan Love", "QB"),
        ("downs", "Josh Downs", "WR"),
        ("allen", "Josh Allen", "QB"),
    ):
        db.add(Player(id=pid, full_name=name, position=pos, team="X"))
    await db.commit()

    found = await find_mentioned_players(db, "Should I start Jordan Addison or Josh Downs this week?")
    assert {p.id for p in found} == {"addison", "downs"}

    # A bare last name still works.
    found = await find_mentioned_players(db, "Start Addison or Downs?")
    assert {p.id for p in found} == {"addison", "downs"}

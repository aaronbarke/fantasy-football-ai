"""Track record: pre-game snapshots freeze at kickoff, grading against actual
points (0 for a player who didn't play), lineup accuracy vs the best possible
lineup in hindsight, and the report's error/record numbers."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    LeagueConnection,
    LineupSnapshot,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    ProjectionSnapshot,
    Recommendation,
    Roster,
    User,
)
from app.services import accuracy_service, projection_service
from app.services.accuracy_service import (
    accuracy_report,
    grade_lineup,
    grade_pending,
    lineup_lock,
    snapshot_week,
)

SEASON = 2026  # the app's current_season
WEEK = 7


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
    monkeypatch.setattr(accuracy_service, "get_external_projections", _empty)


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _player(db, pid, pos, team, ppg):
    db.add(Player(id=pid, full_name=pid.upper(), position=pos, team=team))
    for wk in range(1, 7):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON - 1, week=wk,
                                 fantasy_points_ppr=ppg + (2 if wk % 2 else -2)))


async def _league(db, early_kick: datetime, late_kick: datetime):
    """This week: AAA@BBB early (the main slate, 2 games), CCC@DDD later."""
    db.add(NflSchedule(season=SEASON, week=WEEK, home_team="BBB", away_team="AAA", game_time=early_kick))
    db.add(NflSchedule(season=SEASON, week=WEEK, home_team="EEE", away_team="FFF", game_time=early_kick))
    db.add(NflSchedule(season=SEASON, week=WEEK, home_team="DDD", away_team="CCC", game_time=late_kick))
    _player(db, "qb", "QB", "AAA", 20)
    _player(db, "rb1", "RB", "AAA", 15)
    _player(db, "rb2", "RB", "CCC", 9)
    _player(db, "byeguy", "RB", "ZZZ", 12)  # team has no game this week
    user = User(id=uuid.uuid4(), email="u@x.com", password_hash="x")
    conn = LeagueConnection(id=uuid.uuid4(), user_id=user.id, platform="sleeper", league_id="L",
                            season=SEASON, scoring_type="ppr", team_id="1",
                            roster_positions=["QB", "RB", "BN", "BN"])
    db.add_all([user, conn])
    db.add(Roster(connection_id=conn.id, team_id="1", players=["qb", "rb1", "rb2", "byeguy"],
                  starters=["qb", "rb2"]))
    await db.commit()
    return conn


# --- snapshots --------------------------------------------------------------------


def test_lineup_lock_is_the_main_slate():
    thu = datetime(2026, 10, 15, 0, 15)
    sun = datetime(2026, 10, 18, 17, 0)
    late = datetime(2026, 10, 18, 20, 25)
    assert lineup_lock([thu, sun, sun, sun, late, late]) == sun
    assert lineup_lock([]) is None


async def test_snapshots_freeze_at_kickoff(db: AsyncSession):
    now = _now()
    conn = await _league(db, early_kick=now + timedelta(hours=2), late_kick=now + timedelta(hours=5))

    first = await snapshot_week(db)
    assert first["week"] == WEEK and first["lineups"] == 1
    snaps = {s.player_id: s for s in (await db.execute(select(ProjectionSnapshot))).scalars().all()}
    assert set(snaps) == {"qb", "rb1", "rb2"}            # bye-week player not tracked
    assert snaps["qb"].kickoff == now + timedelta(hours=2)
    assert snaps["rb2"].kickoff == now + timedelta(hours=5)
    lineup = (await db.execute(select(LineupSnapshot))).scalar_one()
    assert lineup.connection_id == conn.id
    assert {r["player_id"] for r in lineup.recommended} == {"qb", "rb1"}
    assert lineup.actual_starters == ["qb", "rb2"]

    # After the early games kick off, their players and the lineup are frozen;
    # the late game's player can still be updated.
    for s in snaps.values():
        s.projected = -1.0
    await db.commit()
    later = now + timedelta(hours=3)
    await snapshot_week(db, now=later)
    snaps = {s.player_id: s for s in (await db.execute(select(ProjectionSnapshot))).scalars().all()}
    assert snaps["qb"].projected == -1.0 and snaps["rb1"].projected == -1.0   # locked
    assert snaps["rb2"].projected > 0                                         # re-captured


# --- grading -------------------------------------------------------------------------


def _lineup_snapshot(**kw) -> LineupSnapshot:
    base = dict(connection_id=uuid.uuid4(), season=SEASON, week=WEEK, scoring="ppr",
                captured_at=_now())
    base.update(kw)
    return LineupSnapshot(**base)


def test_grade_lineup_against_best_in_hindsight():
    snap = _lineup_snapshot(
        roster=["qb", "rb1", "rb2", "wr1", "wr2", "k1"],
        actual_starters=["qb", "rb2", "wr1", "k1"],
        recommended=[{"slot": "QB", "player_id": "qb"}, {"slot": "RB", "player_id": "rb1"},
                     {"slot": "FLEX", "player_id": "wr1"}, {"slot": "K", "player_id": "k1"}],
        swaps=[{"slot": "RB", "start": "rb1", "sit": "rb2"}],
    )
    positions = {"qb": "QB", "rb1": "RB", "rb2": "RB", "wr1": "WR", "wr2": "WR", "k1": "K"}
    actual = {"qb": 20.0, "rb1": 6.0, "rb2": 14.0, "wr1": 9.0, "wr2": 3.0, "k1": 10.0}
    g = grade_lineup(snap, actual, positions)
    # Best: QB qb, RB rb2, FLEX wr1 → we got 2 of 3 skill slots right.
    assert g["slots"] == 3 and g["correct"] == 2
    assert g["recommended_points"] == 35.0 and g["best_points"] == 43.0
    assert g["your_points"] == 43.0      # kicker isn't counted
    assert g["should_have_started"] == ["rb2"] and g["should_have_sat"] == ["rb1"]
    assert g["swaps"][0]["result"] == "loss"


async def test_grading_waits_for_the_week_then_scores_dnp_as_zero(db: AsyncSession):
    now = _now()
    db.add(NflSchedule(season=SEASON, week=WEEK, home_team="BBB", away_team="AAA",
                       game_time=now - timedelta(days=2)))
    db.add(Player(id="played", full_name="P", position="WR", team="AAA"))
    db.add(Player(id="scratched", full_name="S", position="WR", team="AAA"))
    for pid in ("played", "scratched"):
        db.add(ProjectionSnapshot(season=SEASON, week=WEEK, player_id=pid, position="WR",
                                  scoring="ppr", projected=12.0, captured_at=now))
    await db.commit()

    assert (await grade_pending(db))["projections"] == 0   # no stats yet → wait

    db.add(PlayerStatsWeekly(player_id="played", season=SEASON, week=WEEK,
                             fantasy_points_ppr=17.5))
    await db.commit()
    assert (await grade_pending(db))["projections"] == 2
    snaps = {s.player_id: s for s in (await db.execute(select(ProjectionSnapshot))).scalars().all()}
    assert snaps["played"].actual == 17.5
    assert snaps["scratched"].actual == 0.0  # no stat line once the week is in → didn't play


# --- report ------------------------------------------------------------------------------


async def test_report_numbers(db: AsyncSession):
    now = _now()
    user = User(id=uuid.uuid4(), email="r@x.com", password_hash="x")
    conn = LeagueConnection(id=uuid.uuid4(), user_id=user.id, platform="sleeper", league_id="L",
                            season=SEASON, scoring_type="ppr", team_id="1")
    db.add_all([user, conn])
    db.add(Roster(connection_id=conn.id, team_id="1", players=["a", "b"]))
    for pid, pos in (("a", "WR"), ("b", "RB"), ("c", "WR")):
        db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="X"))
    # projected, actual, sleeper, model
    for pid, pos, proj, act, ext, model in (
        ("a", "WR", 10.0, 14.0, 12.0, 8.0),   # miss +4
        ("b", "RB", 15.0, 9.0, 14.0, 16.0),   # miss -6
        ("c", "WR", 8.0, 8.0, 9.0, 7.0),      # spot on
    ):
        db.add(ProjectionSnapshot(season=SEASON, week=WEEK, player_id=pid, position=pos,
                                  scoring="ppr", projected=proj, actual=act, floor=proj - 5,
                                  ceiling=proj + 5, external_proj=ext, model_proj=model,
                                  captured_at=now, graded_at=now))
    db.add(LineupSnapshot(connection_id=conn.id, season=SEASON, week=WEEK, scoring="ppr",
                          roster=["a", "b"], actual_starters=["a"], recommended=[], swaps=[],
                          captured_at=now, graded_at=now,
                          grade={"slots": 2, "correct": 1, "recommended_points": 20.0,
                                 "best_points": 25.0, "your_points": 18.0,
                                 "should_have_started": ["c"], "should_have_sat": ["b"],
                                 "swaps": [{"slot": "RB", "start": "a", "sit": "c",
                                            "start_points": 14.0, "sit_points": 8.0,
                                            "result": "win"}]}))
    db.add(Recommendation(user_id=user.id, connection_id=conn.id, season=SEASON, week=WEEK,
                          picked_player_id="a", alternative_player_id="b", result="loss"))
    await db.commit()

    r = await accuracy_report(db, conn)
    overall = r["projections"]["overall"]
    assert overall["count"] == 3
    assert overall["avg_miss"] == pytest.approx((4 + 6 + 0) / 3, abs=0.01)
    assert overall["bias"] == pytest.approx((4 - 6 + 0) / 3, abs=0.01)
    assert overall["within_range_pct"] == 67      # b's 9 fell outside 10–20
    vs = r["projections"]["vs_sleeper"]
    assert vs["ours"] == pytest.approx(3.33, abs=0.01)
    assert vs["sleeper_only"] == pytest.approx((2 + 5 + 1) / 3, abs=0.01)
    assert {p["id"] for p in r["projections"]["your_players"]} == {"a", "b"}
    assert r["projections"]["biggest_misses"][0]["name"] == "B"

    lt = r["lineups"]["totals"]
    assert lt["correct"] == 1 and lt["slots"] == 2
    assert lt["avg_points_left"] == 5.0 and lt["avg_vs_your_lineup"] == 2.0
    assert r["lineups"]["weeks"][0]["should_have_started"] == ["C"]
    assert r["start_sit"]["game_plan"]["wins"] == 1
    assert r["start_sit"]["chat"]["losses"] == 1


async def test_report_is_empty_before_anything_is_tracked(db: AsyncSession):
    user = User(id=uuid.uuid4(), email="e@x.com", password_hash="x")
    conn = LeagueConnection(id=uuid.uuid4(), user_id=user.id, platform="sleeper",
                            league_id="L", season=SEASON, team_id="1")
    db.add_all([user, conn])
    await db.commit()
    r = await accuracy_report(db, conn)
    assert r["weeks_tracked"] == [] and r["projections"]["overall"] is None
    assert r["lineups"]["totals"] is None

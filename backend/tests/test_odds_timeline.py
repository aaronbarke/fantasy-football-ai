"""Full-period win-probability history: the scheduler records snapshots from
the first kickoff on, each snapshot says whose points moved, and big swings
are attributed to the players behind them."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base
from app.jobs import scheduler as scheduler_mod
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
from app.services.odds_timeline import (
    build_odds_history,
    game_in_progress,
    player_changes,
    starter_points,
    swing_drivers,
)

SEASON = get_settings().current_season


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


@pytest.fixture
async def factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(factory):
    async with factory() as session:
        yield session


@pytest.fixture(autouse=True)
def _no_external(monkeypatch):
    async def _empty(season, week, scoring="ppr"):
        return {}

    monkeypatch.setattr(projection_service, "get_external_projections", _empty)


async def _week_in_progress(db, kickoff: datetime) -> LeagueConnection:
    """Week 2 kicked off at ``kickoff``; user t1 vs t2, nobody has scored."""
    db.add(NflSchedule(season=SEASON, week=1, home_team="H1", away_team="A1",
                       game_time=kickoff - timedelta(days=7)))
    db.add(NflSchedule(season=SEASON, week=2, home_team="H2", away_team="A2",
                       game_time=kickoff))
    db.add(NflSchedule(season=SEASON, week=2, home_team="H3", away_team="A3",
                       game_time=kickoff + timedelta(hours=3)))
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="t1",
        roster_positions=["QB", "WR", "RB", "BN"],
    )
    db.add(conn)
    for team in ("t1", "t2"):
        for pid, pos, ppg in [(f"{team}_qb", "QB", 20), (f"{team}_wr", "WR", 14), (f"{team}_rb", "RB", 12)]:
            db.add(Player(id=pid, full_name=f"{team.upper()} {pos}", position=pos, team="H2"))
            for wk in range(1, 5):
                db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))
        ids = [f"{team}_qb", f"{team}_wr", f"{team}_rb"]
        db.add(Roster(connection_id=conn.id, team_id=team, owner_name=team,
                      players=ids, starters=ids))
    db.add(Matchup(connection_id=conn.id, week=2, team_a_id="t1", team_b_id="t2",
                   team_a_points=0.0, team_b_points=0.0))
    await db.commit()
    return conn


async def _score(db, conn, points: dict[str, float]) -> None:
    """Set live per-player points and the team totals they add up to."""
    for pid, pts in points.items():
        row = (
            await db.execute(
                select(LivePlayerScore).where(
                    LivePlayerScore.connection_id == conn.id, LivePlayerScore.player_id == pid
                )
            )
        ).scalar_one_or_none()
        if row is None:
            db.add(LivePlayerScore(connection_id=conn.id, week=2, player_id=pid, points=pts))
        else:
            row.points = pts
    await db.flush()
    rows = (
        await db.execute(select(LivePlayerScore).where(LivePlayerScore.connection_id == conn.id))
    ).scalars().all()
    a = sum(r.points for r in rows if r.player_id.startswith("t1"))
    b = sum(r.points for r in rows if r.player_id.startswith("t2"))
    await db.execute(
        update(Matchup)
        .where(Matchup.connection_id == conn.id, Matchup.week == 2)
        .values(team_a_points=a, team_b_points=b)
    )
    await db.commit()


async def _snapshots(db, conn) -> list[MatchupOdds]:
    return (
        await db.execute(
            select(MatchupOdds)
            .where(MatchupOdds.connection_id == conn.id)
            .order_by(MatchupOdds.captured_at, MatchupOdds.id)
        )
    ).scalars().all()


# ── Snapshot recording ──────────────────────────────────────────────────────


async def test_scheduler_records_from_kickoff_before_anyone_scores(db):
    now = _now()
    conn = await _week_in_progress(db, kickoff=now - timedelta(minutes=5))

    # A page view at 0-0 isn't "live" and records nothing…
    p = await build_matchup_preview(db, conn, now=now)
    assert p["live"] is False
    assert await _snapshots(db, conn) == []

    # …but the live-odds job anchors the chart at kickoff with the pre-game odds.
    await build_matchup_preview(db, conn, now=now, record_from_kickoff=True)
    snaps = await _snapshots(db, conn)
    assert len(snaps) == 1
    assert snaps[0].captured_at == now
    assert snaps[0].player_points == {
        "t1_qb": 0.0, "t1_wr": 0.0, "t1_rb": 0.0,
        "t2_qb": 0.0, "t2_wr": 0.0, "t2_rb": 0.0,
    }
    assert snaps[0].changes == []


async def test_job_does_not_record_before_the_week_starts(db):
    now = _now()
    conn = await _week_in_progress(db, kickoff=now + timedelta(hours=2))
    await build_matchup_preview(db, conn, now=now, record_from_kickoff=True)
    assert await _snapshots(db, conn) == []


async def test_each_snapshot_records_whose_points_moved(db):
    now = _now()
    conn = await _week_in_progress(db, kickoff=now - timedelta(minutes=30))
    await build_matchup_preview(db, conn, now=now, record_from_kickoff=True)

    await _score(db, conn, {"t1_rb": 7.0, "t2_qb": 1.5})
    await build_matchup_preview(db, conn, now=now + timedelta(minutes=2))
    await _score(db, conn, {"t1_rb": 7.0, "t2_qb": 1.5, "t2_wr": 6.0})
    await build_matchup_preview(db, conn, now=now + timedelta(minutes=4))

    snaps = await _snapshots(db, conn)
    assert len(snaps) == 3
    assert [(c["id"], c["side"], c["delta"]) for c in snaps[1].changes] == [
        ("t1_rb", "user", 7.0),
        ("t2_qb", "opp", 1.5),
    ]
    assert snaps[1].changes[0]["name"] == "T1 RB"
    # Only the new points count: the RB and QB didn't move again.
    assert [(c["id"], c["delta"], c["points"]) for c in snaps[2].changes] == [
        ("t2_wr", 6.0, 6.0)
    ]
    # The user's TD helped, the opponent's catch hurt.
    assert snaps[1].win_probability > snaps[0].win_probability
    assert snaps[2].win_probability < snaps[1].win_probability


async def test_unchanged_score_is_not_rerecorded(db):
    now = _now()
    conn = await _week_in_progress(db, kickoff=now - timedelta(minutes=30))
    await _score(db, conn, {"t1_qb": 4.0})
    await build_matchup_preview(db, conn, now=now, record_from_kickoff=True)
    await build_matchup_preview(db, conn, now=now, record_from_kickoff=True)
    assert len(await _snapshots(db, conn)) == 1


async def test_live_odds_job_syncs_and_records_every_current_league(factory, monkeypatch):
    now = _now()
    async with factory() as db:
        conn = await _week_in_progress(db, kickoff=now - timedelta(minutes=10))
        stale = LeagueConnection(
            id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn", league_id="OLD",
            season=SEASON - 1, team_id="t1",
        )
        db.add(stale)
        await db.commit()

    synced = []

    async def fake_sync(db, c):
        synced.append(c.league_id)

    monkeypatch.setattr(scheduler_mod, "sync_live_scores", fake_sync)
    checked = await scheduler_mod.record_live_odds(factory, now=now)
    assert checked == 1
    assert synced == ["L"]  # last season's league isn't polled
    async with factory() as db:
        assert len(await _snapshots(db, conn)) == 1


async def test_live_odds_job_is_idle_when_no_game_is_on(factory, monkeypatch):
    now = _now()
    async with factory() as db:
        await _week_in_progress(db, kickoff=now - timedelta(hours=10))
        assert await game_in_progress(db, now) is False

    async def boom(db, c):
        raise AssertionError("shouldn't poll the platform off-hours")

    monkeypatch.setattr(scheduler_mod, "sync_live_scores", boom)
    assert await scheduler_mod.record_live_odds(factory, now=now) == 0


async def test_one_failing_league_does_not_stop_the_job(factory, monkeypatch):
    now = _now()
    async with factory() as db:
        conn = await _week_in_progress(db, kickoff=now - timedelta(minutes=10))
        other = LeagueConnection(
            id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn", league_id="BROKEN",
            season=SEASON, team_id="t9",
        )
        db.add(other)
        await db.commit()

    async def flaky(db, c):
        if c.league_id == "BROKEN":
            raise RuntimeError("expired cookie")

    monkeypatch.setattr(scheduler_mod, "sync_live_scores", flaky)
    assert await scheduler_mod.record_live_odds(factory, now=now) == 1
    async with factory() as db:
        assert len(await _snapshots(db, conn)) == 1


# ── Swing attribution ───────────────────────────────────────────────────────


def _row(user=None, opp=None):
    return {"slot": "X", "user": user, "opponent": opp}


def test_starter_points_counts_unscored_starters_as_zero():
    rows = [
        _row({"id": "a", "name": "Jahmyr Gibbs", "position": "RB", "actual_points": 12.3},
             {"id": "b", "name": "Brock Purdy", "position": "QB", "actual_points": None}),
        _row(None, {"id": "c", "name": "Eagles D/ST", "position": "DEF", "actual_points": 2}),
    ]
    pts, meta = starter_points(rows)
    assert pts == {"a": 12.3, "b": 0.0, "c": 2.0}
    assert meta["a"]["side"] == "user" and meta["b"]["side"] == "opp"


def test_player_changes_without_a_baseline_attributes_nothing():
    assert player_changes(None, {"a": 10.0}, {"a": {"name": "A", "side": "user"}}) == []


def test_player_changes_ignores_noise_and_sorts_biggest_first():
    meta = {k: {"name": k.upper(), "side": "user"} for k in "abc"}
    out = player_changes({"a": 1.0, "b": 2.0, "c": 3.0}, {"a": 1.02, "b": 8.0, "c": 1.0}, meta)
    assert [(c["id"], c["delta"]) for c in out] == [("b", 6.0), ("c", -2.0)]


def test_swing_drivers_pick_the_players_pushing_the_odds_that_way():
    changes = [
        {"id": "opp_wr", "side": "opp", "delta": 9.0},
        {"id": "my_rb", "side": "user", "delta": 6.0},
        {"id": "opp_qb", "side": "opp", "delta": -2.0},  # a pick-six against them
    ]
    up = swing_drivers(changes, +0.08)
    assert [c["id"] for c in up] == ["my_rb", "opp_qb"]
    down = swing_drivers(changes, -0.07)
    assert [c["id"] for c in down] == ["opp_wr"]
    # Odds moved with nobody pushing that way (news, lineup change) → show what moved.
    assert swing_drivers([{"id": "x", "side": "user", "delta": 1.0}], -0.06)[0]["id"] == "x"


def _snap(minute: int, wp: float, changes=None) -> MatchupOdds:
    return MatchupOdds(
        captured_at=datetime(2026, 11, 8, 18, minute), win_probability=wp,
        user_points=0, opp_points=0, changes=changes or [],
    )


def test_history_marks_only_moves_over_the_threshold():
    gibbs = {"id": "g", "name": "Jahmyr Gibbs", "side": "user", "delta": 10.5}
    purdy = {"id": "p", "name": "Brock Purdy", "side": "opp", "delta": -2.0}
    rows = [
        _snap(0, 0.50),
        _snap(2, 0.52, [{"id": "w", "name": "W", "side": "user", "delta": 1.0}]),
        _snap(4, 0.60, [gibbs]),           # +8 → swing
        _snap(6, 0.55, [purdy]),           # exactly −5 → swing
        _snap(8, 0.53),
    ]
    kicks = [
        {"t": "2026-11-08T21:25:00", "home": "SF", "away": "LAR"},
        {"t": "2026-11-08T18:00:00", "home": "DET", "away": "GB"},
    ]
    out = build_odds_history(rows, kicks)
    assert out["window_start"] == "2026-11-08T18:00:00"
    assert out["kickoffs"] == kicks
    pts = out["points"]
    assert pts[0]["delta"] is None and pts[0]["swing"] is None
    assert pts[1]["swing"] is None
    assert pts[2]["swing"]["delta"] == pytest.approx(0.08)
    assert [d["name"] for d in pts[2]["swing"]["drivers"]] == ["Jahmyr Gibbs"]
    # Purdy losing 2 points helped the user, so an opponent's drop can't explain
    # a move against them — the fallback still names what moved.
    assert pts[3]["swing"]["delta"] == pytest.approx(-0.05)
    assert [d["name"] for d in pts[3]["swing"]["drivers"]] == ["Brock Purdy"]
    assert pts[4]["swing"] is None


def test_history_handles_legacy_rows_without_changes():
    rows = [_snap(0, 0.4), _snap(5, 0.7)]
    rows[1].changes = None
    out = build_odds_history(rows, [])
    assert out["window_start"] is None
    assert out["points"][1]["swing"] == {"delta": pytest.approx(0.3), "drivers": []}

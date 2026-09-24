"""Regression tests for the September 2026 bug sweep: live scoring, bye weeks,
thin-history players, week-matched Vegas lines, trade values, the trade
finder, injury alerts, Sleeper points, the accuracy tracker and the shared
current-week resolver."""

import inspect
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    GameCondition,
    LeagueConnection,
    LivePlayerScore,
    Matchup,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    Recommendation,
    Roster,
    User,
)
from app.routers import leagues as leagues_router
from app.routers.draft import candidate_context, draft_rounds
from app.services import injury_service, odds_service, projection_service
from app.services.adp_service import espn_projection_for
from app.services.context_builder import build_context
from app.services.gameplan_service import (
    _display_lineup,
    _player_cards,
    _remaining_fraction,
    build_gameplan,
    build_matchup_preview,
    resolve_current_matchup,
)
from app.services.live_draft_service import _parse_picks
from app.services.projection_service import compute_projections
from app.services.recommendation_service import evaluate_pending
from app.services.sync_service import _sleeper_starters, sleeper_points
from app.services.trade_finder_service import rank_trades
from app.services.value_service import compute_player_values
from app.utils.security import block_demo

SEASON = 2026


def _now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


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


def _player(db, pid, pos, team, ppg=None, games=10, season=SEASON - 1, status=None):
    """A player averaging ``ppg`` (±4 week to week, so projections carry real
    variance; an even ``games`` keeps the mean exact)."""
    db.add(Player(id=pid, full_name=pid, position=pos, team=team, injury_status=status))
    if ppg is not None:
        for wk in range(1, games + 1):
            pts = ppg + (4 if wk % 2 else -4)
            db.add(
                PlayerStatsWeekly(
                    player_id=pid, season=season, week=wk, fantasy_points_ppr=pts
                )
            )


def _conn(**kw) -> LeagueConnection:
    base = dict(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="1", roster_positions=["RB"],
    )
    base.update(kw)
    return LeagueConnection(**base)


# --- live matchup scoring ---------------------------------------------------


async def test_live_matchup_scores_the_lineup_actually_set(db: AsyncSession):
    """Mid-game, the user's side must show (and project) the lineup the
    platform is scoring — not the optimal one. A benched star's points don't
    count, and the actual starter's unplayed game still does."""
    now = _now()
    db.add(NflSchedule(season=SEASON, week=3, home_team="AAA", away_team="BBB",
                       game_time=now - timedelta(hours=1)))
    db.add(NflSchedule(season=SEASON, week=3, home_team="CCC", away_team="DDD",
                       game_time=now + timedelta(hours=6)))
    _player(db, "star", "RB", "AAA", 18)
    _player(db, "starter", "RB", "CCC", 12)
    _player(db, "opp", "RB", "DDD", 14)
    conn = _conn()
    db.add(conn)
    db.add(Roster(connection_id=conn.id, team_id="1", players=["star", "starter"],
                  starters=["starter"]))
    db.add(Roster(connection_id=conn.id, team_id="2", players=["opp"], starters=["opp"]))
    db.add(Matchup(connection_id=conn.id, week=3, team_a_id="1", team_b_id="2",
                   team_a_points=0.0, team_b_points=0.1))
    db.add(LivePlayerScore(connection_id=conn.id, week=3, player_id="star", points=9.0))
    await db.commit()

    out = await build_matchup_preview(db, conn)
    assert out["live"] is True
    assert out["rows"][0]["user"]["id"] == "starter"  # who they actually started
    # 0 banked + the starter's full 12 still to play (his game hasn't started)
    assert out["user"]["expected_total"] == pytest.approx(12.0, abs=0.1)
    # ~12 vs ~14.1 is a close game, not a 0% lock
    assert 0.2 < out["win_probability"] < 0.5


async def test_in_progress_game_keeps_its_remaining_share(db: AsyncSession):
    """A starter whose game is half over still has about half his projection to
    come — it must not vanish at kickoff."""
    now = _now()
    half = timedelta(minutes=95)  # half of a 190-minute game
    db.add(NflSchedule(season=SEASON, week=3, home_team="AAA", away_team="BBB",
                       game_time=now - half))
    _player(db, "mine", "RB", "AAA", 18)
    _player(db, "theirs", "RB", "BBB", 10)
    conn = _conn()
    db.add(conn)
    db.add(Roster(connection_id=conn.id, team_id="1", players=["mine"], starters=["mine"]))
    db.add(Roster(connection_id=conn.id, team_id="2", players=["theirs"], starters=["theirs"]))
    db.add(Matchup(connection_id=conn.id, week=3, team_a_id="1", team_b_id="2",
                   team_a_points=6.0, team_b_points=3.0))
    await db.commit()

    out = await build_matchup_preview(db, conn)
    # 6 banked + ~half of 18 still to come
    assert out["user"]["expected_total"] == pytest.approx(15.0, abs=0.5)
    assert out["opponent"]["expected_total"] == pytest.approx(8.0, abs=0.5)


def test_remaining_fraction_shape():
    now = _now()
    assert _remaining_fraction(None, now) == 1.0
    assert _remaining_fraction(now + timedelta(hours=1), now) == 1.0
    assert _remaining_fraction(now - timedelta(minutes=95), now) == pytest.approx(0.5)
    assert _remaining_fraction(now - timedelta(hours=5), now) == 0.0


# --- projections: byes, thin history, kickers, Vegas week ------------------


async def _two_week_schedule(db, now):
    # This week: AAA @ BBB. CCC is on bye; it plays DDD next week.
    db.add(NflSchedule(season=SEASON, week=3, home_team="BBB", away_team="AAA",
                       game_time=now + timedelta(days=2)))
    db.add(NflSchedule(season=SEASON, week=3, home_team="EEE", away_team="DDD",
                       game_time=now + timedelta(days=2)))
    db.add(NflSchedule(season=SEASON, week=4, home_team="CCC", away_team="DDD",
                       game_time=now + timedelta(days=9)))


async def test_bye_week_player_projects_zero_and_sits(db: AsyncSession):
    await _two_week_schedule(db, _now())
    _player(db, "bye_rb", "RB", "CCC", 20)
    _player(db, "healthy_rb", "RB", "AAA", 9)
    await db.commit()

    proj = await compute_projections(db, ["bye_rb", "healthy_rb"], SEASON)
    assert proj["bye_rb"]["projected"] == 0.0
    assert proj["bye_rb"]["bye"] is True
    assert proj["bye_rb"]["components"]["opponent"] is None
    assert proj["healthy_rb"]["components"]["opponent"] == "BBB"

    cards = await _player_cards(db, ["bye_rb", "healthy_rb"], proj)
    lineup = _display_lineup(["RB"], cards)
    assert lineup[0]["player"]["id"] == "healthy_rb"


async def test_kicker_and_defense_on_bye_project_zero(db: AsyncSession):
    await _two_week_schedule(db, _now())
    _player(db, "k_bye", "K", "CCC")
    _player(db, "k_play", "K", "AAA")
    _player(db, "CCC", "DEF", "CCC")
    await db.commit()
    proj = await compute_projections(db, ["k_bye", "k_play", "CCC"], SEASON)
    assert proj["k_bye"]["projected"] == 0.0
    assert proj["CCC"]["projected"] == 0.0
    assert proj["k_play"]["projected"] == projection_service.K_BASELINE


async def test_thin_history_player_uses_external_projection(db: AsyncSession, monkeypatch):
    """A rookie with two games isn't dropped from projections when Sleeper
    projects him — otherwise the optimizer benches him by default."""
    await _two_week_schedule(db, _now())
    _player(db, "rookie", "RB", "BBB", 22, games=2, season=SEASON)
    await db.commit()

    async def _ext(season, week, scoring="ppr"):
        return {"rookie": 14.0}

    monkeypatch.setattr(projection_service, "get_external_projections", _ext)
    proj = await compute_projections(db, ["rookie"], SEASON)
    assert proj["rookie"]["projected"] == 14.0
    assert proj["rookie"]["confidence"] == "low"
    assert proj["rookie"]["components"]["opponent"] == "AAA"


@pytest.mark.parametrize("insert_current_first", [True, False])
async def test_vegas_total_comes_from_this_weeks_game(db: AsyncSession, insert_current_first):
    now = _now()
    db.add(NflSchedule(season=SEASON, week=1, home_team="AAA", away_team="EEE",
                       game_time=now - timedelta(days=14)))
    db.add(NflSchedule(season=SEASON, week=3, home_team="AAA", away_team="BBB",
                       game_time=now + timedelta(days=2)))
    current = GameCondition(season=SEASON, week=3, home_team="AAA", away_team="BBB",
                            implied_total_home=30, implied_total_away=20)
    stale = GameCondition(season=SEASON, week=1, home_team="AAA", away_team="EEE",
                          implied_total_home=14, implied_total_away=24)
    for gc in ((current, stale) if insert_current_first else (stale, current)):
        db.add(gc)
    _player(db, "qb", "QB", "AAA", 20)
    await db.commit()

    proj = await compute_projections(db, ["qb"], SEASON)
    assert proj["qb"]["components"]["vegas_adj"] > 0  # 30-point total, not 14


async def test_projections_follow_league_scoring(db: AsyncSession):
    db.add(Player(id="wr", full_name="wr", position="WR", team="AAA"))
    for wk in range(1, 8):
        db.add(PlayerStatsWeekly(player_id="wr", season=SEASON - 1, week=wk,
                                 fantasy_points_ppr=18, fantasy_points_half=14,
                                 fantasy_points_std=10))
    await db.commit()
    ppr = await compute_projections(db, ["wr"], SEASON, "ppr")
    std = await compute_projections(db, ["wr"], SEASON, "standard")
    assert ppr["wr"]["projected"] == 18.0
    assert std["wr"]["projected"] == 10.0


# --- odds are filed under their own week ------------------------------------


async def test_odds_are_filed_under_their_own_week(db: AsyncSession, monkeypatch):
    db.add(NflSchedule(season=SEASON, week=3, home_team="BUF", away_team="MIA",
                       game_time=datetime(2026, 9, 27, 17)))
    db.add(NflSchedule(season=SEASON, week=4, home_team="BUF", away_team="NO",
                       game_time=datetime(2026, 10, 4, 17)))
    await db.commit()

    def game(home, away, when, spread, total):
        return {
            "home_team": home, "away_team": away, "commence_time": when,
            "bookmakers": [{"markets": [
                {"key": "spreads", "outcomes": [{"name": home, "point": spread}]},
                {"key": "totals", "outcomes": [{"name": "Over", "point": total}]},
            ]}],
        }

    async def fake_fetch():
        return [
            game("Buffalo Bills", "Miami Dolphins", "2026-09-27T17:00:00Z", -7.0, 48.0),
            game("Buffalo Bills", "New Orleans Saints", "2026-10-04T17:00:00Z", -3.0, 41.0),
        ]

    monkeypatch.setattr(odds_service, "fetch_odds", fake_fetch)
    await odds_service.sync_odds(db, SEASON, 3)
    rows = {
        r.week: r
        for r in (await db.execute(select(GameCondition))).scalars().all()
    }
    assert set(rows) == {3, 4}
    assert rows[3].away_team == "MIA" and float(rows[3].over_under) == 48.0
    assert rows[4].away_team == "NO" and float(rows[4].spread) == -3.0


async def test_odds_calendar_fallback_counts_week_boundaries(db: AsyncSession):
    now = datetime(2026, 9, 23, 15)  # a Wednesday in week 3
    this_sunday = datetime(2026, 9, 27, 17)
    next_sunday = datetime(2026, 10, 4, 17)
    monday_night = datetime(2026, 9, 29, 0, 15)  # MNF, early Tuesday UTC
    week = odds_service._week_for_game
    assert await week(db, SEASON, "X", "Y", this_sunday, 3, now) == 3
    assert await week(db, SEASON, "X", "Y", monday_night, 3, now) == 3
    assert await week(db, SEASON, "X", "Y", next_sunday, 3, now) == 4


# --- trade values and the trade finder --------------------------------------


async def test_two_hot_games_do_not_set_a_peak_floor(db: AsyncSession):
    _player(db, "fluke", "WR", "AAA", 8, games=12)
    for wk in (1, 2):
        db.add(PlayerStatsWeekly(player_id="fluke", season=SEASON, week=wk,
                                 fantasy_points_ppr=25))
    _player(db, "steady", "WR", "BBB", 16, games=17)
    for wk in (1, 2):
        db.add(PlayerStatsWeekly(player_id="steady", season=SEASON, week=wk,
                                 fantasy_points_ppr=16))
    for i in range(60):
        _player(db, f"f{i}", "WR", "CCC", 6 + i * 0.05, games=17)
    await db.commit()

    values = await compute_player_values(db)
    assert values["fluke"]["value"] < values["steady"]["value"]


async def test_trade_values_flag_long_term_injuries(db: AsyncSession):
    _player(db, "ir_wr", "WR", "AAA", 15, games=10, status="Injured Reserve")
    await db.commit()
    values = await compute_player_values(db)
    assert values["ir_wr"]["long_term_injury"] is True


def _tp(pid, pos, ppg, value, **kw):
    return {"id": pid, "name": pid, "position": pos, "team": "X",
            "projected": ppg, "value": value, "trend": "steady", **kw}


SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]
PARTNER = {"team_id": "t2", "owner_name": "Rival", "record": "3-0"}
MY = [
    _tp("qb1", "QB", 18, 50), _tp("rb1", "RB", 6, 12), _tp("rb2", "RB", 5, 10),
    _tp("wr1", "WR", 17, 60), _tp("wr2", "WR", 16, 56), _tp("wr3", "WR", 15, 52),
    _tp("wr4", "WR", 15, 44), _tp("te1", "TE", 8, 22),
]


def test_trade_finder_never_targets_long_term_injured():
    theirs = [
        _tp("oqb", "QB", 16, 45),
        # On IR: a healthy-looking ppg and value, but out for weeks
        _tp("rb_ir", "RB", 14.0, 46, long_term_injury=True, injury_status="IR"),
        _tp("rb_b", "RB", 13, 45), _tp("rb_c", "RB", 12, 40),
        _tp("wr_a", "WR", 7, 16), _tp("ote", "TE", 7, 20),
    ]
    cands = rank_trades(MY, theirs, SLOTS, PARTNER)
    assert cands
    assert all(p["id"] != "rb_ir" for c in cands for p in c["receive"])


def test_long_term_injured_player_adds_nothing_to_a_lineup():
    from app.services.trade_finder_service import _roster_dicts

    meta = {
        "ir": Player(id="ir", full_name="IR", position="RB", team="X",
                     injury_status="Injured Reserve"),
        "ok": Player(id="ok", full_name="OK", position="RB", team="X"),
    }
    values = {"ir": {"ppg": 15.0, "value": 40}, "ok": {"ppg": 9.0, "value": 20}}
    rows = {r["id"]: r for r in _roster_dicts(["ir", "ok"], values, meta)}
    assert rows["ir"]["projected"] == 0.0 and rows["ir"]["long_term_injury"]
    assert rows["ok"]["projected"] == 9.0


def test_uneven_package_charges_the_forced_cut():
    # Two bench WRs (35 + 33) for a stud RB (68). With open roster spots it's
    # even; with full rosters the partner must cut a 30-value RB to take two
    # players, so it's no longer a fair deal for them.
    mine = [
        _tp("qb1", "QB", 18, 50), _tp("rb1", "RB", 14, 40), _tp("rb2", "RB", 5, 10),
        _tp("wr1", "WR", 16, 55), _tp("wr2", "WR", 15, 50), _tp("wr3", "WR", 13, 40),
        _tp("wr4", "WR", 12, 35), _tp("wr5", "WR", 11, 33), _tp("te1", "TE", 9, 25),
    ]
    theirs = [
        _tp("oqb", "QB", 15, 45), _tp("rb_stud", "RB", 18, 68), _tp("rb_x", "RB", 12, 35),
        _tp("rb_y", "RB", 10, 30), _tp("owr1", "WR", 6, 30), _tp("owr2", "WR", 5, 31),
        _tp("ote", "TE", 7, 31), _tp("ote2", "TE", 6, 32), _tp("oqb2", "QB", 8, 33),
    ]

    def two_for_one(cands):
        return [c for c in cands if len(c["give"]) == 2 and c["receive"][0]["id"] == "rb_stud"]

    assert two_for_one(rank_trades(mine, theirs, SLOTS, PARTNER))
    full = rank_trades(mine, theirs, SLOTS, PARTNER, roster_size=len(theirs))
    assert not two_for_one(full)


# --- injury alerts ------------------------------------------------------------


async def test_ir_spelling_difference_is_not_a_new_injury(db: AsyncSession, monkeypatch):
    async def feed():
        return [{"espn_id": "123", "name": "X", "status": "Injured Reserve", "body_part": "Knee"}]

    monkeypatch.setattr(injury_service, "fetch_injuries", feed)
    db.add(Player(id="p1", full_name="X", position="WR", espn_id="123", injury_status="IR"))
    await db.commit()
    assert await injury_service.sync_injuries(db) == []


async def test_real_downgrade_still_alerts(db: AsyncSession, monkeypatch):
    async def feed():
        return [{"espn_id": "123", "name": "X", "status": "Out", "body_part": "Knee"}]

    monkeypatch.setattr(injury_service, "fetch_injuries", feed)
    db.add(Player(id="p1", full_name="X", position="WR", espn_id="123",
                  injury_status="Questionable"))
    await db.commit()
    events = await injury_service.sync_injuries(db)
    assert [(e.old_status, e.new_status) for e in events] == [("Questionable", "Out")]


# --- Sleeper sync -------------------------------------------------------------


def test_sleeper_points_include_decimals():
    settings = {"fpts": 1617, "fpts_decimal": 78, "fpts_against": 1670,
                "fpts_against_decimal": 32}
    assert sleeper_points(settings, "fpts") == 1617.78
    assert sleeper_points(settings, "fpts_against") == 1670.32
    assert sleeper_points({}, "fpts") == 0.0


def test_sleeper_empty_starter_slots_are_dropped():
    assert _sleeper_starters(["4046", "0", None, "6794"]) == ["4046", "6794"]


# --- accuracy tracker ---------------------------------------------------------


async def test_pick_whose_player_did_not_play_is_graded(db: AsyncSession):
    db.add(User(id=(uid := uuid.uuid4()), email="u@x.com", password_hash="x"))
    db.add(Player(id="inactive", full_name="Inactive", position="WR"))
    db.add(Player(id="played", full_name="Played", position="WR"))
    db.add(PlayerStatsWeekly(player_id="played", season=SEASON, week=2,
                             fantasy_points_ppr=11.0))
    db.add(Recommendation(user_id=uid, season=SEASON, week=2,
                          picked_player_id="inactive", alternative_player_id="played",
                          scoring_type="ppr"))
    # A pick for a week whose stats aren't loaded yet stays pending.
    db.add(Recommendation(user_id=uid, season=SEASON, week=3,
                          picked_player_id="inactive", alternative_player_id="played",
                          scoring_type="ppr"))
    await db.commit()

    assert await evaluate_pending(db) == 1
    recs = {r.week: r for r in (await db.execute(select(Recommendation))).scalars().all()}
    assert recs[2].result == "loss"
    assert float(recs[2].picked_points) == 0.0
    assert recs[3].result == "pending"


# --- one definition of "this week" -------------------------------------------


async def _espn_style_league(db, now):
    """Full-season schedule (ESPN style) where week 3 is live and has points."""
    for wk, offset in ((2, -7), (3, 0), (4, 7), (14, 77)):
        db.add(NflSchedule(season=SEASON, week=wk, home_team="AAA", away_team="BBB",
                           game_time=now + timedelta(days=offset, hours=-1)))
    conn = _conn(platform="espn", roster_positions=["RB"])
    db.add(conn)
    _player(db, "mine", "RB", "AAA", 12)
    for team in ("2", "3", "4", "5"):
        _player(db, f"opp{team}", "RB", "BBB", 10)
        db.add(Roster(connection_id=conn.id, team_id=team, owner_name=f"Team {team}",
                      players=[f"opp{team}"], starters=[f"opp{team}"]))
    db.add(Roster(connection_id=conn.id, team_id="1", owner_name="Me",
                  players=["mine"], starters=["mine"]))
    for wk, opp, pts in ((2, "2", 100.0), (3, "3", 20.0), (4, "4", 0.0), (14, "5", 0.0)):
        db.add(Matchup(connection_id=conn.id, week=wk, team_a_id="1", team_b_id=opp,
                       team_a_points=pts, team_b_points=pts))
    await db.commit()
    return conn


async def test_every_surface_agrees_on_this_week(db: AsyncSession):
    conn = await _espn_style_league(db, _now())
    user = User(id=conn.user_id, email="me@x.com", password_hash="x")
    db.add(user)
    await db.commit()

    m = await resolve_current_matchup(db, conn)
    assert m.week == 3 and m.team_b_id == "3"

    dash = await leagues_router.get_matchup(str(conn.id), user=user, db=db)
    assert dash.week == 3 and dash.opponent_team.team_id == "3"

    plan = await build_gameplan(db, conn)
    assert plan["opponent"]["week"] == 3 and plan["opponent"]["name"] == "Team 3"

    _, ctx = await build_context(db, conn, "Who is my opponent this week?")
    assert ctx["opponent"]["week"] == 3 and ctx["opponent"]["owner_name"] == "Team 3"


async def test_standings_count_ties_as_half_wins(db: AsyncSession):
    conn = _conn()
    user = User(id=conn.user_id, email="s@x.com", password_hash="x")
    db.add_all([conn, user])
    db.add(Roster(connection_id=conn.id, team_id="a", wins=5, losses=1, ties=0,
                  points_for=900, players=[]))
    db.add(Roster(connection_id=conn.id, team_id="b", wins=5, losses=0, ties=1,
                  points_for=800, players=[]))
    await db.commit()
    rows = await leagues_router.get_standings(str(conn.id), user=user, db=db)
    assert [r.team_id for r in rows] == ["b", "a"]


def test_shared_demo_league_cannot_be_deleted_or_added_to():
    for route in (leagues_router.disconnect_league, leagues_router.connect_league):
        assert inspect.signature(route).parameters["user"].default.dependency is block_demo


# --- draft --------------------------------------------------------------------


def test_draft_advice_context_handles_kicker_candidates():
    kicker = {"player_id": "k1", "name": "K One", "position": "K", "team": "DAL",
              "adp": 150.0, "score": 40.0, "reasons": ["Time to lock in a K"]}
    ctx = candidate_context(kicker, [{"headline": "Kicker news"}])
    assert ctx["name"] == "K One" and ctx["tier"] is None
    assert ctx["recent_news"] == ["Kicker news"]


def test_draft_rounds_ignore_reserve_slots():
    assert draft_rounds(["QB", "RB", "WR", "BN", "IR", "IR", "TAXI"]) == 4


def test_live_draft_maps_team_defense_picks():
    picks = [{"playerId": -16002, "teamId": 1, "overallPickNumber": 1,
              "roundId": 1, "roundPickNumber": 1}]
    out = _parse_picks(picks, {}, "1")
    assert out["drafted_player_ids"] == ["BUF"]
    assert out["unmapped_count"] == 0


def test_espn_draft_projection_converted_per_scoring():
    payload = {"season_proj": 300.0, "season_proj_rec": 100.0}
    assert espn_projection_for(payload, "ppr") == 300.0
    assert espn_projection_for(payload, "half_ppr") == 250.0
    assert espn_projection_for(payload, "standard") == 200.0
    assert espn_projection_for({"season_proj": 300.0}, "standard") == 300.0

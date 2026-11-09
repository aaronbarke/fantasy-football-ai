"""The Matchup chart's curve rebuilt from play-by-play: plays → each starter's
points over time → win probability from first kickoff to now, with big
swings named after the plays (and injury news) behind them."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
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
from app.services import nfl_plays_service, projection_service
from app.services.gameplan_service import build_matchup_preview
from app.services.nfl_plays_service import parse_plays, remaining_share
from app.services.odds_rebuild import (
    name_pattern,
    play_events,
    rebuild_odds_history,
    rebuild_timeline,
)
from app.services.odds_timeline import news_changes

SEASON = get_settings().current_season
K = datetime(2026, 11, 8, 18, 0)  # Sunday kickoff (UTC)


def _p(name, side="user", pid=None, pos="WR"):
    return {"id": pid or name, "name": name, "side": side, "position": pos,
            "pattern": name_pattern(name)}


def _play(t, ptype, text, yards=0, period=1, clock=600):
    return {"t": t.isoformat(), "type": ptype, "text": text, "yards": yards,
            "period": period, "clock": clock, "turnover": False}


# ── Reading plays ───────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "full,text,hit",
    [
        ("Amon-Ra St. Brown", "J.Goff pass short left to A.St. Brown to DET 40", True),
        ("Kenneth Walker III", "K.Walker left end for 4 yards", True),
        ("Ja'Marr Chase", "J.Burrow pass deep to J.Chase for 30 yards", True),
        ("Kenneth Walker III", "K.Walkers left end for 4 yards", False),
        ("Josh Allen", "J.Allenby up the middle", False),
    ],
)
def test_name_pattern_matches_espn_play_names(full, text, hit):
    assert bool(name_pattern(full).search(text)) is hit


def test_passing_touchdown_credits_passer_receiver_and_kicker():
    qb, wr, k = _p("Jordan Love"), _p("Matthew Golden"), _p("Trey Smack", pos="K")
    play = _play(K, "Passing Touchdown",
                 "(Shotgun) J.Love pass short middle to M.Golden for 5 yards, TOUCHDOWN. "
                 "T.Smack extra point is GOOD, Center-M.Orzech, Holder-D.Whelan.", yards=5)
    got = {e["id"]: (e["pts"], e["label"]) for e in play_events(play, [qb, wr, k])}
    assert got["Jordan Love"] == (4.2, "5-yd TD pass")
    assert got["Matthew Golden"] == (7.5, "5-yd TD catch")
    assert got["Trey Smack"] == (1.0, "PAT")


def test_rush_int_fumble_and_field_goal():
    rb, qb, k = _p("Jahmyr Gibbs", pos="RB"), _p("Brock Purdy", pos="QB"), _p("Jake Bates", pos="K")
    run = _play(K, "Rushing Touchdown", "J.Gibbs left end for 45 yards, TOUCHDOWN. J.Bates extra point is GOOD.", 45)
    pick = _play(K, "Pass Interception Return", "(Shotgun) B.Purdy pass deep left intended for G.Kittle INTERCEPTED by X.Y at 50.", 12)
    fum = _play(K, "Fumble Recovery (Opponent)", "J.Gibbs up the middle to DET 30 for 3 yards. FUMBLES (A.B), RECOVERED by GB-C.D at DET 31.", 3)
    fg = _play(K, "Field Goal Good", " J.Bates 52 yard field goal is GOOD, Center-X.", 52)
    assert [(e["id"], e["pts"], e["label"]) for e in play_events(run, [rb, k])] == [
        ("Jahmyr Gibbs", 10.5, "45-yd TD run"), ("Jake Bates", 1.0, "PAT")]
    assert [(e["pts"], e["label"]) for e in play_events(pick, [qb])] == [(-2.0, "INT")]
    assert [(e["pts"], e["label"]) for e in play_events(fum, [rb])] == [(-2.0, "fumble lost")]
    assert [(e["pts"], e["label"]) for e in play_events(fg, [k])] == [(5.0, "52-yd FG")]


def test_penalties_two_point_tries_and_direct_snaps():
    wr, te = _p("Oronde Gadsden", pos="TE"), _p("Chris Rodriguez Jr.", pos="RB")
    no_play = _play(K, "Penalty", "J.Herbert pass to O.Gadsden for 18 yards. PENALTY on X - No Play.", 18)
    two_pt = _play(K, "Passing Touchdown",
                   "J.Herbert pass short right to Q.Johnston for 58 yards, TOUCHDOWN. TWO-POINT CONVERSION "
                   "ATTEMPT. J.Herbert pass to O.Gadsden is incomplete. ATTEMPT FAILS.", 58)
    snap = _play(K, "Rush", "(Shotgun) W.Milum reported in as eligible. Direct snap to C.Rodriguez.  "
                 "C.Rodriguez right tackle to BLT 30 for 2 yards (B.W).", 2)
    assert play_events(no_play, [wr]) == []
    assert play_events(two_pt, [wr]) == []
    assert [(e["pts"], e["label"]) for e in play_events(snap, [te])] == [(0.2, "2-yd run")]


def test_ppr_setting_changes_catch_value():
    wr = _p("Matthew Golden")
    play = _play(K, "Pass Reception", "J.Love pass short right to M.Golden to GB 40 for 10 yards.", 10)
    assert play_events(play, [wr], "standard")[0]["pts"] == 1.0
    assert play_events(play, [wr], "half_ppr")[0]["pts"] == 1.5


def test_parse_plays_orders_by_wallclock_and_reads_clock():
    summary = {"drives": {"previous": [{"plays": [
        {"id": "2", "type": {"text": "Rush"}, "text": "b", "wallclock": "2026-11-08T18:10:00Z",
         "period": {"number": 1}, "clock": {"displayValue": "12:30"}, "statYardage": 3},
        {"id": "1", "type": {"text": "Kickoff"}, "text": "a", "wallclock": "2026-11-08T18:00:00Z",
         "period": {"number": 1}, "clock": {"displayValue": "15:00"}},
        {"id": "3", "type": {"text": "Rush"}, "text": "no time", "period": {"number": 1}},
    ]}]}}
    plays = parse_plays(summary)
    assert [p["text"] for p in plays] == ["a", "b"]
    assert plays[1]["clock"] == 750 and plays[1]["yards"] == 3


def test_remaining_share_by_game_clock():
    assert remaining_share(1, 900) == 1.0
    assert remaining_share(2, 0) == 0.5
    assert remaining_share(4, 450) == pytest.approx(0.125)
    assert remaining_share(5, 300) == 0.0  # overtime
    assert remaining_share(None, None) == 1.0


# ── Rebuilding the curve ───────────────────────────────────────────────────


def _starter(name, side, team, points, proj=12.0, sd=6.0, pos="RB", status=None):
    return {"id": name, "name": name, "position": pos, "team": team, "side": side,
            "points": points, "projected": proj, "stdev": sd, "injury_status": status}


def _game(kickoff, plays, final=True):
    return {"kickoff": kickoff, "plays": plays, "final": final}


def _sunday():
    """You: Gibbs (DET). Them: Purdy (SF). Both games final."""
    det = _game(K, [
        _play(K + timedelta(minutes=1), "Kickoff", "kick", 0, 1, 900),
        _play(K + timedelta(minutes=40), "Rushing Touchdown",
              "J.Gibbs left end for 45 yards, TOUCHDOWN. X.Y extra point is GOOD.", 45, 2, 600),
        _play(K + timedelta(minutes=185), "End of Game", "END GAME", 0, 4, 0),
    ])
    sf = _game(K + timedelta(hours=3, minutes=25), [
        _play(K + timedelta(hours=3, minutes=26), "Kickoff", "kick", 0, 1, 900),
        _play(K + timedelta(hours=4), "Pass Interception Return",
              "B.Purdy pass deep intended for G.K INTERCEPTED by Z at 40.", 0, 2, 300),
        _play(K + timedelta(hours=6, minutes=30), "End of Game", "END GAME", 0, 4, 0),
    ])
    starters = [
        _starter("Jahmyr Gibbs", "user", "DET", points=16.0, proj=15.0, pos="RB"),
        _starter("Brock Purdy", "opp", "SF", points=14.0, proj=18.0, pos="QB"),
    ]
    return starters, {"DET": det, "SF": sf}


def test_curve_spans_first_kickoff_to_now_and_ends_at_real_scores():
    starters, games = _sunday()
    now = K + timedelta(hours=8)
    out = rebuild_timeline(starters, games, [K, K + timedelta(hours=3, minutes=25)], now)
    pts = out["points"]
    assert pts[0]["t"] == K.isoformat()
    assert pts[-1]["t"] == now.isoformat()
    # Every starter ends at his real points (plays + the even spread of the rest).
    assert pts[-1]["user_points"] == 16.0 and pts[-1]["opp_points"] == 14.0
    # All games are over: the side with more points has won.
    assert pts[-1]["win_probability"] == pytest.approx(1.0, abs=1e-3)
    # Dense: a point at least every 5 minutes inside the game window.
    end = datetime.fromisoformat(out["windows"][-1]["end"])
    assert end == K + timedelta(hours=6, minutes=30)  # the last game's final play
    times = [datetime.fromisoformat(p["t"]) for p in pts if datetime.fromisoformat(p["t"]) <= end]
    assert max(b - a for a, b in zip(times, times[1:])) <= timedelta(minutes=5)


def test_touchdown_is_a_named_swing_at_its_real_minute():
    starters, games = _sunday()
    out = rebuild_timeline(starters, games, [K], K + timedelta(hours=8))
    td_time = (K + timedelta(minutes=40)).isoformat()
    td = next(p for p in out["points"] if p["t"] == td_time)
    assert td["delta"] > 0.05
    assert td["swing"]["drivers"][0]["name"] == "Jahmyr Gibbs"
    assert td["swing"]["drivers"][0]["label"] == "45-yd TD run"
    # Just before the play the odds were lower: a step, not a smeared slope.
    before = next(p for p in out["points"]
                  if p["t"] == (K + timedelta(minutes=40) - timedelta(seconds=1)).isoformat())
    assert before["win_probability"] < td["win_probability"]
    # The opponent's interception helps you, and names him.
    pick = next(p for p in out["points"] if p.get("events") and p["events"][0]["label"] == "INT")
    assert pick["events"][0]["name"] == "Brock Purdy" and pick["delta"] > 0


def test_game_without_plays_accrues_evenly():
    starters, games = _sunday()
    games["DET"]["plays"] = None  # ESPN unreachable for that game
    now = K + timedelta(hours=8)
    out = rebuild_timeline(starters, games, [K], now)
    mid = next(p for p in out["points"] if p["t"] == (K + timedelta(minutes=95)).isoformat())
    assert mid["user_points"] == pytest.approx(16.0 * 95 / 190, abs=0.1)
    assert out["points"][-1]["user_points"] == 16.0


def test_injury_news_shows_as_a_named_drop_when_it_landed():
    starters, games = _sunday()
    adams = _starter("Davante Adams", "user", "LAR", points=0.0, proj=0.0, pos="WR",
                     status="Injured Reserve")
    games["LAR"] = _game(K + timedelta(hours=7), None, final=False)
    news_at = K + timedelta(hours=1, minutes=7)
    history = {"Davante Adams": [
        (K - timedelta(hours=20), 16.6, 7.0, "Active"),
        (news_at, 0.0, 0.0, "Injured Reserve"),
    ]}
    out = rebuild_timeline([*starters, adams], games, [K], K + timedelta(hours=8),
                           proj_history=history)
    drop = next(p for p in out["points"] if p["t"] == news_at.isoformat())
    assert drop["delta"] < -0.05
    d = drop["swing"]["drivers"][0]
    assert d["name"] == "Davante Adams" and d["kind"] == "news"
    assert d["label"] == "→ Injured Reserve, −16.6 proj"


def test_nothing_before_the_first_kickoff():
    starters, games = _sunday()
    out = rebuild_timeline(starters, games, [K], K - timedelta(hours=1))
    assert out["points"] == []


def test_news_changes_between_snapshots():
    meta = {"a": {"name": "Davante Adams", "side": "user", "position": "WR"}}
    prev = {"a": {"proj": 16.6, "sd": 7, "status": "Active"}}
    cur = {"a": {"proj": 0.0, "sd": 0, "status": "Injured Reserve"}}
    [c] = news_changes(prev, cur, meta)
    assert c["kind"] == "news" and c["status"] == "Injured Reserve" and c["proj_delta"] == -16.6
    assert news_changes(prev, {"a": {"proj": 16.4, "sd": 7, "status": "Active"}}, meta) == []
    assert news_changes(None, cur, meta) == []


# ── End to end against the database ────────────────────────────────────────


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


async def _league(db, kickoff):
    db.add(NflSchedule(season=SEASON, week=9, home_team="DET", away_team="GB", game_time=kickoff))
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="1", roster_positions=["RB", "BN"],
    )
    db.add(conn)
    for team_id, pid, name, team in (("1", "gibbs", "Jahmyr Gibbs", "DET"), ("2", "jacobs", "Josh Jacobs", "GB")):
        db.add(Player(id=pid, full_name=name, position="RB", team=team))
        for wk in range(1, 9):
            db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=15))
        db.add(Roster(connection_id=conn.id, team_id=team_id, owner_name=team_id,
                      players=[pid], starters=[pid]))
    db.add(Matchup(connection_id=conn.id, week=9, team_a_id="1", team_b_id="2",
                   team_a_points=10.5, team_b_points=2.0))
    db.add(LivePlayerScore(connection_id=conn.id, week=9, player_id="gibbs", points=10.5))
    db.add(LivePlayerScore(connection_id=conn.id, week=9, player_id="jacobs", points=2.0))
    await db.commit()
    return conn


def _espn(kickoff, state="in", period=2, clock=600.0):
    k = kickoff.strftime("%Y-%m-%dT%H:%MZ")
    scoreboard = {"events": [{
        "id": "999", "date": k,
        "competitions": [{"competitors": [
            {"homeAway": "home", "team": {"abbreviation": "DET"}},
            {"homeAway": "away", "team": {"abbreviation": "GB"}},
        ], "status": {"period": period, "clock": clock, "type": {"state": state}}}],
    }]}
    w = lambda m: (kickoff + timedelta(minutes=m)).strftime("%Y-%m-%dT%H:%M:%SZ")  # noqa: E731
    summary = {"drives": {"previous": [{"plays": [
        {"id": "1", "type": {"text": "Kickoff"}, "text": "kick", "wallclock": w(0),
         "period": {"number": 1}, "clock": {"displayValue": "15:00"}},
        {"id": "2", "type": {"text": "Rushing Touchdown"}, "statYardage": 45, "wallclock": w(30),
         "text": "J.Gibbs left end for 45 yards, TOUCHDOWN.", "period": {"number": 1},
         "clock": {"displayValue": "02:00"}},
        {"id": "3", "type": {"text": "Rush"}, "statYardage": 20, "wallclock": w(50),
         "text": "J.Jacobs up the middle to DET 30 for 20 yards.", "period": {"number": 2},
         "clock": {"displayValue": "10:00"}},
    ]}]}}
    return scoreboard, summary


async def test_rebuild_end_to_end_with_espn_plays(db, monkeypatch):
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(hours=1)
    conn = await _league(db, kickoff)
    # A Thursday game with none of these starters isn't part of the chart.
    db.add(NflSchedule(season=SEASON, week=9, home_team="BAL", away_team="JAX",
                       game_time=kickoff - timedelta(days=3)))
    await db.commit()
    scoreboard, summary = _espn(kickoff)

    async def fake_fetch(url, params):
        return summary if "summary" in url else scoreboard

    monkeypatch.setattr(nfl_plays_service, "_fetch_json", fake_fetch)
    out = await rebuild_odds_history(db, conn)
    assert out["week"] == 9 and out["source"] == "plays"
    assert out["window_start"] == kickoff.isoformat()
    assert [k["home"] for k in out["kickoffs"]] == ["DET"]
    pts = out["points"]
    assert pts[0]["t"] == kickoff.isoformat()
    assert pts[-1]["user_points"] == 10.5 and pts[-1]["opp_points"] == 2.0
    td = next(p for p in pts if p.get("events") and p["events"][0]["label"] == "45-yd TD run")
    assert td["events"][0]["name"] == "Jahmyr Gibbs"
    # Rebuilding never writes snapshots.
    assert (await db.execute(select(MatchupOdds))).scalars().all() == []


async def test_live_odds_use_the_game_clock(db, monkeypatch):
    """A final game has nothing left to play, however long ago it kicked off."""
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=30)
    conn = await _league(db, kickoff)
    clockless = await build_matchup_preview(db, conn, record=False)
    scoreboard, summary = _espn(kickoff, state="post")

    async def fake_fetch(url, params):
        return summary if "summary" in url else scoreboard

    monkeypatch.setattr(nfl_plays_service, "_fetch_json", fake_fetch)
    from app.services import cache

    cache._local.clear()
    final = await build_matchup_preview(db, conn, record=False)
    # 30 minutes in, the wall-clock model still expects most of each game…
    assert clockless["user"]["expected_total"] > 20
    # …but ESPN says it's over: expected = what's been scored.
    assert final["user"]["expected_total"] == 10.5
    assert final["opponent"]["expected_total"] == 2.0
    assert final["win_probability"] > 0.99


async def test_snapshots_keep_projections_for_news(db):
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(minutes=30)
    conn = await _league(db, kickoff)
    await build_matchup_preview(db, conn)
    snap = (await db.execute(select(MatchupOdds))).scalars().one()
    assert set(snap.player_proj) == {"gibbs", "jacobs"}
    assert snap.player_proj["gibbs"]["proj"] > 0


# ── Per-play swings, ESPN-id matching, unexplained point jumps ─────────────


def test_three_point_moves_are_swings_and_each_play_stands_alone():
    from app.services.odds_timeline import SWING_THRESHOLD

    assert SWING_THRESHOLD == 0.03
    starters = [
        _starter("Brock Purdy", "user", "SF", points=10.2, proj=18.0, sd=8.0, pos="QB"),
        _starter("Jahmyr Gibbs", "opp", "SF", points=0.0, proj=0.0, sd=0.0, pos="RB"),
        _starter("Puka Nacua", "opp", "LAR", points=0.0, proj=17.0, sd=7.0, pos="WR"),
    ]
    sf = _game(K, [
        _play(K + timedelta(minutes=30), "Passing Touchdown",
              "B.Purdy pass deep left to G.Kittle for 32 yards, TOUCHDOWN.", 32, 1, 300),
        # The next snap, 40 seconds later: a separate moment, not merged in.
        _play(K + timedelta(minutes=30, seconds=40), "Rush",
              "B.Purdy scrambles right end for 12 yards.", 12, 1, 260),
    ], final=False)
    lar = _game(K + timedelta(hours=3), None, final=False)
    out = rebuild_timeline(starters, {"SF": sf, "LAR": lar}, [K], K + timedelta(minutes=60))
    moments = [p for p in out["points"] if p.get("events")]
    assert [m["events"][0]["label"] for m in moments] == ["32-yd TD pass", "12-yd run"]
    td = moments[0]
    assert 0.03 <= td["swing"]["delta"]
    assert td["swing"]["drivers"][0]["name"] == "Brock Purdy"


def test_unexplained_point_jump_names_the_player():
    """ESPN plays unavailable, but the live job saw Gibbs go 2.0 → 10.4."""
    starters = [
        _starter("Jahmyr Gibbs", "user", "DET", points=10.4, proj=15.0, sd=6.0),
        _starter("Puka Nacua", "opp", "LAR", points=0.0, proj=15.0, sd=6.0),
    ]
    games = {"DET": _game(K, None, final=False), "LAR": _game(K + timedelta(hours=3), None, final=False)}
    seen = {"Jahmyr Gibbs": [(K + timedelta(minutes=20), 2.0), (K + timedelta(minutes=50), 10.4)]}
    out = rebuild_timeline(starters, games, [K], K + timedelta(minutes=60), points_history=seen)
    jump = next(p for p in out["points"] if p["t"] == (K + timedelta(minutes=50)).isoformat())
    [e] = jump["events"]
    assert e["kind"] == "points" and e["name"] == "Jahmyr Gibbs" and e["label"] == "+8.4 pts"
    assert jump["swing"]["drivers"][0]["label"] == "+8.4 pts"
    # The rest of his points still add up: he ends at his real total.
    assert out["points"][-1]["user_points"] == 10.4


def test_jump_explained_by_a_matched_play_is_not_double_counted():
    starters = [_starter("Jahmyr Gibbs", "user", "DET", points=10.5, proj=15.0, sd=6.0)]
    det = _game(K, [_play(K + timedelta(minutes=40), "Rushing Touchdown",
                          "J.Gibbs left end for 45 yards, TOUCHDOWN.", 45, 2, 600)], final=False)
    seen = {"Jahmyr Gibbs": [(K + timedelta(minutes=39), 0.0), (K + timedelta(minutes=41), 10.5)]}
    out = rebuild_timeline(starters, {"DET": det}, [K], K + timedelta(minutes=60), points_history=seen)
    labels = [e["label"] for p in out["points"] for e in p.get("events") or []]
    assert labels == ["45-yd TD run"]


def test_match_name_finds_a_player_stored_under_another_name():
    """Our feed says "Hollywood Brown"; ESPN's plays say "M.Brown"."""
    s = _starter("Hollywood Brown", "user", "KC", points=9.0, proj=10.0, sd=5.0, pos="WR")
    s["match_name"] = "Marquise Brown"
    kc = _game(K, [_play(K + timedelta(minutes=10), "Pass Reception",
                         "P.Mahomes pass deep right to M.Brown to KC 40 for 30 yards.", 30, 1, 400)],
               final=False)
    out = rebuild_timeline([s], {"KC": kc}, [K], K + timedelta(minutes=30))
    ev = next(p for p in out["points"] if p.get("events"))["events"][0]
    assert ev["name"] == "Hollywood Brown" and ev["label"] == "30-yd catch"


def test_parse_athletes_reads_espn_ids_from_the_box_score():
    from app.services.nfl_plays_service import parse_athletes

    summary = {"boxscore": {"players": [{"team": {"abbreviation": "WSH"}, "statistics": [
        {"athletes": [{"athlete": {"id": "4429795", "firstName": "Jahmyr", "lastName": "Gibbs",
                                   "displayName": "Jahmyr Gibbs"}}]},
    ]}]}}
    assert parse_athletes(summary) == {"4429795": {"name": "Jahmyr Gibbs", "team": "WAS"}}


async def test_rebuild_matches_players_through_espn_ids(db, monkeypatch):
    kickoff = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0) - timedelta(hours=1)
    conn = await _league(db, kickoff)
    gibbs = await db.get(Player, "gibbs")
    gibbs.full_name = "Sonic Gibbs"  # a nickname "S.Gibbs" would never match…
    gibbs.espn_id = "4429795"
    await db.commit()
    scoreboard, summary = _espn(kickoff)
    summary["drives"]["previous"][0]["plays"][1]["text"] = "J.Gibbs left end for 45 yards, TOUCHDOWN."
    summary["boxscore"] = {"players": [{"team": {"abbreviation": "DET"}, "statistics": [{"athletes": [
        {"athlete": {"id": "4429795", "firstName": "Jahmyr", "lastName": "Gibbs"}}]}]}]}

    async def fake_fetch(url, params):
        return summary if "summary" in url else scoreboard

    monkeypatch.setattr(nfl_plays_service, "_fetch_json", fake_fetch)
    out = await rebuild_odds_history(db, conn)
    ev = next(p for p in out["points"] if p.get("events") and p["events"][0]["side"] == "user")["events"][0]
    # …but his ESPN id finds him as "J.Gibbs".
    assert ev["label"] == "45-yd TD run" and ev["name"] == "Sonic Gibbs"

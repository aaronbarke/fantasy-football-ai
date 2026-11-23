"""Automated trade finder — pure ranking logic + league-scan wiring."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import LeagueConnection, Player, PlayerStatsWeekly, Roster
from app.services.trade_finder_service import FAIRNESS_PCT, find_trades, rank_trades

SEASON = 2025
SLOTS = ["QB", "RB", "RB", "WR", "WR", "TE", "FLEX"]


def _p(pid, pos, ppg, value):
    return {
        "id": pid, "name": pid, "position": pos, "team": "X",
        "projected": ppg, "value": value, "trend": "steady",
    }


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


# --- pure ranking -----------------------------------------------------------

# Me: stacked at WR (three startable + a bench WR), thin at RB.
_MY = [
    _p("qb1", "QB", 18, 50),
    _p("rb1", "RB", 6, 12),
    _p("rb2", "RB", 5, 10),
    _p("wr1", "WR", 17, 60),
    _p("wr2", "WR", 16, 56),
    _p("wr3", "WR", 15, 52),
    _p("wr4", "WR", 15, 44),   # benched WR — expendable
    _p("te1", "TE", 8, 22),
]
# Rival: stacked at RB, thin at WR — the mirror image, so a swap helps both.
_THEIR = [
    _p("oqb", "QB", 16, 45),
    _p("rb_stud", "RB", 16, 58),
    _p("rb_b", "RB", 13, 45),
    _p("rb_c", "RB", 12, 40),
    _p("wr_a", "WR", 7, 16),
    _p("wr_b", "WR", 6, 14),
    _p("ote", "TE", 7, 20),
]
_PARTNER = {"team_id": "t2", "owner_name": "Rival", "record": "3-0"}


def _fair(c):
    bigger = max(c["give_value"], c["receive_value"], 1.0)
    return c["value_gap"] <= FAIRNESS_PCT * bigger + 1e-6


def _winwin(c):
    return (
        c["give"] and c["receive"]
        and c["your_lineup_gain"] > 0
        and c["their_lineup_gain"] >= 0
    )


def test_finder_surfaces_fair_winwin_upgrades():
    cands = rank_trades(_MY, _THEIR, SLOTS, _PARTNER)
    assert cands, "expected at least one win-win RB-for-WR swap"

    for c in cands:
        assert _fair(c)      # roughly equal value (summed across the package)
        assert _winwin(c)    # my lineup up, partner's not down

    # ranked best-first by the composite (upgrade, weighted for mutual benefit)
    scores = [
        c["your_lineup_gain"] + 0.25 * min(c["your_lineup_gain"], c["their_lineup_gain"])
        for c in cands
    ]
    assert scores == sorted(scores, reverse=True)
    # it targets my actual need (RB) with a player I can spare
    assert cands[0]["receive"][0]["position"] == "RB"


def test_finder_surfaces_two_for_one_consolidation():
    # Deep at WR (two benched), thin at RB2 — package two bench WRs for a stud.
    mine = [
        _p("qb1", "QB", 18, 50),
        _p("rb1", "RB", 14, 40),
        _p("rb2", "RB", 5, 10),    # weak starter → the need
        _p("wr1", "WR", 16, 55),
        _p("wr2", "WR", 15, 50),
        _p("wr3", "WR", 13, 40),
        _p("wr4", "WR", 12, 35),   # bench
        _p("wr5", "WR", 11, 33),   # bench
        _p("te1", "TE", 9, 25),
    ]
    theirs = [
        _p("oqb", "QB", 15, 45),
        _p("rb_stud", "RB", 18, 68),   # ≈ wr4+wr5 (35+33)
        _p("rb_x", "RB", 12, 35),
        _p("owr1", "WR", 6, 14),
        _p("owr2", "WR", 5, 12),
        _p("ote", "TE", 7, 20),
    ]
    cands = rank_trades(mine, theirs, SLOTS, _PARTNER)
    assert all(_fair(c) and _winwin(c) for c in cands)
    two_for_one = [c for c in cands if len(c["give"]) == 2 and len(c["receive"]) == 1]
    assert two_for_one, "expected a 2-for-1 consolidation"
    assert two_for_one[0]["receive"][0]["id"] == "rb_stud"


def test_finder_surfaces_one_for_two_depth():
    # I have a tradeable elite WR and holes at RB2 + TE; partner is deep at
    # RB/TE (bench surplus) and weak at WR — split the stud into two starters.
    mine = [
        _p("qb1", "QB", 18, 50),
        _p("rb1", "RB", 14, 40),
        _p("wr1", "WR", 20, 70),   # elite, tradeable
        _p("wr2", "WR", 15, 48),
        _p("wr3", "WR", 13, 40),
    ]
    theirs = [
        _p("oqb", "QB", 15, 45),
        _p("orb1", "RB", 16, 55),
        _p("orb2", "RB", 14, 48),
        _p("orb3", "RB", 13, 38),   # bench RB (givable) ≈ half of wr1
        _p("ote1", "TE", 11, 34),
        _p("ote2", "TE", 10, 32),   # bench TE (givable)
        _p("owr1", "WR", 6, 14),    # weak WR → wr1 upgrades them
        _p("owr2", "WR", 5, 12),
    ]
    cands = rank_trades(mine, theirs, SLOTS, _PARTNER)
    assert all(_fair(c) and _winwin(c) for c in cands)
    one_for_two = [c for c in cands if len(c["give"]) == 1 and len(c["receive"]) == 2]
    assert one_for_two, "expected a 1-for-2 depth deal"
    assert one_for_two[0]["give"][0]["id"] == "wr1"


def test_finder_position_filters():
    # target=RB → every candidate must bring back an RB.
    for c in rank_trades(_MY, _THEIR, SLOTS, _PARTNER, target="RB"):
        assert any(p["position"] == "RB" for p in c["receive"])
    # shed=WR → every candidate must give a WR away.
    for c in rank_trades(_MY, _THEIR, SLOTS, _PARTNER, shed="WR"):
        assert any(p["position"] == "WR" for p in c["give"])
    # Target a position only a QB-for-QB swap could bring back → nothing in
    # the shapes that can't carry one (2-for-2 can bundle a QB swap with an
    # RB, which is a legitimate package).
    for shape in ("1-1", "2-1", "1-2"):
        assert rank_trades(_MY, _THEIR, SLOTS, _PARTNER, target="QB", shape=shape) == []


def test_finder_skips_lopsided_and_non_upgrades():
    # A roster of only low-value scrubs: nothing is both fair AND an upgrade.
    scrubs = [
        _p("s_qb", "QB", 8, 15),
        _p("s_rb", "RB", 4, 6),
        _p("s_wr", "WR", 3, 5),
        _p("s_te", "TE", 2, 4),
    ]
    partner = {"team_id": "t3", "owner_name": "Tank", "record": "0-3"}
    assert rank_trades(_MY, scrubs, SLOTS, partner) == []


def test_finder_never_downgrades_the_user():
    # Reverse the matchup: I'm the RB-rich side. Every proposal must still help
    # the caller and be a fair win-win.
    cands = rank_trades(_THEIR, _MY, SLOTS, {"team_id": "t1", "owner_name": "Me", "record": "1-2"})
    for c in cands:
        assert _winwin(c) and _fair(c)


# --- league scan wiring -----------------------------------------------------


async def _seed_player(db, pid, pos, ppg):
    db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="X"))
    for wk in range(1, 5):
        db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))


async def test_find_trades_scans_league_and_excludes_self(db: AsyncSession):
    for pid, pos, ppg in [
        ("my_qb", "QB", 18), ("my_rb", "RB", 6), ("my_wr1", "WR", 17),
        ("my_wr2", "WR", 16), ("my_wrb", "WR", 14),
        ("riv_rb", "RB", 15), ("riv_wr", "WR", 7), ("riv_te", "TE", 8),
    ]:
        await _seed_player(db, pid, pos, ppg)
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        season=SEASON, scoring_type="ppr", team_id="t1",
        roster_positions=["QB", "RB", "RB", "WR", "WR", "TE", "FLEX", "BN", "BN"],
    )
    db.add(conn)
    db.add(Roster(connection_id=conn.id, team_id="t1", owner_name="Me",
                  players=["my_qb", "my_rb", "my_wr1", "my_wr2", "my_wrb"]))
    db.add(Roster(connection_id=conn.id, team_id="t2", owner_name="Rival",
                  players=["riv_rb", "riv_wr", "riv_te"]))
    await db.commit()

    trades = await find_trades(db, conn)
    assert isinstance(trades, list)
    for t in trades:
        assert t["partner"]["team_id"] != "t1"          # never trade with myself
        assert t["give"] and t["receive"]               # non-empty package sides
        assert t["your_lineup_gain"] > 0                # only real upgrades
        assert t["their_lineup_gain"] >= 0              # win-win


# --- shapes, playoffs horizon, de-duplication -------------------------------


def test_shape_limits_deal_shape_and_2_for_2_is_searched():
    for shape, sizes in (("1-1", (1, 1)), ("2-1", (2, 1)), ("2-2", (2, 2))):
        for c in rank_trades(_MY, _THEIR, SLOTS, _PARTNER, shape=shape):
            assert (len(c["give"]), len(c["receive"])) == sizes
    every = rank_trades(_MY, _THEIR, SLOTS, _PARTNER)
    assert any(len(c["give"]) == 2 and len(c["receive"]) == 2 for c in every)


def test_tiny_gains_are_not_listed():
    from app.services.trade_finder_service import MIN_GAIN

    for c in rank_trades(_MY, _THEIR, SLOTS, _PARTNER):
        assert c["your_lineup_gain"] >= MIN_GAIN


def test_throw_in_variants_collapse_to_one():
    from app.services.trade_finder_service import _distinct

    def deal(give, recv, gain):
        return {
            "partner": {"team_id": "t2"},
            "give": [{"id": g, "ppg": 1} for g in give],
            "receive": [{"id": r, "ppg": p} for r, p in recv],
            "your_lineup_gain": gain,
        }

    ranked = [
        deal(["a", "b"], [("star", 20), ("filler1", 2)], 7.0),
        deal(["a", "b"], [("star", 20), ("filler2", 2)], 7.0),  # same deal, other throw-in
        deal(["a", "c"], [("star", 20)], 6.0),
        deal(["a", "d"], [("star", 20)], 5.0),  # third version for the same star
        deal(["a"], [("other", 15)], 4.0),
    ]
    out = _distinct(ranked)
    assert [len(c["give"]) for c in out] == [2, 2, 1]
    assert [c["receive"][0]["id"] for c in out] == ["star", "star", "other"]


async def test_playoffs_horizon_scores_lineups_with_playoff_projections(db, monkeypatch):
    from app.services import trade_finder_service

    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=uuid.uuid4(), platform="sleeper", league_id="L",
        league_name="L", season=SEASON, scoring_type="ppr", team_id="1",
        roster_positions=["QB", "RB", "WR", "BN", "BN"],
    )
    db.add_all(
        [
            conn,
            Player(id="my_rb", full_name="My RB", position="RB", team="A"),
            Player(id="my_rb2", full_name="My RB2", position="RB", team="A"),
            Player(id="my_wr", full_name="My WR", position="WR", team="A"),
            Player(id="my_qb", full_name="My QB", position="QB", team="A"),
            Player(id="th_wr", full_name="Their WR", position="WR", team="B"),
            Player(id="th_wr2", full_name="Their WR2", position="WR", team="B"),
            Player(id="th_rb", full_name="Their RB", position="RB", team="B"),
            Player(id="th_qb", full_name="Their QB", position="QB", team="B"),
            Roster(connection_id=conn.id, team_id="1", players=["my_qb", "my_rb", "my_rb2", "my_wr"]),
            Roster(connection_id=conn.id, team_id="2", players=["th_qb", "th_rb", "th_wr", "th_wr2"]),
        ]
    )
    await db.commit()

    values = {pid: {"value": 20.0, "ppg": 10.0, "trend": None}
              for pid in ("my_rb", "my_rb2", "my_wr", "my_qb", "th_wr", "th_wr2", "th_rb", "th_qb")}

    async def fake_values(db, scoring):
        return values

    # Season ppg says everyone is equal (no trade helps); the playoff
    # projections say I have a spare RB and need a WR while they need an RB,
    # so my RB2 for one of their WRs helps both sides.
    playoff = {"my_qb": 18, "my_rb": 16, "my_rb2": 14, "my_wr": 9,
               "th_qb": 18, "th_rb": 8, "th_wr": 17, "th_wr2": 15}

    async def fake_playoff(db, conn):
        return playoff

    monkeypatch.setattr(trade_finder_service, "compute_player_values", fake_values)
    monkeypatch.setattr(trade_finder_service, "_playoff_projections", fake_playoff)

    assert await find_trades(db, conn, horizon="week") == []
    deals = await find_trades(db, conn, horizon="playoffs")
    assert deals
    top = deals[0]
    assert [p["id"] for p in top["give"]] == ["my_rb2"]
    assert [p["position"] for p in top["receive"]] == ["WR"]
    assert "fantasy playoffs" in top["rationale"]

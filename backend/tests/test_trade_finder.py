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


def test_finder_surfaces_fair_winwin_upgrades():
    cands = rank_trades(_MY, _THEIR, SLOTS, _PARTNER)
    assert cands, "expected at least one win-win RB-for-WR swap"

    for c in cands:
        bigger = max(c["give"]["value"], c["receive"]["value"], 1.0)
        # roughly equal value
        assert c["value_gap"] <= FAIRNESS_PCT * bigger + 1e-6
        # genuine win-win: my lineup up, partner's not down
        assert c["your_lineup_gain"] > 0
        assert c["their_lineup_gain"] >= 0

    # ranked best-first by the composite score (upgrade, weighted for mutual
    # benefit) the finder uses
    scores = [
        c["your_lineup_gain"] + 0.25 * min(c["your_lineup_gain"], c["their_lineup_gain"])
        for c in cands
    ]
    assert scores == sorted(scores, reverse=True)
    assert cands[0]["your_lineup_gain"] >= 8  # top is a real upgrade
    # it targets my actual need (RB) with a player I can spare
    assert any(c["receive"]["position"] == "RB" for c in cands)
    assert cands[0]["receive"]["position"] == "RB"


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
    # Reverse the matchup: I'm the RB-rich side. Giving my RB depth for their
    # weak WRs must never be proposed as an upgrade to ME.
    cands = rank_trades(_THEIR, _MY, SLOTS, {"team_id": "t1", "owner_name": "Me", "record": "1-2"})
    for c in cands:
        assert c["your_lineup_gain"] > 0  # every proposal still helps the caller


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
        assert t["your_lineup_gain"] > 0                # only real upgrades
        assert t["their_lineup_gain"] >= 0              # win-win

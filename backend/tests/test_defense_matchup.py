"""Opponent defensive-injury adjustment.

Pure tests hit defense_impact_service directly; integration tests run
compute_projections against an in-memory DB with a seeded schedule + depth
chart. Sleeper's external projection is stubbed out so tests stay offline.
"""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import DepthChartEntry, NflSchedule, Player, PlayerStatsWeekly
from app.services import projection_service
from app.services.defense_impact_service import (
    BASE_BUMP_PCT,
    caliber_multiplier,
    defender_role,
    defense_injury_pct,
)
from app.services.projection_service import DEF_INJ_ABS_CAP, compute_projections

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


# --- pure: role classification & caliber ------------------------------------


def test_defender_role_uses_position_and_alignment():
    assert defender_role("CB", "NB") == "slot_cb"
    assert defender_role("CB", "LCB") == "perimeter_cb"
    assert defender_role("DB", "RCB") == "perimeter_cb"
    assert defender_role("DE", "LOLB") == "edge"
    assert defender_role("DT", None) == "interior"
    assert defender_role("LB", "MLB") == "offball_lb"
    assert defender_role("S", "FS") == "safety"
    assert defender_role("G", None) is None


def test_caliber_multiplier_tiers():
    assert caliber_multiplier("Micah Parsons") == 3.0     # wrecker
    assert caliber_multiplier("MONTEZ SWEAT") == 2.0      # star
    assert caliber_multiplier("Random Backup") == 1.0     # plain starter
    assert caliber_multiplier(None) == 1.0


# --- pure: bump computation -------------------------------------------------


def test_edge_out_lifts_qb_scaled_by_caliber():
    star = [{"name": "Montez Sweat", "position": "DE", "slot": "ROLB", "status": "Out"}]
    wrecker = [{"name": "Myles Garrett", "position": "DE", "slot": "LOLB", "status": "Out"}]
    pct_star, _ = defense_injury_pct("QB", None, star)
    pct_wreck, reasons = defense_injury_pct("QB", None, wrecker)
    assert pct_star > 0
    assert pct_wreck > pct_star          # game-wrecker moves it more
    assert "Myles Garrett" in reasons[0]
    # edge-out barely touches the RB (secondary/none) vs the QB
    assert defense_injury_pct("RB", None, wrecker)[0] < pct_wreck


def test_perimeter_corner_out_favors_boundary_wr_over_slot():
    outs = [{"name": "Christian Gonzalez", "position": "CB", "slot": "LCB", "status": "Out"}]
    perimeter, _ = defense_injury_pct("WR", "LWR", outs)
    slot, _ = defense_injury_pct("WR", "SWR", outs)
    assert perimeter > slot >= 0


def test_slot_corner_out_favors_slot_wr():
    outs = [{"name": "Some Nickel", "position": "CB", "slot": "NB", "status": "Out"}]
    slot, _ = defense_injury_pct("WR", "SWR", outs)
    perimeter, _ = defense_injury_pct("WR", "LWR", outs)
    assert slot > perimeter


def test_no_defenders_or_wrong_position_is_zero():
    assert defense_injury_pct("QB", None, []) == (0.0, [])
    outs = [{"name": "Micah Parsons", "position": "LB", "slot": "LOLB", "status": "Out"}]
    assert defense_injury_pct("K", None, outs) == (0.0, [])


def test_interior_run_stuffer_lifts_rb():
    outs = [{"name": "Quinnen Williams", "position": "DT", "slot": "DT", "status": "Out"}]
    rb, _ = defense_injury_pct("RB", None, outs)
    assert rb == pytest.approx(BASE_BUMP_PCT * 3.0 * 1.0)  # wrecker, primary weight 1.0


# --- integration through compute_projections --------------------------------


async def _seed_offense(db: AsyncSession, wr_align: dict[str, str]):
    """BUF offense (QB/RB/TE + WRs) facing MIA, four scoring weeks each. wr_align
    maps a WR id to its depth_chart_position (SWR/LWR)."""
    roster = [("buf_qb", "QB", 20.0), ("buf_rb", "RB", 14.0), ("buf_te", "TE", 9.0)]
    roster += [(wid, "WR", 12.0) for wid in wr_align]
    for pid, pos, ppg in roster:
        db.add(Player(id=pid, full_name=pid.upper(), position=pos, team="BUF"))
        for wk in range(1, 5):
            db.add(PlayerStatsWeekly(player_id=pid, season=SEASON, week=wk, fantasy_points_ppr=ppg))
    for wid, align in wr_align.items():
        db.add(DepthChartEntry(id=wid, team="BUF", position="WR", depth_chart_position=align, depth_chart_order=1))
    db.add(NflSchedule(season=SEASON, week=1, home_team="BUF", away_team="MIA"))
    await db.commit()


async def _add_defender(db, pid, name, pos, slot, order, status):
    db.add(DepthChartEntry(id=pid, full_name=name, team="MIA", position=pos,
                           depth_chart_position=slot, depth_chart_order=order, injury_status=status))
    await db.commit()


def _def_adj(proj, pid):
    return proj[pid]["components"]["defense_injury_adj"]


async def test_healthy_opponent_defense_gives_zero_adjustment(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR"})
    # MIA has a healthy starting edge — present but not injured.
    await _add_defender(db, "mia_edge", "Healthy Edge", "DE", "LOLB", 1, None)
    proj = await compute_projections(db, ["buf_qb", "buf_rb", "buf_wr1"], SEASON)
    for pid in proj:
        assert _def_adj(proj, pid) == 0.0
        assert proj[pid]["defense_reason"] is None


async def test_out_edge_lifts_opposing_qb(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR"})
    await _add_defender(db, "mia_edge", "Myles Garrett", "DE", "LOLB", 1, "Out")
    proj = await compute_projections(db, ["buf_qb", "buf_rb", "buf_wr1"], SEASON)
    assert _def_adj(proj, "buf_qb") > 0
    assert "Myles Garrett" in proj["buf_qb"]["defense_reason"]
    # QB (primary victim of a pass-rush loss) gains more than the RB.
    assert _def_adj(proj, "buf_qb") > _def_adj(proj, "buf_rb")


async def test_out_perimeter_corner_favors_boundary_receiver(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR", "buf_slot": "SWR"})
    await _add_defender(db, "mia_cb", "Christian Gonzalez", "CB", "LCB", 1, "Out")
    proj = await compute_projections(db, ["buf_wr1", "buf_slot"], SEASON)
    assert _def_adj(proj, "buf_wr1") > _def_adj(proj, "buf_slot")


async def test_questionable_defender_gives_no_adjustment(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR"})
    await _add_defender(db, "mia_edge", "Myles Garrett", "DE", "LOLB", 1, "Questionable")
    proj = await compute_projections(db, ["buf_qb"], SEASON)
    assert _def_adj(proj, "buf_qb") == 0.0


async def test_backup_defender_out_gives_no_adjustment(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR"})
    # depth_chart_order 2 → not a starter → ignored.
    await _add_defender(db, "mia_edge2", "Backup Edge", "DE", "ROLB", 2, "Out")
    proj = await compute_projections(db, ["buf_qb"], SEASON)
    assert _def_adj(proj, "buf_qb") == 0.0


async def test_defense_adjustment_is_capped(db: AsyncSession):
    await _seed_offense(db, {"buf_wr1": "LWR"})
    # Pile on several out wreckers; the total is still capped.
    await _add_defender(db, "d1", "Myles Garrett", "DE", "LOLB", 1, "Out")
    await _add_defender(db, "d2", "Micah Parsons", "LB", "ROLB", 1, "Out")
    await _add_defender(db, "d3", "Nick Bosa", "DE", "RDE", 1, "Out")
    proj = await compute_projections(db, ["buf_qb"], SEASON)
    assert 0 < _def_adj(proj, "buf_qb") <= DEF_INJ_ABS_CAP

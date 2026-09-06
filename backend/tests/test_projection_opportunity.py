"""Teammate-injury opportunity boost + kickoff-weighted Sleeper blend.

The opportunity tests run through the real ``compute_projections`` against an
in-memory DB so they exercise the DB-loading path, the redistribution model, and
the point conversion / cap together. The blend-weight tests hit the pure
function directly.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import Player, PlayerStatsWeekly
from app.services.opportunity_service import compute_opportunity_shares
from app.services.projection_service import (
    EXTERNAL_WEIGHT,
    EXTERNAL_WEIGHT_LATE,
    OPP_BOOST_ABS_CAP,
    compute_projections,
    sleeper_blend_weight,
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


async def _add_catcher(
    db: AsyncSession,
    pid: str,
    position: str,
    team: str,
    target_share: float,
    depth: int,
    ppg: float,
    injury_status: str | None = None,
) -> None:
    """A pass-catcher plus four scoring weeks (enough for the ≥3-sample gate),
    each carrying the same target share so the recent-season average is stable.
    """
    db.add(
        Player(
            id=pid,
            full_name=pid.upper(),
            position=position,
            team=team,
            depth_chart_order=depth,
            injury_status=injury_status,
        )
    )
    for week in range(1, 5):
        db.add(
            PlayerStatsWeekly(
                player_id=pid,
                season=SEASON,
                week=week,
                target_share=target_share,
                fantasy_points_ppr=ppg,
            )
        )


async def _seed_team(db: AsyncSession, wr1_status: str | None) -> None:
    """One team: WR1 (target hog), WR2, TE. WR1's status is the variable."""
    await _add_catcher(db, "wr1", "WR", "NYG", target_share=0.28, depth=1, ppg=16.0, injury_status=wr1_status)
    await _add_catcher(db, "wr2", "WR", "NYG", target_share=0.18, depth=2, ppg=12.0)
    await _add_catcher(db, "te1", "TE", "NYG", target_share=0.12, depth=1, ppg=8.0)
    await db.commit()


async def _project(db: AsyncSession) -> dict[str, dict]:
    return await compute_projections(db, ["wr1", "wr2", "te1"], SEASON)


def _opp(proj: dict, pid: str) -> float:
    return proj[pid]["components"]["opportunity_adj"]


# --- Feature 1: opportunity boost ------------------------------------------


async def test_healthy_slate_gets_zero_boost(db: AsyncSession):
    """The critical no-regression check: with nobody out, every opportunity_adj
    is exactly 0.0 and no boost_reason is set, so projections are unchanged."""
    await _seed_team(db, wr1_status=None)
    proj = await _project(db)
    assert set(proj) == {"wr1", "wr2", "te1"}
    for pid in proj:
        assert _opp(proj, pid) == 0.0
        assert proj[pid]["boost_reason"] is None


async def test_out_wr1_boosts_teammates_behind_him(db: AsyncSession):
    await _seed_team(db, wr1_status="Out")
    proj = await _project(db)

    # WR2 and TE behind the out WR1 both gain; WR2 (more share + better slot)
    # absorbs more than the TE.
    assert _opp(proj, "wr2") > 0
    assert _opp(proj, "te1") > 0
    assert _opp(proj, "wr2") > _opp(proj, "te1")

    # The injured player himself is untouched by his own absence.
    assert _opp(proj, "wr1") == 0.0
    assert proj["wr1"]["boost_reason"] is None

    # The reason names the absent teammate and his status.
    assert "WR1" in proj["wr2"]["boost_reason"]
    assert "Out" in proj["wr2"]["boost_reason"]

    # Boost is genuinely additive on top of the baseline projection.
    assert proj["wr2"]["projected"] > proj["wr2"]["components"]["base_ppg"]


async def test_questionable_teammate_gives_no_boost(db: AsyncSession):
    """Official-only rule: Questionable is not a confirmed sit, so no targets
    are treated as vacated."""
    await _seed_team(db, wr1_status="Questionable")
    proj = await _project(db)
    for pid in proj:
        assert _opp(proj, pid) == 0.0


async def test_doubtful_and_ir_also_vacate(db: AsyncSession):
    # Two independent teams, one with a Doubtful WR1 and one with an IR WR1;
    # both should lift the WR2 behind them.
    await _add_catcher(db, "sf_wr1", "WR", "SF", 0.28, 1, 16.0, injury_status="Doubtful")
    await _add_catcher(db, "sf_wr2", "WR", "SF", 0.18, 2, 12.0)
    await _add_catcher(db, "kc_wr1", "WR", "KC", 0.28, 1, 16.0, injury_status="Injured Reserve")
    await _add_catcher(db, "kc_wr2", "WR", "KC", 0.18, 2, 12.0)
    await db.commit()
    proj = await compute_projections(db, ["sf_wr2", "kc_wr2"], SEASON)
    assert _opp(proj, "sf_wr2") > 0
    assert _opp(proj, "kc_wr2") > 0


async def test_boost_is_bounded_by_cap(db: AsyncSession):
    """Even an absurd vacated share can't exceed the absolute cap or 35% of the
    receiver's own baseline."""
    await _add_catcher(db, "wr1", "WR", "DAL", target_share=0.90, depth=1, ppg=20.0, injury_status="Out")
    await _add_catcher(db, "wr2", "WR", "DAL", target_share=0.10, depth=2, ppg=10.0)
    await db.commit()
    proj = await compute_projections(db, ["wr1", "wr2"], SEASON)
    boost = _opp(proj, "wr2")
    assert 0 < boost <= OPP_BOOST_ABS_CAP
    assert boost <= 0.35 * proj["wr2"]["components"]["base_ppg"] + 0.05  # +rounding slack


# --- pure opportunity model -------------------------------------------------


def test_compute_opportunity_shares_empty_when_all_healthy():
    catchers = [
        {"id": "a", "name": "A", "position": "WR", "target_share": 0.25, "depth_chart_order": 1, "injury_status": None},
        {"id": "b", "name": "B", "position": "WR", "target_share": 0.15, "depth_chart_order": 2, "injury_status": "Questionable"},
    ]
    assert compute_opportunity_shares(catchers) == {}


def test_compute_opportunity_shares_conserves_vacated_share():
    catchers = [
        {"id": "out", "name": "Out Guy", "position": "WR", "target_share": 0.30, "depth_chart_order": 1, "injury_status": "Out"},
        {"id": "b", "name": "B", "position": "WR", "target_share": 0.18, "depth_chart_order": 2, "injury_status": None},
        {"id": "c", "name": "C", "position": "TE", "target_share": 0.10, "depth_chart_order": 1, "injury_status": None},
    ]
    shares = compute_opportunity_shares(catchers)
    assert "out" not in shares
    # All 0.30 of vacated share is redistributed among the healthy two.
    assert sum(v["extra_share"] for v in shares.values()) == pytest.approx(0.30)
    assert shares["b"]["extra_share"] > shares["c"]["extra_share"]


def test_low_share_rb_neither_vacates_nor_absorbs():
    catchers = [
        {"id": "wr", "name": "WR", "position": "WR", "target_share": 0.25, "depth_chart_order": 1, "injury_status": "Out"},
        {"id": "rb", "name": "RB", "position": "RB", "target_share": 0.02, "depth_chart_order": 1, "injury_status": None},
    ]
    # Only a non-receiving RB is left to absorb → nobody qualifies.
    assert compute_opportunity_shares(catchers) == {}


# --- Feature 3: kickoff-weighted Sleeper blend ------------------------------


def test_blend_weight_bounds_and_ramp_toward_kickoff():
    now = datetime(2026, 9, 6, 8, 0)
    far = sleeper_blend_weight(now, now + timedelta(hours=100))
    mid = sleeper_blend_weight(now, now + timedelta(hours=36))
    near = sleeper_blend_weight(now, now + timedelta(hours=1))
    at_kick = sleeper_blend_weight(now, now)

    assert far == EXTERNAL_WEIGHT              # 3+ days out: unchanged from baseline
    assert at_kick == EXTERNAL_WEIGHT_LATE     # kickoff: full lean on Sleeper
    assert far < mid < near <= at_kick         # monotonic ramp
    for w in (far, mid, near, at_kick):
        assert EXTERNAL_WEIGHT <= w <= EXTERNAL_WEIGHT_LATE


def test_blend_weight_day_of_week_fallback():
    # No kickoff time known → fall back to day-of-week schedule.
    tuesday = datetime(2026, 9, 8, 10, 0)   # Tue
    sunday = datetime(2026, 9, 13, 10, 0)   # Sun
    assert sleeper_blend_weight(tuesday, None) == EXTERNAL_WEIGHT
    assert sleeper_blend_weight(sunday, None) == EXTERNAL_WEIGHT_LATE

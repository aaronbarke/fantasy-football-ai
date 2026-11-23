"""All-teams schedule rankings per position, and K/DEF ranks in the heatmap."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import NflSchedule, Player, PlayerStatsWeekly
from app.services import projection_service, schedule_service
from app.services.schedule_service import build_schedule_strength, build_team_schedule_rankings

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


async def _seed(db: AsyncSession, monkeypatch):
    # Week 1 history: SOFT's defense gave up 30 PPR to RBs, HARD's only 5.
    db.add_all(
        [
            Player(id="rb1", full_name="Back One", position="RB", team="AAA"),
            Player(id="rb2", full_name="Back Two", position="RB", team="BBB"),
            Player(id="dst", full_name="AAA D/ST", position="DEF", team="AAA"),
            PlayerStatsWeekly(player_id="rb1", season=SEASON, week=1, opponent="SOFT",
                              fantasy_points_ppr=30.0),
            PlayerStatsWeekly(player_id="rb2", season=SEASON, week=1, opponent="HARD",
                              fantasy_points_ppr=5.0),
            # Week 15: AAA plays SOFT, BBB plays HARD.
            NflSchedule(season=SEASON, week=15, home_team="AAA", away_team="SOFT"),
            NflSchedule(season=SEASON, week=15, home_team="BBB", away_team="HARD"),
        ]
    )
    await db.commit()

    async def results(seasons):
        # SOFT's offense scores 10/gm, HARD's 35/gm → facing SOFT is the easy DST draw.
        rows = []
        for team, pf, opp in (("SOFT", 10, "X"), ("HARD", 35, "Y")):
            rows.append({"season": SEASON, "week": 1, "team": team, "opponent": opp,
                         "points_for": pf, "points_against": 40 if team == "SOFT" else 10})
        return rows

    async def no_sync(db, season):
        return None

    monkeypatch.setattr(projection_service, "get_team_results", results)
    monkeypatch.setattr(schedule_service, "ensure_schedule", no_sync)


async def test_teams_are_ranked_by_how_soft_their_schedule_is(db, monkeypatch):
    await _seed(db, monkeypatch)
    r = await build_team_schedule_rankings(db, SEASON, 15, weeks_ahead=3)

    assert r["weeks"] == [15, 16, 17]
    rb = r["positions"]["RB"]
    top = rb[0]
    assert top["team"] == "AAA"
    assert top["rank"] == 1 and top["avg_value"] == 30.0 and top["games"] == 1
    assert top["cells"][0]["opponent"] == "SOFT" and top["cells"][1]["opponent"] is None
    bbb = next(e for e in rb if e["team"] == "BBB")
    assert bbb["avg_value"] == 5.0 and bbb["rank"] > top["rank"]

    # DEF: facing SOFT's weak offense beats facing HARD's.
    dst = {e["team"]: e for e in r["positions"]["DEF"]}
    assert dst["AAA"]["rank"] < dst["BBB"]["rank"]
    # K: SOFT's defense allows 40/gm, so AAA's kicker has the better draw.
    k = {e["team"]: e for e in r["positions"]["K"]}
    assert k["AAA"]["rank"] < k["BBB"]["rank"]


async def test_heatmap_rates_team_defenses(db, monkeypatch):
    await _seed(db, monkeypatch)
    r = await build_schedule_strength(db, SEASON, 15, ["dst"], weeks_ahead=1)
    cell = r["players"][0]["cells"][0]
    assert cell["opponent"] == "SOFT" and cell["rank"] == 1


async def test_rams_stats_coded_la_still_rank_as_lar(db):
    """nflverse calls the Rams "LA"; the schedule calls them "LAR"."""
    from app.services.schedule_service import defense_vs_position_ranks

    db.add_all(
        [
            Player(id="rb1", full_name="Back One", position="RB", team="AAA"),
            PlayerStatsWeekly(player_id="rb1", season=SEASON, week=1, opponent="LA",
                              fantasy_points_ppr=20.0),
            PlayerStatsWeekly(player_id="rb1", season=SEASON, week=2, opponent="LAR",
                              fantasy_points_ppr=10.0),
        ]
    )
    await db.commit()
    ranks = await defense_vs_position_ranks(db, SEASON)
    assert ranks[("LAR", "RB")]["pts_allowed_avg"] == 15.0
    assert ("LA", "RB") not in ranks

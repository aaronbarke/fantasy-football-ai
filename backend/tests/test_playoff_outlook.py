"""Player outlook over the fantasy playoffs: talent crossed with schedule."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import NflSchedule, Player, PlayerStatsWeekly
from app.services import playoff_outlook_service, projection_service
from app.services.playoff_outlook_service import build_player_outlook

SEASON = 2026


@pytest.fixture
async def db(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async def no_sync(db, season):
        return None

    async def no_results(seasons):
        return []

    monkeypatch.setattr(playoff_outlook_service, "ensure_schedule", no_sync)
    monkeypatch.setattr(projection_service, "get_team_results", no_results)
    async with Session() as session:
        yield session
    await engine.dispose()


def _games(pid: str, opp: str, pts: float, weeks=range(1, 5)):
    return [
        PlayerStatsWeekly(player_id=pid, season=SEASON, week=w, opponent=opp, fantasy_points_ppr=pts)
        for w in weeks
    ]


async def test_soft_schedule_lifts_a_lesser_player_past_a_better_one(db):
    db.add_all(
        [
            # STAR scores 20/gm, GOOD 18/gm.
            Player(id="star", full_name="Star Back", position="RB", team="AAA"),
            Player(id="good", full_name="Good Back", position="RB", team="BBB"),
            # Defense history: STINGY allows 8 to RBs, SIEVE 40, MID 20.
            Player(id="x1", full_name="Filler One", position="RB", team="ZZZ"),
            *_games("star", "MID", 20.0),
            *_games("good", "MID", 18.0),
            *_games("x1", "STINGY", 8.0, weeks=range(5, 9)),
            *_games("x1", "SIEVE", 40.0, weeks=range(9, 13)),
            # Playoffs: STAR faces STINGY every week, GOOD faces SIEVE.
            *[NflSchedule(season=SEASON, week=w, home_team="AAA", away_team="STINGY") for w in (15, 16, 17)],
            *[NflSchedule(season=SEASON, week=w, home_team="BBB", away_team="SIEVE") for w in (15, 16, 17)],
        ]
    )
    await db.commit()

    r = await build_player_outlook(db, SEASON, 15, weeks_ahead=3)
    rbs = {e["id"]: e for e in r["positions"]["RB"]}
    star, good = rbs["star"], rbs["good"]

    assert star["base_rank"] < good["base_rank"]  # better player on talent alone
    assert good["rank"] < star["rank"]  # but the schedule flips them
    assert good["proj_ppg"] > good["base_ppg"] and star["proj_ppg"] < star["base_ppg"]
    assert star["games"] == 3 and len(star["cells"]) == 3
    assert star["proj_total"] == pytest.approx(sum(c["proj"] for c in star["cells"]), abs=0.05)


async def test_long_term_injured_players_are_left_out(db):
    db.add_all(
        [
            Player(id="hurt", full_name="Hurt Back", position="RB", team="AAA", injury_status="IR"),
            Player(id="ok", full_name="Fine Back", position="RB", team="AAA", injury_status="Questionable"),
            *_games("hurt", "MID", 25.0),
            *_games("ok", "MID", 10.0),
            NflSchedule(season=SEASON, week=15, home_team="AAA", away_team="MID"),
        ]
    )
    await db.commit()
    r = await build_player_outlook(db, SEASON, 15, weeks_ahead=3)
    ids = [e["id"] for e in r["positions"]["RB"]]
    assert ids == ["ok"]


async def test_each_game_is_75_percent_player_25_percent_matchup(db):
    from app.services.playoff_outlook_service import MATCHUP_WEIGHT, PLAYER_WEIGHT

    db.add_all(
        [
            Player(id="p", full_name="Pat Back", position="RB", team="AAA"),
            Player(id="x1", full_name="Filler One", position="RB", team="ZZZ"),
            Player(id="x2", full_name="Filler Two", position="RB", team="YYY"),
            # League average allowed to RBs = 20; OPP allows 30 (1.5x).
            *_games("p", "MID", 20.0),
            *_games("x1", "OPP", 30.0, weeks=range(5, 9)),
            *_games("x2", "LOW", 10.0, weeks=range(5, 9)),
            NflSchedule(season=SEASON, week=15, home_team="AAA", away_team="OPP"),
        ]
    )
    await db.commit()
    r = await build_player_outlook(db, SEASON, 15, weeks_ahead=1)
    pat = next(e for e in r["positions"]["RB"] if e["id"] == "p")
    # Pat scored 20 every game, so the player half is 20 whatever the tier.
    expected = PLAYER_WEIGHT * 20.0 + MATCHUP_WEIGHT * 20.0 * 30.0 / 20.0
    assert pat["cells"][0]["proj"] == pytest.approx(expected, abs=0.05)


async def test_last_season_fades_out_once_this_season_has_enough_games(db):
    db.add_all(
        [
            Player(id="soph", full_name="Second Year", position="WR", team="AAA"),
            *[
                PlayerStatsWeekly(player_id="soph", season=SEASON - 1, week=w,
                                  opponent="MID", fantasy_points_ppr=5.0)
                for w in range(1, 18)
            ],
            *_games("soph", "MID", 18.0, weeks=range(1, 9)),
        ]
    )
    await db.commit()
    r = await build_player_outlook(db, SEASON, 15, weeks_ahead=1)
    soph = r["positions"]["WR"][0]
    assert soph["base_ppg"] == 18.0  # rookie-year 5s no longer drag him down

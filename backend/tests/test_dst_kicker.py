"""Team-defense and kicker models (opponent offense, defense quality, backup
QB, Vegas, weather; team scoring for kickers), the nflverse results feed, and
ESPN players missing from the ID crosswalk (the opponent's kicker that used to
vanish from the matchup)."""

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.models import (
    GameCondition,
    LeagueConnection,
    NflSchedule,
    Player,
    PlayerStatsWeekly,
    Roster,
)
from app.services import projection_service, sync_service
from app.services.espn_service import ESPNClient
from app.services.projection_service import (
    DST_BASELINE,
    LEAGUE_AVG_TEAM_TOTAL,
    QB_CHANGE_CAP,
    compute_projections,
    dst_model,
    kicker_model,
)
from app.services.sync_service import resolve_espn_ids
from app.services.team_stats_service import parse_games_csv

SEASON = 2026
AVG = LEAGUE_AVG_TEAM_TOTAL


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


def _term(r: dict, label: str) -> float:
    return next(v for k, v in r["terms"] if k == label)


# --- DST model ----------------------------------------------------------------


def test_dst_average_matchup_is_the_baseline():
    r = dst_model(None, None, None, None, 0.0, None, None)
    assert r["model"] == pytest.approx(DST_BASELINE)
    assert r["label"] == "unknown"
    assert all(v == 0 for _, v in r["terms"])


def test_dst_each_factor_moves_the_right_way():
    base = dst_model(AVG, AVG, 0.8, 0.8, 0.0, None, None)["model"]
    weak_offense = dst_model(AVG - 6, AVG, 0.8, 0.8, 0.0, None, None)["model"]
    stingy_defense = dst_model(AVG, AVG - 6, 0.8, 0.8, 0.0, None, None)["model"]
    ballhawks = dst_model(AVG, AVG, 0.8, 1.4, 0.0, None, None)["model"]
    careless_qb = dst_model(AVG, AVG, 1.4, 0.8, 0.0, None, None)["model"]
    backup_qb = dst_model(AVG, AVG, 0.8, 0.8, QB_CHANGE_CAP, None, None)
    low_line = dst_model(AVG, AVG, 0.8, 0.8, 0.0, AVG - 6, None)["model"]
    assert weak_offense > base and stingy_defense > base
    assert ballhawks > base and careless_qb > base and low_line > base
    # A good offense starting its backup QB makes this defense a better play.
    assert backup_qb["model"] > base and _term(backup_qb, "Backup QB") > 0


def test_dst_terms_add_up_to_the_model():
    r = dst_model(26.0, 19.0, 1.1, 0.9, 0.1, 20.5, None)
    assert DST_BASELINE + sum(v for _, v in r["terms"]) == pytest.approx(r["model"], abs=1e-6)


def test_dst_vegas_alone_sets_points_allowed_without_history():
    assert dst_model(None, None, None, None, 0.0, 16.0, None)["label"] == "great"
    assert dst_model(None, None, None, None, 0.0, 29.0, None)["label"] == "tough"


# --- kicker model -------------------------------------------------------------


def test_kicker_follows_expected_team_scoring_and_venue():
    avg = kicker_model(None, None, 0.0, None, False, None)["model"]
    assert avg == projection_service.K_BASELINE
    high = kicker_model(None, None, 0.0, AVG + 6, False, None)["model"]
    low = kicker_model(None, None, 0.0, AVG - 6, False, None)["model"]
    dome = kicker_model(None, None, 0.0, None, True, None)["model"]
    windy = kicker_model(None, None, 0.0, None, False,
                         GameCondition(wind_mph=22, precipitation_pct=0, dome=False))["model"]
    assert high > avg > low
    assert dome > avg > windy
    # His own QB out → fewer drives end in points.
    healthy = kicker_model(AVG, AVG, 0.0, None, False, None)["model"]
    backup = kicker_model(AVG, AVG, QB_CHANGE_CAP, None, False, None)["model"]
    assert backup < healthy


# --- through compute_projections ------------------------------------------------


async def test_defense_facing_a_backup_qb_with_team_history(db: AsyncSession, monkeypatch):
    kick = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(days=5)
    db.add(NflSchedule(season=SEASON, week=4, home_team="NYJ", away_team="CHI", game_time=kick))
    db.add(Player(id="NYJ", full_name="Jets", position="DEF", team="NYJ"))
    db.add(Player(id="nyj_k", full_name="Jets K", position="K", team="NYJ"))
    # Chicago's starter (8 starts) is out; the backup projects far lower.
    db.add(Player(id="starter", full_name="Starter", position="QB", team="CHI",
                  injury_status="Out", depth_chart_order=1))
    db.add(Player(id="backup", full_name="Backup", position="QB", team="CHI", depth_chart_order=2))
    for wk in range(1, 9):
        db.add(PlayerStatsWeekly(player_id="starter", season=SEASON - 1, week=wk,
                                 pass_yards=260, fantasy_points_ppr=22, opponent="GB"))
    await db.commit()

    async def results(seasons):
        # CHI has scored a lot; the Jets have allowed a lot.
        return [
            {"season": SEASON, "week": wk, "team": "CHI", "opponent": "GB",
             "points_for": 30, "points_against": 20}
            for wk in (1, 2, 3)
        ] + [
            {"season": SEASON, "week": wk, "team": "NYJ", "opponent": "MIA",
             "points_for": 17, "points_against": 28}
            for wk in (1, 2, 3)
        ]

    async def sleeper(season, week, scoring="ppr"):
        return {"NYJ": 6.0, "backup": 13.0}

    monkeypatch.setattr(projection_service, "get_team_results", results)
    monkeypatch.setattr(projection_service, "get_external_projections", sleeper)

    proj = await compute_projections(db, ["NYJ", "nyj_k"], SEASON)
    d = proj["NYJ"]
    terms = {t["label"]: t["value"] for t in d["components"]["terms"]}
    assert terms["Opponent offense"] < 0      # facing a high-scoring offense...
    assert terms["Defense quality"] < 0       # ...with a leaky defense...
    assert terms["Backup QB"] > 0             # ...but their starter is out
    assert "Starter (Out) out, Backup starting" in d["qb_reason"]
    # Sleeper's DEF number blends in at the early-week weight.
    c = d["components"]
    assert c["blend_weight"] == 0.5
    assert d["projected"] == pytest.approx(0.5 * 6.0 + 0.5 * c["model_proj"], abs=0.1)
    # The kicker gets a modeled number and a breakdown too.
    k = proj["nyj_k"]["components"]
    assert k["base_label"] == "League-average kicker" and k["model_proj"] is not None


# --- nflverse results -------------------------------------------------------------


def test_parse_games_csv_maps_teams_and_skips_unplayed():
    text = (
        "game_id,season,game_type,week,away_team,away_score,home_team,home_score\n"
        "a,2026,REG,1,LA,24,SF,27\n"
        "b,2026,REG,2,KC,,BUF,\n"       # not played yet
        "c,2026,POST,19,KC,31,BUF,28\n"  # playoffs
        "d,2024,REG,1,KC,20,BAL,27\n"    # season not requested
    )
    rows = parse_games_csv(text, {2025, 2026})
    assert len(rows) == 2
    rams = next(r for r in rows if r["team"] == "LAR")
    assert rams["opponent"] == "SF" and rams["points_for"] == 24 and rams["points_against"] == 27


# --- ESPN players missing from the crosswalk -------------------------------------


def _espn_player(name, pos_id, pro_team, last=None):
    return {"fullName": name, "lastName": last or name.split()[-1],
            "defaultPositionId": pos_id, "proTeamId": pro_team}


async def test_resolve_espn_ids_matches_by_name_and_saves_the_id(db: AsyncSession):
    db.add(Player(id="13545", full_name="Trey Smack", last_name="Smack", position="K", team="GB"))
    db.add(Player(id="m1", full_name="Mike Williams", last_name="Williams", position="WR", team="NYJ"))
    db.add(Player(id="m2", full_name="Mike Williams", last_name="Williams", position="WR", team="PIT"))
    await db.commit()

    espn_map = await resolve_espn_ids(db, [
        ("4869461", _espn_player("Trey Smack", 5, 9)),       # GB kicker
        ("777", _espn_player("Mike Williams", 3, 23)),       # PIT → team breaks the tie
        ("888", _espn_player("Nobody Known", 3, 1)),         # no such player
    ], {})
    assert espn_map["4869461"] == "13545"
    assert espn_map["777"] == "m2"
    assert "888" not in espn_map
    await db.commit()
    assert (await db.get(Player, "13545")).espn_id == "4869461"


async def test_espn_sync_keeps_a_kicker_missing_from_the_crosswalk(db: AsyncSession, monkeypatch):
    db.add(Player(id="13545", full_name="Trey Smack", last_name="Smack", position="K", team="GB"))
    db.add(Player(id="qb1", full_name="Some QB", position="QB", team="GB", espn_id="111"))
    conn = LeagueConnection(id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn",
                            league_id="L", season=SEASON, team_id="2")
    db.add(conn)
    await db.commit()

    def entry(pid, slot, player):
        return {"playerId": pid, "lineupSlotId": slot, "playerPoolEntry": {"player": player}}

    rosters = {"teams": [{
        "id": 2, "name": "Discount double check",
        "roster": {"entries": [
            entry(111, 0, _espn_player("Some QB", 1, 9)),
            entry(4869461, 17, _espn_player("Trey Smack", 5, 9)),  # K slot
        ]},
    }]}

    async def get_rosters(self):
        return rosters

    async def empty(self, *a, **k):
        return {}

    async def close(self):
        return None

    monkeypatch.setattr(ESPNClient, "get_rosters", get_rosters)
    monkeypatch.setattr(ESPNClient, "get_matchups", empty)
    monkeypatch.setattr(ESPNClient, "get_free_agents", empty)
    monkeypatch.setattr(ESPNClient, "close", close)

    await sync_service.sync_espn_league(db, conn)
    roster = (await db.execute(select(Roster).where(Roster.connection_id == conn.id))).scalar_one()
    assert "13545" in roster.players and "13545" in roster.starters

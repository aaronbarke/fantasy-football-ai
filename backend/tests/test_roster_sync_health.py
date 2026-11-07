"""Stale-roster and IR regressions: IR players must stay flagged when ESPN's
injury feed omits them, one failing league mustn't break the background sync
for the rest, and a reconnect with fresh ESPN cookies replaces the old ones."""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base
from app.jobs import scheduler
from app.models import LeagueConnection, Player, User
from app.routers import leagues as leagues_router
from app.schemas.league import ConnectLeagueRequest
from app.services import injury_service, sync_service
from app.utils.credentials import open_credentials, seal_credentials


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
async def db(session_factory):
    async with session_factory() as session:
        yield session


# --- IR survives the ESPN injury sync -----------------------------------------


async def test_ir_player_missing_from_espn_feed_stays_on_ir(db, monkeypatch):
    async def feed():  # ESPN lists the Questionable player, not the IR one
        return [{"espn_id": "2", "name": "Q", "status": "Questionable", "body_part": "Ankle"}]

    monkeypatch.setattr(injury_service, "fetch_injuries", feed)
    db.add(Player(id="ir", full_name="IR Guy", position="WR", espn_id="1", injury_status="IR"))
    db.add(Player(id="q", full_name="Q", position="WR", espn_id="2", injury_status="Out"))
    db.add(Player(id="h", full_name="Healed", position="WR", espn_id="3", injury_status="Out"))
    await db.commit()

    await injury_service.sync_injuries(db)

    status = {p.id: p.injury_status for p in (await db.execute(select(Player))).scalars()}
    assert status == {"ir": "IR", "q": "Questionable", "h": None}


async def test_player_pool_sync_clears_ir_once_activated(db, monkeypatch):
    class FakeSleeper:
        async def get_all_players(self):
            return {
                "ir": {"position": "WR", "full_name": "Back", "injury_status": None},
                "q": {"position": "WR", "full_name": "Q", "injury_status": None},
                "new": {"position": "WR", "full_name": "New", "injury_status": "IR"},
            }

        async def close(self):
            pass

    monkeypatch.setattr(sync_service, "SleeperClient", FakeSleeper)
    db.add(Player(id="ir", full_name="Back", position="WR", injury_status="Injured Reserve"))
    db.add(Player(id="q", full_name="Q", position="WR", injury_status="Questionable"))
    await db.commit()

    await sync_service.sync_player_pool(db)

    status = {p.id: p.injury_status for p in (await db.execute(select(Player))).scalars()}
    # Activated off IR → cleared; game-day status left for the ESPN feed.
    assert status == {"ir": None, "q": "Questionable", "new": "IR"}


# --- background league sync ---------------------------------------------------


async def test_one_failing_league_does_not_block_the_rest(session_factory, monkeypatch):
    async with session_factory() as db:
        for lid in ("bad", "good"):
            db.add(LeagueConnection(
                id=uuid.uuid4(), user_id=uuid.uuid4(), platform="espn",
                league_id=lid, season=2026,
            ))
        await db.commit()

    async def fake_sync(db, conn):
        conn.league_name = f"synced {conn.league_id}"
        if conn.league_id == "bad":
            raise RuntimeError("ESPN 401")
        await db.commit()

    monkeypatch.setattr(scheduler, "SessionLocal", session_factory)
    monkeypatch.setattr(scheduler, "sync_league", fake_sync)
    await scheduler.job_sync_all_leagues()

    async with session_factory() as db:
        names = {
            c.league_id: c.league_name
            for c in (await db.execute(select(LeagueConnection))).scalars()
        }
    # The failed league's half-applied change is rolled back, not committed
    # alongside the next league's sync.
    assert names == {"bad": None, "good": "synced good"}


# --- reconnecting with fresh ESPN cookies ---------------------------------------


OLD_SWID = "{11111111-2222-3333-4444-555555555555}"
NEW_SWID = "{AAAAAAAA-BBBB-CCCC-DDDD-EEEEEEEEEEEE}"


async def test_reconnect_replaces_expired_espn_cookies(db, monkeypatch):
    user = User(id=uuid.uuid4(), email="r@x.com", password_hash="x")
    conn = LeagueConnection(
        id=uuid.uuid4(), user_id=user.id, platform="espn", league_id="123", season=2026,
        credentials=seal_credentials({"espn_s2": "old", "swid": OLD_SWID}), team_id="3",
    )
    db.add_all([user, conn])
    await db.commit()

    synced = []

    async def fake_sync(db, c):
        synced.append(open_credentials(c.credentials))
        await db.commit()

    monkeypatch.setattr(leagues_router, "sync_league", fake_sync)
    body = ConnectLeagueRequest(
        platform="espn", league_id="123", season=2026, espn_s2="new", swid=NEW_SWID
    )
    resp = await leagues_router.connect_league(body, user=user, db=db)

    assert resp.id == str(conn.id)  # same connection, history kept
    assert synced == [{"espn_s2": "new", "swid": NEW_SWID}]
    rows = (await db.execute(select(LeagueConnection))).scalars().all()
    assert len(rows) == 1


# --- the ESPN league's own IR flag --------------------------------------------


async def test_espn_league_ir_flag_marks_player_absent(db):
    def entry(espn_id, status):
        return {
            "playerId": int(espn_id),
            "playerPoolEntry": {"player": {"fullName": espn_id, "injuryStatus": status}},
        }

    teams = [{"id": 3, "roster": {"entries": [
        entry("16800", "INJURY_RESERVE"),  # on IR, missing from the injury feed
        entry("200", "QUESTIONABLE"),     # game-day status: left to the feed
        entry("300", "SUSPENSION"),
        entry("400", "INJURY_RESERVE"),   # already flagged by Sleeper
    ]}}]
    db.add_all([
        Player(id="adams", full_name="Davante Adams", position="WR"),
        Player(id="q", full_name="Q", position="WR"),
        Player(id="s", full_name="S", position="WR"),
        Player(id="ir", full_name="IR", position="WR", injury_status="Injured Reserve"),
    ])
    await db.commit()

    espn_map = {"16800": "adams", "200": "q", "300": "s", "400": "ir"}
    await sync_service._stamp_league_long_term_statuses(db, teams, espn_map)
    await db.commit()

    status = {p.id: p.injury_status for p in (await db.execute(select(Player))).scalars()}
    assert status == {"adams": "IR", "q": None, "s": "Sus", "ir": "Injured Reserve"}

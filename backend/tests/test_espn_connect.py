"""Connecting ESPN leagues without hand-copied cookies: league discovery from
the ESPN account, one refresh fixing every league on that account, tolerant
SWID input — plus the sync failures that used to surface as bare 500s."""

import uuid

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import app
from app.models import LeagueConnection, Roster, User
from app.routers import leagues as leagues_router
from app.schemas.league import ConnectLeagueRequest
from app.services import sync_service
from app.services.espn_service import ESPNClient, normalize_swid, parse_fan_leagues
from app.utils import limits
from app.utils.credentials import open_credentials, seal_credentials

SWID = "{6A9B3C2D-1E4F-5A6B-7C8D-9E0F1A2B3C4D}"
OTHER_SWID = "{11111111-2222-3333-4444-555555555555}"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    Session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with Session() as session:
        yield session
    await engine.dispose()


@pytest.fixture
async def client(db):
    async def _db():
        yield db

    app.dependency_overrides[get_db] = _db
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _fresh_limits():
    limits.rate_windows.clear()


async def signed_in(client, db, email="fan@example.com") -> tuple[dict, User]:
    resp = await client.post(
        "/api/auth/register", json={"email": email, "password": "correct horse"}
    )
    assert resp.status_code == 201, resp.text
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}, user


def espn_league(user, league_id, *, swid=SWID, s2="old", name=None, public=False):
    return LeagueConnection(
        id=uuid.uuid4(), user_id=user.id, platform="espn", league_id=league_id, season=2026,
        league_name=name or f"League {league_id}",
        credentials=None if public else seal_credentials({"espn_s2": s2, "swid": swid}),
    )


def fan_entry(league_id, season=2026, *, game_id=1, abbrev="FFL", team_id=3, name="League"):
    return {
        "metaData": {
            "entry": {
                "entryId": team_id,
                "entryMetadata": {"teamName": f"Team {team_id}"},
                "gameId": game_id,
                "abbrev": abbrev,
                "seasonId": season,
                "groups": [{"groupId": league_id, "groupName": name, "groupSize": 10}],
            }
        }
    }


# --- SWID shape ---------------------------------------------------------------


def test_swid_always_gets_its_braces():
    bare = SWID.strip("{}")
    assert normalize_swid(bare) == SWID
    assert normalize_swid(f"  {SWID} ") == SWID
    assert normalize_swid(None) is None and normalize_swid("") is None
    # The connect form accepts it either way and stores the form ESPN accepts.
    body = ConnectLeagueRequest(
        platform="espn", league_id="1", season=2026, espn_s2="s2", swid=bare
    )
    assert body.swid == SWID


async def test_espn_client_sends_braced_swid():
    client = ESPNClient("1", 2026, espn_s2="s2", swid=SWID.strip("{}"))
    try:
        assert client._client.cookies.get("SWID") == SWID
    finally:
        await client.close()


# --- league discovery ---------------------------------------------------------


def test_fan_profile_lists_only_this_seasons_football_leagues():
    fan = {
        "preferences": [
            fan_entry(111, name="Dynasty"),
            fan_entry(222, game_id=3, abbrev="FBA", name="Hoops"),  # basketball
            fan_entry(333, season=2025, name="Last year"),
            {"metaData": {"entry": {"gameId": 1, "seasonId": 2026}}},  # no league
            {"typeId": 1},  # a non-fantasy preference
        ]
    }
    assert parse_fan_leagues(fan, 2026) == [
        {
            "league_id": "111", "season": 2026, "name": "Dynasty",
            "team_id": "3", "team_name": "Team 3", "total_teams": 10,
        }
    ]


def test_fan_profile_falls_back_to_last_season_in_the_offseason():
    fan = {"preferences": [fan_entry(333, season=2025, name="Last year")]}
    assert [lg["league_id"] for lg in parse_fan_leagues(fan, 2026)] == ["333"]
    assert parse_fan_leagues({}, 2026) == []
    assert parse_fan_leagues({"preferences": None}, 2026) == []


async def test_lookup_marks_leagues_already_connected(client, db, monkeypatch):
    headers, user = await signed_in(client, db)
    db.add(espn_league(user, "111"))
    await db.commit()
    seen = {}

    async def fake_discover(swid, espn_s2, season):
        seen.update(swid=swid, espn_s2=espn_s2)
        return parse_fan_leagues(
            {"preferences": [fan_entry(111, name="Mine"), fan_entry(222, name="New")]}, 2026
        )

    monkeypatch.setattr(leagues_router, "discover_espn_leagues", fake_discover)
    resp = await client.post(
        "/api/leagues/espn/lookup",
        json={"swid": SWID.strip("{}"), "espn_s2": "s2"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert seen == {"swid": SWID, "espn_s2": "s2"}
    assert [(lg["league_id"], lg["connected"]) for lg in resp.json()["leagues"]] == [
        ("111", True), ("222", False),
    ]


async def test_lookup_failure_is_a_readable_error(client, db, monkeypatch):
    headers, _ = await signed_in(client, db)

    async def boom(swid, espn_s2, season):
        raise httpx.ConnectError("fan.api.espn.com unreachable -- internals")

    monkeypatch.setattr(leagues_router, "discover_espn_leagues", boom)
    resp = await client.post("/api/leagues/espn/lookup", json={"swid": SWID}, headers=headers)
    assert resp.status_code == 502
    assert "internals" not in resp.text and "ESPN" in resp.json()["detail"]


async def test_lookup_rejects_a_swid_that_would_bend_the_url(client, db):
    headers, _ = await signed_in(client, db)
    resp = await client.post(
        "/api/leagues/espn/lookup", json={"swid": "../../admin"}, headers=headers
    )
    assert resp.status_code == 422


# --- one refresh fixes every league on the ESPN account -------------------------


async def test_refreshing_cookies_updates_every_league_on_that_espn_account(
    client, db, monkeypatch
):
    headers, user = await signed_in(client, db)
    stranger = User(id=uuid.uuid4(), email="other@example.com", password_hash="x")
    mine_a, mine_b = espn_league(user, "111"), espn_league(user, "222")
    unreadable = espn_league(user, "333")
    unreadable.credentials = {"v": 1, "enc": "not-a-fernet-token"}
    other_account = espn_league(user, "444", swid=OTHER_SWID)
    public = espn_league(user, "555", public=True)
    theirs = espn_league(stranger, "111")
    db.add_all([stranger, mine_a, mine_b, unreadable, other_account, public, theirs])
    await db.commit()

    synced = []

    async def fake_sync(db, conn):
        synced.append(conn.league_id)
        await db.commit()

    monkeypatch.setattr(leagues_router, "sync_league", fake_sync)
    resp = await client.post(
        "/api/leagues/espn/credentials",
        json={"espn_s2": "fresh", "swid": SWID},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert sorted(synced) == ["111", "222", "333"]
    assert all(lg["ok"] for lg in resp.json()["leagues"])

    for conn in (mine_a, mine_b, unreadable):
        await db.refresh(conn)
        assert open_credentials(conn.credentials) == {"espn_s2": "fresh", "swid": SWID}
    for conn in (other_account, theirs):
        await db.refresh(conn)
        assert open_credentials(conn.credentials)["espn_s2"] == "old"
    await db.refresh(public)
    assert public.credentials is None


async def test_a_league_espn_still_refuses_keeps_its_old_cookies(client, db, monkeypatch):
    headers, user = await signed_in(client, db)
    good, bad = espn_league(user, "111"), espn_league(user, "222")
    db.add_all([good, bad])
    await db.commit()
    good_id, bad_id = str(good.id), str(bad.id)  # the rollback expires the rows

    async def fake_sync(db, conn):
        if conn.league_id == "222":
            request = httpx.Request("GET", "https://espn.test")
            raise httpx.HTTPStatusError(
                "401", request=request, response=httpx.Response(401, request=request)
            )
        await db.commit()

    monkeypatch.setattr(leagues_router, "sync_league", fake_sync)
    resp = await client.post(
        "/api/leagues/espn/credentials",
        json={"espn_s2": "fresh", "swid": SWID},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    by_id = {lg["id"]: lg for lg in resp.json()["leagues"]}
    assert by_id[good_id]["ok"] is True
    assert by_id[bad_id]["ok"] is False and "refused" in by_id[bad_id]["detail"]

    await db.refresh(good)
    await db.refresh(bad)
    assert open_credentials(good.credentials)["espn_s2"] == "fresh"
    assert open_credentials(bad.credentials)["espn_s2"] == "old"


async def test_connecting_one_league_shares_the_cookies_with_its_siblings(
    client, db, monkeypatch
):
    headers, user = await signed_in(client, db)
    sibling = espn_league(user, "111")
    other_account = espn_league(user, "444", swid=OTHER_SWID)
    db.add_all([sibling, other_account])
    await db.commit()

    async def fake_sync(db, conn):
        await db.commit()

    monkeypatch.setattr(leagues_router, "sync_league", fake_sync)
    resp = await client.post(
        "/api/leagues/connect",
        json={
            "platform": "espn", "league_id": "999", "season": 2026,
            "espn_s2": "fresh", "swid": SWID, "team_id": "4",
        },
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["team_id"] == "4"

    await db.refresh(sibling)
    await db.refresh(other_account)
    assert open_credentials(sibling.credentials)["espn_s2"] == "fresh"
    assert open_credentials(other_account.credentials)["espn_s2"] == "old"


# --- sync failures the pages can explain ----------------------------------------


async def test_live_score_refresh_failure_is_reported_not_a_bare_500(client, db, monkeypatch):
    headers, user = await signed_in(client, db)
    conn = espn_league(user, "111")
    db.add(conn)
    await db.commit()

    async def expired(db, conn):
        request = httpx.Request("GET", "https://espn.test")
        raise httpx.HTTPStatusError(
            "401", request=request, response=httpx.Response(401, request=request)
        )

    monkeypatch.setattr(leagues_router, "sync_live_scores", expired)
    resp = await client.post(f"/api/leagues/{conn.id}/matchup/refresh", headers=headers)
    assert resp.status_code == 502
    assert "ESPN refused access" in resp.json()["detail"]


async def test_unknown_sleeper_league_is_not_connected_as_an_empty_one(
    client, db, monkeypatch
):
    headers, _ = await signed_in(client, db)

    class NoSuchLeague:
        async def close(self):
            pass

        async def get_league(self, league_id):
            return None  # Sleeper's 404

        async def get_nfl_state(self):
            return {"week": 3}

        async def _empty(self, *args, **kwargs):
            return []

        get_rosters = get_league_users = get_matchups = get_trending = _empty

    monkeypatch.setattr(sync_service, "SleeperClient", NoSuchLeague)
    resp = await client.post(
        "/api/leagues/connect",
        json={"platform": "sleeper", "league_id": "1048437428541685760", "season": 2026},
        headers=headers,
    )
    assert resp.status_code == 502
    assert "couldn't find that league" in resp.json()["detail"]
    assert (await db.execute(select(LeagueConnection))).first() is None
    assert (await db.execute(select(Roster))).first() is None

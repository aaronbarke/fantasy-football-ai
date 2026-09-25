"""Regression tests for the September 2026 security sweep: auth hardening,
demo-account isolation, AI quotas, rate limiting, credential encryption,
input validation and response headers."""

import inspect
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import httpx
import jwt
import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings
from app.database import Base, get_db
from app.jobs.scheduler import send_injury_alerts
from app.main import app
from app.models import (
    ChatMessage,
    InjuryEvent,
    LeagueConnection,
    MockDraft,
    Player,
    Recommendation,
    Roster,
    User,
)
from app.routers import auth as auth_router
from app.routers import chat as chat_router
from app.routers import draft as draft_router
from app.routers import leagues as leagues_router
from app.routers import mock_draft as mock_router
from app.services import email_service
from app.services.news_service import _article_url
from app.services.recommendation_service import evaluate_pending
from app.services.sleeper_service import _seg
from app.utils import limits
from app.utils.credentials import is_sealed, open_credentials, seal_credentials
from app.utils.security import hash_password, verify_password


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
    limits.login_failures.clear()
    limits.ai_quota_counter.clear()
    chat_router._demo_chats.clear()


@pytest.fixture
def fake_ai(monkeypatch):
    """Canned AI + context so chat routes run without Claude or the network."""
    seen: list[list[dict]] = []

    async def build_context(db, conn, message):
        return "general", {}

    async def generate(question, context, history=None, require_pick=False):
        seen.append(list(history or []))
        return f"answer to {question}"

    async def stream(question, context, history=None, require_pick=False):
        seen.append(list(history or []))
        yield f"answer to {question}"

    monkeypatch.setattr(chat_router, "build_context", build_context)
    monkeypatch.setattr(chat_router, "generate_response", generate)
    monkeypatch.setattr(chat_router, "stream_response", stream)
    return seen


def bearer(tokens: dict) -> dict:
    return {"Authorization": f"Bearer {tokens['access_token']}"}


async def register(client, email="fan@example.com", password="correct horse") -> dict:
    resp = await client.post("/api/auth/register", json={"email": email, "password": password})
    assert resp.status_code == 201, resp.text
    return resp.json()


# --- passwords and sessions ---------------------------------------------------


async def test_overlong_password_is_rejected_not_a_server_error(client):
    resp = await client.post(
        "/api/auth/register", json={"email": "a@example.com", "password": "é" * 40}
    )
    assert resp.status_code == 422


def test_passwords_past_bcrypt_limit_still_verify():
    """Hashes made when bcrypt silently truncated at 72 bytes keep working."""
    hashed = hash_password("x" * 72)
    assert verify_password("x" * 80, hashed)
    assert not verify_password("y" * 72, hashed)


def test_password_less_accounts_never_verify():
    assert not verify_password("anything", "!unusable")
    assert not verify_password("anything", None)


async def test_login_is_throttled_per_account(client):
    await register(client)
    for _ in range(auth_router.LOGIN_FAILURE_LIMIT):
        bad = await client.post(
            "/api/auth/login", json={"email": "fan@example.com", "password": "wrong"}
        )
        assert bad.status_code == 401
    good = await client.post(
        "/api/auth/login", json={"email": "fan@example.com", "password": "correct horse"}
    )
    assert good.status_code == 429


async def test_unknown_email_gets_the_generic_error(client):
    resp = await client.post(
        "/api/auth/login", json={"email": "nobody@example.com", "password": "whatever1"}
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


async def test_token_without_session_version_is_rejected(client, db):
    tokens = await register(client)
    user_id = jwt.decode(tokens["access_token"], options={"verify_signature": False})["sub"]
    legacy = jwt.encode(
        {
            "sub": user_id,
            "type": "access",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        get_settings().jwt_secret,
        algorithm="HS256",
    )
    resp = await client.get("/api/leagues", headers={"Authorization": f"Bearer {legacy}"})
    assert resp.status_code == 401
    assert (await client.get("/api/leagues", headers=bearer(tokens))).status_code == 200


async def test_google_sign_in_takes_back_a_squatted_account(client, db, monkeypatch):
    """Someone registers the victim's address with a password, then the real
    owner arrives via Google: the squatter's password and sessions must die."""
    monkeypatch.setattr(get_settings(), "google_client_id", "client-123")
    squatter = await register(client, email="victim@example.com", password="squatter-pw")

    class FakeGoogle:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            claims = {
                "aud": "client-123",
                "iss": "https://accounts.google.com",
                "email": "victim@example.com",
                "email_verified": "true",
            }
            return httpx.Response(200, json=claims)

    monkeypatch.setattr(auth_router.httpx, "AsyncClient", FakeGoogle)
    owner = await client.post("/api/auth/google", json={"credential": "id-token"})
    assert owner.status_code == 200

    assert (await client.get("/api/leagues", headers=bearer(squatter))).status_code == 401
    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": squatter["refresh_token"]}
    )
    assert refreshed.status_code == 401
    relogin = await client.post(
        "/api/auth/login", json={"email": "victim@example.com", "password": "squatter-pw"}
    )
    assert relogin.status_code == 401
    assert (await client.get("/api/leagues", headers=bearer(owner.json()))).status_code == 200


async def test_google_token_for_another_app_is_rejected(client, monkeypatch):
    monkeypatch.setattr(get_settings(), "google_client_id", "client-123")

    class FakeGoogle:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def get(self, url, params=None):
            return httpx.Response(
                200,
                json={"aud": "someone-else", "iss": "accounts.google.com",
                      "email": "x@example.com", "email_verified": "true"},
            )

    monkeypatch.setattr(auth_router.httpx, "AsyncClient", FakeGoogle)
    resp = await client.post("/api/auth/google", json={"credential": "id-token"})
    assert resp.status_code == 401


# --- the shared demo account ----------------------------------------------------


async def demo_login(client) -> dict:
    resp = await client.post("/api/auth/demo")
    assert resp.status_code == 200
    return resp.json()


async def test_demo_visitors_do_not_share_chat_history(client, db, fake_ai):
    alice, bob = await demo_login(client), await demo_login(client)

    resp = await client.post(
        "/api/chat", json={"message": "Should I start my kicker?"}, headers=bearer(alice)
    )
    assert resp.status_code == 200
    await client.post("/api/chat", json={"message": "And my defense?"}, headers=bearer(alice))

    alice_history = (await client.get("/api/chat/history", headers=bearer(alice))).json()
    assert [m["content"] for m in alice_history][:1] == ["Should I start my kicker?"]
    assert len(alice_history) == 4
    assert (await client.get("/api/chat/history", headers=bearer(bob))).json() == []

    # Alice's follow-up saw her first turn; Bob's AI context never sees hers.
    await client.post("/api/chat", json={"message": "Hi"}, headers=bearer(bob))
    assert fake_ai[1] and fake_ai[1][0]["content"] == "Should I start my kicker?"
    assert fake_ai[2] == []

    # Nothing about demo chats lands in the shared database rows.
    assert (await db.execute(select(func.count(ChatMessage.id)))).scalar() == 0

    # Clearing is per visitor.
    await client.delete("/api/chat/history", headers=bearer(bob))
    assert len((await client.get("/api/chat/history", headers=bearer(alice))).json()) == 4


async def test_demo_session_survives_token_refresh(client, fake_ai):
    tokens = await demo_login(client)
    await client.post("/api/chat", json={"message": "Who's my QB?"}, headers=bearer(tokens))
    refreshed = await client.post(
        "/api/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    history = (await client.get("/api/chat/history", headers=bearer(refreshed.json()))).json()
    assert len(history) == 2


async def test_demo_stream_does_not_persist(client, db, fake_ai):
    tokens = await demo_login(client)
    resp = await client.post("/api/chat/stream", json={"message": "Hi"}, headers=bearer(tokens))
    assert resp.status_code == 200 and "[DONE]" in resp.text
    assert (await db.execute(select(func.count(ChatMessage.id)))).scalar() == 0


async def test_real_accounts_still_persist_chat(client, db, fake_ai):
    tokens = await register(client)
    await client.post("/api/chat", json={"message": "Hi"}, headers=bearer(tokens))
    assert (await db.execute(select(func.count(ChatMessage.id)))).scalar() == 2


async def test_chat_stream_errors_are_generic(client, monkeypatch, fake_ai):
    async def boom(*args, **kwargs):
        raise RuntimeError("anthropic said: credit balance too low for org_abc123")
        yield  # pragma: no cover

    monkeypatch.setattr(chat_router, "stream_response", boom)
    tokens = await register(client)
    resp = await client.post("/api/chat/stream", json={"message": "Hi"}, headers=bearer(tokens))
    assert "org_abc123" not in resp.text
    assert "try again" in resp.text


# --- AI spend caps --------------------------------------------------------------


async def test_daily_ai_quota_per_user(client, monkeypatch, fake_ai):
    monkeypatch.setattr(get_settings(), "ai_daily_limit_per_user", 2)
    tokens = await register(client)
    codes = [
        (await client.post("/api/chat", json={"message": "Hi"}, headers=bearer(tokens))).status_code
        for _ in range(3)
    ]
    assert codes == [200, 200, 429]


async def test_demo_ai_quota_is_shared_across_visitors(client, monkeypatch, fake_ai):
    monkeypatch.setattr(get_settings(), "ai_daily_limit_demo_per_ip", 100)
    monkeypatch.setattr(get_settings(), "ai_daily_limit_demo_total", 2)
    codes = []
    for _ in range(3):  # a fresh demo login per call doesn't reset anything
        tokens = await demo_login(client)
        resp = await client.post("/api/chat", json={"message": "Hi"}, headers=bearer(tokens))
        codes.append(resp.status_code)
    assert codes == [200, 200, 429]


def test_every_ai_route_is_metered():
    from app.routers import betting, gameplan, trade
    from app.utils.security import ai_quota

    for route in (
        chat_router.chat,
        chat_router.chat_stream,
        trade.analyze_trade,
        draft_router.draft_advice,
        gameplan.gameplan_brief,
        betting.betting_analysis,
    ):
        params = inspect.signature(route).parameters.values()
        deps = [p.default.dependency for p in params if hasattr(p.default, "dependency")]
        assert ai_quota in deps, route.__name__


# --- rate limiting --------------------------------------------------------------


def _request(peer: str, forwarded: str | None = None):
    headers = {"x-forwarded-for": forwarded} if forwarded else {}
    return SimpleNamespace(client=SimpleNamespace(host=peer), headers=headers)


def test_client_ip_behind_a_proxy_uses_the_proxy_appended_address(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 1)
    # The client forged the first entry; the proxy appended the real one.
    assert limits.client_ip(_request("10.0.0.2", "6.6.6.6, 203.0.113.9")) == "203.0.113.9"
    assert limits.client_ip(_request("10.0.0.2")) == "10.0.0.2"


def test_client_ip_without_proxies_ignores_forwarded_headers(monkeypatch):
    monkeypatch.setattr(get_settings(), "trusted_proxy_count", 0)
    assert limits.client_ip(_request("198.51.100.4", "6.6.6.6")) == "198.51.100.4"


def test_production_trusts_one_proxy_by_default(monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "trusted_proxy_count", None)
    monkeypatch.setattr(settings, "environment", "production")
    assert settings.proxy_hops == 1
    monkeypatch.setattr(settings, "environment", "development")
    assert settings.proxy_hops == 0


def test_sliding_window_limits_and_prunes():
    window = limits.SlidingWindow(max_keys=3, max_window=0)
    assert window.hit("a", 2, 60) and window.hit("a", 2, 60)
    assert not window.hit("a", 2, 60)
    for key in "bcde":
        window.add(key)
    assert len(window._hits) <= 3  # stale keys were dropped


async def test_auth_endpoints_are_rate_limited(client):
    codes = [
        (await client.post("/api/auth/login", json={"email": f"u{i}@example.com",
                                                    "password": "x"})).status_code
        for i in range(31)
    ]
    assert codes[-1] == 429 and 429 not in codes[:30]


async def test_oversized_bodies_are_refused(client):
    resp = await client.post(
        "/api/auth/login",
        content=b"{" + b" " * 1_100_000 + b"}",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 413


# --- response headers & CORS ----------------------------------------------------


async def test_api_responses_carry_security_headers(client):
    resp = await client.get("/api/leagues")
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["cache-control"] == "no-store"
    assert "default-src 'none'" in resp.headers["content-security-policy"]


async def test_cors_never_allows_credentials(client):
    resp = await client.options(
        "/api/leagues",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "GET"},
    )
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:3000"
    assert "access-control-allow-credentials" not in resp.headers


# --- ESPN credentials -----------------------------------------------------------


def test_credentials_round_trip_encrypted():
    creds = {"espn_s2": "AEBsecret%2Bcookie", "swid": "{ABC}"}
    sealed = seal_credentials(creds)
    assert is_sealed(sealed) and "AEBsecret" not in str(sealed)
    assert open_credentials(sealed) == creds


def test_legacy_and_tampered_credentials():
    assert open_credentials({"espn_s2": "plain", "swid": "{X}"}) == {"espn_s2": "plain", "swid": "{X}"}
    assert open_credentials({"v": 1, "enc": "not-a-token"}) == {}
    assert open_credentials(None) == {}


async def test_connecting_espn_stores_sealed_cookies(client, db, monkeypatch):
    async def fake_sync(db, conn):
        conn.league_name = "Test League"
        await db.commit()

    monkeypatch.setattr(leagues_router, "sync_league", fake_sync)
    tokens = await register(client)
    resp = await client.post(
        "/api/leagues/connect",
        json={
            "platform": "espn", "league_id": "123456", "season": 2026,
            "espn_s2": "AEBsecret%2Bcookie", "swid": "{6A9B3C2D-1E4F-5A6B-7C8D-9E0F1A2B3C4D}",
        },
        headers=bearer(tokens),
    )
    assert resp.status_code == 201, resp.text
    assert "credentials" not in resp.json()
    stored = (await db.execute(select(LeagueConnection))).scalar_one().credentials
    assert is_sealed(stored) and "AEBsecret" not in str(stored)
    assert open_credentials(stored)["espn_s2"] == "AEBsecret%2Bcookie"


async def test_sync_failures_do_not_echo_exception_text(client, monkeypatch):
    async def failing_sync(db, conn):
        raise RuntimeError('INSERT INTO rosters VALUES (...) -- secret internals')

    monkeypatch.setattr(leagues_router, "sync_league", failing_sync)
    tokens = await register(client)
    resp = await client.post(
        "/api/leagues/connect",
        json={"platform": "sleeper", "league_id": "1048437428541685760", "season": 2026},
        headers=bearer(tokens),
    )
    assert resp.status_code == 502
    assert "INSERT" not in resp.text and "Sleeper" in resp.json()["detail"]


@pytest.mark.parametrize(
    "field,value",
    [
        ("league_id", "../../user/123"),
        ("league_id", "123?view=mTeam"),
        ("swid", "not-a-swid"),
        ("espn_s2", "abc; Path=/"),
        ("team_id", "1/../2"),
    ],
)
async def test_connect_rejects_values_that_would_bend_upstream_urls(client, field, value):
    tokens = await register(client)
    body = {"platform": "espn", "league_id": "123456", "season": 2026, field: value}
    resp = await client.post("/api/leagues/connect", json=body, headers=bearer(tokens))
    assert resp.status_code == 422


def test_sleeper_path_segments_are_encoded():
    assert _seg("../league/1?x=1") == "..%2Fleague%2F1%3Fx%3D1"


async def test_live_external_takes_no_cookies_in_the_url(client, monkeypatch):
    seen = {}

    async def fake_state(db, league_id, season, espn_s2, swid, team_id):
        seen.update(league_id=league_id, espn_s2=espn_s2, swid=swid)
        return {"status": "not_started"}

    monkeypatch.setattr(draft_router, "espn_external_draft_state", fake_state)
    tokens = await register(client)
    ok = await client.get(
        "/api/draft/live-external?espn_league_id=12345&espn_s2=SECRET&swid={X}",
        headers=bearer(tokens),
    )
    assert ok.status_code == 200
    assert seen == {"league_id": "12345", "espn_s2": None, "swid": None}
    bad = await client.get(
        "/api/draft/live-external?espn_league_id=1/../2", headers=bearer(tokens)
    )
    assert bad.status_code == 422


# --- misc input validation -------------------------------------------------------


async def test_negative_limits_are_rejected_not_passed_to_sql(client):
    tokens = await register(client)
    assert (await client.get("/api/chat/history?limit=-1", headers=bearer(tokens))).status_code == 422
    assert (
        await client.get("/api/players/rankings?limit=-5", headers=bearer(tokens))
    ).status_code == 422


async def test_draft_id_lists_are_bounded(client):
    tokens = await register(client)
    body = {"drafted_ids": [str(i) for i in range(draft_router.MAX_DRAFT_PICKS + 1)]}
    resp = await client.post("/api/draft/recommend", json=body, headers=bearer(tokens))
    assert resp.status_code == 422


def test_news_links_must_be_http():
    assert _article_url({"links": {"web": {"href": "javascript:alert(1)"}}}) is None
    assert _article_url({"links": {"web": {"href": "https://espn.com/a"}}}) == "https://espn.com/a"


async def test_grading_on_demand_only_touches_the_callers_calls(db):
    me, other = uuid.uuid4(), uuid.uuid4()
    for uid in (me, other):
        db.add(User(id=uid, email=f"{uid}@example.com", password_hash="!"))
    db.add(Player(id="p1", full_name="P1", position="WR"))
    db.add(Player(id="p2", full_name="P2", position="WR"))
    from app.models import PlayerStatsWeekly

    db.add(PlayerStatsWeekly(player_id="p1", season=2026, week=1, fantasy_points_ppr=10))
    for uid in (me, other):
        db.add(Recommendation(user_id=uid, season=2026, week=1, picked_player_id="p1",
                              alternative_player_id="p2", scoring_type="ppr"))
    await db.commit()
    assert await evaluate_pending(db, user_id=me) == 1
    results = {
        r.user_id: r.result for r in (await db.execute(select(Recommendation))).scalars()
    }
    assert results[me] == "win" and results[other] == "pending"


async def test_old_mock_drafts_are_pruned(db):
    user = User(email="m@example.com", password_hash="!")
    db.add(user)
    await db.commit()
    drafts = [MockDraft(user_id=user.id, season=2026) for _ in range(mock_router.MAX_MOCKS_PER_USER + 5)]
    db.add_all(drafts)
    await db.commit()
    await mock_router._prune_old_mocks(db, user, keep=drafts[-1].id)
    remaining = (
        await db.execute(select(func.count(MockDraft.id)).where(MockDraft.user_id == user.id))
    ).scalar()
    assert remaining == mock_router.MAX_MOCKS_PER_USER
    assert await db.get(MockDraft, drafts[-1].id) is not None


async def test_injury_emails_escape_feed_text(db, monkeypatch):
    sent = []

    async def capture(to, subject, html):
        sent.append(html)
        return True

    monkeypatch.setattr(email_service, "send_email", capture)
    user = User(email="owner@example.com", password_hash="!")
    db.add(user)
    await db.flush()
    conn = LeagueConnection(user_id=user.id, platform="sleeper", league_id="1", season=2026,
                            team_id="1")
    db.add(conn)
    await db.flush()
    db.add(Player(id="p1", full_name="<img src=x onerror=alert(1)>", position="WR", team="DAL"))
    db.add(Roster(connection_id=conn.id, team_id="1", players=["p1"], starters=["p1"]))
    event = InjuryEvent(player_id="p1", old_status=None, new_status="Out")
    db.add(event)
    await db.commit()

    await send_injury_alerts(db, [event])
    assert sent and "<img" not in sent[0] and "&lt;img" in sent[0]

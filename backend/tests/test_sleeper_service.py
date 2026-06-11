import httpx
import pytest

from app.services.sleeper_service import SleeperClient


@pytest.fixture
def mock_transport():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/v1/user/testuser":
            return httpx.Response(200, json={"user_id": "12345", "display_name": "testuser"})
        if path == "/v1/user/12345/leagues/nfl/2026":
            return httpx.Response(
                200,
                json=[
                    {
                        "league_id": "league1",
                        "name": "Test League",
                        "season": "2026",
                        "total_rosters": 12,
                        "scoring_settings": {"rec": 1.0},
                    }
                ],
            )
        if path == "/v1/user/missing":
            return httpx.Response(404)
        if path == "/v1/state/nfl":
            return httpx.Response(200, json={"week": 10, "season": "2026"})
        return httpx.Response(404)

    return httpx.MockTransport(handler)


@pytest.fixture
def client(mock_transport):
    c = SleeperClient()
    c._client = httpx.AsyncClient(
        base_url="https://api.sleeper.app/v1", transport=mock_transport
    )
    return c


@pytest.mark.asyncio
async def test_get_user(client):
    user = await client.get_user("testuser")
    assert user["user_id"] == "12345"
    await client.close()


@pytest.mark.asyncio
async def test_get_user_not_found(client):
    assert await client.get_user("missing") is None
    await client.close()


@pytest.mark.asyncio
async def test_get_user_leagues(client):
    leagues = await client.get_user_leagues("12345", 2026)
    assert len(leagues) == 1
    assert leagues[0]["name"] == "Test League"
    await client.close()


@pytest.mark.asyncio
async def test_nfl_state(client):
    state = await client.get_nfl_state()
    assert state["week"] == 10
    await client.close()

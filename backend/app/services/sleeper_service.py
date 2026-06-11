"""Sleeper API client. Free, no auth, documented at docs.sleeper.com.
Rate limit guidance: stay under 1000 calls/minute."""

from typing import Any

import httpx

BASE_URL = "https://api.sleeper.app/v1"


class SleeperError(Exception):
    pass


class SleeperClient:
    def __init__(self, timeout: float = 30.0):
        self._client = httpx.AsyncClient(base_url=BASE_URL, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        resp = await self._client.get(path)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.json()

    async def get_user(self, username_or_id: str) -> dict | None:
        return await self._get(f"/user/{username_or_id}")

    async def get_user_leagues(self, user_id: str, season: int) -> list[dict]:
        return await self._get(f"/user/{user_id}/leagues/nfl/{season}") or []

    async def get_league(self, league_id: str) -> dict | None:
        return await self._get(f"/league/{league_id}")

    async def get_rosters(self, league_id: str) -> list[dict]:
        return await self._get(f"/league/{league_id}/rosters") or []

    async def get_league_users(self, league_id: str) -> list[dict]:
        return await self._get(f"/league/{league_id}/users") or []

    async def get_matchups(self, league_id: str, week: int) -> list[dict]:
        return await self._get(f"/league/{league_id}/matchups/{week}") or []

    async def get_transactions(self, league_id: str, week: int) -> list[dict]:
        return await self._get(f"/league/{league_id}/transactions/{week}") or []

    async def get_nfl_state(self) -> dict:
        """Current season/week per Sleeper — drives 'what week is it' everywhere."""
        return await self._get("/state/nfl") or {}

    async def get_all_players(self) -> dict[str, dict]:
        """~5MB payload. Call at most once per day; cached by the sync job."""
        return await self._get("/players/nfl") or {}

    async def get_trending(self, kind: str = "add", limit: int = 50) -> list[dict]:
        return await self._get(f"/players/nfl/trending/{kind}?limit={limit}") or []

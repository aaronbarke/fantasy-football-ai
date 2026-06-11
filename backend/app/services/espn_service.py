"""ESPN Fantasy API client (reverse-engineered, undocumented).

Public leagues need only league_id + season. Private leagues require the
espn_s2 and SWID cookies, which the user copies from their browser session.
"""

import json

import httpx

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"

# ESPN lineup slot IDs → readable positions
SLOT_MAP = {
    0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "DEF", 17: "K",
    20: "BN", 21: "IR", 23: "FLEX",
}
# ESPN position IDs on player objects
POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}


class ESPNClient:
    def __init__(
        self,
        league_id: str,
        season: int,
        espn_s2: str | None = None,
        swid: str | None = None,
        timeout: float = 30.0,
    ):
        self.league_id = league_id
        self.season = season
        cookies = {}
        if espn_s2 and swid:
            cookies = {"espn_s2": espn_s2, "SWID": swid}
        self._client = httpx.AsyncClient(timeout=timeout, cookies=cookies)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def _league_url(self) -> str:
        return f"{BASE_URL}/seasons/{self.season}/segments/0/leagues/{self.league_id}"

    async def _get(self, views: list[str], extra_headers: dict | None = None) -> dict:
        params = [("view", v) for v in views]
        resp = await self._client.get(self._league_url, params=params, headers=extra_headers or {})
        resp.raise_for_status()
        return resp.json()

    async def get_settings(self) -> dict:
        return await self._get(["mSettings"])

    async def get_teams(self) -> dict:
        return await self._get(["mTeam"])

    async def get_rosters(self) -> dict:
        return await self._get(["mRoster", "mTeam"])

    async def get_matchups(self) -> dict:
        return await self._get(["mMatchup"])

    async def get_free_agents(self, limit: int = 100) -> dict:
        """Free agents + waiver players, sorted by ownership. Uses the
        X-Fantasy-Filter header — ESPN's mechanism for filtering player queries."""
        fantasy_filter = {
            "players": {
                "filterStatus": {"value": ["FREEAGENT", "WAIVERS"]},
                "sortPercOwned": {"sortPriority": 1, "sortAsc": False},
                "limit": limit,
            }
        }
        return await self._get(
            ["kona_player_info"],
            extra_headers={"X-Fantasy-Filter": json.dumps(fantasy_filter)},
        )

    @staticmethod
    def parse_roster_entries(team: dict) -> tuple[list[str], list[str]]:
        """Return (all espn player ids, starter espn player ids) for a team blob."""
        all_ids: list[str] = []
        starter_ids: list[str] = []
        entries = (team.get("roster") or {}).get("entries", [])
        for entry in entries:
            pid = str(entry.get("playerId"))
            all_ids.append(pid)
            slot = entry.get("lineupSlotId")
            if slot is not None and SLOT_MAP.get(slot) not in ("BN", "IR"):
                starter_ids.append(pid)
        return all_ids, starter_ids


def scoring_type_from_espn(settings_blob: dict) -> str:
    """ESPN scoringSettings → ppr / half_ppr / standard.
    Stat 53 is receptions in ESPN's scoring item list."""
    try:
        items = settings_blob["settings"]["scoringSettings"]["scoringItems"]
        for item in items:
            if item.get("statId") == 53:
                pts = float(item.get("pointsOverrides", {}).get("16", item.get("points", 0)))
                if pts >= 0.75:
                    return "ppr"
                if pts >= 0.25:
                    return "half_ppr"
        return "standard"
    except (KeyError, TypeError, ValueError):
        return "ppr"

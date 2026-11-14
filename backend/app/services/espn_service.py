"""ESPN Fantasy API client (reverse-engineered, undocumented).

Public leagues need only league_id + season. Private leagues require the
espn_s2 and SWID cookies from the user's ESPN session — handed over by the
FFAI Connect browser extension, or pasted in by hand.
"""

import json
from urllib.parse import quote

import httpx

BASE_URL = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl"
# ESPN's fan profile: every fantasy team an account owns, across sports.
FAN_URL = "https://fan.api.espn.com/apis/v2/fans"
ESPN_FOOTBALL_GAME_ID = 1
ESPN_FOOTBALL_ABBREV = "FFL"


def normalize_swid(swid: str | None) -> str | None:
    """A SWID in the shape ESPN uses everywhere: the GUID wrapped in braces.

    ESPN only accepts the cookie with its braces, and lists league owners the
    same way, so a SWID pasted without them both failed to sign in and never
    matched the user's team."""
    if not swid:
        return None
    return "{" + swid.strip().strip("{}") + "}"

# ESPN lineup slot IDs → readable positions (Sleeper's names for the combo
# slots, so both platforms share one lineup vocabulary). 3 = RB/WR, 5 = WR/TE,
# 7 = OP (superflex); without them those slots silently vanish from the lineup.
SLOT_MAP = {
    0: "QB", 2: "RB", 3: "WRRB_FLEX", 4: "WR", 5: "REC_FLEX", 6: "TE",
    7: "SUPER_FLEX", 16: "DEF", 17: "K", 20: "BN", 21: "IR", 23: "FLEX",
}
# ESPN position IDs on player objects
POSITION_MAP = {1: "QB", 2: "RB", 3: "WR", 4: "TE", 5: "K", 16: "DEF"}

# ESPN proTeamId → team code (Sleeper convention, which is how we key team
# defenses). Team D/ST aren't in the player id crosswalk, so we resolve them by
# their pro team instead.
PRO_TEAM_MAP = {
    1: "ATL", 2: "BUF", 3: "CHI", 4: "CIN", 5: "CLE", 6: "DAL", 7: "DEN",
    8: "DET", 9: "GB", 10: "TEN", 11: "IND", 12: "KC", 13: "LV", 14: "LAR",
    15: "MIA", 16: "MIN", 17: "NE", 18: "NO", 19: "NYG", 20: "NYJ", 21: "PHI",
    22: "ARI", 23: "PIT", 24: "LAC", 25: "SF", 26: "SEA", 27: "TB", 28: "WAS",
    29: "CAR", 30: "JAX", 33: "BAL", 34: "HOU",
}


def espn_defense_code(entry: dict) -> str | None:
    """Team-code id for a D/ST roster entry (our defense Player id), else None."""
    player = (entry.get("playerPoolEntry") or {}).get("player") or {}
    if player.get("defaultPositionId") != 16:
        return None
    return PRO_TEAM_MAP.get(player.get("proTeamId"))


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
            cookies = {"espn_s2": espn_s2, "SWID": normalize_swid(swid)}
        self._client = httpx.AsyncClient(timeout=timeout, cookies=cookies)

    async def close(self) -> None:
        await self._client.aclose()

    @property
    def _league_url(self) -> str:
        league = quote(str(self.league_id), safe="")
        return f"{BASE_URL}/seasons/{int(self.season)}/segments/0/leagues/{league}"

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
        return await self._get(["mRoster", "mTeam", "mSettings"])

    async def get_matchups(self) -> dict:
        # mScoreboard/mLiveScoring surface in-progress ("live") points on the
        # current week; mMatchup alone reports final totals only.
        return await self._get(["mMatchup", "mScoreboard", "mLiveScoring"])

    async def get_draft_detail(self) -> dict:
        """Live draft board. `draftDetail.picks` carries one slot per overall
        pick; `playerId` is -1 until that pick is made, then the ESPN player id.
        `inProgress`/`drafted` flag the draft's state."""
        return await self._get(["mDraftDetail"])

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

    @staticmethod
    def parse_defenses(team: dict) -> tuple[list[str], list[str]]:
        """(all D/ST team-code ids, started D/ST team-code ids) for a team blob.
        Defenses map by pro team, not the player crosswalk."""
        all_def: list[str] = []
        starter_def: list[str] = []
        for entry in (team.get("roster") or {}).get("entries", []):
            code = espn_defense_code(entry)
            if not code:
                continue
            all_def.append(code)
            slot = entry.get("lineupSlotId")
            if slot is not None and SLOT_MAP.get(slot) not in ("BN", "IR"):
                starter_def.append(code)
        return all_def, starter_def


def roster_positions_from_espn(settings_blob: dict) -> list[str] | None:
    """ESPN lineupSlotCounts → a flat roster_positions list (Sleeper-style).

    Expands each lineup slot by its count into the same shape Sleeper leagues
    store, so `starters_per_team` and the draft board treat both platforms
    identically. Order is irrelevant downstream — only the counts matter.
    """
    try:
        counts = settings_blob["settings"]["rosterSettings"]["lineupSlotCounts"]
    except (KeyError, TypeError):
        return None
    positions: list[str] = []
    for slot_id, n in (counts or {}).items():
        name = SLOT_MAP.get(int(slot_id))
        if name and n:
            positions.extend([name] * int(n))
    return positions or None


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


def parse_fan_leagues(fan: dict, season: int) -> list[dict]:
    """The fantasy *football* leagues in an ESPN fan profile for ``season``,
    falling back to the season before it (useful in the offseason).

    Each fantasy team is a ``preferences`` item whose ``metaData.entry`` names
    the game (``FFL``), the season, the team (``entryId``) and its league
    (``groups[0]``)."""
    found: list[dict] = []
    for pref in (fan or {}).get("preferences") or []:
        entry = ((pref or {}).get("metaData") or {}).get("entry") or {}
        if (
            entry.get("gameId") != ESPN_FOOTBALL_GAME_ID
            and str(entry.get("abbrev") or "").upper() != ESPN_FOOTBALL_ABBREV
        ):
            continue
        group = next(iter(entry.get("groups") or []), None) or {}
        try:
            league_id = str(int(group["groupId"]))
            entry_season = int(entry["seasonId"])
        except (KeyError, TypeError, ValueError):
            continue
        meta = entry.get("entryMetadata") or {}
        team_id = entry.get("entryId")
        found.append(
            {
                "league_id": league_id,
                "season": entry_season,
                "name": group.get("groupName") or "ESPN league",
                "team_id": str(team_id) if team_id is not None else None,
                "team_name": meta.get("teamName"),
                "total_teams": group.get("groupSize"),
            }
        )
    for wanted in (season, season - 1):
        leagues = [lg for lg in found if lg["season"] == wanted]
        if leagues:
            return leagues
    return []


async def discover_espn_leagues(
    swid: str, espn_s2: str | None, season: int, timeout: float = 20.0
) -> list[dict]:
    """The user's ESPN fantasy football leagues, so they can pick one instead
    of digging a league ID out of a URL. Raises ``httpx.HTTPError`` if ESPN
    can't be reached or refuses."""
    swid = normalize_swid(swid) or ""
    cookies = {"SWID": swid}
    if espn_s2:
        cookies["espn_s2"] = espn_s2
    async with httpx.AsyncClient(timeout=timeout, cookies=cookies) as client:
        resp = await client.get(
            f"{FAN_URL}/{quote(swid, safe='')}",
            params={"displayHiddenPrefs": "true", "context": "fantasy"},
        )
        resp.raise_for_status()
        return parse_fan_leagues(resp.json(), season)

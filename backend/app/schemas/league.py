from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

# These values are spliced into Sleeper/ESPN request paths and cookies, so they
# are held to the shapes those platforms actually use.
NUMERIC_ID = r"^\d{1,32}$"


class SleeperLookupRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    username: str = Field(min_length=1, max_length=64)


class SleeperLeagueOption(BaseModel):
    league_id: str
    name: str
    season: str
    total_rosters: int
    scoring_type: str | None = None


class SleeperLookupResponse(BaseModel):
    user_id: str
    username: str
    leagues: list[SleeperLeagueOption]


class ConnectLeagueRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    platform: str = Field(max_length=20)  # sleeper | espn
    league_id: str = Field(pattern=NUMERIC_ID)
    season: int = Field(ge=2000, le=2100)
    platform_user_id: str | None = Field(default=None, pattern=NUMERIC_ID)  # sleeper user_id
    # Cookie values: no whitespace, separators or quotes (they'd break the header)
    espn_s2: str | None = Field(default=None, max_length=2048, pattern=r'^[^\s;,"\\]+$')
    swid: str | None = Field(default=None, pattern=r"^\{?[0-9A-Fa-f-]{32,40}\}?$")
    team_id: str | None = Field(default=None, pattern=r"^\d{1,10}$")  # ESPN team selection


class LeagueConnectionResponse(BaseModel):
    id: str
    platform: str
    league_id: str
    league_name: str | None
    season: int
    scoring_type: str | None
    roster_positions: list[str] | None
    team_id: str | None
    last_synced_at: datetime | None


class RosterSlot(BaseModel):
    slot: str
    player: dict[str, Any] | None


class RosterResponse(BaseModel):
    team_id: str
    owner_name: str | None
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float
    starters: list[dict[str, Any]]
    bench: list[dict[str, Any]]


class StandingsEntry(BaseModel):
    team_id: str
    owner_name: str | None
    wins: int
    losses: int
    ties: int
    points_for: float
    points_against: float


class MatchupResponse(BaseModel):
    week: int
    user_team: RosterResponse | None
    opponent_team: RosterResponse | None


class WaiverPlayer(BaseModel):
    player: dict[str, Any]
    trending_count: int | None
    recent_ppr_avg: float | None

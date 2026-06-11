from datetime import datetime
from typing import Any

from pydantic import BaseModel


class SleeperLookupRequest(BaseModel):
    username: str


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
    platform: str  # sleeper | espn
    league_id: str
    season: int
    platform_user_id: str | None = None  # sleeper user_id
    espn_s2: str | None = None
    swid: str | None = None
    team_id: str | None = None  # ESPN team selection


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

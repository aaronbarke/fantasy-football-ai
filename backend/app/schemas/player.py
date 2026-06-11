from pydantic import BaseModel


class PlayerOut(BaseModel):
    id: str
    full_name: str
    position: str | None
    team: str | None
    age: int | None
    status: str | None
    injury_status: str | None
    injury_body_part: str | None

    model_config = {"from_attributes": True}


class WeeklyStatOut(BaseModel):
    season: int
    week: int
    opponent: str | None
    pass_yards: float
    pass_tds: int
    interceptions: int
    rush_yards: float
    rush_tds: int
    receptions: int
    receiving_yards: float
    receiving_tds: int
    targets: int
    snap_pct: float | None
    target_share: float | None
    fantasy_points_ppr: float | None
    fantasy_points_half: float | None
    fantasy_points_std: float | None

    model_config = {"from_attributes": True}

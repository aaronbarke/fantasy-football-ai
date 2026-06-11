from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlayerStatsWeekly(Base):
    __tablename__ = "player_stats_weekly"
    __table_args__ = (
        UniqueConstraint("player_id", "season", "week"),
        Index("idx_stats_player_season", "player_id", "season"),
        Index("idx_stats_season_week", "season", "week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(50), ForeignKey("players.id"))
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)

    pass_yards: Mapped[float] = mapped_column(Numeric, default=0)
    pass_tds: Mapped[int] = mapped_column(Integer, default=0)
    interceptions: Mapped[int] = mapped_column(Integer, default=0)
    rush_attempts: Mapped[int] = mapped_column(Integer, default=0)
    rush_yards: Mapped[float] = mapped_column(Numeric, default=0)
    rush_tds: Mapped[int] = mapped_column(Integer, default=0)
    receptions: Mapped[int] = mapped_column(Integer, default=0)
    receiving_yards: Mapped[float] = mapped_column(Numeric, default=0)
    receiving_tds: Mapped[int] = mapped_column(Integer, default=0)
    targets: Mapped[int] = mapped_column(Integer, default=0)
    snap_pct: Mapped[float | None] = mapped_column(Numeric)
    target_share: Mapped[float | None] = mapped_column(Numeric)
    air_yards_share: Mapped[float | None] = mapped_column(Numeric)
    fantasy_points_ppr: Mapped[float | None] = mapped_column(Numeric)
    fantasy_points_half: Mapped[float | None] = mapped_column(Numeric)
    fantasy_points_std: Mapped[float | None] = mapped_column(Numeric)
    opponent: Mapped[str | None] = mapped_column(String(5))

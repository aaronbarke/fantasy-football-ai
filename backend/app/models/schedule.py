from datetime import datetime

from sqlalchemy import DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class NflSchedule(Base):
    """Full-season NFL schedule, synced from ESPN's public scoreboard API.
    Powers the schedule-strength heatmap (who plays whom in coming weeks)."""

    __tablename__ = "nfl_schedule"
    __table_args__ = (UniqueConstraint("season", "week", "home_team"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    home_team: Mapped[str] = mapped_column(String(5), nullable=False)
    away_team: Mapped[str] = mapped_column(String(5), nullable=False)
    game_time: Mapped[datetime | None] = mapped_column(DateTime)

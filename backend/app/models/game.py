from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, Numeric, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class GameCondition(Base):
    __tablename__ = "game_conditions"
    __table_args__ = (UniqueConstraint("season", "week", "home_team"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    home_team: Mapped[str] = mapped_column(String(5), nullable=False)
    away_team: Mapped[str] = mapped_column(String(5), nullable=False)
    game_time: Mapped[datetime | None] = mapped_column(DateTime)
    spread: Mapped[float | None] = mapped_column(Numeric)  # home team spread
    over_under: Mapped[float | None] = mapped_column(Numeric)
    implied_total_home: Mapped[float | None] = mapped_column(Numeric)
    implied_total_away: Mapped[float | None] = mapped_column(Numeric)
    wind_mph: Mapped[float | None] = mapped_column(Numeric)
    temp_f: Mapped[float | None] = mapped_column(Numeric)
    precipitation_pct: Mapped[float | None] = mapped_column(Numeric)
    dome: Mapped[bool] = mapped_column(Boolean, default=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

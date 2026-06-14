from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Player(Base):
    __tablename__ = "players"

    # Sleeper player_id is the canonical ID
    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    first_name: Mapped[str | None] = mapped_column(String(100))
    last_name: Mapped[str | None] = mapped_column(String(100))
    position: Mapped[str | None] = mapped_column(String(10), index=True)
    team: Mapped[str | None] = mapped_column(String(5), index=True)
    age: Mapped[int | None] = mapped_column(Integer)
    years_exp: Mapped[int | None] = mapped_column(Integer)  # 0 = rookie
    status: Mapped[str | None] = mapped_column(String(50))
    espn_id: Mapped[str | None] = mapped_column(String(50), index=True)
    yahoo_id: Mapped[str | None] = mapped_column(String(50))
    gsis_id: Mapped[str | None] = mapped_column(String(50), index=True)  # nflverse ID
    injury_status: Mapped[str | None] = mapped_column(String(50))
    injury_body_part: Mapped[str | None] = mapped_column(String(100))
    depth_chart_order: Mapped[int | None] = mapped_column(Integer)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

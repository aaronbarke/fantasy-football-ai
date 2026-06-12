import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, Numeric, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class InjuryEvent(Base):
    """A detected injury status change — feeds the alert emails."""

    __tablename__ = "injury_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(String(50), ForeignKey("players.id"))
    old_status: Mapped[str | None] = mapped_column(String(50))
    new_status: Mapped[str | None] = mapped_column(String(50))
    notified: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Recommendation(Base):
    """A start/sit call the AI made, stored at decision time so we can grade
    it against actual fantasy points once the week's stats land."""

    __tablename__ = "recommendations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    connection_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="SET NULL")
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    picked_player_id: Mapped[str] = mapped_column(String(50), ForeignKey("players.id"))
    alternative_player_id: Mapped[str] = mapped_column(String(50), ForeignKey("players.id"))
    scoring_type: Mapped[str] = mapped_column(String(20), default="ppr")
    result: Mapped[str] = mapped_column(String(10), default="pending")  # pending|win|loss|tie
    picked_points: Mapped[float | None] = mapped_column(Numeric)
    alternative_points: Mapped[float | None] = mapped_column(Numeric)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONVariant


class Roster(Base):
    __tablename__ = "rosters"
    __table_args__ = (UniqueConstraint("connection_id", "team_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE"), index=True
    )
    team_id: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_name: Mapped[str | None] = mapped_column(String(255))
    players: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    starters: Mapped[list[str] | None] = mapped_column(JSONVariant)
    wins: Mapped[int] = mapped_column(Integer, default=0)
    losses: Mapped[int] = mapped_column(Integer, default=0)
    ties: Mapped[int] = mapped_column(Integer, default=0)
    points_for: Mapped[float] = mapped_column(Numeric, default=0)
    points_against: Mapped[float] = mapped_column(Numeric, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AvailablePlayer(Base):
    __tablename__ = "available_players"
    __table_args__ = (UniqueConstraint("connection_id", "player_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE"), index=True
    )
    player_id: Mapped[str] = mapped_column(String(50), ForeignKey("players.id"))
    trending_count: Mapped[int | None] = mapped_column(Integer)  # Sleeper trending adds
    recent_ppr_avg: Mapped[float | None] = mapped_column(Numeric)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

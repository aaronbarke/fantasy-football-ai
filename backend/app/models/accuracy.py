"""Pre-game snapshots of what we predicted, graded once the week's stats land —
the raw material for the Track record page (projection error, lineup accuracy,
start/sit calls)."""

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONVariant


class ProjectionSnapshot(Base):
    """A player's projection as it stood right before his game kicked off (the
    number someone actually set a lineup with), and later what he scored."""

    __tablename__ = "projection_snapshots"
    __table_args__ = (
        UniqueConstraint("season", "week", "player_id", "scoring"),
        Index("idx_proj_snap_season_week", "season", "week", "scoring"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[str] = mapped_column(String(50), nullable=False)
    position: Mapped[str | None] = mapped_column(String(10))
    team: Mapped[str | None] = mapped_column(String(5))
    scoring: Mapped[str] = mapped_column(String(20), nullable=False, default="ppr")
    projected: Mapped[float] = mapped_column(Float, nullable=False)
    floor: Mapped[float | None] = mapped_column(Float)
    ceiling: Mapped[float | None] = mapped_column(Float)
    model_proj: Mapped[float | None] = mapped_column(Float)  # our model alone
    external_proj: Mapped[float | None] = mapped_column(Float)  # Sleeper alone
    kickoff: Mapped[datetime | None] = mapped_column(DateTime)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    actual: Mapped[float | None] = mapped_column(Float)  # filled at grading
    graded_at: Mapped[datetime | None] = mapped_column(DateTime)


class LineupSnapshot(Base):
    """The lineup we recommended for one league team right before the week's
    main slate (plus the swaps we suggested and the lineup actually set), and
    later how it graded against the best lineup in hindsight."""

    __tablename__ = "lineup_snapshots"
    __table_args__ = (UniqueConstraint("connection_id", "season", "week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring: Mapped[str] = mapped_column(String(20), nullable=False, default="ppr")
    roster: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    actual_starters: Mapped[list[str]] = mapped_column(JSONVariant, nullable=False, default=list)
    # [{"slot", "player_id", "projected"}]
    recommended: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONVariant, nullable=False, default=list
    )
    # [{"slot", "start", "sit"}]
    swaps: Mapped[list[dict[str, Any]]] = mapped_column(JSONVariant, nullable=False, default=list)
    captured_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    grade: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    graded_at: Mapped[datetime | None] = mapped_column(DateTime)

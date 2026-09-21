import uuid
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class LivePlayerScore(Base):
    """A player's live/final fantasy points for one league-week, captured from
    the platform so the matchup can show real points instead of projections.
    Scoped per connection because scoring settings are league-specific."""

    __tablename__ = "live_player_scores"
    __table_args__ = (
        UniqueConstraint("connection_id", "week", "player_id"),
        Index("idx_live_scores_conn_week", "connection_id", "week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE"), index=True
    )
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[str] = mapped_column(String(50), nullable=False)
    points: Mapped[float] = mapped_column(Float, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

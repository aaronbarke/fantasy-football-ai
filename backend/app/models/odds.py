import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONVariant


class MatchupOdds(Base):
    """A point-in-time snapshot of a live matchup's win probability, so the
    Matchup page can chart how the odds moved through the week's games.

    Recorded by the live-odds scheduler job all through the scoring period (and
    whenever someone has the page open). ``player_points`` keeps every starter's
    live points at capture time, so the next snapshot can say whose points moved
    (``changes``) — that's what labels the chart's big swings."""

    __tablename__ = "matchup_odds"
    __table_args__ = (Index("idx_matchup_odds_conn_week", "connection_id", "week"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE"), index=True
    )
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    win_probability: Mapped[float] = mapped_column(Float, nullable=False)
    user_points: Mapped[float | None] = mapped_column(Float)
    opp_points: Mapped[float | None] = mapped_column(Float)
    # {player_id: live points} for both starting lineups at capture time.
    player_points: Mapped[dict[str, float] | None] = mapped_column(JSONVariant)
    # Starters whose points moved since the previous snapshot:
    # [{id, name, position, side: "user"|"opp", delta, points}], biggest first.
    changes: Mapped[list[dict[str, Any]] | None] = mapped_column(JSONVariant)

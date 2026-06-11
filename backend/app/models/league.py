import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONVariant


class LeagueConnection(Base):
    __tablename__ = "league_connections"
    __table_args__ = (UniqueConstraint("user_id", "platform", "league_id", "season"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    platform: Mapped[str] = mapped_column(String(20), nullable=False)  # sleeper | espn | yahoo
    platform_user_id: Mapped[str | None] = mapped_column(String(255))
    league_id: Mapped[str] = mapped_column(String(255), nullable=False)
    league_name: Mapped[str | None] = mapped_column(String(255))
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring_type: Mapped[str | None] = mapped_column(String(20))  # ppr | half_ppr | standard
    scoring_settings: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    roster_positions: Mapped[list[str] | None] = mapped_column(JSONVariant)
    credentials: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    team_id: Mapped[str | None] = mapped_column(String(50))  # the user's own team in this league
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

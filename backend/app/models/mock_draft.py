import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base, JSONVariant


class MockDraft(Base):
    """One practice draft against simulated opponents."""

    __tablename__ = "mock_drafts"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False)
    scoring: Mapped[str] = mapped_column(String(20), nullable=False, default="ppr")
    teams: Mapped[int] = mapped_column(Integer, nullable=False, default=12)
    rounds: Mapped[int] = mapped_column(Integer, nullable=False, default=15)
    my_slot: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    roster_positions: Mapped[list[str] | None] = mapped_column(JSONVariant)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class MockDraftPick(Base):
    """A single selection in a mock draft, in overall pick order."""

    __tablename__ = "mock_draft_picks"
    __table_args__ = (UniqueConstraint("draft_id", "overall_pick"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("mock_drafts.id", ondelete="CASCADE"), index=True
    )
    overall_pick: Mapped[int] = mapped_column(Integer, nullable=False)
    round: Mapped[int] = mapped_column(Integer, nullable=False)
    team_slot: Mapped[int] = mapped_column(Integer, nullable=False)
    player_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("players.id"), nullable=False
    )
    is_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Snapshot of what the player was worth when taken, so grading doesn't
    # change under you if the board is re-synced mid-draft.
    snapshot: Mapped[dict[str, Any] | None] = mapped_column(JSONVariant)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

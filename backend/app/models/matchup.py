import uuid

from sqlalchemy import ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Matchup(Base):
    __tablename__ = "matchups"
    __table_args__ = (
        UniqueConstraint("connection_id", "week", "team_a_id"),
        Index("idx_matchups_connection_week", "connection_id", "week"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("league_connections.id", ondelete="CASCADE")
    )
    week: Mapped[int] = mapped_column(Integer, nullable=False)
    team_a_id: Mapped[str | None] = mapped_column(String(50))
    team_b_id: Mapped[str | None] = mapped_column(String(50))
    team_a_points: Mapped[float | None] = mapped_column(Numeric)
    team_b_points: Mapped[float | None] = mapped_column(Numeric)

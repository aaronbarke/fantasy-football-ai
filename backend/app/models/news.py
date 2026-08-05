from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlayerNews(Base):
    """A news item tagged to a player.

    Preseason value lives in freshness — camp battles, depth-chart moves, and
    holdouts move draft stock faster than any ranking service updates. Deduped
    on (player_id, url) so re-polling the same feed is idempotent.
    """

    __tablename__ = "player_news"
    __table_args__ = (UniqueConstraint("player_id", "url"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    headline: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(String(50))
    url: Mapped[str] = mapped_column(String(1000), nullable=False)
    category: Mapped[str | None] = mapped_column(String(50))  # Story | HeadlineNews | ...
    published_at: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

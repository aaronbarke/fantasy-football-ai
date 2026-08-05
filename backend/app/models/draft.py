from datetime import datetime

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class PlayerDraftProfile(Base):
    """Preseason draft market data for one player, in one scoring format.

    ADP is format-sensitive (a pass-catching back goes earlier in PPR than in
    standard), so there is one row per player/season/scoring rather than one
    per player. ESPN publishes a single format-agnostic ADP, so its columns
    repeat across the three rows; Fantasy Football Calculator is what actually
    varies by format.
    """

    __tablename__ = "player_draft_profiles"
    __table_args__ = (UniqueConstraint("player_id", "season", "scoring"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    player_id: Mapped[str] = mapped_column(
        String(50), ForeignKey("players.id", ondelete="CASCADE"), index=True
    )
    season: Mapped[int] = mapped_column(Integer, nullable=False, index=True)
    scoring: Mapped[str] = mapped_column(String(20), nullable=False)  # ppr|half_ppr|standard

    # Draft market
    adp_espn: Mapped[float | None] = mapped_column(Float)
    adp_ffc: Mapped[float | None] = mapped_column(Float)
    adp_consensus: Mapped[float | None] = mapped_column(Float)
    # Spread of real draft outcomes — drives "will he last until my next pick?"
    adp_stdev: Mapped[float | None] = mapped_column(Float)
    adp_high: Mapped[int | None] = mapped_column(Integer)  # earliest pick seen
    adp_low: Mapped[int | None] = mapped_column(Integer)  # latest pick seen
    times_drafted: Mapped[int | None] = mapped_column(Integer)
    auction_value: Mapped[float | None] = mapped_column(Float)
    percent_owned: Mapped[float | None] = mapped_column(Float)

    # Season-long expectations
    espn_season_proj: Mapped[float | None] = mapped_column(Float)
    prior_season_actual: Mapped[float | None] = mapped_column(Float)
    bye_week: Mapped[int | None] = mapped_column(Integer)

    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

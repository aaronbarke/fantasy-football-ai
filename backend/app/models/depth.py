from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class DepthChartEntry(Base):
    """Depth-chart / alignment snapshot for skill-position receivers AND
    defensive personnel, synced from Sleeper's player pool.

    It exists because two things the projection model needs are NOT on the
    ``players`` table and can't be added there safely (prod provisions schema
    with ``create_all`` on boot, which never ALTERs an existing table):

    1. Offensive alignment — whether a WR/TE lines up in the slot (``SWR``) or
       on the perimeter (``LWR`` / ``RWR``), so a boundary corner going out
       helps outside receivers more than slot guys.
    2. Defensive personnel — CB / edge / interior-DL / off-ball-LB / safety
       starters with their team, alignment and injury status, so an opponent
       losing a key defender lifts the offensive positions that defender
       suppresses.

    One row per player (id = Sleeper player_id). ``injury_status`` is stamped by
    the same ESPN injury sync that updates ``players``.
    """

    __tablename__ = "depth_chart"

    id: Mapped[str] = mapped_column(String(50), primary_key=True)
    full_name: Mapped[str | None] = mapped_column(String(255))
    team: Mapped[str | None] = mapped_column(String(5), index=True)
    position: Mapped[str | None] = mapped_column(String(10), index=True)  # raw Sleeper pos
    depth_chart_position: Mapped[str | None] = mapped_column(String(10))  # SWR/LWR/NB/LCB/MLB…
    depth_chart_order: Mapped[int | None] = mapped_column(Integer)
    espn_id: Mapped[str | None] = mapped_column(String(50), index=True)
    injury_status: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )

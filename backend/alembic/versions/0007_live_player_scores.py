"""Live per-player scores: live_player_scores table.

create_all with checkfirst only creates the missing table (same pattern as
0002/0004/0005/0006). Prod also provisions it via create_all on boot.

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-21
"""

from alembic import op

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NEW_TABLES = ["live_player_scores"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in NEW_TABLES:
        op.drop_table(table)

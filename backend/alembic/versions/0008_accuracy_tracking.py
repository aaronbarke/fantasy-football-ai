"""Accuracy tracking: projection_snapshots and lineup_snapshots tables.

create_all with checkfirst only creates the missing tables (same pattern as
0002/0004–0007). Prod also provisions them via create_all on boot.

Revision ID: 0008
Revises: 0007
Create Date: 2026-10-12
"""

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

NEW_TABLES = ["lineup_snapshots", "projection_snapshots"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in NEW_TABLES:
        op.drop_table(table)

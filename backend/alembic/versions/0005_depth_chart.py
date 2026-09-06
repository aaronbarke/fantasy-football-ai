"""Depth-chart / defensive-personnel snapshot table.

create_all with checkfirst only creates the missing table, so this stays in
sync with the ORM metadata (same pattern as 0002/0004). Prod also provisions it
via create_all on boot; this migration keeps Alembic-managed environments level.

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-06
"""

from alembic import op

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

NEW_TABLES = ["depth_chart"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in NEW_TABLES:
        op.drop_table(table)

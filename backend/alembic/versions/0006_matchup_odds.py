"""Matchup odds history: matchup_odds table.

create_all with checkfirst only creates the missing table, so this stays in
sync with the ORM metadata (same pattern as 0002/0004/0005). Prod also
provisions it via create_all on boot.

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-21
"""

from alembic import op

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

NEW_TABLES = ["matchup_odds"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in NEW_TABLES:
        op.drop_table(table)

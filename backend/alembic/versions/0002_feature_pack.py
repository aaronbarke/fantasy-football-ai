"""Feature pack: nfl_schedule, injury_events, recommendations tables.

create_all with checkfirst only creates the missing tables, so this stays in
sync with the ORM metadata.

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11
"""

from alembic import op
import sqlalchemy as sa

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

NEW_TABLES = ["nfl_schedule", "injury_events", "recommendations"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in reversed(NEW_TABLES):
        op.drop_table(table)

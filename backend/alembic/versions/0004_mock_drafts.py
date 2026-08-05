"""Mock drafts: mock_drafts and mock_draft_picks.

Revision ID: 0004
Revises: 0003
Create Date: 2026-08-05
"""

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

NEW_TABLES = ["mock_draft_picks", "mock_drafts"]


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind(), checkfirst=True)


def downgrade() -> None:
    for table in NEW_TABLES:  # picks first — it has the FK
        op.drop_table(table)

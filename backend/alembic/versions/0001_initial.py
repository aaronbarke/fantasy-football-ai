"""Initial schema — created from ORM metadata so it can't drift from the models.

Revision ID: 0001
Revises:
Create Date: 2026-06-11
"""

from alembic import op

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.create_all(bind=op.get_bind())


def downgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    Base.metadata.drop_all(bind=op.get_bind())

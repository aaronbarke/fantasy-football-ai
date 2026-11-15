"""Win-probability history: matchup_odds.player_proj.

Each snapshot keeps the starters' projections and injury statuses, so the
rebuilt chart can show an injury designation as a named drop at the moment it
landed. Prod adds it on boot via app.database.add_missing_columns.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0011"
down_revision = "0010"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("matchup_odds")}
    if "player_proj" not in cols:
        op.add_column("matchup_odds", sa.Column("player_proj", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("matchup_odds", "player_proj")

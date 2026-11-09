"""Win-probability swing attribution: matchup_odds.player_points + changes.

Each snapshot keeps the starters' live points so the next one can record whose
points moved, which labels the big swings on the Matchup chart. Prod adds them
on boot via app.database.add_missing_columns (create_all never ALTERs a table).

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None

_JSON = sa.JSON().with_variant(JSONB(), "postgresql")


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("matchup_odds")}
    if "player_points" not in cols:
        op.add_column("matchup_odds", sa.Column("player_points", _JSON, nullable=True))
    if "changes" not in cols:
        op.add_column("matchup_odds", sa.Column("changes", _JSON, nullable=True))


def downgrade() -> None:
    op.drop_column("matchup_odds", "changes")
    op.drop_column("matchup_odds", "player_points")

"""Track-record calibration: projection_snapshots.calibration_adj.

The points the per-position calibration added to a saved projection, so later
bias is measured on the uncalibrated number. Prod adds it on boot via
app.database.add_missing_columns (create_all never ALTERs an existing table).

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-04
"""

import sqlalchemy as sa
from alembic import op

revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    cols = {c["name"] for c in sa.inspect(op.get_bind()).get_columns("projection_snapshots")}
    if "calibration_adj" not in cols:
        op.add_column("projection_snapshots", sa.Column("calibration_adj", sa.Float(), nullable=True))


def downgrade() -> None:
    op.drop_column("projection_snapshots", "calibration_adj")

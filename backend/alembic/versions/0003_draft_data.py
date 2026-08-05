"""Draft data: player_draft_profiles, player_news, and players.fp_id.

create_all with checkfirst only creates the missing tables, so this stays in
sync with the ORM metadata.

New *columns* on an existing table are invisible to create_all, so players.fp_id
is added explicitly — but 0001 builds the schema from live ORM metadata, which
means a database created *after* fp_id was added to the model already has the
column. Both paths have to work, so the add is guarded by an inspector check.

Revision ID: 0003
Revises: 0002
Create Date: 2026-08-04
"""

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

NEW_TABLES = ["player_draft_profiles", "player_news"]
FP_INDEX = "ix_players_fp_id"


def _has_column(bind, table: str, column: str) -> bool:
    return column in {c["name"] for c in sa.inspect(bind).get_columns(table)}


def _has_index(bind, table: str, index: str) -> bool:
    return index in {i["name"] for i in sa.inspect(bind).get_indexes(table)}


def upgrade() -> None:
    from app.database import Base
    from app import models  # noqa: F401

    bind = op.get_bind()
    if not _has_column(bind, "players", "fp_id"):
        op.add_column("players", sa.Column("fp_id", sa.String(50), nullable=True))
    if not _has_index(bind, "players", FP_INDEX):
        op.create_index(FP_INDEX, "players", ["fp_id"])

    Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    if _has_index(bind, "players", FP_INDEX):
        op.drop_index(FP_INDEX, table_name="players")
    if _has_column(bind, "players", "fp_id"):
        op.drop_column("players", "fp_id")

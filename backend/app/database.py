import logging
from collections.abc import AsyncGenerator

from sqlalchemy import JSON, inspect, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

# JSONB on Postgres, plain JSON elsewhere (sqlite in tests/dev)
JSONVariant = JSON().with_variant(JSONB(), "postgresql")

engine = create_async_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


logger = logging.getLogger(__name__)

# Columns added to a table that already exists in production. ``create_all``
# only creates missing tables — it never ALTERs one — so add these on boot.
# Nullable, so the ALTER is instant and old rows stay valid. (Alembic carries
# the same change for databases that run migrations.)
ADDED_COLUMNS: list[tuple[str, str, str]] = [
    ("projection_snapshots", "calibration_adj", "FLOAT"),
    ("matchup_odds", "player_points", "JSONB"),
    ("matchup_odds", "changes", "JSONB"),
    ("matchup_odds", "player_proj", "JSONB"),
]


def add_missing_columns(sync_conn) -> list[str]:
    """Add any ``ADDED_COLUMNS`` the database doesn't have yet. Idempotent."""
    insp = inspect(sync_conn)
    added = []
    for table, column, ddl in ADDED_COLUMNS:
        if not insp.has_table(table):
            continue
        if column in {c["name"] for c in insp.get_columns(table)}:
            continue
        sync_conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
        added.append(f"{table}.{column}")
    return added


class Base(DeclarativeBase):
    pass


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with SessionLocal() as session:
        yield session


async def create_all() -> None:
    """Dev convenience — production uses Alembic migrations."""
    from app import models  # noqa: F401  ensure models are registered

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with engine.begin() as conn:
            added = await conn.run_sync(add_missing_columns)
        if added:
            logger.info("Added columns: %s", ", ".join(added))
    except Exception:
        logger.exception("Couldn't add new columns; the features that use them will fail")

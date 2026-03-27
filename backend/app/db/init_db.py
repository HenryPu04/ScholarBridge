"""
Database initialisation — called once at application startup.
"""

import logging

from sqlalchemy import text

from app.db.engine import Base, engine
from app.db import models  # noqa: F401 — ensures ORM classes are registered before create_all

logger = logging.getLogger(__name__)

# Additive migrations: each entry is (table, column, DDL fragment).
# Safe to run on every startup — skipped if the column already exists.
_MIGRATIONS: list[tuple[str, str, str]] = [
    ("papers", "ss_paper_id", "ALTER TABLE papers ADD COLUMN ss_paper_id TEXT"),
]


async def create_tables() -> None:
    """Create all tables and apply any pending additive column migrations."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Apply lightweight additive migrations (ADD COLUMN only).
    # SQLite does not support IF NOT EXISTS on ALTER TABLE, so we check
    # the pragma first and skip columns that are already present.
    async with engine.begin() as conn:
        for table, column, ddl in _MIGRATIONS:
            result = await conn.execute(text(f"PRAGMA table_info({table})"))
            existing_columns = {row[1] for row in result.fetchall()}
            if column not in existing_columns:
                await conn.execute(text(ddl))
                logger.info("Migration applied: added column %s.%s", table, column)
            else:
                logger.debug("Migration skipped (already exists): %s.%s", table, column)

    logger.info("Database tables initialised.")

"""
backend/db/database.py
======================
Async SQLAlchemy engine, session maker, declarative base, and database dependencies.
"""

import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import declarative_base

from core.config import settings

# Determine database URL
DATABASE_URL = settings.async_database_url

# Configure engine arguments
engine_kwargs = {"echo": False}
if DATABASE_URL.startswith("sqlite"):
    from sqlalchemy.pool import NullPool

    engine_kwargs["connect_args"] = {"check_same_thread": False}
    engine_kwargs["poolclass"] = NullPool  # file-based SQLite: connect per use, no cross-loop reuse

engine = create_async_engine(DATABASE_URL, **engine_kwargs)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
Base = declarative_base()


async def get_db():
    """FastAPI dependency for async database sessions."""
    async with AsyncSessionLocal() as session:
        yield session


async def init_db():
    """Initialize database tables from SQLAlchemy metadata and ensure schema columns."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        def _migrate_columns(sync_conn):
            from sqlalchemy import text
            try:
                # Check columns in client_profiles
                result = sync_conn.execute(text("PRAGMA table_info(client_profiles)"))
                existing = {row[1] for row in result.fetchall()}
                new_cols = [
                    ("source_of_funds", "TEXT DEFAULT 'salary'"),
                    ("drawdown_reaction", "TEXT DEFAULT 'hold'"),
                    ("monitoring_frequency", "TEXT DEFAULT 'monthly'"),
                    ("pep_status", "BOOLEAN DEFAULT 0"),
                    ("high_risk_jurisdiction", "BOOLEAN DEFAULT 0"),
                ]
                for col_name, col_type in new_cols:
                    if col_name not in existing:
                        sync_conn.execute(text(f"ALTER TABLE client_profiles ADD COLUMN {col_name} {col_type}"))
            except Exception:
                pass

        def _migrate_postgres(sync_conn):
            from sqlalchemy import text
            try:
                sync_conn.execute(text("ALTER TABLE audit_log ALTER COLUMN timestamp TYPE TIMESTAMP WITH TIME ZONE"))
            except Exception:
                pass

        if DATABASE_URL.startswith("sqlite"):
            await conn.run_sync(_migrate_columns)
        elif "postgres" in DATABASE_URL:
            await conn.run_sync(_migrate_postgres)

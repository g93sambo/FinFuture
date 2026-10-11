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
    """Initialize database tables from SQLAlchemy metadata."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

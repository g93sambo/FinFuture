"""
backend/tests/conftest.py
Global test configuration and fixtures.
"""

import os
import sys
import tempfile

# Isolate the test environment BEFORE any application module reads settings:
# throwaway SQLite file, no broker/LLM network calls, simulated paper fills.
_TEST_DB_DIR = tempfile.mkdtemp(prefix="wealth_agent_tests_")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TEST_DB_DIR.replace(os.sep, '/')}/test.db"
os.environ["DRY_RUN"] = "true"
os.environ["OPENAI_API_KEY"] = ""
os.environ["ALPACA_API_KEY"] = ""
os.environ["ALPACA_SECRET_KEY"] = ""
os.environ["REDIS_URL"] = "redis://127.0.0.1:1/0"  # unreachable -> in-memory fallback

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Ensure backend root directory is on sys.path
backend_root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if backend_root not in sys.path:
    sys.path.insert(0, backend_root)

from db.database import Base
import db.models  # ensure models and listeners are loaded


@pytest_asyncio.fixture
async def db_engine():
    """Provides an isolated in-memory SQLite engine with all tables created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        echo=False,
        connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(db_engine):
    """Provides an isolated AsyncSession bound to the in-memory engine."""
    session_factory = async_sessionmaker(
        db_engine,
        class_=AsyncSession,
        expire_on_commit=False
    )
    async with session_factory() as session:
        yield session

"""
Adversarial Stress Test Suite for Milestone 1 Foundation (Extended).
"""

import asyncio
import os
import time
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import text

from services.cache import (
    InMemoryCache,
    CacheService,
    key_trade_lock,
)
from services.audit_logger import (
    AuditLogger,
    log_audit_entry,
    verify_audit_chain,
    compute_entry_hash,
    compute_hmac_signature,
    canonicalize_details,
    canonicalize_timestamp,
    GENESIS_HASH,
)
from db.database import Base
import db.models


@pytest_asyncio.fixture
async def adv_db_engine(tmp_path):
    db_file = tmp_path / "adv_test.db"
    db_url = f"sqlite+aiosqlite:///{db_file}"
    engine = create_async_engine(
        db_url,
        echo=False,
        connect_args={"check_same_thread": False, "timeout": 60.0}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def adv_session_factory(adv_db_engine):
    return async_sessionmaker(adv_db_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_lock_hijacking_on_delayed_release():
    """
    VULNERABILITY PROBE:
    Process A acquires lock with 0.1s timeout.
    Process A takes 0.12s (lock expires).
    Process B acquires the expired lock (valid for 0.5s).
    Process A finishes and calls release_lock().
    Process C attempts to acquire the lock immediately.
    """
    cache = InMemoryCache()
    lock_key = "lock:trade:hijack_test"

    acquired_a = await cache.acquire_lock(lock_key, timeout_seconds=0.1)
    assert acquired_a is True

    await asyncio.sleep(0.12)

    acquired_b = await cache.acquire_lock(lock_key, timeout_seconds=0.5)
    assert acquired_b is True

    await cache.release_lock(lock_key)

    acquired_c = await cache.acquire_lock(lock_key, timeout_seconds=0.5)
    # Documents that release_lock is unowned
    assert acquired_c is True


@pytest.mark.asyncio
async def test_audit_log_100_concurrent_writes_same_client(adv_session_factory):
    """
    STRESS TEST:
    100 concurrent coroutines attempting to write to the SAME client's audit log.
    Tests whether serialization holds under 100 coroutines, no chain forks occur,
    and all 100 entries verify in sequence.
    """
    client_id = "stress-client-100-concurrent"
    logger = AuditLogger()

    async def log_task(task_id: int):
        async with adv_session_factory() as session:
            return await logger.log_audit_entry(
                db=session,
                client_id=client_id,
                event_type=f"EVENT_{task_id}",
                actor="ACTOR",
                details={"step": task_id},
                status="PASS"
            )

    tasks = [log_task(i) for i in range(100)]
    entries = await asyncio.gather(*tasks)
    assert len(entries) == 100

    async with adv_session_factory() as verify_session:
        is_valid, corrupted_id = await logger.verify_audit_chain(verify_session, client_id)
        assert is_valid is True, f"100-entry concurrent chain failed verification! Corrupted ID: {corrupted_id}"
        assert corrupted_id is None


@pytest.mark.asyncio
async def test_cache_200_extreme_concurrency():
    cache = InMemoryCache()
    lock_key = "lock:trade:extreme_200"

    tasks = [cache.acquire_lock(lock_key, timeout_seconds=30) for _ in range(200)]
    results = await asyncio.gather(*tasks)

    winners = [r for r in results if r is True]
    assert len(winners) == 1, f"Expected exactly 1 winner out of 200, got {len(winners)}"


def test_canonicalize_details_complex_nesting():
    payload_a = {"z": 1, "a": 2, "m": {"sub_z": "val", "sub_a": "val2", "list": [3, 2, 1]}}
    payload_b = {"a": 2, "m": {"list": [3, 2, 1], "sub_a": "val2", "sub_z": "val"}, "z": 1}

    canon_a = canonicalize_details(payload_a)
    canon_b = canonicalize_details(payload_b)

    assert canon_a == canon_b

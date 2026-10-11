"""
Unit tests for backend/services/cache.py
Testing CacheService, in-memory TTL fallback, distributed/in-memory lock behavior, and key helpers.
"""

import asyncio
import pytest
from services.cache import (
    CacheService,
    key_quote,
    key_ohlcv,
    key_holdings,
    key_macro,
    key_treasury,
    key_trade_lock,
    key_profile_draft,
    key_session,
    TTL_QUOTES,
    TTL_TRADE_LOCK,
)


@pytest.fixture
def cache():
    # Fresh CacheService with invalid Redis URL to guarantee in-memory fallback testing
    service = CacheService(redis_url="redis://localhost:9999/0")
    return service


@pytest.mark.asyncio
async def test_cache_get_set_delete(cache):
    # Set and Get
    assert await cache.set("test:key1", "value1") is True
    assert await cache.get("test:key1") == "value1"

    # Exists
    assert await cache.exists("test:key1") is True
    assert await cache.exists("nonexistent:key") is False

    # Delete
    assert await cache.delete("test:key1") is True
    assert await cache.get("test:key1") is None
    assert await cache.exists("test:key1") is False


@pytest.mark.asyncio
async def test_cache_ttl_expiration(cache):
    # Set with 1s expiration
    assert await cache.set("test:expiring", "temporary", expire=1) is True
    assert await cache.get("test:expiring") == "temporary"

    await asyncio.sleep(1.1)
    assert await cache.get("test:expiring") is None


@pytest.mark.asyncio
async def test_cache_json_helpers(cache):
    data = {"symbols": ["AAPL", "MSFT"], "count": 2, "active": True}
    assert await cache.set_json("test:json", data) is True

    retrieved = await cache.get_json("test:json")
    assert retrieved == data
    assert retrieved["symbols"] == ["AAPL", "MSFT"]

    # Non-existent returns None
    assert await cache.get_json("test:missing_json") is None


@pytest.mark.asyncio
async def test_acquire_and_release_lock(cache):
    lock_key = "lock:trade:client-100"

    # 1. Acquire lock successfully
    assert await cache.acquire_lock(lock_key, timeout_seconds=30) is True

    # 2. Duplicate acquire while held returns False (rejects double submit)
    assert await cache.acquire_lock(lock_key, timeout_seconds=30) is False

    # 3. Release lock
    assert await cache.release_lock(lock_key) is True

    # 4. Acquire again succeeds
    assert await cache.acquire_lock(lock_key, timeout_seconds=30) is True


@pytest.mark.asyncio
async def test_lock_timeout_expiration(cache):
    lock_key = "lock:trade:client-200"

    # Acquire lock with 1s timeout
    assert await cache.acquire_lock(lock_key, timeout_seconds=1) is True
    assert await cache.acquire_lock(lock_key, timeout_seconds=1) is False

    # Wait for lock to expire automatically
    await asyncio.sleep(1.1)
    assert await cache.acquire_lock(lock_key, timeout_seconds=1) is True


def test_standard_key_helpers():
    assert key_quote("aapl") == "data:quotes:AAPL"
    assert key_ohlcv("yfinance", "vti", "1d") == "data:yfinance:VTI:1d"
    assert key_holdings("spy") == "data:holdings:SPY"
    assert key_macro("GDP") == "data:macro:gdp"
    assert key_treasury() == "data:treasury:yield_curve"
    assert key_trade_lock("client_123") == "lock:trade:client_123"
    assert key_profile_draft("sess_456") == "profile:draft:sess_456"
    assert key_session("sess_789") == "session:sess_789"
    assert TTL_QUOTES == 30
    assert TTL_TRADE_LOCK == 30


@pytest.mark.asyncio
async def test_cache_clear_and_close(cache):
    from services.cache import get_cache_service

    await cache.set("key_to_clear", "val")
    assert await cache.exists("key_to_clear") is True
    await cache.clear()
    assert await cache.exists("key_to_clear") is False

    assert cache.is_redis_online is False
    await cache.close()

    singleton = get_cache_service()
    assert singleton is not None

"""
backend/services/cache.py
=========================
Dual-backend cache service supporting Redis and transparent in-memory TTL fallback.
"""

import os
import time
import json
import asyncio
import logging
from typing import Optional, Any, Dict, Tuple

try:
    import redis.asyncio as aioredis
    from redis.exceptions import RedisError, ConnectionError as RedisConnError, TimeoutError as RedisTimeoutError
    HAS_REDIS = True
except ImportError:
    HAS_REDIS = False
    RedisError = Exception
    RedisConnError = Exception
    RedisTimeoutError = Exception

logger = logging.getLogger(__name__)

# --- Standard TTL Constants (seconds) ---
TTL_QUOTES: int = 30           # Live market quotes (30s)
TTL_TRADE_LOCK: int = 30       # Trade double-submit prevention lock (30s)
TTL_PROFILE_DRAFT: int = 3600  # Risk profiler draft state (1h)
TTL_HOLDINGS: int = 21600      # ETF / Portfolio holdings (6h)
TTL_TREASURY: int = 43200      # US Treasury yield curve (12h)
TTL_OHLCV: int = 86400         # Daily OHLCV price history (24h)
TTL_MACRO: int = 86400         # Macro economic indicators (24h)
TTL_SESSION: int = 86400       # User chat / advisory session (24h)


# --- Standard Key Formatters ---
def key_quote(symbol: str) -> str:
    return f"data:quotes:{symbol.upper()}"


def key_ohlcv(source: str, symbol: str, timeframe: str) -> str:
    return f"data:{source}:{symbol.upper()}:{timeframe}"


def key_holdings(symbol: str) -> str:
    return f"data:holdings:{symbol.upper()}"


def key_macro(indicator: str) -> str:
    return f"data:macro:{indicator.lower()}"


def key_treasury() -> str:
    return "data:treasury:yield_curve"


def key_trade_lock(client_id: str) -> str:
    return f"lock:trade:{client_id}"


def key_profile_draft(session_id: str) -> str:
    return f"profile:draft:{session_id}"


def key_session(session_id: str) -> str:
    return f"session:{session_id}"


class InMemoryCache:
    """Thread-safe and asyncio-safe in-memory cache with TTL expiration."""

    def __init__(self):
        self._data: Dict[str, Tuple[str, Optional[float]]] = {}
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Optional[str]:
        async with self._lock:
            if key not in self._data:
                return None
            val, expire_at = self._data[key]
            if expire_at is not None and time.time() > expire_at:
                del self._data[key]
                return None
            return val

    async def set(self, key: str, value: str, expire: Optional[int] = None) -> bool:
        async with self._lock:
            expire_at = (time.time() + expire) if expire is not None else None
            self._data[key] = (value, expire_at)
            return True

    async def delete(self, key: str) -> bool:
        async with self._lock:
            self._data.pop(key, None)
            return True

    async def exists(self, key: str) -> bool:
        val = await self.get(key)
        return val is not None

    async def acquire_lock(self, lock_key: str, timeout_seconds: int = 30) -> bool:
        async with self._lock:
            now = time.time()
            if lock_key in self._data:
                _, expire_at = self._data[lock_key]
                if expire_at is None or expire_at > now:
                    return False  # Lock already active
            self._data[lock_key] = ("LOCKED", now + timeout_seconds)
            return True

    async def release_lock(self, lock_key: str) -> bool:
        async with self._lock:
            self._data.pop(lock_key, None)
            return True

    async def clear(self) -> None:
        async with self._lock:
            self._data.clear()


class CacheService:
    """
    Unified Cache & Lock Service.
    Attempts Redis first; falls back transparently to InMemoryCache if Redis is down or unavailable.
    """

    def __init__(self, redis_url: Optional[str] = None):
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")
        self.fallback = InMemoryCache()
        self._redis_client: Optional[Any] = None
        self._redis_available: bool = False
        self._last_redis_check: float = 0.0
        self._reconnect_cooldown: float = 30.0  # seconds between redis reconnection attempts

    async def _init_redis(self) -> bool:
        """Attempt to initialize and ping Redis connection."""
        if not HAS_REDIS or not self.redis_url:
            self._redis_available = False
            return False

        now = time.time()
        if not self._redis_available and (now - self._last_redis_check < self._reconnect_cooldown):
            return False

        self._last_redis_check = now
        try:
            if self._redis_client is None:
                self._redis_client = aioredis.from_url(
                    self.redis_url,
                    socket_connect_timeout=1.0,
                    socket_timeout=1.0,
                    decode_responses=True
                )
            await self._redis_client.ping()
            if not self._redis_available:
                # Log host only: the URL can carry a password (rediss://user:pass@host)
                logger.info("Connected to Redis at %s", self.redis_url.rsplit("@", 1)[-1])
            self._redis_available = True
            return True
        except Exception as e:
            if self._redis_available:
                logger.warning(f"Redis connection lost: {e}. Switching to in-memory fallback.")
            self._redis_available = False
            return False

    @property
    def is_redis_online(self) -> bool:
        return self._redis_available

    async def get(self, key: str) -> Optional[str]:
        if await self._init_redis():
            try:
                return await self._redis_client.get(key)
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis get failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.get(key)

    async def set(self, key: str, value: str, expire: Optional[int] = None) -> bool:
        if await self._init_redis():
            try:
                if expire is not None:
                    await self._redis_client.set(key, value, ex=expire)
                else:
                    await self._redis_client.set(key, value)
                return True
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis set failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.set(key, value, expire=expire)

    async def delete(self, key: str) -> bool:
        if await self._init_redis():
            try:
                await self._redis_client.delete(key)
                return True
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis delete failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.delete(key)

    async def exists(self, key: str) -> bool:
        if await self._init_redis():
            try:
                res = await self._redis_client.exists(key)
                return bool(res)
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis exists failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.exists(key)

    async def acquire_lock(self, lock_key: str, timeout_seconds: int = 30) -> bool:
        """
        Acquire a mutual-exclusion lock.
        Returns True if the lock was acquired, False if already held.
        """
        if await self._init_redis():
            try:
                acquired = await self._redis_client.set(
                    lock_key, "1", nx=True, ex=timeout_seconds
                )
                return bool(acquired)
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis acquire_lock failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.acquire_lock(lock_key, timeout_seconds=timeout_seconds)

    async def release_lock(self, lock_key: str) -> bool:
        """Release the mutual-exclusion lock."""
        if await self._init_redis():
            try:
                await self._redis_client.delete(lock_key)
                return True
            except (RedisConnError, RedisTimeoutError, RedisError) as e:
                logger.warning(f"Redis release_lock failed ({e}), falling back to memory.")
                self._redis_available = False
        return await self.fallback.release_lock(lock_key)

    # --- JSON Helper Utilities ---
    async def get_json(self, key: str) -> Optional[Any]:
        raw = await self.get(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except Exception:
            return None

    async def set_json(self, key: str, value: Any, expire: Optional[int] = None) -> bool:
        payload = json.dumps(value, default=str)
        return await self.set(key, payload, expire=expire)

    async def clear(self) -> None:
        """Clear memory cache and redis db (used primarily for tests)."""
        await self.fallback.clear()
        if self._redis_available and self._redis_client is not None:
            try:
                await self._redis_client.flushdb()
            except Exception:
                pass

    async def close(self) -> None:
        """Gracefully close the redis connection."""
        if self._redis_client is not None:
            try:
                await self._redis_client.aclose()
            except Exception:
                pass


# Global singleton instance
_cache_instance: Optional[CacheService] = None


def get_cache_service() -> CacheService:
    global _cache_instance
    if _cache_instance is None:
        _cache_instance = CacheService()
    return _cache_instance

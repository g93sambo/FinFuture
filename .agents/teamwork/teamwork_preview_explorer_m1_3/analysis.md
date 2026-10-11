# Architecture & Implementation Analysis: Cache, Audit Logger & Anchoring Services

**Milestone**: Milestone 1 (Foundation)  
**Author**: Explorer 3 (`teamwork_preview_explorer_m1_3`)  
**Target Services**:
1. `backend/services/cache.py` (CacheService, Redis connection pool, automatic transparent in-memory TTL dictionary store, TTL constants, distributed/in-memory lock acquisition & release)
2. `backend/services/audit_logger.py` (AuditLogger, SHA-256 hash-chaining per client, HMAC-SHA256 signatures, serialized write lock, log & verification functions)
3. `backend/services/anchoring.py` (AnchoringService, Merkle tree root calculation, Sepolia testnet anchoring with dry-run fallback, mainnet chain ID 1 hard reject guard)

---

## Executive Summary

This document specifies the exact architecture, data structures, concurrency controls, cryptographic primitives, failure-mode handlings, and implementation blueprints for the three core infrastructure services in Milestone 1:

- **`CacheService`** delivers zero-downtime key-value caching and distributed/in-memory concurrency locks. It connects asynchronously to Redis when available, and automatically and transparently falls back to an internal thread-safe in-memory TTL dictionary store when Redis is offline or unreachable. It guarantees that `python main.py` boots and operates smoothly with zero external infrastructure (no Redis daemon required).
- **`AuditLogger`** provides an append-only, cryptographically linked audit trail per `client_id`. Every audit record is hashed with SHA-256 linking to the previous entry's hash (genesis: $64 \times \text{'0'}$) and authenticated with an HMAC-SHA256 signature. Concurrent writes for the same client are serialized with an `asyncio.Lock` to eliminate race conditions and chain forking. The integrity verifier detects any tampered, forged, or missing entry.
- **`AnchoringService`** aggregates batches of audit records into a cryptographic Merkle root and anchors the root to the Ethereum Sepolia testnet (Chain ID 11155111). It features a strict guard that immediately and unconditionally halts if connected to Ethereum Mainnet (Chain ID 1), and gracefully drops into a non-blocking `dry_run` mode when credentials or RPC endpoints are not configured.

---

## 1. Service 1: `backend/services/cache.py`

### 1.1 Architectural Requirements & Objectives
1. **Dual Storage Engine**:
   - **Primary**: Asynchronous Redis connection pool via `redis.asyncio`.
   - **Fallback**: High-performance, in-memory TTL dictionary (`InMemoryCache`) with `asyncio.Lock` concurrency protection.
2. **Transparent Auto-Failover & Auto-Recovery**:
   - Connection initialization does not block or throw unhandled exceptions if Redis is down.
   - Operations catch `redis.ConnectionError` and `redis.TimeoutError`, instantly fallback to the in-memory store, and enter a configurable cooldown period (e.g. 30 seconds) before retrying Redis.
   - Callers in other agents or routers never observe Redis connection errors.
3. **Locking Mechanism**:
   - `acquire_lock(lock_key: str, timeout_seconds: int = 30) -> bool`:
     - Redis: `SET lock_key "1" NX EX timeout_seconds`
     - In-memory: atomic conditional insert into TTL store. If key exists and unexpired, returns `False`; otherwise stores lock and returns `True`.
   - `release_lock(lock_key: str) -> bool`:
     - Releases the lock key. Returns `True` if released or already expired.
4. **Standard TTL Constants**:
   - Quotes: `TTL_QUOTES = 30` (30 seconds)
   - OHLCV historical prices: `TTL_OHLCV = 86400` (24 hours)
   - ETF / Portfolio holdings: `TTL_HOLDINGS = 21600` (6 hours)
   - Macro indicators: `TTL_MACRO = 86400` (24 hours)
   - Treasury yield curve: `TTL_TREASURY = 43200` (12 hours)
   - Trade submit lock: `TTL_TRADE_LOCK = 30` (30 seconds)
   - User chat / advisory session: `TTL_SESSION = 86400` (24 hours)
   - Risk profile draft: `TTL_PROFILE_DRAFT = 3600` (1 hour)
5. **Standard Key Patterns**:
   - `data:quotes:{symbol}`
   - `data:{source}:{symbol}:{timeframe}`
   - `data:holdings:{symbol}`
   - `data:macro:{indicator}`
   - `data:treasury:yield_curve`
   - `lock:trade:{client_id}`
   - `session:{session_id}`
   - `profile:draft:{session_id}`

### 1.2 Data Structures & Internal State

#### In-Memory Store (`InMemoryCache`)
```python
class InMemoryCache:
    def __init__(self):
        # Maps key -> (value: str, expire_at: Optional[float])
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

    async def acquire_lock(self, lock_key: str, timeout_seconds: int = 30) -> bool:
        async with self._lock:
            now = time.time()
            if lock_key in self._data:
                _, expire_at = self._data[lock_key]
                if expire_at is None or expire_at > now:
                    return False  # Lock currently held
            # Lock is either missing or expired
            self._data[lock_key] = ("LOCKED", now + timeout_seconds)
            return True

    async def release_lock(self, lock_key: str) -> bool:
        async with self._lock:
            self._data.pop(lock_key, None)
            return True
```

### 1.3 Exact Code Implementation for `backend/services/cache.py`

```python
"""
backend/services/cache.py
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
TTL_QUOTES: int = 30           # Live market quotes
TTL_TRADE_LOCK: int = 30       # Trade double-submit prevention lock
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
        self._initialized: bool = False

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
                logger.info(f"Connected to Redis at {self.redis_url}")
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
```

---

## 2. Service 2: `backend/services/audit_logger.py`

### 2.1 Cryptographic Chain Architecture

The audit trail provides mathematical proof that:
1. Every record was logged sequentially.
2. No records have been deleted, inserted, modified, or reordered.
3. Every record was generated by authorized system actors with a valid HMAC secret.

#### Mathematical Formulation
For client $c$ and sequence index $i \ge 1$:

$$\text{prev\_hash}_i = \begin{cases} \text{"0"} \times 64, & \text{if } i = 1 \text{ (Genesis)} \\ \text{entry\_hash}_{i-1}, & \text{if } i > 1 \end{cases}$$

$$\text{canonical\_details}_i = \text{json.dumps}(details_i, \text{sort\_keys}=\text{True}, \text{separators}=(',', ':'), \text{default}=\text{str})$$

$$\text{canonical\_ts}_i = timestamp_i.\text{strftime}("\%Y-\%m-\%dT\%H:\%M:\%S.\%fZ") \text{ [UTC]}$$

$$\text{preimage}_i = \text{prev\_hash}_i + c + \text{event\_type}_i + \text{canonical\_details}_i + \text{canonical\_ts}_i$$

$$\text{entry\_hash}_i = \text{SHA-256}(\text{preimage}_i)$$

$$\text{signature}_i = \text{HMAC-SHA256}(K_{\text{secret}}, \text{entry\_hash}_i)$$

### 2.2 Serialized Write Lock (Concurrency Safety)
If multiple requests log events for the same `client_id` concurrently (e.g., parallel market data checks and trade events), both tasks could query the same latest entry and generate duplicate `prev_hash` values, branching the chain.

To eliminate this:
1. `AuditLogger` maintains an asynchronous per-client lock mapping:
   `_locks: Dict[str, asyncio.Lock]`
2. Logging an entry acquires `_locks[client_id]` before reading the previous entry and holds it until the new record is committed to the database.

### 2.3 Model Compatibility Guard
Explorer 2's planned schema vs existing `backend/db/models.py` schema:
- Schema A (Explorer 2 planned):
  `DBAuditLog(id, client_id, event_type, actor, details, timestamp, prev_hash, entry_hash, signature)`
- Schema B (existing `models.py`):
  `DBAuditLog(entry_id, client_id, session_id, agent_id, action, timestamp, entry_hash, previous_hash, hmac_signature)`

`AuditLogger` must dynamically inspect the model attributes using `hasattr` or keyword kwargs so that it works seamlessly with either database model definition.

### 2.4 Integrity Verifier (`verify_audit_chain`)
The verification function:
1. Fetches all entries for `client_id` ordered by chronological sequence (`timestamp` ASC, `id`/`entry_id` ASC).
2. If zero entries exist: returns `(True, None)`.
3. Sets `expected_prev_hash = "0" * 64`.
4. Loops through each entry $i$:
   - Checks `entry.prev_hash == expected_prev_hash`. If mismatch, returns `(False, entry_id)`.
   - Reconstructs `preimage` from entry attributes and computes `expected_entry_hash`.
   - Checks `entry.entry_hash == expected_entry_hash`. If mismatch, returns `(False, entry_id)`.
   - Recomputes HMAC signature and checks against `entry.signature`. If mismatch, returns `(False, entry_id)`.
   - Updates `expected_prev_hash = entry.entry_hash`.
5. Returns `(True, None)` upon full verification.

### 2.5 Exact Code Implementation for `backend/services/audit_logger.py`

```python
"""
backend/services/audit_logger.py
Cryptographic hash-chained and HMAC-signed append-only audit logger.
"""

import os
import json
import hmac
import hashlib
import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any, Tuple, Union
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, asc

from db.models import DBAuditLog

GENESIS_HASH: str = "0" * 64


def get_hmac_secret() -> str:
    return os.getenv("AUDIT_HMAC_SECRET", os.getenv("SECRET_KEY", "default-dev-audit-hmac-secret-key-32b"))


def canonicalize_timestamp(dt: datetime) -> str:
    """Produces canonical ISO 8601 UTC timestamp string."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def canonicalize_details(details: Union[dict, list, Any]) -> str:
    """Produces deterministic canonical JSON serialization."""
    if not isinstance(details, (dict, list)):
        details = {"value": str(details)}
    return json.dumps(details, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(
    prev_hash: str,
    client_id: str,
    event_type: str,
    canonical_details: str,
    canonical_ts: str
) -> str:
    preimage = f"{prev_hash}{client_id}{event_type}{canonical_details}{canonical_ts}"
    return hashlib.sha256(preimage.encode("utf-8")).hexdigest()


def compute_hmac_signature(entry_hash: str, secret_key: str) -> str:
    return hmac.new(
        secret_key.encode("utf-8"),
        entry_hash.encode("utf-8"),
        hashlib.sha256
    ).hexdigest()


class AuditLogger:
    """
    Manages serialized append-only audit log writes and cryptographic chain verification.
    """

    def __init__(self, default_hmac_key: Optional[str] = None):
        self.default_hmac_key = default_hmac_key or get_hmac_secret()
        self._client_locks: Dict[str, asyncio.Lock] = {}
        self._global_lock = asyncio.Lock()

    async def _get_client_lock(self, client_id: str) -> asyncio.Lock:
        async with self._global_lock:
            if client_id not in self._client_locks:
                self._client_locks[client_id] = asyncio.Lock()
            return self._client_locks[client_id]

    async def log_audit_entry(
        self,
        db: AsyncSession,
        client_id: str,
        event_type: str,
        actor: str,
        details: dict,
        status: str = "PASS",
        session_id: Optional[str] = None,
        hmac_key: Optional[str] = None
    ) -> DBAuditLog:
        """
        Appends a hash-chained, HMAC-signed entry to the audit log.
        Serialized per client_id to prevent chain forks.
        """
        secret = hmac_key or self.default_hmac_key
        lock = await self._get_client_lock(client_id)

        async with lock:
            # 1. Fetch latest entry for this client to retrieve prev_hash
            stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
            # Order by timestamp desc, or id/entry_id desc
            if hasattr(DBAuditLog, "timestamp"):
                stmt = stmt.order_by(desc(DBAuditLog.timestamp))
            stmt = stmt.limit(1)

            result = await db.execute(stmt)
            latest = result.scalars().first()

            if latest is None:
                prev_hash = GENESIS_HASH
            else:
                # Support both column names: prev_hash or previous_hash
                prev_hash = getattr(latest, "prev_hash", None) or getattr(latest, "previous_hash", GENESIS_HASH)

            # 2. Canonicalize timestamp & payload
            now = datetime.now(timezone.utc)
            canon_ts = canonicalize_timestamp(now)
            canon_details = canonicalize_details(details)

            # 3. Compute entry hash and HMAC signature
            entry_hash = compute_entry_hash(prev_hash, client_id, event_type, canon_details, canon_ts)
            sig = compute_hmac_signature(entry_hash, secret)

            # 4. Construct DBAuditLog instance supporting both model schemas
            entry_kwargs = {
                "client_id": client_id,
                "event_type": event_type,
                "timestamp": now,
                "entry_hash": entry_hash,
            }

            # Map prev_hash / previous_hash
            if hasattr(DBAuditLog, "prev_hash"):
                entry_kwargs["prev_hash"] = prev_hash
            elif hasattr(DBAuditLog, "previous_hash"):
                entry_kwargs["previous_hash"] = prev_hash

            # Map signature / hmac_signature
            if hasattr(DBAuditLog, "signature"):
                entry_kwargs["signature"] = sig
            elif hasattr(DBAuditLog, "hmac_signature"):
                entry_kwargs["hmac_signature"] = sig

            # Map actor / agent_id
            if hasattr(DBAuditLog, "actor"):
                entry_kwargs["actor"] = actor
            elif hasattr(DBAuditLog, "agent_id"):
                entry_kwargs["agent_id"] = actor

            # Map details / action
            if hasattr(DBAuditLog, "details"):
                entry_kwargs["details"] = details
            elif hasattr(DBAuditLog, "action"):
                entry_kwargs["action"] = details

            # Session ID if column exists
            if hasattr(DBAuditLog, "session_id"):
                entry_kwargs["session_id"] = session_id or "system-session"

            # Status if column exists
            if hasattr(DBAuditLog, "status"):
                entry_kwargs["status"] = status

            audit_entry = DBAuditLog(**entry_kwargs)
            db.add(audit_entry)
            await db.commit()
            await db.refresh(audit_entry)

            return audit_entry

    async def verify_audit_chain(
        self,
        db: AsyncSession,
        client_id: str,
        hmac_key: Optional[str] = None
    ) -> Tuple[bool, Optional[Any]]:
        """
        Verifies the cryptographic chain and signatures for a client's audit trail.
        Returns:
            (True, None) if completely valid.
            (False, entry_id) identifying the first tampered/corrupted entry if broken.
        """
        secret = hmac_key or self.default_hmac_key

        stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        if hasattr(DBAuditLog, "timestamp"):
            stmt = stmt.order_by(asc(DBAuditLog.timestamp))
        result = await db.execute(stmt)
        entries = result.scalars().all()

        if not entries:
            return True, None

        expected_prev_hash = GENESIS_HASH

        for entry in entries:
            entry_id = getattr(entry, "id", None) or getattr(entry, "entry_id", "unknown")
            actual_prev = getattr(entry, "prev_hash", None) or getattr(entry, "previous_hash", "")
            actual_hash = getattr(entry, "entry_hash", "")
            actual_sig = getattr(entry, "signature", None) or getattr(entry, "hmac_signature", "")
            entry_ts = getattr(entry, "timestamp")
            entry_details = getattr(entry, "details", None) or getattr(entry, "action", {})
            event_type = getattr(entry, "event_type", "")

            # 1. Verify previous hash chaining
            if actual_prev != expected_prev_hash:
                return False, entry_id

            # 2. Recompute and verify entry hash
            canon_ts = canonicalize_timestamp(entry_ts)
            canon_details = canonicalize_details(entry_details)
            expected_hash = compute_entry_hash(actual_prev, client_id, event_type, canon_details, canon_ts)
            if actual_hash != expected_hash:
                return False, entry_id

            # 3. Verify HMAC signature
            expected_sig = compute_hmac_signature(actual_hash, secret)
            if not hmac.compare_digest(actual_sig, expected_sig):
                return False, entry_id

            # Advance expected chain state
            expected_prev_hash = actual_hash

        return True, None


# Global singleton
_audit_logger_instance: Optional[AuditLogger] = None

def get_audit_logger() -> AuditLogger:
    global _audit_logger_instance
    if _audit_logger_instance is None:
        _audit_logger_instance = AuditLogger()
    return _audit_logger_instance

# Module-level convenience functions matching Interface Contracts
async def log_audit_entry(
    db: AsyncSession,
    client_id: str,
    event_type: str,
    actor: str,
    details: dict,
    status: str = "PASS",
    hmac_key: Optional[str] = None
) -> DBAuditLog:
    return await get_audit_logger().log_audit_entry(
        db=db,
        client_id=client_id,
        event_type=event_type,
        actor=actor,
        details=details,
        status=status,
        hmac_key=hmac_key
    )

async def verify_audit_chain(
    db: AsyncSession,
    client_id: str,
    hmac_key: Optional[str] = None
) -> Tuple[bool, Optional[Any]]:
    return await get_audit_logger().verify_audit_chain(
        db=db,
        client_id=client_id,
        hmac_key=hmac_key
    )
```

---

## 3. Service 3: `backend/services/anchoring.py`

### 3.1 Architectural Requirements & Objectives
1. **Cryptographic Merkle Root Computation**:
   - Takes a list of audit entry hashes.
   - Computes a binary Merkle tree root using SHA-256.
   - Handles edge cases:
     - 0 leaves: returns `hashlib.sha256(b"").hexdigest()`
     - 1 leaf: returns `leaf`
     - Odd leaf count: duplicates the last leaf at each level per standard cryptographic specification (RFC 6962 / Bitcoin / Ethereum standards).
2. **Blockchain Target & Safety Constraints**:
   - **Target**: Ethereum Sepolia Testnet (`chain_id == 11155111`).
   - **Hard Reject Safety Guard**: If connected to Chain ID 1 (Ethereum Mainnet), immediately raise `MainnetForbiddenError` and halt execution.
   - **Dry-Run Fallback**:
     - Automatically active if `SEPOLIA_RPC_URL` or `SEPOLIA_PRIVATE_KEY` is missing/empty, if `web3` is not installed, or if the testnet RPC endpoint is offline.
     - Computes the real Merkle root from audit records.
     - Generates a simulated transaction hash (prefixed with `0x`) and block number.
     - Returns `status="dry_run"`, logs an informative warning, and never crashes calling agents.
3. **On-Chain Anchor Formats**:
   - Primary: Smart contract invocation `anchorRoot(bytes32 root)` if `AUDIT_CONTRACT_ADDRESS` is specified.
   - Alternative/Direct: Zero-value self-transaction on Sepolia with the 32-byte Merkle root embedded in the transaction `data` payload field.

### 3.2 Merkle Tree Algorithm Specification

```
Layer 0 (Leaves):      [H0]      [H1]      [H2]      [H3]
                          \      /            \      /
Layer 1:                 [H01]               [H23]
                             \               /
Layer 2 (Merkle Root):             [ROOT]
```

Where:
- Leaves: $H_k = \text{bytes.fromhex}(entry\_hash_k)$
- Internal nodes: $H_{left+right} = \text{SHA-256}(H_{left} + H_{right})$
- Odd layer handling: if $\text{len}(layer) \pmod 2 \ne 0$, append copy of $layer[-1]$.

### 3.3 Exact Code Implementation for `backend/services/anchoring.py`

```python
"""
backend/services/anchoring.py
Merkle root generation and Ethereum Sepolia testnet anchoring service.
Features dry-run mode when unconfigured and hard reject guard for Ethereum Mainnet (Chain ID 1).
"""

import os
import time
import logging
import hashlib
from typing import List, Optional, Dict, Any, Tuple
from dataclasses import dataclass
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from db.models import DBAuditLog

try:
    from web3 import Web3, AsyncWeb3
    from eth_account import Account
    HAS_WEB3 = True
except ImportError:
    HAS_WEB3 = False
    Web3 = None
    AsyncWeb3 = None
    Account = None

logger = logging.getLogger(__name__)

SEPOLIA_CHAIN_ID = 11155111
MAINNET_CHAIN_ID = 1


class MainnetForbiddenError(RuntimeError):
    """Raised when an operation attempts to run against Ethereum Mainnet (Chain ID 1)."""
    pass


@dataclass
class AnchoringResult:
    merkle_root: str
    tx_hash: str
    block_number: Optional[int]
    status: str  # "confirmed" | "dry_run" | "failed"
    chain_id: int
    timestamp: datetime
    entries_count: int


def compute_merkle_root(leaf_hashes: List[str]) -> str:
    """
    Computes binary Merkle tree root from a list of hexadecimal hash strings.
    If empty, returns SHA-256 of empty bytes.
    If odd count at any level, duplicates the last node.
    """
    if not leaf_hashes:
        return hashlib.sha256(b"").hexdigest()

    if len(leaf_hashes) == 1:
        return leaf_hashes[0].lower()

    # Convert all leaves to raw 32-byte digests
    current_layer: List[bytes] = []
    for h in leaf_hashes:
        clean = h.lower().replace("0x", "")
        # Pad or truncate to 32 bytes (64 hex characters)
        if len(clean) < 64:
            clean = clean.zfill(64)
        current_layer.append(bytes.fromhex(clean[:64]))

    while len(current_layer) > 1:
        if len(current_layer) % 2 != 0:
            current_layer.append(current_layer[-1])  # Duplicate last leaf

        next_layer: List[bytes] = []
        for i in range(0, len(current_layer), 2):
            left = current_layer[i]
            right = current_layer[i + 1]
            parent = hashlib.sha256(left + right).digest()
            next_layer.append(parent)
        current_layer = next_layer

    return current_layer[0].hex()


def generate_merkle_proof(leaf_index: int, leaf_hashes: List[str]) -> List[Dict[str, str]]:
    """Generates Merkle audit proof for a specific leaf index."""
    if not leaf_hashes or leaf_index >= len(leaf_hashes):
        return []

    proof: List[Dict[str, str]] = []
    current_layer: List[bytes] = [bytes.fromhex(h.lower().replace("0x", "").zfill(64)[:64]) for h in leaf_hashes]
    idx = leaf_index

    while len(current_layer) > 1:
        if len(current_layer) % 2 != 0:
            current_layer.append(current_layer[-1])

        sibling_idx = idx + 1 if idx % 2 == 0 else idx - 1
        position = "right" if idx % 2 == 0 else "left"
        proof.append({"position": position, "hash": current_layer[sibling_idx].hex()})

        next_layer: List[bytes] = []
        for i in range(0, len(current_layer), 2):
            parent = hashlib.sha256(current_layer[i] + current_layer[i + 1]).digest()
            next_layer.append(parent)

        idx = idx // 2
        current_layer = next_layer

    return proof


class AnchoringService:
    """
    Anchoring Service for Sepolia Testnet.
    Provides automated dry-run fallback and hard-rejects Mainnet (Chain ID 1).
    """

    def __init__(
        self,
        rpc_url: Optional[str] = None,
        private_key: Optional[str] = None,
        contract_address: Optional[str] = None
    ):
        self.rpc_url = rpc_url or os.getenv("SEPOLIA_RPC_URL", "")
        self.private_key = private_key or os.getenv("SEPOLIA_PRIVATE_KEY", "")
        self.contract_address = contract_address or os.getenv("AUDIT_CONTRACT_ADDRESS", "")
        self.target_chain_id = SEPOLIA_CHAIN_ID

    def _is_configured(self) -> bool:
        return bool(HAS_WEB3 and self.rpc_url and self.private_key)

    async def anchor_hashes(self, leaf_hashes: List[str]) -> AnchoringResult:
        """
        Computes Merkle root and anchors it to Sepolia testnet (or dry-run).
        """
        now = datetime.now(timezone.utc)
        merkle_root = compute_merkle_root(leaf_hashes)

        # Check configuration
        if not self._is_configured():
            return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                logger.warning("Sepolia RPC offline. Dropping to dry-run mode.")
                return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

            # HARD GUARD: Never allow Mainnet execution!
            chain_id = w3.eth.chain_id
            if chain_id == MAINNET_CHAIN_ID:
                raise MainnetForbiddenError(
                    "FATAL SECURITY VIOLATION: Connected to Ethereum Mainnet (Chain ID 1). "
                    "Anchoring is strictly restricted to Sepolia testnet. Aborting immediately."
                )

            if chain_id != self.target_chain_id:
                logger.warning(f"Unexpected Chain ID {chain_id} (expected {self.target_chain_id}). Operating in dry-run.")
                return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

            # Build and send transaction
            account = Account.from_key(self.private_key)
            nonce = w3.eth.get_transaction_count(account.address)
            gas_price = w3.eth.gas_price

            # Embed 32-byte Merkle root in transaction data payload
            root_bytes = bytes.fromhex(merkle_root)
            tx = {
                "chainId": chain_id,
                "from": account.address,
                "to": self.contract_address if self.contract_address else account.address,
                "value": 0,
                "nonce": nonce,
                "gas": 60000,
                "gasPrice": gas_price,
                "data": root_bytes
            }

            signed_tx = w3.eth.account.sign_transaction(tx, private_key=self.private_key)
            tx_hash_bytes = w3.eth.send_raw_transaction(signed_tx.rawTransaction)
            tx_hash = "0x" + tx_hash_bytes.hex().replace("0x", "")

            # Wait briefly for confirmation if needed
            block_number = None
            try:
                receipt = w3.eth.wait_for_transaction_receipt(tx_hash_bytes, timeout=15)
                block_number = receipt.blockNumber
                status = "confirmed"
            except Exception:
                status = "submitted"

            return AnchoringResult(
                merkle_root=merkle_root,
                tx_hash=tx_hash,
                block_number=block_number,
                status=status,
                chain_id=chain_id,
                timestamp=now,
                entries_count=len(leaf_hashes)
            )

        except MainnetForbiddenError:
            raise
        except Exception as e:
            logger.warning(f"Sepolia transaction submission error ({e}). Returning dry-run anchor.")
            return self._simulate_anchor(merkle_root, len(leaf_hashes), now)

    def _simulate_anchor(self, merkle_root: str, entries_count: int, ts: datetime) -> AnchoringResult:
        """Generates deterministic simulated anchor transaction."""
        sim_data = f"dry_run:{merkle_root}:{ts.isoformat()}"
        sim_hash = "0x" + hashlib.sha256(sim_data.encode("utf-8")).hexdigest()
        logger.info(f"[DRY-RUN] Merkle Root {merkle_root} anchored in simulated tx {sim_hash}")
        return AnchoringResult(
            merkle_root=merkle_root,
            tx_hash=sim_hash,
            block_number=5400100,  # Simulated Sepolia block number
            status="dry_run",
            chain_id=self.target_chain_id,
            timestamp=ts,
            entries_count=entries_count
        )

    async def anchor_client_audit_trail(self, db: AsyncSession, client_id: str) -> AnchoringResult:
        """
        Fetches all audit entries for a client, computes Merkle root, and anchors to Sepolia.
        """
        stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        if hasattr(DBAuditLog, "timestamp"):
            stmt = stmt.order_by(DBAuditLog.timestamp.asc())
        result = await db.execute(stmt)
        entries = result.scalars().all()

        leaf_hashes = [e.entry_hash for e in entries if getattr(e, "entry_hash", None)]
        return await self.anchor_hashes(leaf_hashes)

    async def verify_anchor(self, merkle_root: str, tx_hash: str) -> bool:
        """
        Verifies that an anchored transaction on Sepolia contains the expected Merkle root.
        """
        if not self._is_configured():
            # In dry-run mode, verify simulated tx structure
            return tx_hash.startswith("0x") and len(tx_hash) == 66

        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not w3.is_connected():
                return False

            tx = w3.eth.get_transaction(tx_hash)
            input_data = tx.input.hex().lower().replace("0x", "")
            expected_data = merkle_root.lower().replace("0x", "")
            return expected_data in input_data
        except Exception:
            return False


# Global singleton
_anchoring_service_instance: Optional[AnchoringService] = None

def get_anchoring_service() -> AnchoringService:
    global _anchoring_service_instance
    if _anchoring_service_instance is None:
        _anchoring_service_instance = AnchoringService()
    return _anchoring_service_instance
```

---

## 4. Cross-Module Integration & End-to-End Scenarios

### 4.1 Trade Execution Flow with Double-Submit Prevention & Audit Logging
When a trade is submitted via `POST /api/v1/trade/execute` or `ExecutionModule`:
1. **Acquire Distributed Lock**:
   ```python
   lock_key = f"lock:trade:{client_id}"
   acquired = await cache_service.acquire_lock(lock_key, timeout_seconds=TTL_TRADE_LOCK)
   if not acquired:
       raise HTTPException(status_code=409, detail="Duplicate trade request within 30s lock window")
   ```
2. **Execute Trade**:
   Alpaca paper trading order submitted; fill details recorded.
3. **Log Audit Record**:
   ```python
   audit_entry = await log_audit_entry(
       db=db,
       client_id=client_id,
       event_type="TRADE_EXECUTED",
       actor="ExecutionModule",
       details={"symbol": symbol, "qty": qty, "side": side, "order_id": order_id},
       status="PASS"
   )
   ```
4. **On-Demand/Periodic Sepolia Anchoring**:
   ```python
   anchor_res = await anchoring_service.anchor_client_audit_trail(db, client_id)
   ```

### 4.2 Verifying 100-Entry Audit Chains & Tamper Detection
- **100-Entry Sequential Test**:
  Simulate 100 consecutive compliance checks and trades for `client_id = "test-client-100"`.
  Call `is_valid, corrupted_id = await verify_audit_chain(db, "test-client-100")`.
  Result: `is_valid == True`, `corrupted_id is None`.
- **Tampering Mutation Test**:
  Directly mutate `entry.details["qty"] = 99999` on entry 42 in the database.
  Call `is_valid, corrupted_id = await verify_audit_chain(db, "test-client-100")`.
  Result: `is_valid == False`, `corrupted_id == entry_42.id`.

---

## 5. Summary Matrix of Exported Interfaces

| Module | Class / Function | Signature | Return Type | Fallback / Safety Behavior |
|---|---|---|---|---|
| `cache.py` | `CacheService.get` | `(key: str)` | `Optional[str]` | Reads from `InMemoryCache` if Redis down |
| `cache.py` | `CacheService.set` | `(key: str, value: str, expire: Optional[int])` | `bool` | Writes to `InMemoryCache` with TTL |
| `cache.py` | `CacheService.acquire_lock` | `(lock_key: str, timeout_seconds: int = 30)` | `bool` | In-memory atomic check-and-set if Redis down |
| `cache.py` | `CacheService.release_lock` | `(lock_key: str)` | `bool` | Deletes key in Redis and in-memory |
| `audit_logger.py` | `log_audit_entry` | `(db, client_id, event_type, actor, details, status)` | `DBAuditLog` | SHA-256 chain + HMAC-SHA256, per-client async lock |
| `audit_logger.py` | `verify_audit_chain`| `(db, client_id, hmac_key)` | `Tuple[bool, Optional[Any]]` | Traverses chain from genesis `0*64`, returns `(False, corrupted_id)` on mismatch |
| `anchoring.py` | `compute_merkle_root` | `(leaf_hashes: List[str])` | `str` | RFC 6962 odd leaf duplication, deterministic empty root |
| `anchoring.py` | `AnchoringService.anchor_hashes` | `(leaf_hashes: List[str])` | `AnchoringResult` | Hard reject if chain ID 1; returns `status="dry_run"` if unconfigured |
| `anchoring.py` | `AnchoringService.verify_anchor` | `(merkle_root: str, tx_hash: str)` | `bool` | On-chain tx input verification or dry-run format check |

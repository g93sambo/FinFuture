"""
backend/research/memory.py
==========================
Tenant-Isolated Memory and Stratified TTL Cache Invalidation for Financial Research.

Enforces:
- Strict user-level tenant isolation (prevent cross-user data leakage).
- Stratified TTL caching hierarchy:
    * Real-time Quotes: 60s
    * SEC Filings & Fundamentals: 24h (86,400s)
    * Macro / Treasury Data: 4h (14,400s)
    * Research Reports / Syntheses: 12h (43,200s)
- User Profile Memory, Research Memory, Decision Memory.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("wealth_advisor.research.memory")


class MemoryEntry(BaseModel):
    key: str
    user_id: str
    category: str  # "profile", "research", "decision", "market"
    value: Dict[str, Any]
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


class StratifiedTTL:
    REALTIME_QUOTE = 60
    MACRO_DATA = 14400       # 4 hours
    RESEARCH_SYNTHESIS = 43200  # 12 hours
    SEC_FILING = 86400       # 24 hours
    PROFILE_MEMORY = 604800   # 7 days


class TenantMemoryManager:
    """
    Isolated memory manager providing safe storage and retrieval of research
    artifacts scoped strictly per user_id.
    """

    def __init__(self, cache_service: Optional[Any] = None):
        self.cache = cache_service
        self._local_store: Dict[str, MemoryEntry] = {}

    def _scoped_key(self, user_id: str, key: str) -> str:
        if not user_id:
            raise ValueError("user_id must not be empty for tenant memory isolation.")
        return f"tenant:{user_id}:{key}"

    async def store(
        self,
        user_id: str,
        key: str,
        category: str,
        value: Dict[str, Any],
        ttl_seconds: int = StratifiedTTL.RESEARCH_SYNTHESIS,
    ) -> None:
        """Stores a memory entry with strict user scoping and TTL."""
        scoped = self._scoped_key(user_id, key)
        expires_at = datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds)
        entry = MemoryEntry(
            key=key,
            user_id=user_id,
            category=category,
            value=value,
            expires_at=expires_at,
        )
        self._local_store[scoped] = entry

        if self.cache:
            try:
                await self.cache.set(scoped, json.dumps(entry.model_dump(mode="json")), ttl_seconds)
            except Exception as exc:
                logger.warning("Cache write error: %s", exc)

    async def retrieve(self, user_id: str, key: str) -> Optional[Dict[str, Any]]:
        """Retrieves a memory entry, verifying tenant ownership and freshness."""
        scoped = self._scoped_key(user_id, key)

        if self.cache:
            try:
                cached = await self.cache.get(scoped)
                if cached:
                    data = json.loads(cached)
                    entry = MemoryEntry(**data)
                    if entry.user_id != user_id:
                        logger.error("Tenant isolation violation detected! Blocked access.")
                        return None
                    return entry.value
            except Exception as exc:
                logger.warning("Cache read error: %s", exc)

        entry = self._local_store.get(scoped)
        if not entry:
            return None

        # Check tenant isolation
        if entry.user_id != user_id:
            logger.error("Tenant isolation violation detected! Blocked access.")
            return None

        # Check freshness
        if entry.expires_at and datetime.now(timezone.utc) > entry.expires_at:
            del self._local_store[scoped]
            return None

        return entry.value

    async def invalidate(self, user_id: str, key: str) -> None:
        """Invalidates a memory key for the authorized user."""
        scoped = self._scoped_key(user_id, key)
        self._local_store.pop(scoped, None)
        if self.cache:
            try:
                await self.cache.delete(scoped)
            except Exception:
                pass

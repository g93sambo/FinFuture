"""
backend/services/audit_logger.py
================================
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

from core.config import settings
from db.models import DBAuditLog

GENESIS_HASH: str = "0" * 64


def get_hmac_secret() -> str:
    return settings.audit_secret_key or os.getenv("AUDIT_SECRET_KEY", "default-dev-audit-hmac-secret-key-32b")


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
        # Ensure all nested values in details (e.g. datetime objects) are JSON-serializable
        details = json.loads(json.dumps(details, default=str))
        lock = await self._get_client_lock(client_id)

        async with lock:
            # 1. Fetch latest entry for this client to retrieve prev_hash
            stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
            if hasattr(DBAuditLog, "timestamp"):
                stmt = stmt.order_by(desc(DBAuditLog.timestamp))
            stmt = stmt.limit(1)

            result = await db.execute(stmt)
            latest = result.scalars().first()

            if latest is None:
                prev_hash = GENESIS_HASH
            else:
                prev_hash = getattr(latest, "entry_hash", None) or GENESIS_HASH

            # 2. Canonicalize timestamp & payload
            now = datetime.now(timezone.utc)
            canon_ts = canonicalize_timestamp(now)
            canon_details = canonicalize_details(details)

            # 3. Compute entry hash and HMAC signature
            entry_hash = compute_entry_hash(prev_hash, client_id, event_type, canon_details, canon_ts)
            sig = compute_hmac_signature(entry_hash, secret)

            # 4. Construct DBAuditLog instance (ensure naive UTC for PostgreSQL timestamp without time zone)
            db_timestamp = now.replace(tzinfo=None)
            entry_kwargs = {
                "client_id": client_id,
                "event_type": event_type,
                "timestamp": db_timestamp,
                "entry_hash": entry_hash,
            }

            if hasattr(DBAuditLog, "prev_hash"):
                entry_kwargs["prev_hash"] = prev_hash
            elif hasattr(DBAuditLog, "previous_hash"):
                entry_kwargs["previous_hash"] = prev_hash

            if hasattr(DBAuditLog, "signature"):
                entry_kwargs["signature"] = sig
            elif hasattr(DBAuditLog, "hmac_signature"):
                entry_kwargs["hmac_signature"] = sig

            if hasattr(DBAuditLog, "actor"):
                entry_kwargs["actor"] = actor
            elif hasattr(DBAuditLog, "agent_id"):
                entry_kwargs["agent_id"] = actor

            if hasattr(DBAuditLog, "details"):
                entry_kwargs["details"] = details
            elif hasattr(DBAuditLog, "action"):
                entry_kwargs["action"] = details

            if hasattr(DBAuditLog, "session_id"):
                entry_kwargs["session_id"] = session_id or "system-session"

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
        stmt = stmt.execution_options(populate_existing=True)
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

"""Audit routes: cryptographic audit trail inspection, verification, and blockchain anchoring."""

from __future__ import annotations

import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.config import settings
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBAuditLog, DBClientProfile, DBUser
from services.anchoring import compute_merkle_root, generate_merkle_proof, get_anchoring_service, verify_merkle_proof

router = APIRouter(prefix="/api/v1", tags=["audit"])


@router.get("/audit/logs")
async def get_audit_logs(
    limit: int = Query(100, ge=1, le=1000),
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prompt alias for /audit/{client_id}."""
    profile = (
        await db.execute(
            select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
        )
    ).scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Client profile not found. Complete onboarding first.")
    return await get_audit_trail(client_id=profile.client_id, limit=limit, user=user, db=db)


@router.get("/audit/{client_id}")
async def get_audit_trail(
    client_id: str,
    limit: int = Query(100, ge=1, le=1000),
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_client_ownership(user, client_id, db)
    rows = (
        await db.execute(
            select(DBAuditLog).where(DBAuditLog.client_id == client_id).order_by(desc(DBAuditLog.timestamp)).limit(limit)
        )
    ).scalars().all()
    return {
        "client_id": client_id,
        "entries": [
            {
                "entry_id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "event_type": r.event_type,
                "actor": r.actor,
                "status": r.status,
                "details": r.details,
                "entry_hash": r.entry_hash,
                "prev_hash": r.prev_hash,
                "signature": r.signature,
            }
            for r in rows
        ],
    }


@router.get("/audit/{client_id}/verify")
async def verify_audit(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, client_id, db)
    valid, bad_entry = await c.audit.verify_audit_chain(db, client_id)
    return {"client_id": client_id, "valid": valid, "first_invalid_entry": bad_entry}


# Every real anchor is a Sepolia transaction paid from the server wallet, so it is rate limited:
# per client through the shared cache (holds across instances with Redis), and server-wide here.
_recent_anchors: deque[float] = deque()


def _anchor_wait_seconds() -> int:
    """Seconds until the server-wide hourly anchor budget frees up (0 if available)."""
    now = time.time()
    while _recent_anchors and now - _recent_anchors[0] >= 3600:
        _recent_anchors.popleft()
    if len(_recent_anchors) < settings.anchor_max_per_hour:
        return 0
    return int(3600 - (now - _recent_anchors[0])) + 1


def _too_many(detail: str, retry_after: int) -> HTTPException:
    return HTTPException(status_code=429, detail=detail, headers={"Retry-After": str(max(1, retry_after))})


@router.post("/audit/{client_id}/anchor")
async def anchor_audit(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Anchor the Merkle root of this client's audit trail on Sepolia (when a wallet is configured).

    A transaction that was actually sent is recorded as an ``AUDIT_ANCHORED`` audit entry with its
    Etherscan link, so it can be looked up again later.
    """
    await verify_client_ownership(user, client_id, db)

    cooldown_key = f"anchor:cooldown:{client_id}"
    limited = settings.is_anchoring_configured and not settings.dry_run
    if limited:
        wait = _anchor_wait_seconds()
        if wait:
            raise _too_many(f"Anchoring is busy right now. Try again in about {max(1, wait // 60)} minutes.", wait)
        if settings.anchor_cooldown_seconds and not await c.cache.acquire_lock(cooldown_key, settings.anchor_cooldown_seconds):
            minutes = max(1, settings.anchor_cooldown_seconds // 60)
            raise _too_many(
                f"Your audit trail was anchored recently. You can anchor again up to {minutes} minutes after the last one.",
                settings.anchor_cooldown_seconds,
            )

    result = await get_anchoring_service().anchor_client_audit_trail(db, client_id)
    if limited:
        if result.tx_hash:
            _recent_anchors.append(time.time())
        else:
            # Nothing was sent (e.g. RPC error): let the client retry straight away
            await c.cache.release_lock(cooldown_key)
    if result.tx_hash:
        await c.audit.log_audit_entry(
            db=db, client_id=client_id, event_type="AUDIT_ANCHORED", actor=f"USER:{user.id}",
            details={
                "merkle_root": result.merkle_root,
                "tx_hash": result.tx_hash,
                "explorer_url": result.explorer_url,
                "chain_id": result.chain_id,
                "block_number": result.block_number,
                "entries_count": result.entries_count,
                "status": result.status,
            },
        )
    return result.__dict__


@router.get("/audit/{client_id}/merkle-proof/{entry_id}")
async def get_entry_merkle_proof(
    client_id: str,
    entry_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Computes RFC 6962 binary Merkle inclusion proof for a specific audit entry."""
    await verify_client_ownership(user, client_id, db)
    rows = (
        await db.execute(
            select(DBAuditLog).where(DBAuditLog.client_id == client_id).order_by(DBAuditLog.timestamp.asc())
        )
    ).scalars().all()

    leaf_hashes = [r.entry_hash for r in rows if getattr(r, "entry_hash", None)]
    entry_ids = [r.id for r in rows if getattr(r, "entry_hash", None)]

    if entry_id not in entry_ids:
        return {
            "client_id": client_id,
            "entry_id": entry_id,
            "verified": False,
            "leaf_index": -1,
            "total_leaves": len(leaf_hashes),
            "leaf_hash": None,
            "merkle_root": compute_merkle_root(leaf_hashes),
            "proof": [],
        }

    idx = entry_ids.index(entry_id)
    merkle_root = compute_merkle_root(leaf_hashes)
    proof = generate_merkle_proof(idx, leaf_hashes)

    return {
        "client_id": client_id,
        "entry_id": entry_id,
        "verified": verify_merkle_proof(leaf_hashes[idx], proof, merkle_root),
        "leaf_index": idx,
        "total_leaves": len(leaf_hashes),
        "leaf_hash": leaf_hashes[idx],
        "merkle_root": merkle_root,
        "proof": proof,
    }


@router.get("/audit/network/sepolia")
async def get_sepolia_network_status():
    """Whether Sepolia anchoring is configured, plus the RPC's live block height and the anchoring wallet."""
    return get_anchoring_service().get_sepolia_health()



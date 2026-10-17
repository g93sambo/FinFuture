"""Audit routes: cryptographic audit trail inspection, verification, and blockchain anchoring."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBAuditLog, DBUser
from services.anchoring import compute_merkle_root, generate_merkle_proof, get_anchoring_service

router = APIRouter(prefix="/api/v1", tags=["audit"])


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


@router.post("/audit/{client_id}/anchor")
async def anchor_audit(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_client_ownership(user, client_id, db)
    result = await get_anchoring_service().anchor_client_audit_trail(db, client_id)
    return result.__dict__ if hasattr(result, "__dict__") else dict(result)


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
        "verified": True,
        "leaf_index": idx,
        "total_leaves": len(leaf_hashes),
        "leaf_hash": leaf_hashes[idx],
        "merkle_root": merkle_root,
        "proof": proof,
        "chain_id": 11155111,
        "network": "Ethereum Sepolia Testnet",
    }


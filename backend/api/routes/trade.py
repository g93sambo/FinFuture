"""Trade routes: trade proposals, execution gates, order status and history."""

from __future__ import annotations

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.execution_module import SIMULATED_PRICES
from agents.orchestrator import AgentContainer, TradeBlocked
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBClientProfile, DBTrade, DBUser

router = APIRouter(prefix="/api/v1", tags=["trade"])


class TradeProposalRequest(BaseModel):
    client_id: str
    symbol: str = Field(min_length=1, max_length=10)
    side: str
    qty: float = Field(gt=0)
    broker: Optional[str] = Field(default=None, description="alpaca or bamboo")
    currency: Optional[str] = Field(default=None, description="USD or NGN")


class TradeRequest(BaseModel):
    client_id: str
    symbol: Optional[str] = Field(default=None, max_length=10)
    qty: Optional[float] = Field(default=None, gt=0)
    side: Optional[str] = None
    broker: Optional[str] = Field(default=None, description="alpaca or bamboo")
    currency: Optional[str] = Field(default=None, description="USD or NGN")
    user_approved: bool = False
    proposal_id: Optional[str] = None
    mfa_code: Optional[str] = Field(default=None, description="Step-Up 6-digit MFA OTP for Red-Tier trades")
    fiduciary_attested: Optional[bool] = Field(default=None, description="Non-discretionary client suitability attestation")
    autonomous: bool = Field(default=False, description="Tier 5 autonomous execution flag (hard-blocked if True)")


def _status_for(error_type: str) -> int:
    if error_type == "DuplicateTradeError":
        return 409
    if error_type == "ExpiredApprovalError":
        return 400
    return 403


@router.post("/trade/propose")
async def propose_trade(
    req: TradeProposalRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, req.client_id, db)
    proposal = await c.orchestrator.create_trade_proposal(db, req.client_id, req.symbol, req.side, req.qty)
    return {"proposal": proposal, "requires_user_approval": True}


@router.post("/trade/execute")
async def execute_trade(
    req: TradeRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Execute a previously proposed trade (or propose+execute in one call).

    ``user_approved`` MUST be true (non-discretionary, REG-003) and ``autonomous`` MUST be false
    (PERM-TIER-5); otherwise the trade is blocked, audited and a 403 is returned.
    """
    if req.autonomous:
        c.compliance.record_security_incident(
            str(user.id),
            reason="PERM-TIER-5: Attempted autonomous trade execution without human approval.",
            incident_type="AUTONOMOUS_EXECUTION_BLOCKED",
        )
        raise HTTPException(
            status_code=403,
            detail={
                "error": "AutonomousExecutionDisabledError",
                "reason": "PERM-TIER-5: Autonomous trade execution is hard-disabled in code. Every trade requires explicit non-discretionary user approval.",
                "violations": [{"rule_id": "PERM-TIER-5", "severity": "BLOCK", "description": "Autonomous execution disabled."}],
            },
        )
    await verify_client_ownership(user, req.client_id, db)
    proposal_id = req.proposal_id
    if not proposal_id:
        if not (req.symbol and req.side and req.qty):
            raise HTTPException(status_code=422, detail="Provide proposal_id, or symbol + side + qty")
        proposal = await c.orchestrator.create_trade_proposal(db, req.client_id, req.symbol, req.side, req.qty)
        proposal_id = proposal["proposal_id"]

    try:
        events = await c.orchestrator.handle_trade_approval(
            db,
            user.id,
            proposal_id,
            approved=req.user_approved,
            mfa_code=req.mfa_code,
            fiduciary_attested=req.fiduciary_attested,
        )
    except TradeBlocked as blocked:
        raise HTTPException(
            status_code=_status_for(blocked.error_type),
            detail={
                "error": blocked.error_type,
                "reason": blocked.reason,
                "violations": [v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in blocked.violations],
                "proposal_id": proposal_id,
            },
        )
    filled = next((e for e in events if e.get("event") == "trade_filled"), None)
    return {"status": "success", "execution": filled["execution"] if filled else None, "events": events}


def _format_trade_dict(t: DBTrade) -> dict:
    filled_px = t.filled_price if t.filled_price is not None else SIMULATED_PRICES.get(t.symbol, 100.0)
    broker_name = (getattr(t, "broker", None) or "webank").lower()
    order_id = t.alpaca_order_id or getattr(t, "bamboo_order_id", None) or f"{broker_name.upper()}-ORD-{t.id[:8].upper()}"
    created_iso = t.created_at.isoformat() if t.created_at else None
    audit_hash = hashlib.sha256(f"{t.id}:{t.symbol}:{t.qty}:{created_iso}".encode()).hexdigest()
    return {
        "trade_id": t.id,
        "client_id": t.client_id,
        "symbol": t.symbol,
        "side": t.side,
        "qty": t.qty,
        "status": t.status,
        "filled_price": filled_px,
        "broker": broker_name,
        "currency": getattr(t, "currency", "USD"),
        "alpaca_order_id": t.alpaca_order_id,
        "bamboo_order_id": getattr(t, "bamboo_order_id", None),
        "broker_order_id": order_id,
        "clearing_ref": f"CLR-{broker_name.upper()}-{t.id[:8].upper()}",
        "audit_hash": f"0x{audit_hash[:16]}...{audit_hash[-8:]}",
        "full_audit_hash": audit_hash,
        "custody_account": f"{broker_name.upper()}-CUSTODY-01",
        "settlement_cycle": "T+1 (SEC Rule 15c6-1 / Sandbox Instant)",
        "created_at": created_iso,
    }


@router.get("/trade/{order_id}")
async def get_trade_order(
    order_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    trade = (await db.execute(select(DBTrade).where(DBTrade.id == order_id))).scalars().first()
    if not trade:
        raise HTTPException(status_code=404, detail="Trade order not found")
    await verify_client_ownership(user, trade.client_id, db)
    return _format_trade_dict(trade)


@router.get("/trades/{client_id}")
async def list_trades(
    client_id: str,
    limit: int = Query(50, ge=1, le=500),
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await verify_client_ownership(user, client_id, db)
    rows = (
        await db.execute(
            select(DBTrade).where(DBTrade.client_id == client_id).order_by(desc(DBTrade.created_at)).limit(limit)
        )
    ).scalars().all()
    return {
        "client_id": client_id,
        "trades": [_format_trade_dict(t) for t in rows],
    }


@router.get("/trade/orders")
async def list_trade_orders(
    limit: int = Query(50, ge=1, le=500),
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Prompt alias for /trades/{client_id}."""
    profile = (
        await db.execute(
            select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
        )
    ).scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Client profile not found. Complete onboarding first.")
    rows = (
        await db.execute(
            select(DBTrade).where(DBTrade.client_id == profile.client_id).order_by(desc(DBTrade.created_at)).limit(limit)
        )
    ).scalars().all()
    formatted = [_format_trade_dict(t) for t in rows]
    return {
        "client_id": profile.client_id,
        "orders": formatted,
        "trades": formatted,
    }


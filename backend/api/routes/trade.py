"""Trade routes: trade proposals, execution gates, order status and history."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer, TradeBlocked
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBClientProfile, DBTrade, DBUser
from services.otp_service import OTPError

router = APIRouter(prefix="/api/v1", tags=["trade"])


class TradeProposalRequest(BaseModel):
    client_id: str
    symbol: str = Field(min_length=1, max_length=10)
    side: str
    qty: float = Field(gt=0)
    broker: Optional[str] = Field(default=None, description="Ignored: orders always route to Alpaca paper")
    currency: Optional[str] = Field(default=None, description="Ignored: orders are always USD")


class TradeRequest(BaseModel):
    client_id: str
    symbol: Optional[str] = Field(default=None, max_length=10)
    qty: Optional[float] = Field(default=None, gt=0)
    side: Optional[str] = None
    broker: Optional[str] = Field(default=None, description="Ignored: orders always route to Alpaca paper")
    currency: Optional[str] = Field(default=None, description="Ignored: orders are always USD")
    user_approved: bool = False
    proposal_id: Optional[str] = None
    mfa_code: Optional[str] = Field(
        default=None, max_length=12, description="Step-up 6-digit code emailed via POST /trade/{proposal_id}/step-up"
    )
    fiduciary_attested: Optional[bool] = Field(default=None, description="Non-discretionary client suitability attestation")
    autonomous: bool = Field(default=False, description="Tier 5 autonomous execution flag (hard-blocked if True)")


def _status_for(error_type: str) -> int:
    if error_type == "DuplicateTradeError":
        return 409
    if error_type in ("ExpiredApprovalError", "AttestationRequiredError"):
        return 400
    return 403


@router.post("/trade/{proposal_id}/step-up")
async def request_step_up_code(
    proposal_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Email a single-use 6-digit code that authorises one Red-tier proposal (PERM-STEP-UP-MFA).

    Calling again re-sends a fresh code (rate limited) and invalidates the previous one.
    """
    try:
        return await c.orchestrator.request_step_up_code(db, user.id, user.email, proposal_id)
    except OTPError as exc:
        headers = {"Retry-After": str(exc.retry_after)} if exc.retry_after else None
        raise HTTPException(
            status_code=exc.status_code,
            detail={"error": exc.error_type, "reason": exc.reason, "retry_after": exc.retry_after},
            headers=headers,
        )
    except TradeBlocked as blocked:
        raise HTTPException(
            status_code=_status_for(blocked.error_type),
            detail={"error": blocked.error_type, "reason": blocked.reason, "proposal_id": proposal_id},
        )


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
    created_iso = t.created_at.isoformat() if t.created_at else None
    order_id = t.alpaca_order_id or f"ORD-{t.id[:8].upper()}"
    report = t.compliance_report if isinstance(t.compliance_report, dict) else {}
    return {
        "trade_id": t.id,
        "client_id": t.client_id,
        "symbol": t.symbol,
        "side": t.side,
        "qty": t.qty,
        "status": t.status,
        "filled_price": t.filled_price,
        "broker": "alpaca",
        "currency": "USD",
        "alpaca_order_id": t.alpaca_order_id,
        "broker_order_id": order_id,
        # A simulated fill (no Alpaca credentials or DRY_RUN) never reached a broker
        "simulated": bool(report.get("dry_run")) or order_id.startswith("dry-run-"),
        "created_at": created_iso,
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


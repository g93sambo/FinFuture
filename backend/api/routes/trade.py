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
from db.models import DBTrade, DBUser

router = APIRouter(prefix="/api/v1", tags=["trade"])


class TradeProposalRequest(BaseModel):
    client_id: str
    symbol: str = Field(min_length=1, max_length=10)
    side: str
    qty: float = Field(gt=0)


class TradeRequest(BaseModel):
    client_id: str
    symbol: Optional[str] = Field(default=None, max_length=10)
    qty: Optional[float] = Field(default=None, gt=0)
    side: Optional[str] = None
    user_approved: bool = False
    proposal_id: Optional[str] = None


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

    ``user_approved`` MUST be true (non-discretionary, REG-003); otherwise the
    trade is blocked, audited and a 403 is returned.
    """
    await verify_client_ownership(user, req.client_id, db)
    proposal_id = req.proposal_id
    if not proposal_id:
        if not (req.symbol and req.side and req.qty):
            raise HTTPException(status_code=422, detail="Provide proposal_id, or symbol + side + qty")
        proposal = await c.orchestrator.create_trade_proposal(db, req.client_id, req.symbol, req.side, req.qty)
        proposal_id = proposal["proposal_id"]

    try:
        events = await c.orchestrator.handle_trade_approval(db, user.id, proposal_id, approved=req.user_approved)
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
    return {
        "trade_id": trade.id,
        "client_id": trade.client_id,
        "symbol": trade.symbol,
        "side": trade.side,
        "qty": trade.qty,
        "status": trade.status,
        "filled_price": trade.filled_price,
        "alpaca_order_id": trade.alpaca_order_id,
        "created_at": trade.created_at.isoformat() if trade.created_at else None,
    }


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
        "trades": [
            {
                "trade_id": t.id,
                "symbol": t.symbol,
                "side": t.side,
                "qty": t.qty,
                "status": t.status,
                "filled_price": t.filled_price,
                "alpaca_order_id": t.alpaca_order_id,
                "created_at": t.created_at.isoformat() if t.created_at else None,
            }
            for t in rows
        ],
    }

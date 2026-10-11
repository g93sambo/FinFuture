"""Market data routes: asset quotes, macroeconomic context, and Treasury yield curve."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["market"])


@router.get("/market/quote/{symbol}")
async def get_market_quote(
    symbol: str,
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    try:
        q = await c.market.get_quote(symbol)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Market data unavailable: {exc}")
    return q.model_dump(mode="json")


@router.get("/market/macro")
async def get_macro_indicators(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    try:
        macro = await c.market.get_macro_context()
        curve = await c.market.get_yield_curve()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Market data unavailable: {exc}")
    return {"macro": macro, "yield_curve": curve, "as_of": datetime.now(timezone.utc).isoformat()}

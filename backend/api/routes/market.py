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


@router.get("/market/history/{symbol}")
async def get_market_history(
    symbol: str,
    period: str = "6mo",
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    sym = symbol.strip().upper()
    try:
        df = await c.market.get_history([sym], period=period)
        series = df[sym] if sym in df.columns else df.iloc[:, 0]
        points = [
            {"date": idx.strftime("%Y-%m-%d"), "close": round(float(val), 2)}
            for idx, val in series.items()
        ]
        start_price = points[0]["close"] if points else 0.0
        end_price = points[-1]["close"] if points else 0.0
        period_return_pct = round(((end_price - start_price) / start_price) * 100.0, 2) if start_price > 0 else 0.0
        return {
            "symbol": sym,
            "period": period,
            "points": points,
            "start_price": start_price,
            "end_price": end_price,
            "period_return_pct": period_return_pct,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Historical data unavailable for {sym}: {exc}")


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

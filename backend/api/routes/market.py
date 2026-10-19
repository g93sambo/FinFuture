"""
backend/api/routes/market.py
============================
Market data routes: asset quotes, macroeconomic context, Treasury yield curve,
symbol search, fundamentals, and FX currency rates.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, Depends, HTTPException, Query

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.models import DBUser
from services.symbol_directory import search_symbols, get_symbol_fundamentals, SYMBOL_CATALOG

router = APIRouter(prefix="/api/v1", tags=["market"])
logger = logging.getLogger("wealth_advisor.api.market")


@router.get("/market/search")
async def search_market_symbols(
    q: str = Query(default="", description="Search query for ticker or company name"),
    limit: int = Query(default=10, ge=1, le=50),
    user: DBUser = Depends(get_current_user),
):
    """Search for symbols across US Equities, Global ETFs, and Nigerian (NGX) stocks."""
    results = search_symbols(query=q, limit=limit)
    return {"query": q, "count": len(results), "results": results}


@router.get("/market/fundamentals/{symbol}")
async def get_market_fundamentals(
    symbol: str,
    user: DBUser = Depends(get_current_user),
):
    """Retrieve company fundamentals, P/E ratio, dividend yield, and 52-week range."""
    fund = get_symbol_fundamentals(symbol)
    if not fund:
        raise HTTPException(status_code=404, detail=f"Fundamentals for ticker '{symbol.upper()}' not found in registry.")
    return fund


@router.get("/market/quote/{symbol}")
async def get_market_quote(
    symbol: str,
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    sym = symbol.strip().upper()
    try:
        q = await c.market.get_quote(sym)
        return q.model_dump(mode="json")
    except Exception as exc:  # noqa: BLE001
        # If symbol is completely unknown and not in catalog or pipeline
        if sym not in SYMBOL_CATALOG:
            raise HTTPException(status_code=404, detail=f"Symbol '{sym}' not found.")
        logger.warning("Quote fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"Market data temporarily unavailable for {sym}.")


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
        if df is None or df.empty or (sym not in df.columns and df.shape[1] == 0):
            raise HTTPException(status_code=404, detail=f"No price history available for '{sym}'.")

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
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        if sym not in SYMBOL_CATALOG:
            raise HTTPException(status_code=404, detail=f"Symbol '{sym}' not found.")
        logger.warning("History fetch failed for %s: %s", sym, exc)
        raise HTTPException(status_code=502, detail=f"Historical data unavailable for {sym}.")


@router.get("/market/macro")
async def get_macro_indicators(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    try:
        macro = await c.market.get_macro_context()
        curve = await c.market.get_yield_curve()
    except Exception as exc:  # noqa: BLE001
        logger.warning("Macro fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Market data temporarily unavailable.")
    return {"macro": macro, "yield_curve": curve, "as_of": datetime.now(timezone.utc).isoformat()}

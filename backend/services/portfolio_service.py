"""
backend/services/portfolio_service.py
=====================================
Portfolio state service. Source of truth, in priority order:

1. Alpaca paper account (when credentials exist and DRY_RUN is off)
2. Ledger derived from recorded FILLED trades in the ``trades`` table
   on top of a configurable starting cash balance (paper simulation).

Every call can persist a ``DBPortfolioSnapshot`` so the health report and
drift monitor have history to work with.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DBPortfolioSnapshot, DBTrade

logger = logging.getLogger("wealth_advisor.services.portfolio")

DEFAULT_STARTING_CASH = float(os.getenv("PAPER_STARTING_CASH", "100000"))

FALLBACK_PRICES: Dict[str, float] = {
    "SPY": 510.50, "QQQ": 440.25, "BND": 72.40, "VTI": 260.10, "AGG": 98.50,
    "SHY": 82.20, "AAPL": 185.00, "MSFT": 420.00, "GOOGL": 175.00,
    "AMZN": 185.00, "NVDA": 125.00,
    # Nigerian Equities (NGX)
    "DANGCEM": 650.00, "MTNN": 240.00, "GTCO": 48.50, "ZENITHBANK": 42.00,
    "ACCESSCORP": 21.50, "UBA": 29.80, "SEPLAT": 3400.00, "AIRTELAFRI": 2150.00,
}


class PortfolioService:
    def __init__(self, execution_module: Any = None, market_data_agent: Any = None) -> None:
        self.execution = execution_module
        self.market = market_data_agent

    async def _price(self, symbol: str) -> float:
        if self.market is not None:
            try:
                q = await self.market.get_quote(symbol)
                price = float(getattr(q, "price", 0.0) or 0.0)
                if price > 0:
                    return price
            except Exception as exc:  # noqa: BLE001
                logger.debug("Quote lookup failed for %s: %s", symbol, exc)
        return FALLBACK_PRICES.get(symbol.upper(), 100.0)

    async def _from_alpaca(self) -> Optional[Dict[str, Any]]:
        client = getattr(self.execution, "client", None)
        if client is None:
            return None
        try:
            account = await asyncio.to_thread(client.get_account)
            raw_positions = await asyncio.to_thread(client.get_all_positions)
            positions = {p.symbol: float(p.qty) for p in raw_positions}
            prices = {p.symbol: float(p.current_price) for p in raw_positions}
            return {
                "source": "alpaca_paper",
                "cash": float(account.cash),
                "positions": positions,
                "prices": prices,
            }
        except Exception as exc:  # noqa: BLE001
            logger.warning("Alpaca account sync failed, using ledger: %s", exc)
            return None

    async def _from_ledger(self, db: AsyncSession, client_id: str) -> Dict[str, Any]:
        result = await db.execute(
            select(DBTrade).where(DBTrade.client_id == client_id, DBTrade.status == "FILLED")
        )
        cash = DEFAULT_STARTING_CASH
        positions: Dict[str, float] = {}
        last_prices: Dict[str, float] = {}
        for t in result.scalars().all():
            qty = float(t.filled_qty or t.qty or 0.0)
            price = float(t.filled_price or FALLBACK_PRICES.get(t.symbol, 100.0))
            sign = 1.0 if str(t.side).upper() == "BUY" else -1.0
            positions[t.symbol] = positions.get(t.symbol, 0.0) + sign * qty
            cash -= sign * qty * price
            last_prices[t.symbol] = price
        positions = {s: q for s, q in positions.items() if abs(q) > 1e-9}
        return {"source": "ledger", "cash": cash, "positions": positions, "prices": last_prices}

    async def get_portfolio(
        self, db: AsyncSession, client_id: str, persist_snapshot: bool = False
    ) -> Dict[str, Any]:
        state = await self._from_alpaca() or await self._from_ledger(db, client_id)
        prices = dict(state["prices"])
        for sym in state["positions"]:
            if sym not in prices:
                prices[sym] = await self._price(sym)

        market_values = {s: q * prices[s] for s, q in state["positions"].items()}
        invested = sum(market_values.values())
        total_value = invested + state["cash"]
        weights = (
            {s: v / total_value for s, v in market_values.items()} if total_value > 0 else {}
        )

        portfolio = {
            "client_id": client_id,
            "source": state["source"],
            "total_value": round(total_value, 2),
            "cash": round(state["cash"], 2),
            "invested_value": round(invested, 2),
            "positions": [
                {
                    "symbol": s,
                    "qty": q,
                    "price": round(prices[s], 4),
                    "market_value": round(market_values[s], 2),
                    "weight": round(weights.get(s, 0.0), 6),
                }
                for s, q in state["positions"].items()
            ],
            "weights": weights,
            "prices": prices,
            "position_qty": dict(state["positions"]),
        }

        if persist_snapshot:
            db.add(
                DBPortfolioSnapshot(
                    client_id=client_id,
                    total_value=total_value,
                    positions=dict(state["positions"]),
                    cash=state["cash"],
                )
            )
            await db.commit()
        return portfolio

    async def projected_weight(
        self, db: AsyncSession, client_id: str, symbol: str, side: str, qty: float
    ) -> Dict[str, float]:
        """Weight of ``symbol`` after the proposed order, for CONC-001."""
        pf = await self.get_portfolio(db, client_id)
        price = pf["prices"].get(symbol) or await self._price(symbol)
        delta = qty * price * (1.0 if side.upper() == "BUY" else -1.0)
        current_value = pf["weights"].get(symbol, 0.0) * pf["total_value"]
        total_after = max(pf["total_value"], 1.0)
        return {
            "price": price,
            "projected_weight": max(0.0, (current_value + delta) / total_after),
            "notional_value": qty * price,
        }

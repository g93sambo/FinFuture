"""
backend/services/portfolio_service.py
=====================================
Portfolio state service. Each client's portfolio is their own ledger: a configurable
starting cash balance plus the fills of *their* trades in the ``trades`` table, valued
at live prices.

All clients route orders through one shared Alpaca paper account, so that account's
cash and positions are never shown to a client: they mix every user's trades. Instead,
orders still open at Alpaca (e.g. placed while the market was closed) are synced back
to the ``trades`` table here, so fills land in the right client's ledger at the real
fill price.

Every call can persist a ``DBPortfolioSnapshot`` so the health report and
drift monitor have history to work with.
"""

from __future__ import annotations

import asyncio
import logging
import os
from datetime import timezone
from typing import Any, Dict, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import DBPortfolioSnapshot, DBTrade

# Alpaca statuses that will not change again (plus our own labels)
FINAL_STATUSES = {"FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "DONE_FOR_DAY", "REPLACED", "BLOCKED"}
FILL_STATUSES = ("FILLED", "PARTIALLY_FILLED")
MAX_ORDER_SYNCS = 20

logger = logging.getLogger("wealth_advisor.services.portfolio")

DEFAULT_STARTING_CASH = float(os.getenv("PAPER_STARTING_CASH", "100000"))

FALLBACK_PRICES: Dict[str, float] = {
    "SPY": 510.50, "QQQ": 440.25, "BND": 72.40, "VTI": 260.10, "AGG": 98.50,
    "SHY": 82.20, "AAPL": 185.00, "MSFT": 420.00, "GOOGL": 175.00,
    "AMZN": 185.00, "NVDA": 125.00,
}


class PortfolioService:
    def __init__(self, execution_module: Any = None, market_data_agent: Any = None) -> None:
        self.execution = execution_module
        self.market = market_data_agent

    async def market_price(self, symbol: str) -> Optional[float]:
        """Live quote, or None when no market data is available."""
        if self.market is None:
            return None
        try:
            q = await self.market.get_quote(symbol)
            price = float(getattr(q, "price", 0.0) or 0.0)
            return price if price > 0 else None
        except Exception as exc:  # noqa: BLE001
            logger.debug("Quote lookup failed for %s: %s", symbol, exc)
            return None

    async def _price(self, symbol: str) -> float:
        return await self.market_price(symbol) or FALLBACK_PRICES.get(symbol.upper(), 100.0)

    async def sync_open_orders(self, db: AsyncSession, client_id: str) -> int:
        """Refresh this client's still-open Alpaca orders; returns how many changed."""
        client = getattr(self.execution, "client", None)
        if client is None:
            return 0
        result = await db.execute(
            select(DBTrade)
            .where(DBTrade.client_id == client_id, DBTrade.alpaca_order_id.is_not(None))
            .order_by(DBTrade.created_at.desc())
        )
        open_trades = [
            t for t in result.scalars().all()
            if str(t.status).upper() not in FINAL_STATUSES and not str(t.alpaca_order_id).startswith(("dry-run-", "mock-", "sim-"))
        ][:MAX_ORDER_SYNCS]
        changed = 0
        for t in open_trades:
            try:
                order = await asyncio.to_thread(client.get_order_by_id, t.alpaca_order_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug("Order sync failed for %s: %s", t.alpaca_order_id, exc)
                continue
            status = str(getattr(order.status, "value", order.status)).upper()
            filled_qty = float(getattr(order, "filled_qty", None) or 0.0)
            avg = getattr(order, "filled_avg_price", None)
            if status == t.status and filled_qty == float(t.filled_qty or 0.0):
                continue
            t.status = status
            t.filled_qty = filled_qty
            if avg:
                t.filled_price = float(avg)
            filled_at = getattr(order, "filled_at", None)
            if filled_at is not None and hasattr(filled_at, "astimezone"):
                t.filled_at = filled_at.astimezone(timezone.utc).replace(tzinfo=None) if filled_at.tzinfo else filled_at
            changed += 1
        if changed:
            await db.commit()
        return changed

    async def _from_ledger(self, db: AsyncSession, client_id: str) -> Dict[str, Any]:
        result = await db.execute(select(DBTrade).where(DBTrade.client_id == client_id))
        cash = DEFAULT_STARTING_CASH
        positions: Dict[str, float] = {}
        fill_prices: Dict[str, float] = {}
        reserved_cash = 0.0
        reserved_qty: Dict[str, float] = {}
        for t in result.scalars().all():
            status = str(t.status).upper()
            side = str(t.side).upper()
            if status in FILL_STATUSES:
                qty = float(t.filled_qty or 0.0) if status == "PARTIALLY_FILLED" else float(t.filled_qty or t.qty or 0.0)
                price = float(t.filled_price or FALLBACK_PRICES.get(t.symbol, 100.0))
                sign = 1.0 if side == "BUY" else -1.0
                positions[t.symbol] = positions.get(t.symbol, 0.0) + sign * qty
                cash -= sign * qty * price
                fill_prices[t.symbol] = price
                remaining = float(t.qty or 0.0) - qty if status == "PARTIALLY_FILLED" else 0.0
            elif status not in FINAL_STATUSES:
                remaining = float(t.qty or 0.0)  # still open at the broker
            else:
                remaining = 0.0
            if remaining > 1e-9:
                # Open orders hold back cash (buys) or shares (sells) so they cannot be spent twice
                if side == "BUY":
                    reserved_cash += remaining * float(t.filled_price or FALLBACK_PRICES.get(t.symbol, 100.0))
                else:
                    reserved_qty[t.symbol] = reserved_qty.get(t.symbol, 0.0) + remaining
        positions = {s: q for s, q in positions.items() if abs(q) > 1e-9}
        return {
            "source": "ledger",
            "cash": cash,
            "positions": positions,
            "fill_prices": fill_prices,
            "reserved_cash": reserved_cash,
            "reserved_qty": reserved_qty,
        }

    async def get_portfolio(
        self, db: AsyncSession, client_id: str, persist_snapshot: bool = False
    ) -> Dict[str, Any]:
        try:
            await self.sync_open_orders(db, client_id)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Open-order sync skipped: %s", exc)
            await db.rollback()
        state = await self._from_ledger(db, client_id)
        prices: Dict[str, float] = {}
        for sym in state["positions"]:
            prices[sym] = await self.market_price(sym) or state["fill_prices"].get(sym) or await self._price(sym)

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
            "reserved_cash": round(state["reserved_cash"], 2),
            "reserved_qty": dict(state["reserved_qty"]),
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

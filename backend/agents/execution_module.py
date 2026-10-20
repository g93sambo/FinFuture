"""
backend/agents/execution_module.py
==================================
Hardened brokerage execution module enforcing paper trading, pre-trade compliance gates,
distributed double-submit locking, DB persistence, and cryptographic audit logging.
"""

from __future__ import annotations

import os
import json
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from core.config import settings
from db.models import DBTrade, DBClientProfile
from services.cache import CacheService, get_cache_service, key_trade_lock, TTL_TRADE_LOCK
from services.audit_logger import AuditLogger, get_audit_logger

try:
    from alpaca.trading.client import TradingClient
    from alpaca.trading.requests import MarketOrderRequest
    from alpaca.trading.enums import OrderSide, TimeInForce
    HAS_ALPACA = True
except ImportError:
    HAS_ALPACA = False

logger = logging.getLogger("wealth_advisor.agents.execution_module")


# ============================================================================
# Custom Exception Hierarchy (all inherit from ValueError)
# ============================================================================

class ExecutionError(ValueError):
    """Base exception for execution module errors."""
    pass


KYC_ACCEPTED_SOURCES = {"salary", "business", "investments", "pension", "inheritance", "savings", "employment"}


def describe_kyc_gap(profile: Any) -> str:
    """Say why identity checks failed and what the client can do about it (no internal IDs)."""
    if getattr(profile, "pep_status", False) or getattr(profile, "high_risk_jurisdiction", False):
        return (
            "Trading is paused while your account is reviewed: your profile declares a politically exposed person "
            "or a high-risk jurisdiction, which needs a manual compliance review. If that was selected by mistake, "
            "update it on the Risk profile page."
        )
    source = str(getattr(profile, "source_of_funds", "") or "").lower()
    if source not in KYC_ACCEPTED_SOURCES:
        return (
            "Trading is paused because your source of funds could not be verified. On the Risk profile page, choose "
            "where your money comes from (salary, business, investments, savings, pension or inheritance) and save."
        )
    if getattr(profile, "aml_flag", False):
        return (
            "Trading is paused while your account is reviewed: your declared income and assets need a manual "
            "compliance check. Review your details on the Risk profile page."
        )
    return (
        "Trading is paused because your identity checks are not complete. Review and save your details on the "
        "Risk profile page to re-run them."
    )


def describe_broker_error(exc: Exception, symbol: str) -> str:
    """Turn an Alpaca API error (often a raw JSON body) into a sentence a client can act on."""
    raw = str(exc)
    message = raw
    try:
        body = json.loads(raw[raw.index("{"):]) if "{" in raw else {}
        message = str(body.get("message") or raw)
    except (ValueError, AttributeError):
        pass
    lower = message.lower()
    if "wash trade" in lower:
        return (
            f"The broker refused this order because an open order on the opposite side for {symbol} is still pending "
            "(wash-trade protection). Wait for that order to fill or cancel it, then try again."
        )
    if "insufficient" in lower and ("buying power" in lower or "balance" in lower or "qty" in lower):
        return f"The paper account does not have enough buying power or shares of {symbol} for this order."
    if "not tradable" in lower or "not active" in lower or ("asset" in lower and "not found" in lower):
        return f"{symbol} cannot be traded on the broker right now."
    if "market" in lower and "closed" in lower:
        return "The market is closed, so the broker did not accept this order. Try again during trading hours."
    return f"The broker rejected this order: {message.strip().rstrip('.')}."


class UnapprovedTradeError(ExecutionError):
    """Raised when trade lacks explicit client authorization (REG-003)."""
    pass


class ExpiredApprovalError(ExecutionError):
    """Raised when client approval timestamp exceeds 15-minute window (REG-004)."""
    pass


class KYCUnverifiedError(ExecutionError):
    """Raised when client profile is unverified for KYC."""
    pass


class DuplicateTradeError(ExecutionError):
    """Raised when distributed lock detects duplicate submission within 30s."""
    pass


# ============================================================================
# Result Schemas
# ============================================================================

class TradeExecutionResult(BaseModel):
    """Structured result returned by ExecutionModule.execute_trade."""
    success: bool = Field(..., description="Whether execution was completed")
    order_id: Optional[str] = Field(None, description="Alpaca paper or simulated order ID")
    trade_id: Optional[str] = Field(None, description="Database DBTrade record UUID")
    client_id: str = Field(..., description="Client identifier")
    proposal_id: str = Field(..., description="Trade proposal identifier")
    symbol: str = Field(..., description="Asset ticker symbol")
    side: str = Field(..., description="Order side: BUY or SELL")
    qty: float = Field(..., description="Quantity of shares")
    filled_price: Optional[float] = Field(None, description="Executed price per share")
    filled_qty: Optional[float] = Field(None, description="Total executed quantity")
    broker: str = Field(default="alpaca", description="Brokerage route (Alpaca paper)")
    currency: str = Field(default="USD", description="Currency of execution")
    fee: Optional[float] = Field(default=None, description="Brokerage or commission fee")
    total_price: Optional[float] = Field(default=None, description="Total order amount")
    status: str = Field(..., description="Order status: FILLED, PENDING, BLOCKED, REJECTED")
    executed_at: datetime = Field(..., description="Execution timestamp (UTC)")
    dry_run: bool = Field(default=False, description="Whether execution ran in dry-run mode")
    error: Optional[str] = Field(None, description="Error message if blocked or failed")

    # Dictionary access compatibility for legacy callers
    def __getitem__(self, item: str) -> Any:
        return getattr(self, item)

    def get(self, key: str, default: Any = None) -> Any:
        return getattr(self, key, default)


# Realistic fallback prices for simulated dry-run fills
SIMULATED_PRICES: Dict[str, float] = {
    # Broad Core & Factor ETFs
    "SPY": 510.50,
    "QQQ": 440.25,
    "DIA": 395.20,
    "IWM": 208.40,
    "VTI": 260.10,
    "VOO": 468.80,
    "VXUS": 61.20,
    "URTH": 142.60,
    "ACWI": 115.30,
    "EEM": 42.50,
    "EFA": 79.20,
    "VNQ": 88.40,
    # Chinese & Hong Kong Securities
    "ASHR": 28.50,
    "FXI": 29.40,
    "MCHI": 44.80,
    "KWEB": 31.60,
    "000300.SS": 3920.00,
    "2800.HK": 20.80,
    "^GSPC": 5120.00,
    "^NDX": 18240.00,
    "^DJI": 39800.00,
    "^RUT": 2080.00,
    "^HSI": 18450.00,
    # Fixed Income & Treasuries
    "BND": 72.40,
    "AGG": 98.50,
    "SHY": 82.20,
    "IEF": 94.10,
    "TLT": 92.80,
    "TIP": 107.50,
    "LQD": 108.20,
    "HYG": 77.40,
    # Commodities & Precious Metals
    "GLD": 218.50,
    "SLV": 27.80,
    "USO": 76.50,
    # Digital Asset / Spot Crypto ETFs
    "BTC": 67800.00,
    "ETH": 3520.00,
    "IBIT": 38.50,
    "FBTC": 62.40,
    "ETHA": 24.10,
    # Mega-Cap Equities
    "AAPL": 185.00,
    "MSFT": 420.00,
    "GOOGL": 175.00,
    "AMZN": 185.00,
    "NVDA": 125.00,
    "META": 495.00,
    "TSLA": 220.00,
    "BRK.B": 412.00,
    "JPM": 198.00,
    "DEFAULT": 100.00,
}


# ============================================================================
# ExecutionModule Implementation
# ============================================================================

class ExecutionModule:
    """
    Hardened Execution Agent for Wealth Advisory Agent.
    Enforces non-discretionary approval, freshness windows, KYC checks,
    mutual-exclusion locks, database persistence, and cryptographic audit logs.
    Orders go to Alpaca Paper Trading, or are filled at a simulated price (and labelled
    dry_run) when no Alpaca credentials are configured.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
        cache_service: Optional[CacheService] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        # 1. Hard Paper Trading Enforcement Guard for Alpaca
        if not paper or not getattr(settings, "alpaca_paper", True):
            raise RuntimeError(
                "CRITICAL SECURITY GUARD: Live trading is strictly prohibited! "
                "ExecutionModule operates exclusively in paper trading mode (paper=True)."
            )
        self.paper = True

        # 2. Broker Credentials & Settings
        self.api_key = api_key or getattr(settings, "alpaca_api_key", "") or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or getattr(settings, "alpaca_secret_key", "") or os.getenv("ALPACA_SECRET_KEY", "")
        self.cache_service = cache_service or get_cache_service()
        self.audit_logger = audit_logger or get_audit_logger()
        # Set by the container: PortfolioService for the per-client cash/holdings gate
        self.portfolio: Any = None

        # 3. Client Initialization with Graceful DRY_RUN Fallback
        is_global_dry_run = getattr(settings, "dry_run", False)
        if HAS_ALPACA and self.api_key and self.secret_key and not is_global_dry_run:
            try:
                self.client = TradingClient(self.api_key, self.secret_key, paper=True)
                logger.info("Alpaca TradingClient initialized successfully in paper trading mode.")
            except Exception as e:
                logger.warning(f"Failed to initialize Alpaca TradingClient: {e}. Falling back to DRY_RUN mode.")
                self.client = None
        else:
            self.client = None
            logger.info("ExecutionModule running in DRY_RUN mode (credentials missing or dry_run configured).")

    async def execute_trade(
        self,
        db: AsyncSession,
        client_id: str,
        proposal_id: str,
        symbol: str,
        side: str,
        qty: float,
        approved: bool,
        approval_timestamp: datetime,
        dry_run: Optional[bool] = None,
        broker: Optional[str] = None,
        currency: Optional[str] = None,
        user_id: Optional[str] = None,
    ) -> TradeExecutionResult:
        """
        Executes a trade order subject to strict pre-trade validation gates,
        distributed locks, database persistence, and audit logging.
        Orders are routed to Alpaca paper trading (or a labelled simulated fill).
        """
        symbol_clean = symbol.strip().upper() if symbol else ""
        side_clean = side.strip().upper() if side else ""
        now_utc = datetime.now(timezone.utc)

        chosen_broker = "alpaca"
        chosen_currency = "USD"

        # ---------------------------------------------------------------------
        # Pre-Trade Validation Gates
        # ---------------------------------------------------------------------

        # Gate 0: Input Argument Validation
        if not symbol_clean:
            raise ValueError("Trade rejected: Symbol cannot be empty.")
        if side_clean not in ("BUY", "SELL"):
            raise ValueError(f"Trade rejected: Invalid side '{side}'. Must be BUY or SELL.")
        if qty <= 0:
            raise ValueError(f"Trade rejected: Quantity must be positive, got {qty}.")

        # Gate 1: Non-Discretionary User Approval (REG-003)
        if not approved:
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="REG-003",
                reason="Non-discretionary user approval required. Trade is not approved.",
            )
            raise UnapprovedTradeError(
                "Trade rejected: Non-discretionary user approval required (REG-003). approved must be True."
            )

        # Gate 2: 15-Minute Approval Freshness Window (REG-004)
        if approval_timestamp.tzinfo is None:
            ts_utc = approval_timestamp.replace(tzinfo=timezone.utc)
        else:
            ts_utc = approval_timestamp.astimezone(timezone.utc)

        elapsed_seconds = (now_utc - ts_utc).total_seconds()
        # Disallow future timestamps beyond 60s clock skew
        if elapsed_seconds < -60.0:
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="REG-004",
                reason=f"Approval timestamp is invalid in future ({ts_utc.isoformat()}).",
            )
            raise ExpiredApprovalError("Trade rejected: Approval timestamp cannot be in the future.")

        if elapsed_seconds > 900.0:  # 15 minutes = 900 seconds
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="REG-004",
                reason=f"Approval expired. Elapsed {elapsed_seconds:.1f}s exceeds 15-minute window (900s).",
            )
            raise ExpiredApprovalError(
                f"Trade rejected: Approval timestamp expired (REG-004). "
                f"Approvals are valid for 15 minutes; elapsed {elapsed_seconds:.1f}s."
            )

        # Gate 3: KYC Verification Check
        stmt = select(DBClientProfile).where(DBClientProfile.client_id == client_id)
        result = await db.execute(stmt)
        profile = result.scalars().first()

        if profile is None:
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="KYC_VERIFICATION",
                reason=f"Client profile '{client_id}' not found.",
            )
            raise KYCUnverifiedError("Investor profile not found. Complete onboarding before placing orders.")

        if not getattr(profile, "kyc_verified", False):
            user_reason = describe_kyc_gap(profile)
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="KYC_VERIFICATION",
                reason=user_reason,
            )
            raise KYCUnverifiedError(user_reason)

        # Gate 3b: the client's own cash and holdings. All clients share one Alpaca paper
        # account, so the broker's buying-power check alone would let one client spend another's money.
        est_price: Optional[float] = None
        portfolio_service = getattr(self, "portfolio", None)
        if portfolio_service is not None:
            pf = await portfolio_service.get_portfolio(db, client_id)
            est_price = await portfolio_service.market_price(symbol_clean) or pf["prices"].get(symbol_clean)
            shortfall: Optional[str] = None
            if side_clean == "BUY" and est_price:
                available = pf["cash"] - pf.get("reserved_cash", 0.0)
                cost = float(qty) * est_price
                if cost > available + 0.01:
                    shortfall = (
                        f"Not enough cash for this order: it costs about ${cost:,.2f} and you have "
                        f"${max(available, 0.0):,.2f} available."
                    )
            elif side_clean == "SELL":
                held = pf["position_qty"].get(symbol_clean, 0.0) - pf.get("reserved_qty", {}).get(symbol_clean, 0.0)
                if float(qty) > held + 1e-9:
                    shortfall = (
                        f"You can sell at most {max(held, 0.0):g} shares of {symbol_clean}; this order is for {float(qty):g}."
                        if held > 1e-9
                        else f"You do not hold any {symbol_clean} shares to sell."
                    )
            if shortfall:
                await self._log_block(
                    db=db,
                    client_id=client_id,
                    proposal_id=proposal_id,
                    symbol=symbol_clean,
                    side=side_clean,
                    qty=qty,
                    gate="CLIENT_BALANCE",
                    reason=shortfall,
                )
                raise ExecutionError(shortfall)

        # Gate 4: 30-Second Double-Submit Lock
        lock_key = key_trade_lock(client_id)
        lock_acquired = await self.cache_service.acquire_lock(lock_key, timeout_seconds=TTL_TRADE_LOCK)
        if lock_acquired and db is not None:
            # Durable secondary check: verify no identical trade was committed in DB within 30s
            try:
                cutoff_30s = (now_utc - timedelta(seconds=TTL_TRADE_LOCK)).replace(tzinfo=None)
                stmt_recent = (
                    select(DBTrade)
                    .where(
                        DBTrade.client_id == client_id,
                        DBTrade.symbol == symbol_clean,
                        DBTrade.side == side_clean,
                        DBTrade.created_at >= cutoff_30s,
                    )
                    .limit(1)
                )
                recent_trade = (await db.execute(stmt_recent)).scalars().first()
                if recent_trade is not None:
                    lock_acquired = False
            except Exception as exc:
                logger.debug("Database duplicate check fallback: %s", exc)

        if not lock_acquired:
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="DOUBLE_SUBMIT_LOCK",
                reason=f"Duplicate trade submission detected within 30-second window for client '{client_id}'.",
            )
            raise DuplicateTradeError(
                f"Duplicate submit rejected: trade in progress within 30 seconds for client '{client_id}'."
            )

        # ---------------------------------------------------------------------
        # Order Execution Flow (Alpaca paper, or simulated fill when unconfigured)
        # ---------------------------------------------------------------------
        is_global_dry_run = getattr(settings, "dry_run", False)
        order_fee = None
        total_price = None
        alpaca_order_id = None

        is_dry_run = dry_run if dry_run is not None else (is_global_dry_run or self.client is None)
        if is_dry_run:
            # Simulated fill (no Alpaca credentials or DRY_RUN): labelled dry_run everywhere
            order_id = f"dry-run-alpaca-{uuid.uuid4().hex[:10]}"
            alpaca_order_id = order_id
            status = "FILLED"
            filled_price = SIMULATED_PRICES.get(symbol_clean, SIMULATED_PRICES["DEFAULT"])
            filled_qty = float(qty)
            total_price = filled_price * filled_qty
            executed_at = now_utc
            logger.info(f"[DRY-RUN] Simulated {side_clean} {qty} {symbol_clean} @ ${filled_price:.2f}")
        else:
            # Engine A: Alpaca Paper Trading Execution
            order_side = OrderSide.BUY if side_clean == "BUY" else OrderSide.SELL
            order_request = MarketOrderRequest(
                symbol=symbol_clean,
                qty=qty,
                side=order_side,
                time_in_force=TimeInForce.DAY,
            )
            try:
                # Alpaca SDK submit_order is synchronous; run non-blocking in threadpool
                order = await asyncio.to_thread(self.client.submit_order, order_request)
                order_id = str(order.id)
                alpaca_order_id = order_id
                status = str(order.status.value if hasattr(order.status, "value") else order.status).upper()
                raw_filled_price = float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None
                raw_filled_qty = float(order.filled_qty) if getattr(order, "filled_qty", None) else 0.0

                # For paper trading and accepted orders, ensure filled price and qty reflect the executed order
                # so the client receipt and order history are immediately transparent instead of showing blank/zero.
                # Until the order fills, record the live quote as the estimate; PortfolioService
                # replaces it with the real average fill price when it syncs the order.
                filled_price = raw_filled_price if raw_filled_price is not None else (
                    est_price or SIMULATED_PRICES.get(symbol_clean, SIMULATED_PRICES.get("DEFAULT", 100.0))
                )
                filled_qty = raw_filled_qty if raw_filled_qty > 0 else float(qty)
                total_price = filled_price * filled_qty
                cand_time = getattr(order, "filled_at", None) or getattr(order, "submitted_at", None)
                executed_at = cand_time if isinstance(cand_time, datetime) else now_utc
            except Exception as e:
                logger.error(f"Alpaca API order submission error: {e}")
                reason = describe_broker_error(e, symbol_clean)
                await self._log_block(
                    db=db,
                    client_id=client_id,
                    proposal_id=proposal_id,
                    symbol=symbol_clean,
                    side=side_clean,
                    qty=qty,
                    gate="BROKER_API_ERROR",
                    reason=reason,
                )
                raise ExecutionError(reason) from e

        # ---------------------------------------------------------------------
        # Database Persistence (`trades` table / DBTrade)
        # ---------------------------------------------------------------------
        trade_id = str(uuid.uuid4())
        # Ensure naive UTC datetimes for PostgreSQL TIMESTAMP WITHOUT TIME ZONE columns
        ts_utc_db = ts_utc.astimezone(timezone.utc).replace(tzinfo=None) if ts_utc else None
        # Duck-typed (not isinstance(..., datetime)) so this stays correct when `datetime` is patched.
        if hasattr(executed_at, "astimezone"):
            executed_at_db = (
                executed_at.astimezone(timezone.utc).replace(tzinfo=None)
                if getattr(executed_at, "tzinfo", None)
                else executed_at
            )
        else:
            executed_at_db = now_utc.replace(tzinfo=None)
        now_utc_db = now_utc.astimezone(timezone.utc).replace(tzinfo=None) if now_utc else datetime.utcnow()

        db_trade = DBTrade(
            id=trade_id,
            client_id=client_id,
            symbol=symbol_clean,
            qty=float(qty),
            side=side_clean,
            order_type="MARKET",
            status=status,
            filled_price=filled_price,
            filled_qty=filled_qty,
            broker=chosen_broker,
            currency=chosen_currency,
            alpaca_order_id=alpaca_order_id,
            compliance_report={
                "proposal_id": proposal_id,
                "approved": approved,
                "approval_timestamp": ts_utc.isoformat(),
                "dry_run": is_dry_run,
                "broker": chosen_broker,
                "currency": chosen_currency,
                "fee": order_fee,
                "total_price": total_price,
                "validation_gates": ["REG-003", "REG-004", "KYC", "30S_LOCK"],
            },
            user_approved_at=ts_utc_db,
            filled_at=executed_at_db,
            created_at=now_utc_db,
        )
        try:
            db.add(db_trade)
            await db.commit()
            await db.refresh(db_trade)
        except Exception:
            await db.rollback()
            raise

        # ---------------------------------------------------------------------
        # Cryptographic Audit Logging (TRADE_EXECUTED)
        # ---------------------------------------------------------------------
        await self.audit_logger.log_audit_entry(
            db=db,
            client_id=client_id,
            event_type="TRADE_EXECUTED",
            actor=f"SYSTEM:EXECUTION_MODULE:{chosen_broker.upper()}",
            details={
                "trade_id": trade_id,
                "order_id": order_id,
                "broker": chosen_broker,
                "currency": chosen_currency,
                "proposal_id": proposal_id,
                "symbol": symbol_clean,
                "side": side_clean,
                "qty": qty,
                "filled_price": filled_price,
                "filled_qty": filled_qty,
                "fee": order_fee,
                "total_price": total_price,
                "status": status,
                "dry_run": is_dry_run,
            },
            status="PASS",
        )

        return TradeExecutionResult(
            success=True,
            order_id=order_id,
            trade_id=trade_id,
            client_id=client_id,
            proposal_id=proposal_id,
            symbol=symbol_clean,
            side=side_clean,
            qty=qty,
            filled_price=filled_price,
            filled_qty=filled_qty,
            broker=chosen_broker,
            currency=chosen_currency,
            fee=order_fee,
            total_price=total_price,
            status=status,
            executed_at=executed_at,
            dry_run=is_dry_run,
        )

    async def get_order_status(self, order_id: str, broker: Optional[str] = None) -> Dict[str, Any]:
        """
        Polls or retrieves order status from Alpaca, or reports a simulated fill.
        """
        if order_id.startswith(("dry-run-", "mock-", "sim-")) or not self.client:
            return {
                "order_id": order_id,
                "status": "FILLED",
                "filled_qty": None,
                "filled_price": None,
                "dry_run": True,
            }

        try:
            order = await asyncio.to_thread(self.client.get_order_by_id, order_id)
            return {
                "order_id": str(order.id),
                "status": str(order.status.value if hasattr(order.status, "value") else order.status).upper(),
                "symbol": str(order.symbol),
                "qty": float(order.qty),
                "filled_qty": float(order.filled_qty or 0.0),
                "filled_avg_price": float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None,
                "created_at": getattr(order, "created_at", None),
                "filled_at": getattr(order, "filled_at", None),
                "dry_run": False,
            }
        except Exception as e:
            logger.error(f"Failed to fetch order status for {order_id}: {e}")
            return {
                "order_id": order_id,
                "status": "UNKNOWN",
                "error": str(e),
                "dry_run": False,
            }

    async def _log_block(
        self,
        db: AsyncSession,
        client_id: str,
        proposal_id: str,
        symbol: str,
        side: str,
        qty: float,
        gate: str,
        reason: str,
    ) -> None:
        """Helper to record blocked trade attempts in the cryptographic audit log."""
        try:
            await self.audit_logger.log_audit_entry(
                db=db,
                client_id=client_id,
                event_type="TRADE_BLOCKED",
                actor="SYSTEM:EXECUTION_MODULE",
                details={
                    "proposal_id": proposal_id,
                    "symbol": symbol,
                    "side": side,
                    "qty": qty,
                    "gate": gate,
                    "reason": reason,
                },
                status="BLOCK",
            )
        except Exception as e:
            logger.error(f"Failed to write audit entry for blocked trade: {e}")

    def place_order(self, symbol: str, qty: float, side: str, user_approved: bool) -> Dict[str, Any]:
        """Backward-compatible synchronous order execution wrapper."""
        if not user_approved:
            raise ValueError("Cannot execute trade: User has not approved.")

        symbol_clean = symbol.strip().upper()
        side_clean = side.strip().upper()

        if not self.client:
            logger.info(f"[DRY-RUN] Placing {side_clean} order for {qty} shares of {symbol_clean}")
            return {
                "status": "mock_filled",
                "symbol": symbol_clean,
                "qty": qty,
                "side": side_clean,
                "filled_price": SIMULATED_PRICES.get(symbol_clean, SIMULATED_PRICES["DEFAULT"]),
                "order_id": f"dummy-order-{uuid.uuid4().hex[:8]}",
            }

        order_side = OrderSide.BUY if side_clean == "BUY" else OrderSide.SELL
        order_request = MarketOrderRequest(
            symbol=symbol_clean,
            qty=qty,
            side=order_side,
            time_in_force=TimeInForce.DAY,
        )
        try:
            order = self.client.submit_order(order_request)
            return {
                "status": str(order.status.value if hasattr(order.status, "value") else order.status),
                "symbol": order.symbol,
                "qty": order.qty,
                "side": order.side,
                "order_id": str(order.id),
            }
        except Exception as e:
            logger.error(f"Alpaca API error: {e}")
            raise

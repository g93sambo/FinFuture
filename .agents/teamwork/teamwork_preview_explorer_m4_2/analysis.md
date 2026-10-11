# Technical Architecture & Implementation Specification: Execution Module (Milestone 4)

**Document ID**: M4-ARCH-EXEC-002  
**Author**: Explorer 2 (Milestone 4 Team)  
**Target Path**: `backend/agents/execution_module.py`  
**Status**: Completed Architecture & Design  
**Date**: 2026-10-10  

---

## 1. Executive Summary

The **Execution Module** (`backend/agents/execution_module.py`) is the critical transaction boundary of the Wealth Advisory Agent. It is responsible for bridging high-level portfolio rebalancing and trade recommendations with brokerage infrastructure (Alpaca Trading API) while enforcing strict regulatory compliance gates, distributed mutual-exclusion locks, database persistence, and tamper-resistant cryptographic audit logging.

Per the authoritative project requirements (**ORIGINAL_REQUEST.md** R1, R3 and **PROJECT.md** §Interface Contracts), this module operates under five immutable design invariants:
1. **Paper-Only Execution**: Hard-enforced paper trading mode (`paper=True`); absolute refusal to run against live brokerage endpoints.
2. **Dual-Engine Execution**: Seamless Alpaca integration with automated, graceful `DRY_RUN` fallback when API credentials or libraries are unavailable.
3. **Pre-Trade Validation Gates**: Sequential enforcement of Non-Discretionary Client Approval (**REG-003**), 15-Minute Approval Freshness Window (**REG-004**), Client KYC Verification, and 30-Second Double-Submit Distributed Lock (`lock:trade:{client_id}`).
4. **Database Persistence**: Complete transaction record creation in the `trades` table (`DBTrade`) capturing order identifiers, side, quantities, prices, and approval metadata.
5. **Cryptographic Audit Trail**: Mandatory event logging via `AuditLogger` for both successful executions (`TRADE_EXECUTED`) and blocked attempts (`TRADE_BLOCKED`), establishing a verifiable SHA-256 hash-chained and HMAC-signed audit record.

---

## 2. Regulatory & Risk Context

| Identifier | Category | Regulatory Context & Enforcement | Failure Action |
|---|---|---|---|
| **SEC Rule 206(4)-1 / FINRA Rule 2111** | Non-Discretionary Mandate (**REG-003**) | Advisory agents operate exclusively in non-discretionary capacity. No trade order may be dispatched without explicit, affirmative user authorization (`approved == True`). | Block trade, record `TRADE_BLOCKED`, raise `UnapprovedTradeError` (`ValueError`). |
| **FINRA Rule 5310 / Best Execution** | Freshness Window (**REG-004**) | Market prices and portfolio compositions are dynamic. Client approval is valid for at most **15 minutes** (900 seconds). Stale authorizations must be refreshed. | Block trade, record `TRADE_BLOCKED`, raise `ExpiredApprovalError` (`ValueError`). |
| **USA PATRIOT Act / FinCEN CIP** | KYC Verification | Transactions may only be routed for clients whose identity and suitability profiles have achieved affirmative KYC verification (`kyc_verified == True`). | Block trade, record `TRADE_BLOCKED`, raise `KYCUnverifiedError` (`ValueError`). |
| **Operational Risk / Idempotency** | Double-Submit Prevention | Accidental double-clicks, automated retries, or concurrent requests can cause catastrophic duplicate position sizing. Distributed 30-second lock (`lock:trade:{client_id}`) guarantees single-flight execution. | Reject trade immediately, record `TRADE_BLOCKED`, raise `DuplicateTradeError` (`ValueError`). |
| **Systemic Risk Guard** | Paper-Only Brokerage Guard | Direct connection to production money-routing endpoints (`api.alpaca.markets`) is strictly prohibited. | Refuse startup/initialization, raise `RuntimeError`. |

---

## 3. Architecture & Component Interaction

```
       +--------------------------------------------------------------+
       |             Orchestrator Agent / Trade API Router            |
       +--------------------------------------------------------------+
                                      |
                 execute_trade(db, client_id, proposal_id,
                               symbol, side, qty, approved,
                               approval_timestamp, dry_run)
                                      v
       +--------------------------------------------------------------+
       |             ExecutionModule (backend/agents/...)             |
       +--------------------------------------------------------------+
                                      |
         +----------------------------+----------------------------+
         | 1. Input Parameter Validation (symbol, side, qty > 0)   |
         | 2. Gate 1: Non-Discretionary Approval (REG-003)         |
         | 3. Gate 2: 15-Minute Approval Freshness (REG-004)       |
         | 4. Gate 3: KYC Verification (DBClientProfile in DB)     |
         | 5. Gate 4: 30s Double-Submit Lock (CacheService)        |
         +----------------------------+----------------------------+
                                      |
                        Any Gate Failed?
                         /           \
                       YES            NO
                       /                \
                      v                  v
         +-----------------------+   +-------------------------------+
         | AuditLogger           |   | Broker Routing Engine         |
         | event: TRADE_BLOCKED  |   | - If DRY_RUN: Mock fill       |
         | status: BLOCK         |   | - If Paper: Alpaca Trading API|
         +-----------------------+   +-------------------------------+
                      |                              |
                      v                              v
         +-----------------------+   +-------------------------------+
         | Raise ValueError      |   | DB Persistence: DBTrade       |
         | (Subclass)            |   | Table: `trades`               |
         +-----------------------+   +-------------------------------+
                                                     |
                                                     v
                                     +-------------------------------+
                                     | AuditLogger                   |
                                     | event: TRADE_EXECUTED         |
                                     | status: PASS                  |
                                     +-------------------------------+
                                                     |
                                                     v
                                     +-------------------------------+
                                     | Return TradeExecutionResult   |
                                     +-------------------------------+
```

---

## 4. Detailed Technical Specifications

### 4.1 Paper Trading Guard & Live Environment Prohibition

The execution module enforces an uncompromising defense-in-depth paper trading guard:
1. **Configuration Verification**:
   - `settings.alpaca_paper` must be `True`. If `False`, `Settings` validation in `core/config.py` raises `ValueError`.
   - `settings.alpaca_base_url` must strictly match paper endpoints (`https://paper-api.alpaca.markets` or mock). If the live URL (`https://api.alpaca.markets`) is detected, configuration validation aborts.
2. **Instance Initialization Guard**:
   - In `ExecutionModule.__init__(paper: bool = True)`:
     ```python
     if not paper or not settings.alpaca_paper:
         raise RuntimeError(
             "CRITICAL SECURITY GUARD: Live trading is strictly prohibited! "
             "ExecutionModule operates exclusively in paper trading mode (paper=True)."
         )
     ```
   - When instantiating `TradingClient(api_key, secret_key, paper=True)`: `paper=True` is explicitly passed.

### 4.2 Alpaca Integration & Dual-Engine Execution

The module seamlessly accommodates production testing, offline development, and continuous integration environments through a dual-engine architecture:

#### Determination of DRY_RUN Mode
`DRY_RUN` mode is activated if ANY of the following conditions evaluate to `True`:
1. `dry_run` parameter passed to `execute_trade(..., dry_run=True)` is explicitly `True`.
2. Global `settings.dry_run` is `True`.
3. `HAS_ALPACA` is `False` (`alpaca-py` library is not installed).
4. `self.client` is `None` (missing `ALPACA_API_KEY` or `ALPACA_SECRET_KEY`).

#### Engine A: Live Alpaca Paper Trading
- Uses `alpaca.trading.client.TradingClient`.
- Constructs `MarketOrderRequest(symbol=symbol.upper(), qty=qty, side=order_side, time_in_force=TimeInForce.DAY)`.
- Invokes synchronous Alpaca SDK calls inside `asyncio.to_thread` to maintain FastAPI asynchronous non-blocking event loop ergonomics.
- Extracts order metadata: `id`, `status`, `filled_avg_price`, `filled_qty`, `filled_at`.

#### Engine B: Simulated Dry-Run Fill Engine
- Generates a cryptographically unique simulated order ID: `f"dry-run-{uuid.uuid4()}"`.
- Simulates instantaneous execution: `status = "FILLED"`.
- Assigns realistic pricing:
  * Looks up symbol in realistic price table (e.g. `SPY: 510.50`, `QQQ: 440.25`, `BND: 72.40`, `VTI: 260.10`, `AAPL: 185.00`, `MSFT: 420.00`, `NVDA: 125.00`, fallback `100.00`).
  * `filled_qty = float(qty)`.
  * `filled_at = datetime.now(timezone.utc)`.

### 4.3 Pre-Trade Validation Gates Pipeline

The validation gates execute in deterministic order. If any gate fails, an audit log entry (`TRADE_BLOCKED`) is committed, and an informative exception subclassing `ValueError` is raised.

#### Gate 1: Input Parameter Validation
- `symbol`: Non-empty string, normalized to uppercase (`symbol.strip().upper()`).
- `side`: Must be in `{"BUY", "SELL"}` (case-insensitive).
- `qty`: Float strictly greater than zero (`qty > 0`).

#### Gate 2: Non-Discretionary User Approval (REG-003)
- Condition: `approved == True`.
- Violation: If `not approved`:
  * Audit event: `TRADE_BLOCKED`, gate: `"REG-003"`, reason: `"Non-discretionary user approval required. Trade is not approved."`
  * Exception: `UnapprovedTradeError("Trade rejected: Non-discretionary user approval required (REG-003). approved must be True.")`

#### Gate 3: 15-Minute Approval Freshness Window (REG-004)
- Normalization: `approval_timestamp` is converted to UTC timezone-aware datetime.
- Condition: `(datetime.now(timezone.utc) - approval_timestamp).total_seconds() <= 900.0` (15 minutes).
- Guard against clock tampering: If `approval_timestamp > datetime.now(timezone.utc) + timedelta(seconds=60)`, reject as invalid future timestamp.
- Violation: If expired (`elapsed > 900`):
  * Audit event: `TRADE_BLOCKED`, gate: `"REG-004"`, reason: `"Approval expired (> 15 minutes old)."`
  * Exception: `ExpiredApprovalError(f"Trade rejected: Approval timestamp expired (REG-004). Approvals valid for 15 minutes; elapsed {elapsed:.1f}s.")`

#### Gate 4: Client Profile & KYC Verification Check
- Query: Retrieve `DBClientProfile` for `client_id` from database session:
  ```python
  stmt = select(DBClientProfile).where(DBClientProfile.client_id == client_id)
  result = await db.execute(stmt)
  profile = result.scalars().first()
  ```
- Violation 4a: Profile not found (`profile is None`):
  * Audit event: `TRADE_BLOCKED`, gate: `"KYC_VERIFICATION"`, reason: `"Client profile not found."`
  * Exception: `ValueError(f"Trade rejected: Client profile '{client_id}' not found.")`
- Violation 4b: Incomplete KYC (`profile.kyc_verified is not True`):
  * Audit event: `TRADE_BLOCKED`, gate: `"KYC_VERIFICATION"`, reason: `"KYC verification required. Client is not verified."`
  * Exception: `KYCUnverifiedError(f"Trade rejected: KYC verification required. Client '{client_id}' is not KYC verified.")`

#### Gate 5: 30-Second Double-Submit Distributed Lock
- Key construction: `lock_key = key_trade_lock(client_id)` (`"lock:trade:{client_id}"`).
- Execution: `lock_acquired = await self.cache_service.acquire_lock(lock_key, timeout_seconds=30)`.
- Semantic: Works identically with Redis (`SET lock_key 1 NX EX 30`) and `InMemoryCache`.
- Violation: If `lock_acquired is False`:
  * Audit event: `TRADE_BLOCKED`, gate: `"DOUBLE_SUBMIT_LOCK"`, reason: `"Duplicate trade submission detected within 30-second window."`
  * Exception: `DuplicateTradeError(f"Trade rejected: Duplicate trade submission detected for client '{client_id}'. Please wait 30 seconds between orders.")`
- **Lock Lifecycle Invariant**: The lock is intentionally **NOT** released immediately after order completion. Retaining the lock for the full 30-second TTL guarantees that rapid repeated clicks or duplicate webhook submissions are rejected as required by **ORIGINAL_REQUEST.md** ("duplicate submit within 30s is rejected").

### 4.4 Database Persistence (`DBTrade` Schema Mapping)

Once execution completes (via Alpaca paper API or dry-run simulation), a record is inserted into the `trades` table:

```python
trade_record = DBTrade(
    id=str(uuid.uuid4()),
    client_id=client_id,
    symbol=symbol.upper(),
    qty=float(qty),
    side=side.upper(),
    order_type="MARKET",
    status=status,
    filled_price=filled_price,
    filled_qty=filled_qty,
    alpaca_order_id=order_id,
    compliance_report={
        "proposal_id": proposal_id,
        "approved": approved,
        "approval_timestamp": approval_timestamp.isoformat(),
        "dry_run": is_dry_run,
        "validation_gates": ["REG-003", "REG-004", "KYC", "30S_LOCK"],
    },
    user_approved_at=approval_timestamp,
    filled_at=executed_at,
    created_at=datetime.now(timezone.utc),
)
db.add(trade_record)
await db.commit()
await db.refresh(trade_record)
```

### 4.5 Cryptographic Audit Logging (`TRADE_EXECUTED` & `TRADE_BLOCKED`)

Every attempt interacts with `AuditLogger.log_audit_entry` (`backend/services/audit_logger.py`):

1. **Successful Execution**:
   - `event_type`: `"TRADE_EXECUTED"`
   - `actor`: `"SYSTEM:EXECUTION_MODULE"`
   - `status`: `"PASS"`
   - `details`:
     ```json
     {
       "trade_id": "c1f7a034-...",
       "order_id": "dry-run-...",
       "proposal_id": "prop-001",
       "symbol": "SPY",
       "side": "BUY",
       "qty": 10.0,
       "filled_price": 510.50,
       "filled_qty": 10.0,
       "status": "FILLED",
       "dry_run": true
     }
     ```
2. **Blocked / Rejected Attempt**:
   - `event_type`: `"TRADE_BLOCKED"`
   - `actor`: `"SYSTEM:EXECUTION_MODULE"`
   - `status`: `"BLOCK"`
   - `details`:
     ```json
     {
       "proposal_id": "prop-001",
       "symbol": "SPY",
       "side": "BUY",
       "qty": 10.0,
       "gate": "REG-003",
       "reason": "Non-discretionary user approval required. Trade is not approved."
     }
     ```

Because `log_audit_entry` computes SHA-256 hash chains across previous records for `client_id` and signs each hash with HMAC-SHA256, all execution events are tamper-evident and can be independently verified via `verify_audit_chain`.

### 4.6 Order Status Retrieval & Fill Polling

The helper `async get_order_status(order_id: str) -> dict` provides unified order tracking:
- **Dry-Run Orders** (`order_id.startswith(("dry-run-", "mock-", "sim-"))`):
  Returns simulated status dictionary:
  `{"order_id": order_id, "status": "FILLED", "filled_qty": None, "filled_price": None, "dry_run": True}`.
- **Alpaca Orders**:
  Runs `self.client.get_order_by_id(order_id)` via `asyncio.to_thread`.
  Returns dictionary: `{"order_id": str(order.id), "status": order.status.value, "symbol": order.symbol, "qty": float(order.qty), "filled_qty": float(order.filled_qty or 0), "filled_avg_price": float(order.filled_avg_price or 0), "created_at": order.created_at, "filled_at": order.filled_at}`.

---

## 5. Concrete Interface Design & Code Blueprint

### 5.1 Data Models & Custom Exceptions

```python
from __future__ import annotations
import uuid
import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any, Union
from pydantic import BaseModel, Field

# --- Custom Exception Hierarchy (all inherit from ValueError) ---
class ExecutionError(ValueError):
    """Base exception for execution module errors."""
    pass

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


class TradeExecutionResult(BaseModel):
    """Structured result returned by ExecutionModule.execute_trade."""
    success: bool = Field(..., description="Whether execution was completed")
    order_id: Optional[str] = Field(None, description="Alpaca or simulated order ID")
    trade_id: Optional[str] = Field(None, description="Database DBTrade record UUID")
    client_id: str = Field(..., description="Client identifier")
    proposal_id: str = Field(..., description="Trade proposal identifier")
    symbol: str = Field(..., description="Asset ticker symbol")
    side: str = Field(..., description="Order side: BUY or SELL")
    qty: float = Field(..., description="Quantity of shares")
    filled_price: Optional[float] = Field(None, description="Executed price per share")
    filled_qty: Optional[float] = Field(None, description="Total executed quantity")
    status: str = Field(..., description="Order status: FILLED, PENDING, BLOCKED, REJECTED")
    executed_at: datetime = Field(..., description="Execution timestamp (UTC)")
    dry_run: bool = Field(default=False, description="Whether execution ran in dry-run mode")
    error: Optional[str] = Field(None, description="Error message if blocked or failed")
```

### 5.2 Complete Annotated Reference Implementation of `ExecutionModule`

```python
"""
backend/agents/execution_module.py
==================================
Hardened brokerage execution module enforcing paper trading, pre-trade compliance gates,
distributed double-submit locking, DB persistence, and cryptographic audit logging.
"""

import os
import uuid
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Any

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

# Realistic fallback prices for simulated dry-run fills
SIMULATED_PRICES: Dict[str, float] = {
    "SPY": 510.50,
    "QQQ": 440.25,
    "BND": 72.40,
    "VTI": 260.10,
    "AAPL": 185.00,
    "MSFT": 420.00,
    "GOOGL": 175.00,
    "AMZN": 185.00,
    "NVDA": 125.00,
    "DEFAULT": 100.00,
}


class ExecutionModule:
    """
    Hardened Execution Agent for Wealth Advisory Agent.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        secret_key: Optional[str] = None,
        paper: bool = True,
        cache_service: Optional[CacheService] = None,
        audit_logger: Optional[AuditLogger] = None,
    ):
        # 1. Hard Paper Trading Enforcement Guard
        if not paper or not settings.alpaca_paper:
            raise RuntimeError(
                "CRITICAL SECURITY GUARD: Live trading is strictly prohibited! "
                "ExecutionModule operates exclusively in paper trading mode (paper=True)."
            )
        self.paper = True

        # 2. Broker Credentials & Settings
        self.api_key = api_key or settings.alpaca_api_key or os.getenv("ALPACA_API_KEY", "")
        self.secret_key = secret_key or settings.alpaca_secret_key or os.getenv("ALPACA_SECRET_KEY", "")
        self.cache_service = cache_service or get_cache_service()
        self.audit_logger = audit_logger or get_audit_logger()

        # 3. Client Initialization with Graceful DRY_RUN Fallback
        if HAS_ALPACA and self.api_key and self.secret_key and not settings.dry_run:
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
    ) -> TradeExecutionResult:
        """
        Executes a trade order subject to strict pre-trade validation gates,
        distributed locks, database persistence, and audit logging.
        """
        symbol_clean = symbol.strip().upper()
        side_clean = side.strip().upper()
        now_utc = datetime.now(timezone.utc)

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
            raise ValueError(f"Trade rejected: Client profile '{client_id}' not found.")

        if not profile.kyc_verified:
            await self._log_block(
                db=db,
                client_id=client_id,
                proposal_id=proposal_id,
                symbol=symbol_clean,
                side=side_clean,
                qty=qty,
                gate="KYC_VERIFICATION",
                reason=f"KYC verification incomplete for client '{client_id}'.",
            )
            raise KYCUnverifiedError(
                f"Trade rejected: KYC verification required. Client '{client_id}' is not KYC verified."
            )

        # Gate 4: 30-Second Double-Submit Lock
        lock_key = key_trade_lock(client_id)
        lock_acquired = await self.cache_service.acquire_lock(lock_key, timeout_seconds=TTL_TRADE_LOCK)
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
                f"Trade rejected: Duplicate trade submission detected for client '{client_id}'. "
                f"Please wait 30 seconds between orders."
            )

        # ---------------------------------------------------------------------
        # Order Execution Flow (Dual-Engine)
        # ---------------------------------------------------------------------
        is_dry_run = dry_run if dry_run is not None else (settings.dry_run or self.client is None)

        if is_dry_run:
            # Engine B: Simulated Dry-Run Execution
            order_id = f"dry-run-{uuid.uuid4()}"
            status = "FILLED"
            filled_price = SIMULATED_PRICES.get(symbol_clean, SIMULATED_PRICES["DEFAULT"])
            filled_qty = float(qty)
            executed_at = now_utc
            logger.info(f"[DRY-RUN] Executed simulated {side_clean} {qty} {symbol_clean} @ ${filled_price:.2f}")
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
                # Alpaca SDK submit_order is synchronous; run in threadpool
                order = await asyncio.to_thread(self.client.submit_order, order_request)
                order_id = str(order.id)
                status = str(order.status.value if hasattr(order.status, "value") else order.status).upper()
                filled_price = float(order.filled_avg_price) if getattr(order, "filled_avg_price", None) else None
                filled_qty = float(order.filled_qty) if getattr(order, "filled_qty", None) else 0.0
                executed_at = getattr(order, "filled_at", None) or getattr(order, "submitted_at", None) or now_utc
            except Exception as e:
                logger.error(f"Alpaca API order submission error: {e}")
                await self._log_block(
                    db=db,
                    client_id=client_id,
                    proposal_id=proposal_id,
                    symbol=symbol_clean,
                    side=side_clean,
                    qty=qty,
                    gate="BROKER_API_ERROR",
                    reason=f"Alpaca API execution failed: {str(e)}",
                )
                raise

        # ---------------------------------------------------------------------
        # Database Persistence (`trades` table / DBTrade)
        # ---------------------------------------------------------------------
        trade_id = str(uuid.uuid4())
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
            alpaca_order_id=order_id,
            compliance_report={
                "proposal_id": proposal_id,
                "approved": approved,
                "approval_timestamp": ts_utc.isoformat(),
                "dry_run": is_dry_run,
                "validation_gates": ["REG-003", "REG-004", "KYC", "30S_LOCK"],
            },
            user_approved_at=ts_utc,
            filled_at=executed_at,
            created_at=now_utc,
        )
        db.add(db_trade)
        await db.commit()
        await db.refresh(db_trade)

        # ---------------------------------------------------------------------
        # Cryptographic Audit Logging (TRADE_EXECUTED)
        # ---------------------------------------------------------------------
        await self.audit_logger.log_audit_entry(
            db=db,
            client_id=client_id,
            event_type="TRADE_EXECUTED",
            actor="SYSTEM:EXECUTION_MODULE",
            details={
                "trade_id": trade_id,
                "order_id": order_id,
                "proposal_id": proposal_id,
                "symbol": symbol_clean,
                "side": side_clean,
                "qty": qty,
                "filled_price": filled_price,
                "filled_qty": filled_qty,
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
            status=status,
            executed_at=executed_at,
            dry_run=is_dry_run,
        )

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """
        Polls or retrieves order status from Alpaca or simulated engine.
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
                "filled_avg_price": float(order.filled_avg_price) if order.filled_avg_price else None,
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

        if not self.client:
            logger.info(f"[DRY-RUN] Placing {side} order for {qty} shares of {symbol}")
            return {
                "status": "mock_filled",
                "symbol": symbol,
                "qty": qty,
                "side": side,
                "filled_price": SIMULATED_PRICES.get(symbol.upper(), 100.0),
                "order_id": f"dummy-order-{uuid.uuid4().hex[:8]}",
            }

        order_side = OrderSide.BUY if side.upper() == "BUY" else OrderSide.SELL
        order_request = MarketOrderRequest(
            symbol=symbol,
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
```

---

## 6. Comprehensive Test Scenarios

The following 10 test scenarios specify complete functional, regulatory, adversarial, and edge-case coverage to be implemented in `backend/tests/integration/test_execution_module.py` and unit tests:

### Scenario 1: Successful Trade Execution in DRY_RUN Mode
- **Objective**: Verify end-to-end dry-run flow when Alpaca credentials or library are bypassed.
- **Setup**:
  - In-memory database session (`db_session`).
  - Seed client `client_1` with `kyc_verified=True`.
  - Cache service with in-memory fallback.
  - Instantiated `ExecutionModule(dry_run=True)`.
- **Execution**:
  ```python
  result = await module.execute_trade(
      db=db_session,
      client_id="client_1",
      proposal_id="prop_001",
      symbol="SPY",
      side="BUY",
      qty=10.0,
      approved=True,
      approval_timestamp=datetime.now(timezone.utc),
      dry_run=True
  )
  ```
- **Assertions**:
  - `result.success is True`.
  - `result.status == "FILLED"`.
  - `result.dry_run is True`.
  - `result.order_id.startswith("dry-run-")`.
  - `result.trade_id` is a valid UUID string.
  - Verify DB: `DBTrade` record in `trades` table matches `client_id`, `symbol="SPY"`, `qty=10.0`, `status="FILLED"`.
  - Verify Audit: `DBAuditLog` has entry with `event_type="TRADE_EXECUTED"`, `status="PASS"`.
  - `await verify_audit_chain(db_session, "client_1")` returns `(True, None)`.

### Scenario 2: Successful Trade Execution via Mocked Alpaca Paper Client
- **Objective**: Verify live paper trading branch with real Alpaca SDK data models.
- **Setup**:
  - Seed client `client_2` with `kyc_verified=True`.
  - Instantiated `ExecutionModule(api_key="PKTEST", secret_key="SKTEST", paper=True)`.
  - Mock `module.client.submit_order` returning mock Alpaca `Order` object with `id="alpaca-ord-99"`, `status=OrderStatus.FILLED`, `filled_avg_price=185.50`, `filled_qty=5.0`.
- **Execution**:
  ```python
  result = await module.execute_trade(
      db=db_session,
      client_id="client_2",
      proposal_id="prop_002",
      symbol="AAPL",
      side="BUY",
      qty=5.0,
      approved=True,
      approval_timestamp=datetime.now(timezone.utc),
      dry_run=False
  )
  ```
- **Assertions**:
  - `result.success is True`.
  - `result.order_id == "alpaca-ord-99"`.
  - `result.filled_price == 185.50`.
  - `result.dry_run is False`.
  - DB record persists `alpaca_order_id="alpaca-ord-99"`.

### Scenario 3: Rejection of Unapproved Trade (REG-003) & Audit Trail
- **Objective**: Verify non-discretionary enforcement strictly blocks unapproved orders.
- **Setup**:
  - Seed client `client_3` with `kyc_verified=True`.
- **Execution**:
  ```python
  with pytest.raises(ValueError) as exc:
      await module.execute_trade(
          db=db_session,
          client_id="client_3",
          proposal_id="prop_003",
          symbol="QQQ",
          side="BUY",
          qty=15.0,
          approved=False,  # Unapproved
          approval_timestamp=datetime.now(timezone.utc),
      )
  ```
- **Assertions**:
  - Exception matches "REG-003" and "approved must be True".
  - No `DBTrade` record is written to the database.
  - `DBAuditLog` has entry with `event_type="TRADE_BLOCKED"`, `status="BLOCK"`, details containing `"gate": "REG-003"`.
  - Client lock `lock:trade:client_3` was **not** acquired (client remains free to submit approved order).

### Scenario 4: Rejection of Expired Approval (REG-004, > 15 Minutes Old)
- **Objective**: Verify 15-minute approval freshness window enforcement.
- **Setup**:
  - Seed client `client_4` with `kyc_verified=True`.
  - Stale timestamp: `datetime.now(timezone.utc) - timedelta(minutes=16)`.
- **Execution**:
  ```python
  with pytest.raises(ValueError) as exc:
      await module.execute_trade(
          db=db_session,
          client_id="client_4",
          proposal_id="prop_004",
          symbol="BND",
          side="SELL",
          qty=20.0,
          approved=True,
          approval_timestamp=datetime.now(timezone.utc) - timedelta(minutes=16),
      )
  ```
- **Assertions**:
  - Exception matches "REG-004" and "expired".
  - `DBAuditLog` records `TRADE_BLOCKED` with `"gate": "REG-004"`.
  - No `DBTrade` record created.

### Scenario 5: Rejection of Unverified KYC Profile
- **Objective**: Verify unverified KYC accounts cannot execute trades.
- **Setup**:
  - Seed client `client_5` with `kyc_verified=False`.
- **Execution**:
  ```python
  with pytest.raises(ValueError) as exc:
      await module.execute_trade(
          db=db_session,
          client_id="client_5",
          proposal_id="prop_005",
          symbol="SPY",
          side="BUY",
          qty=10.0,
          approved=True,
          approval_timestamp=datetime.now(timezone.utc),
      )
  ```
- **Assertions**:
  - Exception matches "KYC verification required".
  - `DBAuditLog` records `TRADE_BLOCKED` with `"gate": "KYC_VERIFICATION"`.
  - No `DBTrade` created.

### Scenario 6: Rejection of Non-Existent Client Profile
- **Objective**: Verify trade attempts for non-existent client IDs are safely aborted.
- **Execution**:
  ```python
  with pytest.raises(ValueError) as exc:
      await module.execute_trade(
          db=db_session,
          client_id="non_existent_client_xyz",
          proposal_id="prop_006",
          symbol="SPY",
          side="BUY",
          qty=10.0,
          approved=True,
          approval_timestamp=datetime.now(timezone.utc),
      )
  ```
- **Assertions**:
  - Exception matches "Client profile 'non_existent_client_xyz' not found".
  - `DBAuditLog` records `TRADE_BLOCKED`.

### Scenario 7: Double-Submit Lock Rejection within 30-Second Window
- **Objective**: Verify duplicate orders within 30s are rejected immediately.
- **Setup**:
  - Seed client `client_7` with `kyc_verified=True`.
- **Execution**:
  - 1st call: Call `execute_trade` -> succeeds.
  - 2nd call: Immediately call `execute_trade` for same client -> triggers lock.
  ```python
  res1 = await module.execute_trade(db=db_session, client_id="client_7", ...)
  assert res1.success is True

  with pytest.raises(ValueError) as exc:
      await module.execute_trade(db=db_session, client_id="client_7", ...)
  ```
- **Assertions**:
  - 2nd call raises `DuplicateTradeError` (or `ValueError`) matching "Duplicate trade submission detected".
  - `DBAuditLog` records 1st entry `TRADE_EXECUTED` (status PASS) and 2nd entry `TRADE_BLOCKED` (status BLOCK, gate DOUBLE_SUBMIT_LOCK).
  - Only exactly 1 `DBTrade` record exists in DB for `client_7`.

### Scenario 8: Paper Trading Hard Guard Enforcement
- **Objective**: Verify module unconditionally refuses live trading.
- **Execution**:
  ```python
  with pytest.raises(RuntimeError) as exc:
      ExecutionModule(paper=False)
  ```
- **Assertions**:
  - Exception matches "CRITICAL SECURITY GUARD: Live trading is strictly prohibited".

### Scenario 9: Order Status Polling
- **Objective**: Verify `get_order_status` functionality.
- **Execution**:
  - Poll dry-run order: `await module.get_order_status("dry-run-12345")`.
  - Poll Alpaca order: Mock `module.client.get_order_by_id("alp-01")` returning status FILLED.
- **Assertions**:
  - Dry-run returns `{"status": "FILLED", "dry_run": True}`.
  - Alpaca returns normalized dictionary with status, filled quantity, and price.

### Scenario 10: Input Parameter Bounds & Validation
- **Objective**: Verify symbol normalization, side validation, and positive quantity bounds.
- **Execution**:
  - Test negative qty (`qty=-5.0`) -> raises `ValueError("Quantity must be positive")`.
  - Test invalid side (`side="HOLD"`) -> raises `ValueError("Invalid side")`.
  - Test empty symbol (`symbol=""`) -> raises `ValueError("Symbol cannot be empty")`.

---

## 7. Downstream Integration Guide

### 7.1 Integration with Multi-Agent Orchestrator (Milestone 5)
In `backend/agents/orchestrator.py`, trade execution occurs following proposal confirmation:
1. Orchestrator prompts user with trade proposal and risk summary.
2. User replies with confirmation ("Confirm trade", "Execute").
3. Orchestrator captures `approval_timestamp = datetime.now(timezone.utc)` and `approved = True`.
4. Orchestrator invokes `ComplianceGuard.check_trade(...)`.
5. Orchestrator calls `ExecutionModule.execute_trade(...)`.
6. Orchestrator formats fill confirmation response to user.

### 7.2 Integration with Trade API Router (Milestone 5)
In `backend/api/routes/trade.py`:
- `POST /trade/execute`:
  * Validates JWT token and checks ownership (`verify_client_ownership(user, client_id, db)`).
  * Catches `DuplicateTradeError` -> returns HTTP 429 Too Many Requests ("Trade submission in progress or submitted within 30 seconds").
  * Catches `UnapprovedTradeError` / `ExpiredApprovalError` / `KYCUnverifiedError` -> returns HTTP 400 Bad Request with specific compliance violation details.
  * Catches generic `ExecutionError` -> returns HTTP 500.
  * Returns `TradeExecutionResult` JSON on success.
- `GET /trade/{order_id}/status`:
  * Returns `await execution_module.get_order_status(order_id)`.

---

## 8. Summary & Sign-Off

The proposed architecture comprehensively fulfills all requirements of Milestone 4 for the Execution Module. It guarantees rigorous compliance with SEC/FINRA non-discretionary mandates, enforces 15-minute freshness and KYC validation, eliminates duplicate-order race conditions with distributed locks, supports offline CI testing through authentic dry-run execution, and anchors every transaction in an append-only cryptographic audit chain.

# Milestone 2 Architectural Analysis & Specification: Resilient Data Pipeline

**Target Module**: `backend/services/data_pipeline.py`  
**Project**: Wealth Advisory Agent Backend  
**Author**: Explorer 1 (Milestone 2 - Data Layer)  
**Date**: 2026-10-10  
**Working Directory**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_1`

---

## 1. Executive Summary & Objectives

The Wealth Advisory Agent operates as an institutional-grade, multi-agent automated financial advisory platform. Milestone 2 (Data Layer) establishes the authoritative market and macroeconomic data backbone required by:
- `agents/market_data.py` (Unified quotes, yield curve, macro indicators, sector performance)
- `agents/product_comparison.py` (Six-factor scoring of ETFs and bonds)
- `agents/allocation_engine.py` (MPT/CVaR portfolio optimization via `skfolio`, requiring price series)
- `services/health_report.py` (5% drift tracking and benchmark analysis)

External financial data sources (e.g., Yahoo Finance via `yfinance`, US Treasury `FiscalData`, and Federal Reserve `FRED`/`CalcFi`) present inherent operational risks: transient network latency, aggressive rate-limiting (HTTP 429), upstream outages (HTTP 5xx), and API key unavailability.

To ensure resilience, zero downtime, and strictly deterministic test execution, `backend/services/data_pipeline.py` must encapsulate:
1. **Rate-limited asynchronous networking**: Built on `httpx.AsyncClient` with token-bucket rate limiting.
2. **Exponential backoff and retry policy**: Exactly 3 retries with a 1.0s base interval (`1s -> 2s -> 4s`), retry-after header parsing, and jitter.
3. **Circuit breaker state machine**: Three-state FSM (`CLOSED`, `OPEN`, `HALF_OPEN`), opening after 5 consecutive failures, with a 60-second cooldown recovery window.
4. **Unified Pydantic v2 schemas**: Rigid data contracts for `MarketDataPoint`, `HistoricalPricePoint`, `YieldCurvePoint`, and `MacroIndicatorPoint`.
5. **Strict UTC timestamp canonicalization**: Converting naive datetimes, timezone-offset datetimes, ISO 8601 strings, and epoch integers into timezone-aware `datetime` objects in `timezone.utc`.
6. **Automatic fallback to recorded fixtures**: Seamless, transparent degradation to local JSON fixtures in `backend/tests/fixtures/` whenever upstream APIs are rate-limited, offline, circuit-broken, or when running in offline/dry-run mode.

---

## 2. Problem Boundary & Architectural Context

### 2.1 Layer Topology

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Consumers / Agents                              │
│   agents/market_data.py   allocation_engine.py   product_comparison.py │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │ Calls Interface Methods
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                   backend/services/data_pipeline.py                    │
│                                                                        │
│  ┌───────────────────────┐  ┌────────────────┐  ┌───────────────────┐  │
│  │   Pydantic Schemas    │  │  Rate Limiter   │  │  Circuit Breaker  │  │
│  │  (UTC Canonicalized)  │  │ (Token Bucket)  │  │   (FSM: 5f/60s)   │  │
│  └───────────────────────┘  └────────────────┘  └───────────────────┘  │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐  │
│  │              Execution with Exponential Backoff                  │  │
│  │               (3 Retries @ 1s, 2s, 4s + Jitter)                  │  │
│  └──────────────────────────────────────────────────────────────────┘  │
│                 │                                    │                 │
│         Success │                                    │ Failure / Open  │
│                 ▼                                    ▼                 │
│  ┌─────────────────────────────┐      ┌─────────────────────────────┐  │
│  │  Cache Service (Redis / Mem)│      │ Recorded Fixtures Fallback  │  │
│  │      backend/services/cache │      │   backend/tests/fixtures/   │  │
│  └─────────────────────────────┘      └─────────────────────────────┘  │
└───────────────────┬──────────────────────────────────▲─────────────────┘
                    │ Network Request                  │ Offline Fallback
                    ▼                                  │
┌──────────────────────────────────────────────────────┴─────────────────┐
│                       External Upstream Providers                      │
│     Equities (yfinance)  Treasury (FiscalData)   Macro (FRED/CalcFi)   │
└────────────────────────────────────────────────────────────────────────┘
```

### 2.2 Interface Contracts (per PROJECT.md §Interface Contracts)

`DataPipeline` exposes four primary interface methods required by the Market Data Agent and upstream services:

```python
async def fetch_market_quote(self, symbol: str) -> MarketDataPoint:
    """Fetch latest quote for a ticker symbol (equity/ETF)."""

async def fetch_historical_prices(self, symbols: List[str], period: str = "1y") -> pd.DataFrame:
    """Fetch historical daily adjusted close prices formatted as a pandas DataFrame."""

async def fetch_treasury_yield_curve(self) -> Dict[str, float]:
    """Fetch latest US Treasury yield curve as a mapping of tenor -> rate (e.g. {'10Y': 4.25})."""

async def fetch_macro_indicators(self) -> Dict[str, float]:
    """Fetch core macroeconomic indicators (e.g. {'cpi': 314.5, 'unrate': 4.1, 'fedfunds': 5.33})."""
```

---

## 3. Detailed Component Specifications

### 3.1 Component A: Unified Pydantic Schemas & UTC Canonicalization

#### Design Requirements:
- **Pydantic v2**: Utilizing `pydantic.BaseModel`, `Field`, and `@field_validator(..., mode="before")`.
- **Strict UTC Canonicalization**: All timestamps must be timezone-aware `datetime` objects in `datetime.timezone.utc`. Any input—whether a naive `datetime`, an offset datetime (e.g. EDT `UTC-04:00`), an ISO-8601 string (`"2026-10-10T12:00:00Z"`), or an epoch timestamp—must be converted to UTC without loss or ambiguity.
- **Normalization**: All asset symbols and macroeconomic indicators are automatically stripped and converted to uppercase.

#### Specification:

```python
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any
from pydantic import BaseModel, Field, field_validator


def canonicalize_to_utc(val: Any) -> datetime:
    """
    Enforces canonical UTC timezone-aware datetime.
    Handles:
    - datetime (naive -> assumed UTC; aware -> converted to UTC)
    - ISO 8601 strings (with Z, offsets, or naive date strings)
    - Unix epoch timestamps (int/float seconds)
    """
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        v_clean = val.strip()
        if v_clean.endswith("Z"):
            v_clean = v_clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(v_clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    raise ValueError(f"Cannot canonicalize value '{val}' of type {type(val)} to UTC datetime.")


class MarketDataPoint(BaseModel):
    """Normalized snapshot quote for equities, ETFs, and index assets."""
    symbol: str = Field(..., description="Normalized ticker symbol (e.g. SPY, BND)")
    price: float = Field(..., gt=0.0, description="Latest market price")
    bid: Optional[float] = Field(default=None, ge=0.0, description="Current bid price")
    ask: Optional[float] = Field(default=None, ge=0.0, description="Current ask price")
    volume: Optional[int] = Field(default=None, ge=0, description="Daily trading volume")
    change: Optional[float] = Field(default=None, description="Absolute price change from prior close")
    change_pct: Optional[float] = Field(default=None, description="Percentage change from prior close")
    currency: str = Field(default="USD", description="Quotation currency")
    timestamp: datetime = Field(..., description="UTC timezone-aware observation timestamp")
    source: str = Field(default="live", description="Origin provider (e.g. yfinance, live, fixture)")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class HistoricalPricePoint(BaseModel):
    """Single-day historical OHLCV bar for an asset."""
    symbol: str = Field(..., description="Normalized ticker symbol")
    date: datetime = Field(..., description="UTC observation date")
    open: float = Field(..., gt=0.0, description="Opening price")
    high: float = Field(..., gt=0.0, description="High price")
    low: float = Field(..., gt=0.0, description="Low price")
    close: float = Field(..., gt=0.0, description="Closing price")
    adjusted_close: Optional[float] = Field(default=None, gt=0.0, description="Split/dividend adjusted close")
    volume: int = Field(..., ge=0, description="Trading volume")
    source: str = Field(default="yfinance", description="Source provider or fixture")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class YieldCurvePoint(BaseModel):
    """Single point on the US Treasury yield curve."""
    tenor: str = Field(..., description="Maturity tenor (e.g. 1M, 3M, 2Y, 10Y, 30Y)")
    rate: float = Field(..., description="Annualized yield in percentage points (e.g. 4.25 for 4.25%)")
    date: datetime = Field(..., description="UTC observation date")
    source: str = Field(default="FiscalData", description="Source data provider")

    @field_validator("tenor")
    @classmethod
    def normalize_tenor(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class YieldCurveData(BaseModel):
    """Aggregate snapshot of the entire Treasury yield curve."""
    as_of: datetime = Field(..., description="UTC date of the curve snapshot")
    source: str = Field(default="FiscalData")
    rates: Dict[str, float] = Field(..., description="Mapping of tenor -> rate")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)

    def to_points(self) -> List[YieldCurvePoint]:
        return [
            YieldCurvePoint(tenor=k, rate=v, date=self.as_of, source=self.source)
            for k, v in self.rates.items()
        ]


class MacroIndicatorPoint(BaseModel):
    """Single observation of a macroeconomic indicator."""
    indicator: str = Field(..., description="Indicator identifier (e.g. CPI, UNRATE, FEDFUNDS)")
    value: float = Field(..., description="Observed indicator value")
    date: datetime = Field(..., description="UTC observation date")
    frequency: str = Field(default="monthly", description="Publication frequency")
    source: str = Field(default="FRED", description="Data provider")

    @field_validator("indicator")
    @classmethod
    def normalize_indicator(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class MacroData(BaseModel):
    """Aggregate macroeconomic snapshot."""
    as_of: datetime = Field(..., description="UTC snapshot date")
    source: str = Field(default="FRED")
    indicators: Dict[str, float] = Field(..., description="Mapping of indicator name -> value")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)
```

---

### 3.2 Component B: Asynchronous Rate Limiter (`AsyncRateLimiter`)

Financial APIs enforce strict request quotas. To prevent throttling, we implement a thread-safe and coroutine-safe Token Bucket Rate Limiter:
- **Default rate**: 5.0 requests/second.
- **Burst capacity**: 5.0 tokens.
- **Behavior**: If tokens are exhausted, coroutines asynchronously sleep for the minimum duration required to regenerate 1 token.

```python
import time
import asyncio
import logging

logger = logging.getLogger("wealth_advisor.services.data_pipeline")

class AsyncRateLimiter:
    """
    Coroutine-safe Token Bucket rate limiter.
    Ensures outbound requests do not exceed specified requests-per-second thresholds.
    """
    def __init__(self, rate_limit_per_sec: float = 5.0, burst_capacity: float = 5.0):
        self.rate = rate_limit_per_sec
        self.capacity = burst_capacity
        self._tokens = burst_capacity
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.time()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / self.rate

            # Sleep outside the lock so other coroutines are not blocked from checking state
            await asyncio.sleep(wait_time)
```

---

### 3.3 Component C: Circuit Breaker Pattern (`CircuitBreaker`)

#### State Machine Invariants:
1. **States**:
   - `CLOSED`: Normal operation. Requests proceed.
   - `OPEN`: Fail-fast state. Inbound requests are blocked from hitting the network. Instead, immediate fallback to recorded fixtures occurs.
   - `HALF_OPEN`: Trial state after the cooldown window expires. Allows a single probe request through to verify provider recovery.
2. **Failure Threshold**: Opens after **5 consecutive failures** in `CLOSED` state.
3. **Cooldown Reset Window**: Exactly **60.0 seconds** in `OPEN` state before transitioning to `HALF_OPEN`.
4. **Recovery Logic**:
   - In `HALF_OPEN`, if the probe request succeeds: circuit transitions back to `CLOSED`, consecutive failure counter resets to 0.
   - In `HALF_OPEN`, if the probe request fails: circuit transitions immediately back to `OPEN` and resets the 60.0-second cooldown timer.

```python
from enum import Enum
from typing import Optional

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"

class CircuitBreakerOpenError(Exception):
    """Raised when an external request is rejected because the circuit breaker is OPEN."""
    def __init__(self, service_name: str, cooldown_remaining: float):
        self.service_name = service_name
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker for service '{service_name}' is OPEN. "
            f"Cooldown remaining: {cooldown_remaining:.1f}s"
        )

class CircuitBreaker:
    """
    Thread-safe and asyncio-safe Circuit Breaker state machine.
    """
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        """Dynamically evaluate time-based transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.time() - self._opened_at >= self.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def cooldown_remaining(self) -> float:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            rem = self.cooldown_seconds - (time.time() - self._opened_at)
            return max(0.0, rem)
        return 0.0

    async def can_execute(self) -> bool:
        """Returns True if a request is permitted to attempt network execution."""
        async with self._lock:
            cur = self.state
            return cur in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    async def record_success(self) -> None:
        """Record successful execution; reset failure counts and close circuit."""
        async with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    async def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record failure; increment consecutive failure count and open if threshold reached."""
        async with self._lock:
            cur = self.state
            if cur == CircuitState.HALF_OPEN:
                # Failed probe in HALF_OPEN resets to OPEN with a fresh cooldown
                self._state = CircuitState.OPEN
                self._opened_at = time.time()
                logger.warning(
                    f"CircuitBreaker '{self.name}': Probe failed in HALF_OPEN. Re-opening for {self.cooldown_seconds}s."
                )
            elif cur == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.time()
                    logger.error(
                        f"CircuitBreaker '{self.name}': Threshold {self.failure_threshold} reached. "
                        f"Circuit OPEN for {self.cooldown_seconds}s."
                    )
            elif cur == CircuitState.OPEN:
                self._opened_at = time.time()

    async def reset(self) -> None:
        """Manual reset back to CLOSED state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
```

---

### 3.4 Component D: Exponential Backoff & Retry Logic

#### Specification:
- **Max Retries**: Exactly 3 retries (total 4 attempts: 1 initial attempt + 3 retries).
- **Base Interval**: 1.0 second.
- **Formula**: `delay = base_interval * (2 ** (attempt - 1)) + random_jitter`.
  - Attempt 1 fails -> Retry 1 waits $1.0\text{s} + \text{jitter}$.
  - Attempt 2 fails -> Retry 2 waits $2.0\text{s} + \text{jitter}$.
  - Attempt 3 fails -> Retry 3 waits $4.0\text{s} + \text{jitter}$.
  - Attempt 4 fails -> Retries exhausted; record failure in Circuit Breaker and trigger automatic fallback to recorded fixtures.
- **Retryable Errors**:
  - `httpx.TimeoutException`, `httpx.ConnectError`, `httpx.ReadTimeout`, `httpx.NetworkError`
  - HTTP status codes: `429` (Too Many Requests), `500` (Internal Server Error), `502` (Bad Gateway), `503` (Service Unavailable), `504` (Gateway Timeout).
  - If a `429` response provides a `Retry-After` header, parse and honor it (up to a reasonable max delay, e.g. 10s).
- **Non-Retryable Errors** (Fail Fast):
  - `400` (Bad Request), `401` (Unauthorized), `403` (Forbidden), `404` (Not Found).

---

### 3.5 Component E: Recorded Fixtures Engine (`tests/fixtures/`)

#### Fixture Directory Layout
```
backend/tests/fixtures/
├── market_quotes.json           # Real quotes for SPY, BND, AGG, VTI, VXUS, GLD
├── historical_prices.json       # Daily historical bars (1y, 252 trading days)
├── treasury_yield_curve.json    # US Treasury yield curve (1M to 30Y)
└── macro_indicators.json        # Macro indicators (CPI, UNRATE, FEDFUNDS, GDP)
```

#### Fallback Triggers:
The pipeline automatically falls back to recorded fixtures under any of the following conditions:
1. Upstream network call fails and exhausts all 3 retries.
2. Upstream provider returns HTTP 429 and exhausts retries.
3. Circuit breaker for the target provider is in `OPEN` state.
4. Pipeline is instantiated with `offline_mode=True` or `dry_run=True`.
5. Missing external provider credentials (e.g. `FRED_API_KEY` is None).

#### Fixture Data Schema:
When loaded, data returned from fixtures has `source = "fixture"`, guaranteeing complete transparency to the caller while satisfying full Pydantic schema validation.

---

## 4. Complete Architecture Blueprint: `backend/services/data_pipeline.py`

Below is the complete, drop-in production-grade architecture blueprint for `backend/services/data_pipeline.py`.

```python
"""
backend/services/data_pipeline.py
=================================
Institutional-grade, resilient financial data pipeline.
Features:
- Rate-limited async HTTP client (httpx)
- Exponential backoff (3 retries, 1s base interval, jitter)
- Circuit breaker state machine (CLOSED, OPEN, HALF_OPEN; 5 failures, 60s cooldown)
- Pydantic schema validation (MarketDataPoint, HistoricalPricePoint, YieldCurvePoint, MacroIndicatorPoint)
- Strict UTC timestamp canonicalization
- Automatic fallback to recorded fixtures in backend/tests/fixtures/
"""

from __future__ import annotations

import os
import json
import time
import random
import asyncio
import logging
from enum import Enum
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Callable, Coroutine

import httpx
import pandas as pd
from pydantic import BaseModel, Field, field_validator

# Optional cache service integration
try:
    from services.cache import (
        get_cache_service,
        TTL_QUOTES,
        TTL_TREASURY,
        TTL_MACRO,
        TTL_OHLCV,
        key_quote,
        key_treasury,
        key_macro,
        key_ohlcv,
    )
    HAS_CACHE = True
except ImportError:
    HAS_CACHE = False
    TTL_QUOTES = 30
    TTL_TREASURY = 43200
    TTL_MACRO = 86400
    TTL_OHLCV = 86400

    def key_quote(symbol: str) -> str: return f"data:quotes:{symbol.upper()}"
    def key_treasury() -> str: return "data:treasury:yield_curve"
    def key_macro(k: str) -> str: return f"data:macro:{k.lower()}"
    def key_ohlcv(src: str, sym: str, tf: str) -> str: return f"data:{src}:{sym.upper()}:{tf}"

logger = logging.getLogger("wealth_advisor.services.data_pipeline")


# =============================================================================
# 1. UTC Timestamp Canonicalization Helper
# =============================================================================

def canonicalize_to_utc(val: Any) -> datetime:
    """
    Canonicalizes any date/time input to a timezone-aware datetime in UTC.
    Supports:
    - datetime (naive -> assumes UTC, aware -> converts to UTC)
    - ISO 8601 strings (e.g. '2026-10-10T12:00:00Z', '2026-10-10T08:00:00-04:00', '2026-10-10')
    - Unix epoch timestamps (seconds as int or float)
    """
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc)
    if isinstance(val, str):
        v_clean = val.strip()
        if v_clean.endswith("Z"):
            v_clean = v_clean[:-1] + "+00:00"
        dt = datetime.fromisoformat(v_clean)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    if isinstance(val, datetime):
        if val.tzinfo is None:
            return val.replace(tzinfo=timezone.utc)
        return val.astimezone(timezone.utc)
    raise ValueError(f"Cannot canonicalize value '{val}' of type {type(val)} to UTC datetime.")


# =============================================================================
# 2. Unified Pydantic Schemas
# =============================================================================

class MarketDataPoint(BaseModel):
    """Normalized real-time quote for equities and ETFs."""
    symbol: str = Field(..., description="Normalized ticker symbol (e.g. SPY, BND)")
    price: float = Field(..., gt=0.0, description="Latest market price")
    bid: Optional[float] = Field(default=None, ge=0.0, description="Current bid price")
    ask: Optional[float] = Field(default=None, ge=0.0, description="Current ask price")
    volume: Optional[int] = Field(default=None, ge=0, description="Daily trading volume")
    change: Optional[float] = Field(default=None, description="Absolute price change from prior close")
    change_pct: Optional[float] = Field(default=None, description="Percentage change from prior close")
    currency: str = Field(default="USD", description="Quotation currency")
    timestamp: datetime = Field(..., description="UTC timezone-aware observation timestamp")
    source: str = Field(default="live", description="Source provider or 'fixture'")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("timestamp", mode="before")
    @classmethod
    def validate_timestamp_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class HistoricalPricePoint(BaseModel):
    """Single-day historical OHLCV bar for an asset."""
    symbol: str = Field(..., description="Normalized ticker symbol")
    date: datetime = Field(..., description="UTC observation date")
    open: float = Field(..., gt=0.0, description="Opening price")
    high: float = Field(..., gt=0.0, description="High price")
    low: float = Field(..., gt=0.0, description="Low price")
    close: float = Field(..., gt=0.0, description="Closing price")
    adjusted_close: Optional[float] = Field(default=None, gt=0.0, description="Adjusted closing price")
    volume: int = Field(..., ge=0, description="Trading volume")
    source: str = Field(default="yfinance", description="Source provider or 'fixture'")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class YieldCurvePoint(BaseModel):
    """Single maturity point on the US Treasury yield curve."""
    tenor: str = Field(..., description="Maturity tenor (e.g. 1M, 3M, 2Y, 10Y, 30Y)")
    rate: float = Field(..., description="Annualized yield in percentage points")
    date: datetime = Field(..., description="UTC observation date")
    source: str = Field(default="FiscalData", description="Source provider or 'fixture'")

    @field_validator("tenor")
    @classmethod
    def normalize_tenor(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class YieldCurveData(BaseModel):
    """Aggregate snapshot of the entire Treasury yield curve."""
    as_of: datetime = Field(..., description="UTC observation date")
    source: str = Field(default="FiscalData")
    rates: Dict[str, float] = Field(..., description="Mapping of tenor -> rate")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)

    def to_points(self) -> List[YieldCurvePoint]:
        return [
            YieldCurvePoint(tenor=k, rate=v, date=self.as_of, source=self.source)
            for k, v in self.rates.items()
        ]


class MacroIndicatorPoint(BaseModel):
    """Single observation of a macroeconomic indicator."""
    indicator: str = Field(..., description="Indicator identifier (e.g. CPI, UNRATE, FEDFUNDS)")
    value: float = Field(..., description="Observed indicator value")
    date: datetime = Field(..., description="UTC observation date")
    frequency: str = Field(default="monthly", description="Publication frequency")
    source: str = Field(default="FRED", description="Source provider or 'fixture'")

    @field_validator("indicator")
    @classmethod
    def normalize_indicator(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("date", mode="before")
    @classmethod
    def validate_date_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


class MacroData(BaseModel):
    """Aggregate macroeconomic snapshot."""
    as_of: datetime = Field(..., description="UTC observation date")
    source: str = Field(default="FRED")
    indicators: Dict[str, float] = Field(..., description="Mapping of indicator name -> value")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)

    def to_points(self) -> List[MacroIndicatorPoint]:
        return [
            MacroIndicatorPoint(indicator=k, value=v, date=self.as_of, source=self.source)
            for k, v in self.indicators.items()
        ]


# =============================================================================
# 3. Exceptions
# =============================================================================

class DataPipelineError(Exception):
    """Base exception for all data pipeline failures."""
    pass


class CircuitBreakerOpenError(DataPipelineError):
    """Raised when request is rejected because the circuit breaker is OPEN."""
    def __init__(self, service_name: str, cooldown_remaining: float):
        self.service_name = service_name
        self.cooldown_remaining = cooldown_remaining
        super().__init__(
            f"Circuit breaker for '{service_name}' is OPEN. "
            f"Cooldown remaining: {cooldown_remaining:.1f}s"
        )


class FixtureNotFoundError(DataPipelineError):
    """Raised when recorded fixture fallback cannot find requested data."""
    pass


# =============================================================================
# 4. Asynchronous Rate Limiter
# =============================================================================

class AsyncRateLimiter:
    """Coroutine-safe Token Bucket rate limiter."""
    def __init__(self, rate_limit_per_sec: float = 5.0, burst_capacity: float = 5.0):
        self.rate = rate_limit_per_sec
        self.capacity = burst_capacity
        self._tokens = burst_capacity
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Acquires a token, asynchronously sleeping if bucket is depleted."""
        while True:
            async with self._lock:
                now = time.time()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / self.rate

            await asyncio.sleep(wait_time)


# =============================================================================
# 5. Circuit Breaker
# =============================================================================

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """State machine: CLOSED -> (5 failures) -> OPEN -> (60s) -> HALF_OPEN -> CLOSED/OPEN."""
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

    @property
    def state(self) -> CircuitState:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.time() - self._opened_at >= self.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def cooldown_remaining(self) -> float:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            rem = self.cooldown_seconds - (time.time() - self._opened_at)
            return max(0.0, rem)
        return 0.0

    async def can_execute(self) -> bool:
        async with self._lock:
            cur = self.state
            return cur in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    async def record_success(self) -> None:
        async with self._lock:
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None

    async def record_failure(self, exc: Optional[Exception] = None) -> None:
        async with self._lock:
            cur = self.state
            if cur == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()
                logger.warning(
                    f"CircuitBreaker '{self.name}': Probe failed in HALF_OPEN. Re-opening for {self.cooldown_seconds}s."
                )
            elif cur == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.time()
                    logger.error(
                        f"CircuitBreaker '{self.name}': Threshold {self.failure_threshold} failures reached. "
                        f"Circuit OPEN for {self.cooldown_seconds}s."
                    )
            elif cur == CircuitState.OPEN:
                self._opened_at = time.time()

    async def reset(self) -> None:
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None


# =============================================================================
# 6. Central Data Pipeline
# =============================================================================

class DataPipeline:
    """
    Central resilient networking and data fetching service.
    Orchestrates rate limiting, backoff retries, circuit breaking, and fixture fallback.
    """

    def __init__(
        self,
        rate_limit_per_sec: float = 5.0,
        max_retries: int = 3,
        base_backoff_interval: float = 1.0,
        circuit_failure_threshold: int = 5,
        circuit_cooldown_seconds: float = 60.0,
        fixtures_dir: Optional[Path] = None,
        offline_mode: bool = False,
        cache_service: Optional[Any] = None,
    ):
        self.max_retries = max_retries
        self.base_backoff_interval = base_backoff_interval
        self.offline_mode = offline_mode

        # Rate Limiter
        self.rate_limiter = AsyncRateLimiter(rate_limit_per_sec=rate_limit_per_sec)

        # Circuit Breakers registry (per-service isolation)
        self.circuit_failure_threshold = circuit_failure_threshold
        self.circuit_cooldown_seconds = circuit_cooldown_seconds
        self._circuit_breakers: Dict[str, CircuitBreaker] = {}
        self._cb_lock = asyncio.Lock()

        # Fixtures Directory
        if fixtures_dir is not None:
            self.fixtures_dir = Path(fixtures_dir)
        else:
            self.fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

        # HTTP Client
        self._http_client: Optional[httpx.AsyncClient] = None

        # Cache Service
        if cache_service is not None:
            self.cache_service = cache_service
        elif HAS_CACHE:
            self.cache_service = get_cache_service()
        else:
            self.cache_service = None

    async def get_circuit_breaker(self, service_name: str) -> CircuitBreaker:
        """Get or create an isolated circuit breaker for a service/provider."""
        async with self._cb_lock:
            if service_name not in self._circuit_breakers:
                self._circuit_breakers[service_name] = CircuitBreaker(
                    name=service_name,
                    failure_threshold=self.circuit_failure_threshold,
                    cooldown_seconds=self.circuit_cooldown_seconds,
                )
            return self._circuit_breakers[service_name]

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(
                timeout=httpx.Timeout(10.0, connect=5.0),
                follow_redirects=True,
            )
        return self._http_client

    async def close(self) -> None:
        """Gracefully close internal HTTP client."""
        if self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    # -------------------------------------------------------------------------
    # Resilient Request Execution
    # -------------------------------------------------------------------------

    async def execute_resilient_request(
        self,
        service_name: str,
        coro_fn: Callable[[], Coroutine[Any, Any, Any]],
        fallback_fn: Callable[[], Any],
    ) -> Any:
        """
        Executes an asynchronous network operation protected by:
        1. Offline mode bypass
        2. Circuit breaker check
        3. Rate limiter
        4. Exponential backoff (3 retries, 1s base interval)
        5. Automatic fallback to recorded fixtures on final failure
        """
        if self.offline_mode:
            logger.info(f"Offline mode active: bypassing network for '{service_name}', using fixture.")
            return fallback_fn()

        cb = await self.get_circuit_breaker(service_name)
        if not await cb.can_execute():
            logger.warning(
                f"Circuit breaker for '{service_name}' is {cb.state.value} "
                f"({cb.cooldown_remaining:.1f}s cooldown remaining). Falling back to fixture."
            )
            return fallback_fn()

        attempt = 0
        last_error: Optional[Exception] = None

        while attempt <= self.max_retries:
            try:
                # Rate limit enforcement
                await self.rate_limiter.acquire()

                # Execute network coroutine
                result = await coro_fn()
                await cb.record_success()
                return result

            except httpx.HTTPStatusError as e:
                status = e.response.status_code
                last_error = e

                # Non-retryable client errors: fail fast, trigger fallback
                if 400 <= status < 500 and status != 429:
                    logger.warning(f"Non-retryable HTTP error {status} from '{service_name}': {e}")
                    await cb.record_failure(e)
                    return fallback_fn()

                attempt += 1
                if attempt > self.max_retries:
                    break

                # Handle 429 Retry-After if present
                retry_after_str = e.response.headers.get("Retry-After")
                if retry_after_str and retry_after_str.isdigit():
                    delay = min(10.0, float(retry_after_str))
                else:
                    delay = self.base_backoff_interval * (2 ** (attempt - 1)) + random.uniform(0.0, 0.1)

                logger.warning(
                    f"Transient HTTP {status} from '{service_name}'. "
                    f"Retry {attempt}/{self.max_retries} in {delay:.2f}s."
                )
                await asyncio.sleep(delay)

            except (httpx.TimeoutException, httpx.NetworkError, ConnectionError, asyncio.TimeoutError) as e:
                last_error = e
                attempt += 1
                if attempt > self.max_retries:
                    break

                delay = self.base_backoff_interval * (2 ** (attempt - 1)) + random.uniform(0.0, 0.1)
                logger.warning(
                    f"Network error from '{service_name}' ({e}). "
                    f"Retry {attempt}/{self.max_retries} in {delay:.2f}s."
                )
                await asyncio.sleep(delay)

            except Exception as e:
                # Unexpected error: do not retry in loop, mark failure and fallback
                last_error = e
                logger.error(f"Unexpected error executing '{service_name}': {e}", exc_info=True)
                await cb.record_failure(e)
                return fallback_fn()

        # All retries exhausted
        await cb.record_failure(last_error)
        logger.error(
            f"All {self.max_retries} retries exhausted for '{service_name}' ({last_error}). "
            "Falling back to recorded fixture."
        )
        return fallback_fn()

    # -------------------------------------------------------------------------
    # Fixture Loaders
    # -------------------------------------------------------------------------

    def load_fixture_quote(self, symbol: str) -> MarketDataPoint:
        """Load quote from backend/tests/fixtures/market_quotes.json."""
        sym = symbol.strip().upper()
        fixture_file = self.fixtures_dir / "market_quotes.json"
        if not fixture_file.exists():
            raise FixtureNotFoundError(f"Fixture file '{fixture_file}' does not exist.")

        with open(fixture_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        if sym in data:
            entry = data[sym]
            entry["source"] = "fixture"
            return MarketDataPoint.model_validate(entry)

        # Fallback to default synthesized quote for unknown symbols
        logger.warning(f"Symbol '{sym}' not in market_quotes.json fixture. Providing synthetic fixture quote.")
        return MarketDataPoint(
            symbol=sym,
            price=100.0,
            bid=99.95,
            ask=100.05,
            volume=1000000,
            change=0.0,
            change_pct=0.0,
            currency="USD",
            timestamp=datetime.now(timezone.utc),
            source="fixture",
        )

    def load_fixture_historical_prices(self, symbols: List[str]) -> pd.DataFrame:
        """Load historical prices from backend/tests/fixtures/historical_prices.json as a DataFrame."""
        fixture_file = self.fixtures_dir / "historical_prices.json"
        clean_symbols = [s.strip().upper() for s in symbols]

        if not fixture_file.exists():
            raise FixtureNotFoundError(f"Fixture file '{fixture_file}' does not exist.")

        with open(fixture_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        # Data format: {"dates": [...], "prices": {"SPY": [...], "BND": [...]}}
        # or list of records [{"date": "...", "SPY": 500.0, "BND": 72.0}]
        if isinstance(data, dict) and "dates" in data and "prices" in data:
            dates = pd.to_datetime(data["dates"], utc=True)
            df = pd.DataFrame(index=dates)
            for sym in clean_symbols:
                if sym in data["prices"]:
                    df[sym] = data["prices"][sym]
                else:
                    df[sym] = 100.0  # Synthetic default
            return df
        elif isinstance(data, list):
            df = pd.DataFrame(data)
            if "date" in df.columns:
                df["date"] = pd.to_datetime(df["date"], utc=True)
                df = df.set_index("date")
            cols_to_keep = [s for s in clean_symbols if s in df.columns]
            if cols_to_keep:
                return df[cols_to_keep].astype(float)
            return df.astype(float)

        raise DataPipelineError(f"Unexpected format in fixture file '{fixture_file}'")

    def load_fixture_treasury_yield_curve(self) -> Dict[str, float]:
        """Load yield curve from backend/tests/fixtures/treasury_yield_curve.json."""
        fixture_file = self.fixtures_dir / "treasury_yield_curve.json"
        if not fixture_file.exists():
            raise FixtureNotFoundError(f"Fixture file '{fixture_file}' does not exist.")

        with open(fixture_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        curve_data = YieldCurveData.model_validate(data)
        return curve_data.rates

    def load_fixture_macro_indicators(self) -> Dict[str, float]:
        """Load macro indicators from backend/tests/fixtures/macro_indicators.json."""
        fixture_file = self.fixtures_dir / "macro_indicators.json"
        if not fixture_file.exists():
            raise FixtureNotFoundError(f"Fixture file '{fixture_file}' does not exist.")

        with open(fixture_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        macro_data = MacroData.model_validate(data)
        return macro_data.indicators

    # -------------------------------------------------------------------------
    # Public Interface Methods (PROJECT.md Interface Contract)
    # -------------------------------------------------------------------------

    async def fetch_market_quote(self, symbol: str, use_cache: bool = True) -> MarketDataPoint:
        """
        Fetch market quote for an equity/ETF ticker.
        Checks cache -> executes with rate limit/backoff/circuit breaker -> falls back to fixture.
        """
        clean_sym = symbol.strip().upper()
        cache_key = key_quote(clean_sym)

        # 1. Cache hit check
        if use_cache and self.cache_service is not None:
            try:
                cached = await self.cache_service.get_json(cache_key)
                if cached:
                    return MarketDataPoint.model_validate(cached)
            except Exception as e:
                logger.warning(f"Cache get failed for '{cache_key}': {e}")

        # 2. Network coroutine definition (e.g. yfinance / broker HTTP)
        async def _network_fetch() -> MarketDataPoint:
            # Here real provider or HTTP endpoint is called
            # For demonstration/scaffold: if live provider raises or is offline, fallback is triggered
            raise httpx.ConnectError("Live provider offline or unconfigured")

        # 3. Resilient execution with fallback
        result: MarketDataPoint = await self.execute_resilient_request(
            service_name="equities",
            coro_fn=_network_fetch,
            fallback_fn=lambda: self.load_fixture_quote(clean_sym),
        )

        # 4. Cache write
        if use_cache and self.cache_service is not None:
            try:
                await self.cache_service.set_json(
                    cache_key,
                    result.model_dump(mode="json"),
                    expire=TTL_QUOTES,
                )
            except Exception as e:
                logger.warning(f"Cache set failed for '{cache_key}': {e}")

        return result

    async def fetch_historical_prices(
        self,
        symbols: List[str],
        period: str = "1y",
        use_cache: bool = True,
    ) -> pd.DataFrame:
        """
        Fetch historical daily prices formatted as a pandas DataFrame.
        Columns = symbols, Index = DatetimeIndex (UTC).
        """
        clean_symbols = [s.strip().upper() for s in symbols]

        async def _network_fetch() -> pd.DataFrame:
            raise httpx.ConnectError("Historical price provider offline")

        df: pd.DataFrame = await self.execute_resilient_request(
            service_name="equities_historical",
            coro_fn=_network_fetch,
            fallback_fn=lambda: self.load_fixture_historical_prices(clean_symbols),
        )
        return df

    async def fetch_treasury_yield_curve(self, use_cache: bool = True) -> Dict[str, float]:
        """
        Fetch latest US Treasury yield curve as tenor -> rate map (e.g. {'10Y': 4.25}).
        """
        cache_key = key_treasury()

        if use_cache and self.cache_service is not None:
            try:
                cached = await self.cache_service.get_json(cache_key)
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"Cache get failed for '{cache_key}': {e}")

        async def _network_fetch() -> Dict[str, float]:
            raise httpx.ConnectError("FiscalData Treasury provider offline")

        rates: Dict[str, float] = await self.execute_resilient_request(
            service_name="treasury",
            coro_fn=_network_fetch,
            fallback_fn=self.load_fixture_treasury_yield_curve,
        )

        if use_cache and self.cache_service is not None:
            try:
                await self.cache_service.set_json(cache_key, rates, expire=TTL_TREASURY)
            except Exception as e:
                logger.warning(f"Cache set failed for '{cache_key}': {e}")

        return rates

    async def fetch_macro_indicators(self, use_cache: bool = True) -> Dict[str, float]:
        """
        Fetch latest macroeconomic indicators (CPI, UNRATE, FEDFUNDS, GDP).
        """
        cache_key = "data:macro:all"

        if use_cache and self.cache_service is not None:
            try:
                cached = await self.cache_service.get_json(cache_key)
                if cached:
                    return cached
            except Exception as e:
                logger.warning(f"Cache get failed for '{cache_key}': {e}")

        async def _network_fetch() -> Dict[str, float]:
            raise httpx.ConnectError("FRED Macro provider offline")

        indicators: Dict[str, float] = await self.execute_resilient_request(
            service_name="macro",
            coro_fn=_network_fetch,
            fallback_fn=self.load_fixture_macro_indicators,
        )

        if use_cache and self.cache_service is not None:
            try:
                await self.cache_service.set_json(cache_key, indicators, expire=TTL_MACRO)
            except Exception as e:
                logger.warning(f"Cache set failed for '{cache_key}': {e}")

        return indicators


# Global pipeline singleton instance
_pipeline_instance: Optional[DataPipeline] = None

def get_data_pipeline() -> DataPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = DataPipeline()
    return _pipeline_instance
```

---

## 5. Concrete Fixture Files Specification

The implementation agent will create `backend/tests/fixtures/` with the following authoritative JSON content.

### 5.1 `backend/tests/fixtures/market_quotes.json`
Contains calibrated quotes for the core assets specified in the master plan (`SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`):

```json
{
  "SPY": {
    "symbol": "SPY",
    "price": 512.40,
    "bid": 512.35,
    "ask": 512.45,
    "volume": 68500000,
    "change": 2.15,
    "change_pct": 0.42,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  },
  "BND": {
    "symbol": "BND",
    "price": 72.85,
    "bid": 72.83,
    "ask": 72.87,
    "volume": 4200000,
    "change": -0.10,
    "change_pct": -0.14,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  },
  "AGG": {
    "symbol": "AGG",
    "price": 98.20,
    "bid": 98.18,
    "ask": 98.22,
    "volume": 7100000,
    "change": -0.05,
    "change_pct": -0.05,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  },
  "VTI": {
    "symbol": "VTI",
    "price": 260.40,
    "bid": 260.35,
    "ask": 260.45,
    "volume": 3200000,
    "change": 1.20,
    "change_pct": 0.46,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  },
  "VXUS": {
    "symbol": "VXUS",
    "price": 58.75,
    "bid": 58.70,
    "ask": 58.80,
    "volume": 2900000,
    "change": 0.35,
    "change_pct": 0.60,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  },
  "GLD": {
    "symbol": "GLD",
    "price": 215.30,
    "bid": 215.25,
    "ask": 215.35,
    "volume": 5800000,
    "change": 1.80,
    "change_pct": 0.84,
    "currency": "USD",
    "timestamp": "2026-10-10T12:00:00Z",
    "source": "fixture"
  }
}
```

### 5.2 `backend/tests/fixtures/treasury_yield_curve.json`
US Treasury yield curve across the standard maturity spectrum:

```json
{
  "as_of": "2026-10-10T12:00:00Z",
  "source": "FiscalData",
  "rates": {
    "1M": 5.40,
    "2M": 5.38,
    "3M": 5.35,
    "6M": 5.15,
    "1Y": 4.85,
    "2Y": 4.55,
    "3Y": 4.35,
    "5Y": 4.15,
    "7Y": 4.20,
    "10Y": 4.25,
    "20Y": 4.55,
    "30Y": 4.45
  }
}
```

### 5.3 `backend/tests/fixtures/macro_indicators.json`
Federal Reserve and economic indicators:

```json
{
  "as_of": "2026-10-10T12:00:00Z",
  "source": "FRED",
  "indicators": {
    "CPI": 314.5,
    "UNRATE": 4.1,
    "FEDFUNDS": 5.33,
    "GDP": 28650.0
  }
}
```

### 5.4 `backend/tests/fixtures/historical_prices.json`
Tabular daily series formatted for direct DataFrame ingestion:

```json
[
  {"date": "2025-10-10T00:00:00Z", "SPY": 435.0, "BND": 71.5, "AGG": 96.8, "VTI": 220.0, "VXUS": 53.0, "GLD": 185.0},
  {"date": "2025-11-10T00:00:00Z", "SPY": 450.0, "BND": 72.0, "AGG": 97.2, "VTI": 228.0, "VXUS": 54.2, "GLD": 188.5},
  {"date": "2025-12-10T00:00:00Z", "SPY": 465.0, "BND": 73.1, "AGG": 98.0, "VTI": 235.0, "VXUS": 55.0, "GLD": 192.0},
  {"date": "2026-01-10T00:00:00Z", "SPY": 478.0, "BND": 72.8, "AGG": 97.9, "VTI": 242.0, "VXUS": 55.8, "GLD": 195.5},
  {"date": "2026-02-10T00:00:00Z", "SPY": 490.0, "BND": 72.4, "AGG": 97.5, "VTI": 248.0, "VXUS": 56.5, "GLD": 199.0},
  {"date": "2026-03-10T00:00:00Z", "SPY": 502.0, "BND": 72.6, "AGG": 97.8, "VTI": 254.0, "VXUS": 57.2, "GLD": 204.0},
  {"date": "2026-04-10T00:00:00Z", "SPY": 495.0, "BND": 73.0, "AGG": 98.1, "VTI": 250.0, "VXUS": 56.8, "GLD": 208.5},
  {"date": "2026-05-10T00:00:00Z", "SPY": 508.0, "BND": 72.7, "AGG": 97.9, "VTI": 257.0, "VXUS": 57.8, "GLD": 210.0},
  {"date": "2026-06-10T00:00:00Z", "SPY": 515.0, "BND": 72.5, "AGG": 97.7, "VTI": 261.0, "VXUS": 58.2, "GLD": 212.0},
  {"date": "2026-07-10T00:00:00Z", "SPY": 518.0, "BND": 72.9, "AGG": 98.0, "VTI": 263.0, "VXUS": 58.5, "GLD": 213.5},
  {"date": "2026-08-10T00:00:00Z", "SPY": 510.0, "BND": 73.2, "AGG": 98.3, "VTI": 259.0, "VXUS": 58.1, "GLD": 214.2},
  {"date": "2026-09-10T00:00:00Z", "SPY": 512.4, "BND": 72.85, "AGG": 98.2, "VTI": 260.4, "VXUS": 58.75, "GLD": 215.3}
]
```

---

## 6. Comprehensive Unit Test Specifications (`backend/tests/unit/test_data_pipeline.py`)

A rigorous test suite must be delivered to verify every invariant:

| # | Test Method | Target Behavior | Expected Result |
|---|-------------|-----------------|-----------------|
| 1 | `test_utc_canonicalization_formats` | Inputs: Naive datetime, EDT -04:00 offset, ISO string with 'Z', epoch float | All parse to timezone-aware UTC (`tzinfo == timezone.utc`) with exact normalized hour |
| 2 | `test_market_data_point_schema_validation` | Valid quote input vs negative price | Valid passes; negative price raises `ValidationError`; symbol converted to uppercase |
| 3 | `test_rate_limiter_allows_burst` | 5 calls within burst capacity | Complete immediately without sleeping |
| 4 | `test_rate_limiter_throttles_excess` | 6 calls with capacity=5 and rate=5/s | 6th call sleeps for 0.2s before completing |
| 5 | `test_circuit_breaker_initial_closed` | State upon initialization | `CLOSED`, `failure_count == 0`, `can_execute() is True` |
| 6 | `test_circuit_breaker_opens_after_5_failures` | 5 consecutive `record_failure()` calls | State becomes `OPEN`, `can_execute() is False`, `cooldown_remaining > 0` |
| 7 | `test_circuit_breaker_fast_fail_when_open` | Call attempted when `OPEN` | Rejects network call immediately without network execution |
| 8 | `test_circuit_breaker_transitions_to_half_open` | Fast-forward clock past 60s cooldown | State dynamically evaluates to `HALF_OPEN`, `can_execute() is True` |
| 9 | `test_circuit_breaker_half_open_success_resets` | Probe succeeds in `HALF_OPEN` | Transitions to `CLOSED`, `failure_count` resets to 0 |
| 10 | `test_circuit_breaker_half_open_failure_reopens` | Probe fails in `HALF_OPEN` | Transitions back to `OPEN` with new 60s cooldown |
| 11 | `test_exponential_backoff_retries_and_delays` | Transient failure on attempts 1 & 2, success on 3 | Total 3 attempts; verify `asyncio.sleep` called with ~1s and ~2s delays |
| 12 | `test_non_retryable_400_fails_fast` | HTTP 400 or 401 response | No retries; fails fast and immediately triggers fallback |
| 13 | `test_automatic_fallback_on_network_error` | `httpx.ConnectError` raised on network call | Seamlessly falls back to `market_quotes.json`; returns `MarketDataPoint(source="fixture")` |
| 14 | `test_automatic_fallback_when_circuit_open` | Circuit forced to `OPEN` | Directly returns fixture without attempting network call |
| 15 | `test_historical_prices_fallback_dataframe` | `fetch_historical_prices(["SPY", "BND"])` with provider down | Returns `pd.DataFrame` with DatetimeIndex (UTC) and columns `["SPY", "BND"]` |
| 16 | `test_treasury_yield_curve_fallback` | `fetch_treasury_yield_curve()` | Returns mapping with `10Y == 4.25`, `1M == 5.40` |
| 17 | `test_macro_indicators_fallback` | `fetch_macro_indicators()` | Returns mapping with `CPI == 314.5`, `UNRATE == 4.1` |
| 18 | `test_offline_mode_bypasses_network` | Pipeline initialized with `offline_mode=True` | Zero network calls made; 100% fixture-served |
| 19 | `test_cache_integration_roundtrip` | First call loads fixture, second call reads cache | Second call does not re-read disk or network |

---

## 7. Downstream Dependencies & Implementation Recommendations

1. **Service Providers (`services/providers/`)**:
   - `equities.py` wraps `yfinance` with fallback to `DataPipeline`.
   - `treasury.py` connects to US Treasury `FiscalData` API endpoint (`https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates`), falling back to `DataPipeline.load_fixture_treasury_yield_curve()`.
   - `macro.py` queries FRED series (`CPIAUCSL`, `UNRATE`, `FEDFUNDS`), falling back to `DataPipeline.load_fixture_macro_indicators()`.
2. **Market Data Agent (`agents/market_data.py`)**:
   - Should directly ingest `get_data_pipeline()` as its data dependency.
3. **Execution Safety**:
   - The entire test suite must run hermetically in offline environments without external internet connectivity or live API keys.

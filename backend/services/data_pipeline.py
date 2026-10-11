"""
backend/services/data_pipeline.py
=================================
Resilient, rate-limited, retrying, circuit-broken financial data pipeline
with strict Pydantic v2 schemas and automatic recorded-fixture fallback.
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
from typing import Optional, Dict, List, Any, Callable, Awaitable

import httpx
import pandas as pd
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("wealth_advisor.services.data_pipeline")

# =====================================================================
# 1. UTC Timestamp Canonicalization & Pydantic v2 Schemas
# =====================================================================

def canonicalize_to_utc(val: Any) -> datetime:
    """
    Normalizes any datetime representation to a timezone-aware UTC datetime.
    Supports:
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
    symbol: str = Field(..., description="Normalized uppercase ticker symbol (e.g. SPY)")
    price: float = Field(..., gt=0.0, description="Latest market price in USD")
    bid: Optional[float] = Field(default=None, ge=0.0, description="Current bid price")
    ask: Optional[float] = Field(default=None, ge=0.0, description="Current ask price")
    volume: Optional[int] = Field(default=None, ge=0, description="Daily trading volume")
    change: Optional[float] = Field(default=0.0, description="Absolute price change from prior close")
    change_pct: Optional[float] = Field(default=0.0, description="Percentage change from prior close")
    change_percent: Optional[float] = Field(default=0.0, description="Fractional or percentage change")
    open: Optional[float] = Field(default=None, ge=0.0, description="Session opening price")
    high: Optional[float] = Field(default=None, ge=0.0, description="Session high price")
    low: Optional[float] = Field(default=None, ge=0.0, description="Session low price")
    previous_close: Optional[float] = Field(default=None, ge=0.0, description="Prior close price")
    currency: str = Field(default="USD", description="Quotation currency")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timezone-aware observation timestamp"
    )
    source: str = Field(default="live", description="Origin provider (e.g. yfinance, live, fixture, cache)")

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
    volume: int = Field(default=0, ge=0, description="Trading volume")
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
    rate: float = Field(..., description="Annualized yield in percentage points")
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
    """Aggregate snapshot of the Treasury yield curve."""
    as_of: datetime = Field(..., description="UTC date of the curve snapshot")
    source: str = Field(default="FiscalData")
    rates: Dict[str, float] = Field(..., description="Mapping of tenor -> rate")
    spread_10y_2y: Optional[float] = Field(default=None, description="10Y - 2Y par yield spread")
    spread_10y_3m: Optional[float] = Field(default=None, description="10Y - 3M par yield spread")
    is_inverted: Optional[bool] = Field(default=None, description="Whether curve is inverted (10Y < 2Y)")

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
    regime: Optional[str] = Field(default=None, description="Macroeconomic regime classification")

    @field_validator("as_of", mode="before")
    @classmethod
    def validate_as_of_utc(cls, v: Any) -> datetime:
        return canonicalize_to_utc(v)


# =====================================================================
# 2. Asynchronous Token Bucket Rate Limiter
# =====================================================================

class AsyncRateLimiter:
    """
    Coroutine-safe Token Bucket rate limiter.
    Ensures outbound requests do not exceed specified requests-per-second thresholds.
    """
    def __init__(self, rate_limit_per_sec: float = 5.0, burst_capacity: float = 5.0):
        self.rate = float(rate_limit_per_sec)
        self.capacity = float(burst_capacity)
        self._tokens = float(burst_capacity)
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

            # Sleep outside the lock so other coroutines can compute their wait
            await asyncio.sleep(max(0.001, wait_time))


# =====================================================================
# 3. Circuit Breaker State Machine
# =====================================================================

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
    Transitions:
      CLOSED -> OPEN (after failure_threshold consecutive failures)
      OPEN -> HALF_OPEN (after cooldown_seconds elapsed)
      HALF_OPEN -> CLOSED (if probe succeeds)
      HALF_OPEN -> OPEN (if probe fails)
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


# =====================================================================
# 4. Resilient Execution with Exponential Backoff
# =====================================================================

RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404}


async def execute_with_retry(
    operation: Callable[[], Awaitable[Any]],
    rate_limiter: Optional[AsyncRateLimiter] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    max_retries: int = 3,
    base_interval: float = 1.0,
    jitter: bool = True,
) -> Any:
    """
    Executes an async operation with rate limiting, circuit breaker gating,
    and exponential backoff retry.
    """
    if circuit_breaker and not await circuit_breaker.can_execute():
        raise CircuitBreakerOpenError(
            circuit_breaker.name, circuit_breaker.cooldown_remaining
        )

    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        if rate_limiter:
            await rate_limiter.acquire()

        try:
            result = await operation()
            if circuit_breaker:
                await circuit_breaker.record_success()
            return result
        except httpx.HTTPStatusError as e:
            last_exc = e
            status = e.response.status_code
            if status in NON_RETRYABLE_STATUS_CODES:
                if circuit_breaker:
                    await circuit_breaker.record_failure(e)
                raise
            if status not in RETRYABLE_STATUS_CODES:
                if circuit_breaker:
                    await circuit_breaker.record_failure(e)
                raise
        except (httpx.TimeoutException, httpx.NetworkError, httpx.ConnectError, ConnectionError, TimeoutError) as e:
            last_exc = e
        except Exception as e:
            last_exc = e
            # General unknown errors: fail fast unless custom
            if circuit_breaker:
                await circuit_breaker.record_failure(e)
            raise

        # If we exhausted retries, break
        if attempt == max_retries:
            break

        # Calculate backoff delay
        delay = base_interval * (2 ** attempt)
        if jitter:
            delay += random.uniform(0.05, 0.25)
        logger.warning(
            f"Operation attempt {attempt + 1} failed ({last_exc}). "
            f"Retrying in {delay:.2f}s..."
        )
        await asyncio.sleep(delay)

    # Exhausted all retries
    if circuit_breaker and last_exc:
        await circuit_breaker.record_failure(last_exc)

    raise last_exc or RuntimeError("Operation failed after maximum retries.")


# =====================================================================
# 5. Core Data Pipeline Service
# =====================================================================

class DataPipeline:
    """
    High-reliability, rate-limited, circuit-broken market & macroeconomic data pipeline.
    Automatically degrades to recorded fixtures in backend/tests/fixtures/ on failure or offline mode.
    """
    def __init__(
        self,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        circuit_breaker: Optional[CircuitBreaker] = None,
        fixtures_dir: Optional[Path] = None,
        offline_mode: bool = False,
        http_client: Optional[httpx.AsyncClient] = None,
    ):
        self.rate_limiter = rate_limiter or AsyncRateLimiter(rate_limit_per_sec=5.0, burst_capacity=5.0)
        self.circuit_breaker = circuit_breaker or CircuitBreaker(name="market_data", failure_threshold=5, cooldown_seconds=60.0)
        self.offline_mode = offline_mode
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else (Path(__file__).parents[1] / "tests" / "fixtures")
        self._http_client = http_client
        self._own_client = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._http_client is None or self._http_client.is_closed:
            self._http_client = httpx.AsyncClient(timeout=10.0)
            self._own_client = True
        return self._http_client

    async def close(self) -> None:
        if self._own_client and self._http_client is not None and not self._http_client.is_closed:
            await self._http_client.aclose()

    # --- Recorded Fixture Loaders ---

    def _load_fixture_json(self, filename: str) -> Any:
        path = self.fixtures_dir / filename
        if not path.exists():
            raise FileNotFoundError(f"Fixture file not found: {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _fallback_quote(self, symbol: str) -> MarketDataPoint:
        sym = symbol.strip().upper()
        quotes = self._load_fixture_json("market_quotes.json")
        if sym in quotes:
            raw = dict(quotes[sym])
            raw["source"] = "fixture"
            return MarketDataPoint(**raw)
        # Default baseline quote for unknown symbol
        return MarketDataPoint(
            symbol=sym,
            price=100.0,
            open=100.0,
            high=101.0,
            low=99.0,
            previous_close=100.0,
            change=0.0,
            change_pct=0.0,
            change_percent=0.0,
            volume=1000000,
            source="fixture"
        )

    def _fallback_historical_prices(self, symbols: List[str]) -> pd.DataFrame:
        data = self._load_fixture_json("historical_prices.json")
        records = data.get("records", [])
        if not records:
            raise ValueError("Historical prices fixture contains no records.")
        df = pd.DataFrame(records).set_index("date")
        df.index = pd.to_datetime(df.index, utc=True)
        # Select requested symbols (or available ones)
        requested_upper = [s.strip().upper() for s in symbols]
        available_cols = [c for c in requested_upper if c in df.columns]
        if not available_cols:
            # If none of requested columns exist, return all numeric columns
            available_cols = list(df.columns)
        return df[available_cols].astype(float)

    def _fallback_yield_curve(self) -> Dict[str, float]:
        try:
            data = self._load_fixture_json("treasury_yield_curve.json")
        except FileNotFoundError:
            data = self._load_fixture_json("yield_curve.json")
        return data.get("rates", {})

    def _fallback_macro(self) -> Dict[str, float]:
        data = self._load_fixture_json("macro_indicators.json")
        return data.get("indicators", {})

    # --- Public Pipeline Interface Contracts ---

    async def fetch_market_quote(self, symbol: str) -> MarketDataPoint:
        """
        Fetch latest market quote for an equity or ETF symbol.
        Falls back to recorded fixtures on network error, circuit open, or offline mode.
        """
        sym = symbol.strip().upper()
        if self.offline_mode:
            return self._fallback_quote(sym)

        async def _op() -> MarketDataPoint:
            # Import providers lazily to avoid circular dependencies
            from services.providers.equities import EquitiesProvider
            provider = EquitiesProvider(offline_mode=False, fixtures_dir=self.fixtures_dir)
            data = await provider.get_quote(sym)
            if not isinstance(data, MarketDataPoint):
                return MarketDataPoint(**data)
            return data

        try:
            return await execute_with_retry(
                operation=_op,
                rate_limiter=self.rate_limiter,
                circuit_breaker=self.circuit_breaker,
                max_retries=3,
                base_interval=1.0
            )
        except Exception as e:
            logger.warning(f"fetch_market_quote failed for {sym} ({e}). Degrading to fixture.")
            return self._fallback_quote(sym)

    async def fetch_historical_prices(self, symbols: List[str], period: str = "1y") -> pd.DataFrame:
        """
        Fetch historical daily prices formatted as a pandas DataFrame.
        DataFrame index is UTC DatetimeIndex; columns are uppercase tickers.
        """
        syms = [s.strip().upper() for s in symbols]
        if self.offline_mode:
            return self._fallback_historical_prices(syms)

        async def _op() -> pd.DataFrame:
            from services.providers.equities import EquitiesProvider
            provider = EquitiesProvider(offline_mode=False, fixtures_dir=self.fixtures_dir)
            df = await provider.get_historical_prices(syms, period=period)
            if df is None or df.empty:
                raise ValueError("Empty DataFrame returned from live equities provider.")
            return df

        try:
            return await execute_with_retry(
                operation=_op,
                rate_limiter=self.rate_limiter,
                circuit_breaker=self.circuit_breaker,
                max_retries=3,
                base_interval=1.0
            )
        except Exception as e:
            logger.warning(f"fetch_historical_prices failed for {syms} ({e}). Degrading to fixture.")
            return self._fallback_historical_prices(syms)

    async def fetch_treasury_yield_curve(self) -> Dict[str, float]:
        """
        Fetch US Treasury yield curve as a mapping of tenor -> rate (e.g. {'10Y': 4.50}).
        """
        if self.offline_mode:
            return self._fallback_yield_curve()

        async def _op() -> Dict[str, float]:
            from services.providers.treasury import TreasuryProvider
            provider = TreasuryProvider(
                offline_mode=False,
                fixtures_dir=self.fixtures_dir,
                http_client=await self._get_client()
            )
            return await provider.get_yield_curve()

        try:
            return await execute_with_retry(
                operation=_op,
                rate_limiter=self.rate_limiter,
                circuit_breaker=self.circuit_breaker,
                max_retries=3,
                base_interval=1.0
            )
        except Exception as e:
            logger.warning(f"fetch_treasury_yield_curve failed ({e}). Degrading to fixture.")
            return self._fallback_yield_curve()

    async def fetch_macro_indicators(self) -> Dict[str, float]:
        """
        Fetch macroeconomic indicators (e.g. {'cpi': 3.48, 'unemployment_rate': 3.9, 'fed_funds_rate': 5.33}).
        """
        if self.offline_mode:
            return self._fallback_macro()

        async def _op() -> Dict[str, float]:
            from services.providers.macro import MacroProvider
            provider = MacroProvider(
                offline_mode=False,
                fixtures_dir=self.fixtures_dir,
                http_client=await self._get_client()
            )
            return await provider.get_macro_indicators()

        try:
            return await execute_with_retry(
                operation=_op,
                rate_limiter=self.rate_limiter,
                circuit_breaker=self.circuit_breaker,
                max_retries=3,
                base_interval=1.0
            )
        except Exception as e:
            logger.warning(f"fetch_macro_indicators failed ({e}). Degrading to fixture.")
            return self._fallback_macro()


# Global pipeline instance
_pipeline_instance: Optional[DataPipeline] = None


def get_data_pipeline(offline_mode: bool = False) -> DataPipeline:
    global _pipeline_instance
    if _pipeline_instance is None:
        _pipeline_instance = DataPipeline(offline_mode=offline_mode)
    return _pipeline_instance

"""
backend/tests/unit/test_data_pipeline.py
========================================
Comprehensive unit test suite for resilient data pipeline:
- Pydantic v2 models and strict UTC timestamp canonicalization
- Token bucket AsyncRateLimiter
- CircuitBreaker finite state machine (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Exponential backoff retry mechanics
- Seamless fallback to recorded fixtures
"""

import time
import pytest
import asyncio
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch

import httpx
import pandas as pd
from pydantic import ValidationError

from services.data_pipeline import (
    canonicalize_to_utc,
    MarketDataPoint,
    HistoricalPricePoint,
    YieldCurvePoint,
    YieldCurveData,
    MacroIndicatorPoint,
    MacroData,
    AsyncRateLimiter,
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    execute_with_retry,
    DataPipeline,
    get_data_pipeline,
)


# =====================================================================
# 1. UTC Timestamp Canonicalization & Pydantic Schema Tests
# =====================================================================

def test_canonicalize_to_utc_iso_string():
    # ISO string with trailing Z
    dt1 = canonicalize_to_utc("2026-10-10T12:00:00Z")
    assert dt1.tzinfo == timezone.utc
    assert dt1.year == 2026
    assert dt1.hour == 12

    # ISO string with offset
    dt2 = canonicalize_to_utc("2026-10-10T08:00:00-04:00")
    assert dt2.tzinfo == timezone.utc
    assert dt2.hour == 12  # 08:00 EDT is 12:00 UTC


def test_canonicalize_to_utc_epoch():
    epoch = 1700000000.0
    dt = canonicalize_to_utc(epoch)
    assert dt.tzinfo == timezone.utc
    assert dt == datetime.fromtimestamp(epoch, tz=timezone.utc)


def test_canonicalize_to_utc_naive_datetime():
    naive = datetime(2026, 1, 15, 10, 30, 0)
    aware = canonicalize_to_utc(naive)
    assert aware.tzinfo == timezone.utc
    assert aware.hour == 10


def test_canonicalize_invalid_type_raises():
    with pytest.raises(ValueError, match="Cannot canonicalize"):
        canonicalize_to_utc(["invalid_date"])


def test_market_data_point_valid():
    mdp = MarketDataPoint(
        symbol="spy",
        price=512.50,
        volume=50000000,
        timestamp="2026-10-10T15:00:00Z",
    )
    assert mdp.symbol == "SPY"
    assert mdp.price == 512.50
    assert mdp.timestamp.tzinfo == timezone.utc
    assert mdp.source == "live"


def test_market_data_point_invalid_price():
    with pytest.raises(ValidationError):
        MarketDataPoint(symbol="SPY", price=-10.0)

    with pytest.raises(ValidationError):
        MarketDataPoint(symbol="SPY", price=0.0)


def test_historical_price_point_valid():
    hpp = HistoricalPricePoint(
        symbol="bnd",
        date="2026-10-09",
        open=72.0,
        high=72.5,
        low=71.8,
        close=72.3,
        adjusted_close=72.3,
        volume=3000000,
    )
    assert hpp.symbol == "BND"
    assert hpp.date.tzinfo == timezone.utc
    assert hpp.close == 72.3


def test_yield_curve_data_to_points():
    ycd = YieldCurveData(
        as_of="2026-10-09T00:00:00Z",
        source="FiscalData",
        rates={"1M": 5.48, "10Y": 4.50},
        spread_10y_2y=-0.40,
    )
    points = ycd.to_points()
    assert len(points) == 2
    assert points[0].tenor in ("1M", "10Y")
    assert points[0].date.tzinfo == timezone.utc


def test_macro_indicator_models():
    mip = MacroIndicatorPoint(
        indicator="cpi",
        value=3.48,
        date="2026-10-01"
    )
    assert mip.indicator == "CPI"
    assert mip.date.tzinfo == timezone.utc

    md = MacroData(
        as_of="2026-10-01",
        indicators={"CPI": 3.48, "UNRATE": 3.9}
    )
    assert md.as_of.tzinfo == timezone.utc
    assert len(md.indicators) == 2


# =====================================================================
# 2. Token Bucket AsyncRateLimiter Tests
# =====================================================================

@pytest.mark.asyncio
async def test_rate_limiter_token_burst():
    limiter = AsyncRateLimiter(rate_limit_per_sec=10.0, burst_capacity=3.0)
    start = time.time()
    # Consume burst capacity of 3 tokens immediately
    await limiter.acquire()
    await limiter.acquire()
    await limiter.acquire()
    elapsed = time.time() - start
    assert elapsed < 0.2  # Immediate execution within burst capacity


@pytest.mark.asyncio
async def test_rate_limiter_throttles_excess():
    limiter = AsyncRateLimiter(rate_limit_per_sec=10.0, burst_capacity=1.0)
    await limiter.acquire()  # Consume initial token

    start = time.time()
    await limiter.acquire()  # Must wait for 1 token to refill (~0.1s)
    elapsed = time.time() - start
    assert elapsed >= 0.08


# =====================================================================
# 3. CircuitBreaker State Machine Tests
# =====================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_starts_closed():
    cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=1.0)
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_circuit_breaker_trips_to_open_on_threshold():
    cb = CircuitBreaker(name="test", failure_threshold=3, cooldown_seconds=1.0)
    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 1

    await cb.record_failure()
    assert cb.state == CircuitState.CLOSED

    await cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 3
    assert await cb.can_execute() is False
    assert cb.cooldown_remaining > 0.0


@pytest.mark.asyncio
async def test_circuit_breaker_transitions_to_half_open_after_cooldown():
    cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=0.1)
    await cb.record_failure()
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    # Sleep past the cooldown
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN
    assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_probe_success_resets():
    cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=0.1)
    await cb.record_failure()
    await cb.record_failure()
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    await cb.record_success()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_half_open_probe_failure_reopens():
    cb = CircuitBreaker(name="test", failure_threshold=2, cooldown_seconds=0.1)
    await cb.record_failure()
    await cb.record_failure()
    await asyncio.sleep(0.15)
    assert cb.state == CircuitState.HALF_OPEN

    await cb.record_failure()
    assert cb.state == CircuitState.OPEN


@pytest.mark.asyncio
async def test_circuit_breaker_manual_reset():
    cb = CircuitBreaker(name="test", failure_threshold=1, cooldown_seconds=60.0)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    await cb.reset()
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0


# =====================================================================
# 4. Exponential Backoff & Retry Tests
# =====================================================================

@pytest.mark.asyncio
async def test_execute_with_retry_succeeds_on_first_try():
    mock_op = AsyncMock(return_value="OK")
    result = await execute_with_retry(
        operation=mock_op,
        max_retries=3,
        base_interval=0.01,
        jitter=False
    )
    assert result == "OK"
    assert mock_op.call_count == 1


@pytest.mark.asyncio
async def test_execute_with_retry_retries_transient_error():
    calls = 0

    async def _failing_op():
        nonlocal calls
        calls += 1
        if calls < 3:
            req = httpx.Request("GET", "https://api.example.com")
            resp = httpx.Response(500, request=req)
            raise httpx.HTTPStatusError("Server Error", request=req, response=resp)
        return "SUCCESS"

    result = await execute_with_retry(
        operation=_failing_op,
        max_retries=3,
        base_interval=0.01,
        jitter=False
    )
    assert result == "SUCCESS"
    assert calls == 3


@pytest.mark.asyncio
async def test_execute_with_retry_non_retryable_fails_fast():
    calls = 0

    async def _bad_request_op():
        nonlocal calls
        calls += 1
        req = httpx.Request("GET", "https://api.example.com")
        resp = httpx.Response(400, request=req)
        raise httpx.HTTPStatusError("Bad Request", request=req, response=resp)

    with pytest.raises(httpx.HTTPStatusError):
        await execute_with_retry(
            operation=_bad_request_op,
            max_retries=3,
            base_interval=0.01,
            jitter=False
        )

    assert calls == 1  # No retries on 400


@pytest.mark.asyncio
async def test_execute_with_retry_circuit_breaker_open_raises():
    cb = CircuitBreaker(name="test_cb", failure_threshold=1, cooldown_seconds=60.0)
    await cb.record_failure()
    assert cb.state == CircuitState.OPEN

    mock_op = AsyncMock(return_value="OK")
    with pytest.raises(CircuitBreakerOpenError):
        await execute_with_retry(operation=mock_op, circuit_breaker=cb)


# =====================================================================
# 5. DataPipeline Fallback & Interface Tests
# =====================================================================

@pytest.mark.asyncio
async def test_pipeline_fetch_market_quote_offline_fallback():
    pipeline = DataPipeline(offline_mode=True)
    quote = await pipeline.fetch_market_quote("SPY")
    assert isinstance(quote, MarketDataPoint)
    assert quote.symbol == "SPY"
    assert quote.price > 0.0
    assert quote.source == "fixture"
    assert quote.timestamp.tzinfo == timezone.utc


@pytest.mark.asyncio
async def test_pipeline_fetch_historical_prices_offline_fallback():
    pipeline = DataPipeline(offline_mode=True)
    symbols = ["SPY", "BND", "AGG", "GLD"]
    df = await pipeline.fetch_historical_prices(symbols)
    assert isinstance(df, pd.DataFrame)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None  # Timezone-aware UTC
    assert list(df.columns) == symbols
    assert len(df) == 252
    assert not df.isnull().values.any()


@pytest.mark.asyncio
async def test_pipeline_fetch_treasury_yield_curve_offline_fallback():
    pipeline = DataPipeline(offline_mode=True)
    curve = await pipeline.fetch_treasury_yield_curve()
    assert isinstance(curve, dict)
    assert "10Y" in curve
    assert "2Y" in curve
    assert curve["10Y"] > 0.0


@pytest.mark.asyncio
async def test_pipeline_fetch_macro_indicators_offline_fallback():
    pipeline = DataPipeline(offline_mode=True)
    macro = await pipeline.fetch_macro_indicators()
    assert isinstance(macro, dict)
    assert "cpi" in macro
    assert "unemployment_rate" in macro
    assert "fed_funds_rate" in macro


@pytest.mark.asyncio
async def test_pipeline_degrades_to_fixture_on_live_error():
    # Pipeline in live mode, but live provider raises network failure
    pipeline = DataPipeline(offline_mode=False)

    with patch("services.providers.equities.EquitiesProvider.get_quote", side_effect=ConnectionError("Network Down")):
        quote = await pipeline.fetch_market_quote("BND")
        assert isinstance(quote, MarketDataPoint)
        assert quote.symbol == "BND"
        assert quote.source == "fixture"


@pytest.mark.asyncio
async def test_pipeline_live_routes_success():
    pipeline = DataPipeline(offline_mode=False)

    # 1. Mock live quote
    with patch("services.providers.equities.EquitiesProvider.get_quote", return_value={"symbol": "SPY", "price": 515.0}):
        q = await pipeline.fetch_market_quote("SPY")
        assert q.price == 515.0
        assert q.symbol == "SPY"

    # 2. Mock live history
    mock_df = pd.DataFrame({"SPY": [510.0, 515.0]}, index=pd.date_range("2026-10-08", periods=2, tz=timezone.utc))
    with patch("services.providers.equities.EquitiesProvider.get_historical_prices", return_value=mock_df):
        h_df = await pipeline.fetch_historical_prices(["SPY"])
        assert len(h_df) == 2

    # 3. Mock live treasury
    with patch("services.providers.treasury.TreasuryProvider.get_yield_curve", return_value={"10Y": 4.55}):
        yc = await pipeline.fetch_treasury_yield_curve()
        assert yc["10Y"] == 4.55

    # 4. Mock live macro
    with patch("services.providers.macro.MacroProvider.get_macro_indicators", return_value={"cpi": 3.50}):
        mi = await pipeline.fetch_macro_indicators()
        assert mi["cpi"] == 3.50

    await pipeline.close()


def test_get_data_pipeline_singleton():
    p1 = get_data_pipeline(offline_mode=True)
    p2 = get_data_pipeline(offline_mode=True)
    assert p1 is p2

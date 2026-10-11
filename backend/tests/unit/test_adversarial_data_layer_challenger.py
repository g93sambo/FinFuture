"""
backend/tests/unit/test_adversarial_data_layer_challenger.py
============================================================
Adversarial Stress & Empirical Challenge Suite for Milestone 2 (Data Layer)
Targeting CircuitBreaker and AsyncRateLimiter:
1. Force 5 consecutive errors -> verify state is OPEN.
2. Test requests during OPEN -> verify circuit trips to fallback without calling provider.
3. Fast-forward time past 60s cooldown -> verify transition to HALF_OPEN (including 59.9s boundary).
4. Test recovery on successful probe -> transition to CLOSED.
5. Test failed probe during HALF_OPEN -> immediate re-open & cooldown reset.
6. Stress test AsyncRateLimiter with bursts exceeding capacity (25 concurrent, 100 concurrent).
7. Verify token bucket capacity capping after extended idle periods.
8. End-to-end DataPipeline integration verifying zero provider calls during OPEN.
"""

import time
import asyncio
from datetime import timezone
from unittest.mock import AsyncMock, patch, MagicMock

import httpx
import pytest
import pandas as pd

from services.data_pipeline import (
    AsyncRateLimiter,
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    execute_with_retry,
    DataPipeline,
    MarketDataPoint,
)


# =====================================================================
# 1. CircuitBreaker State Machine & Invariant Tests
# =====================================================================

@pytest.mark.asyncio
async def test_circuit_breaker_exact_threshold_5_errors():
    """
    Empirical challenge: Force exactly 5 consecutive errors on a standard
    CircuitBreaker(failure_threshold=5, cooldown_seconds=60.0).
    Verify state transitions from CLOSED to OPEN exactly on the 5th error.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    # Initial invariant
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert await cb.can_execute() is True

    # Incur 4 consecutive errors: must remain CLOSED
    for i in range(1, 5):
        await cb.record_failure(RuntimeError(f"Error {i}"))
        assert cb.state == CircuitState.CLOSED, f"Circuit unexpectedly changed state on error {i}"
        assert cb.failure_count == i
        assert await cb.can_execute() is True

    # Incur 5th error: must transition to OPEN
    await cb.record_failure(RuntimeError("Error 5"))
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 5
    assert await cb.can_execute() is False
    assert 59.0 <= cb.cooldown_remaining <= 60.0


@pytest.mark.asyncio
async def test_circuit_breaker_partial_failures_reset_on_success():
    """
    Empirical challenge: Consecutive failure counter must reset to 0
    upon a successful execution before reaching threshold.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    # Incur 4 failures (one below threshold)
    for _ in range(4):
        await cb.record_failure(RuntimeError("Transient"))
    assert cb.failure_count == 4
    assert cb.state == CircuitState.CLOSED

    # Successful execution resets count
    await cb.record_success()
    assert cb.failure_count == 0
    assert cb.state == CircuitState.CLOSED

    # Incur another 4 failures: still CLOSED
    for _ in range(4):
        await cb.record_failure(RuntimeError("Transient"))
    assert cb.failure_count == 4
    assert cb.state == CircuitState.CLOSED

    # 5th consecutive failure trips to OPEN
    await cb.record_failure(RuntimeError("5th consecutive"))
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 5


@pytest.mark.asyncio
async def test_circuit_breaker_open_blocks_execution_without_provider_call():
    """
    Empirical challenge: When circuit is OPEN, execute_with_retry must immediately
    raise CircuitBreakerOpenError without invoking the underlying operation.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    # Trip to OPEN
    for _ in range(5):
        await cb.record_failure(RuntimeError("Fail"))
    assert cb.state == CircuitState.OPEN

    mock_provider = AsyncMock()

    with pytest.raises(CircuitBreakerOpenError) as exc_info:
        await execute_with_retry(operation=mock_provider, circuit_breaker=cb)

    assert "is OPEN" in str(exc_info.value)
    # The provider MUST NOT have been called
    assert mock_provider.call_count == 0


@pytest.mark.asyncio
async def test_circuit_breaker_cooldown_boundary_timing():
    """
    Empirical challenge: Fast-forward time past 60s cooldown.
    Verify exact timing boundaries:
    - At t = 59.9s -> state is still OPEN, can_execute() is False.
    - At t = 60.0s -> state is HALF_OPEN, can_execute() is True.
    - At t = 120.0s -> state is HALF_OPEN, can_execute() is True.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    start_time = 1000.0

    with patch("time.time", return_value=start_time):
        for _ in range(5):
            await cb.record_failure(RuntimeError("Fail"))
        assert cb.state == CircuitState.OPEN
        assert cb._opened_at == start_time

    # 1. Test at 59.9s (boundary right before cooldown expires)
    with patch("time.time", return_value=start_time + 59.9):
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False
        assert round(cb.cooldown_remaining, 2) == 0.1

    # 2. Test at exactly 60.0s (exact cooldown boundary)
    with patch("time.time", return_value=start_time + 60.0):
        assert cb.state == CircuitState.HALF_OPEN
        assert await cb.can_execute() is True
        assert cb.cooldown_remaining == 0.0

    # 3. Test well past 60s (e.g. 120s)
    with patch("time.time", return_value=start_time + 120.0):
        assert cb.state == CircuitState.HALF_OPEN
        assert await cb.can_execute() is True
        assert cb.cooldown_remaining == 0.0


@pytest.mark.asyncio
async def test_circuit_breaker_recovery_on_successful_probe():
    """
    Empirical challenge: When HALF_OPEN, a successful probe transitions
    the circuit back to CLOSED, resets failure_count to 0, and clears opened_at.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    start_time = 2000.0
    with patch("time.time", return_value=start_time):
        for _ in range(5):
            await cb.record_failure(RuntimeError("Fail"))
        assert cb.state == CircuitState.OPEN

    # Fast forward past cooldown
    with patch("time.time", return_value=start_time + 65.0):
        assert cb.state == CircuitState.HALF_OPEN

        # Execute probe successfully
        await cb.record_success()

        # Invariants after probe success
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb._opened_at is None
        assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_circuit_breaker_probe_failure_in_half_open_reopens_and_resets_cooldown():
    """
    Empirical challenge: When HALF_OPEN, if the probe operation fails,
    the circuit must immediately transition back to OPEN and restart a full 60s cooldown.
    """
    cb = CircuitBreaker(name="test_cb", failure_threshold=5, cooldown_seconds=60.0)

    t0 = 3000.0
    with patch("time.time", return_value=t0):
        for _ in range(5):
            await cb.record_failure(RuntimeError("Fail"))

    # Move to t0 + 70s (HALF_OPEN)
    t_probe = t0 + 70.0
    with patch("time.time", return_value=t_probe):
        assert cb.state == CircuitState.HALF_OPEN

        # Probe fails
        await cb.record_failure(RuntimeError("Probe network timeout"))

        # Must immediately re-open with new opened_at timestamp
        assert cb.state == CircuitState.OPEN
        assert cb._opened_at == t_probe

    # At t0 + 80s (10s after failed probe), must still be OPEN
    with patch("time.time", return_value=t0 + 80.0):
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False
        assert round(cb.cooldown_remaining, 1) == 50.0

    # At t0 + 130.0s (60s after failed probe), transitions back to HALF_OPEN
    with patch("time.time", return_value=t_probe + 60.0):
        assert cb.state == CircuitState.HALF_OPEN
        assert await cb.can_execute() is True


@pytest.mark.asyncio
async def test_circuit_breaker_concurrent_failure_race():
    """
    Empirical challenge: 50 concurrent coroutines record failure simultaneously.
    Verify circuit breaker lock prevents state corruption or race conditions.
    """
    cb = CircuitBreaker(name="stress_cb", failure_threshold=5, cooldown_seconds=60.0)

    async def _fail(i: int):
        await cb.record_failure(RuntimeError(f"Concurrent failure {i}"))

    await asyncio.gather(*[_fail(i) for i in range(50)])

    assert cb.state == CircuitState.OPEN
    assert cb.failure_count >= 5
    assert await cb.can_execute() is False


# =====================================================================
# 2. AsyncRateLimiter Stress & Adversarial Tests
# =====================================================================

@pytest.mark.asyncio
async def test_rate_limiter_burst_capacity_immediate_consumption():
    """
    Empirical challenge: Requests within burst capacity execute immediately (< 0.05s).
    The very next request must be throttled according to the refill rate.
    """
    limiter = AsyncRateLimiter(rate_limit_per_sec=10.0, burst_capacity=5.0)

    t0 = time.time()
    for _ in range(5):
        await limiter.acquire()
    elapsed_burst = time.time() - t0

    assert elapsed_burst < 0.05, f"Burst of 5 tokens took too long: {elapsed_burst}s"

    # 6th request requires 1 token at 10 tokens/sec = ~0.10s
    t_throttle_start = time.time()
    await limiter.acquire()
    elapsed_throttle = time.time() - t_throttle_start

    assert elapsed_throttle >= 0.08, f"6th request was not throttled: {elapsed_throttle}s"


@pytest.mark.asyncio
async def test_rate_limiter_burst_exceeding_capacity_concurrency_stress():
    """
    Empirical challenge: Launch 25 concurrent requests against a limiter
    with capacity=5.0 and rate=20.0 tokens/sec (5x capacity).
    - 5 requests consume burst capacity at t=0.
    - 20 remaining requests require 20 / 20 = 1.0s of refill time.
    Verify all 25 complete, total time >= 0.90s, and no tokens dropped.
    """
    limiter = AsyncRateLimiter(rate_limit_per_sec=20.0, burst_capacity=5.0)

    completed = 0
    lock = asyncio.Lock()

    async def _worker():
        nonlocal completed
        await limiter.acquire()
        async with lock:
            completed += 1

    t0 = time.time()
    tasks = [_worker() for _ in range(25)]
    await asyncio.gather(*tasks)
    total_elapsed = time.time() - t0

    assert completed == 25
    # Theoretical minimum is 1.0s (20 excess tokens / 20 tokens/sec)
    assert total_elapsed >= 0.88, f"Total elapsed {total_elapsed}s was faster than rate limit permits"


@pytest.mark.asyncio
async def test_rate_limiter_token_accumulation_capped_at_capacity():
    """
    Empirical challenge: After a long idle period, tokens must NOT accumulate
    beyond burst_capacity.
    """
    limiter = AsyncRateLimiter(rate_limit_per_sec=5.0, burst_capacity=5.0)

    # Simulate 60 seconds of idle time
    limiter._last_refill = time.time() - 60.0

    # First 5 should succeed immediately
    t0 = time.time()
    for _ in range(5):
        await limiter.acquire()
    elapsed = time.time() - t0
    assert elapsed < 0.05

    # 6th request must wait for a refill (~0.2s for 1 token at 5/s)
    t1 = time.time()
    await limiter.acquire()
    elapsed_6th = time.time() - t1
    assert elapsed_6th >= 0.16, f"6th request did not throttle after idle: {elapsed_6th}s"


@pytest.mark.asyncio
async def test_rate_limiter_heavy_concurrency_100_workers():
    """
    Empirical challenge: 100 concurrent workers compete for tokens.
    Rate = 50.0 req/s, capacity = 10.0.
    Verify all 100 coroutines complete safely without deadlock or token corruption.
    """
    limiter = AsyncRateLimiter(rate_limit_per_sec=50.0, burst_capacity=10.0)

    order = []
    lock = asyncio.Lock()

    async def _worker(worker_id: int):
        await limiter.acquire()
        async with lock:
            order.append((worker_id, time.time()))

    t0 = time.time()
    await asyncio.gather(*[_worker(i) for i in range(100)])
    elapsed = time.time() - t0

    assert len(order) == 100
    # 90 tokens to generate at 50/s = ~1.8s
    assert elapsed >= 1.6, f"100 requests finished in {elapsed}s, expected >= 1.6s"


# =====================================================================
# 3. DataPipeline End-to-End Resilience & Zero-Provider Invocation
# =====================================================================

@pytest.mark.asyncio
async def test_pipeline_e2e_trip_circuit_and_fixture_fallback_without_calling_provider():
    """
    Empirical challenge: End-to-end integration test with DataPipeline.
    1. Force 5 consecutive errors -> verify circuit breaker trips to OPEN.
    2. Execute requests while circuit is OPEN:
       - Verify returned quote is valid fallback fixture.
       - Verify EquitiesProvider.get_quote is NEVER called while circuit is OPEN.
    3. Fast-forward past 60s cooldown -> state is HALF_OPEN.
    4. Successful execution in HALF_OPEN recovers circuit to CLOSED.
    """
    cb = CircuitBreaker(name="market_data_test", failure_threshold=5, cooldown_seconds=60.0)
    limiter = AsyncRateLimiter(rate_limit_per_sec=100.0, burst_capacity=100.0)
    pipeline = DataPipeline(circuit_breaker=cb, rate_limiter=limiter, offline_mode=False)

    call_count = 0

    async def _failing_get_quote(symbol: str):
        nonlocal call_count
        call_count += 1
        req = httpx.Request("GET", "https://api.example.com")
        resp = httpx.Response(500, request=req)
        raise httpx.HTTPStatusError("Server Error", request=req, response=resp)

    # 1. Force 5 consecutive errors to trip circuit
    with patch("services.providers.equities.EquitiesProvider.get_quote", side_effect=_failing_get_quote):
        for _ in range(5):
            quote = await pipeline.fetch_market_quote("SPY")
            assert quote.symbol == "SPY"
            assert quote.source == "fixture"

    # Circuit breaker must now be OPEN
    assert cb.state == CircuitState.OPEN
    assert cb.failure_count == 5
    # The provider was called during the 5 failures
    assert call_count >= 5
    prior_call_count = call_count

    # 2. Make 10 requests while circuit is OPEN
    # Verify provider is NEVER called
    with patch("services.providers.equities.EquitiesProvider.get_quote", side_effect=_failing_get_quote):
        for _ in range(10):
            fallback_quote = await pipeline.fetch_market_quote("SPY")
            assert fallback_quote.symbol == "SPY"
            assert fallback_quote.source == "fixture"
            assert fallback_quote.price > 0

    # Call count must be EXACTLY unchanged: 0 provider invocations during OPEN!
    assert call_count == prior_call_count, f"Provider was called {call_count - prior_call_count} times while circuit was OPEN!"

    # 3. Fast-forward time past 60s cooldown -> HALF_OPEN
    # Simulate time jump
    cb._opened_at = time.time() - 65.0
    assert cb.state == CircuitState.HALF_OPEN
    assert await cb.can_execute() is True

    # 4. Probe in HALF_OPEN succeeds -> circuit recovers to CLOSED
    async def _successful_get_quote(symbol: str):
        return MarketDataPoint(
            symbol=symbol,
            price=520.0,
            volume=45000000,
            source="live_provider",
            timestamp="2026-10-10T15:00:00Z"
        )

    with patch("services.providers.equities.EquitiesProvider.get_quote", side_effect=_successful_get_quote):
        recovered_quote = await pipeline.fetch_market_quote("SPY")
        assert recovered_quote.price == 520.0
        assert recovered_quote.source == "live_provider"

    # Circuit breaker must be fully recovered to CLOSED
    assert cb.state == CircuitState.CLOSED
    assert cb.failure_count == 0
    assert cb._opened_at is None


@pytest.mark.asyncio
async def test_pipeline_historical_yield_macro_fallback_when_circuit_open():
    """
    Empirical challenge: Verify fetch_historical_prices, fetch_treasury_yield_curve,
    and fetch_macro_indicators all cleanly degrade to valid fixtures when circuit is OPEN,
    without raising exceptions or returning None.
    """
    cb = CircuitBreaker(name="market_data_test", failure_threshold=5, cooldown_seconds=60.0)
    for _ in range(5):
        await cb.record_failure(RuntimeError("Forced"))
    assert cb.state == CircuitState.OPEN

    pipeline = DataPipeline(circuit_breaker=cb, offline_mode=False)

    # 1. Historical prices fallback
    df = await pipeline.fetch_historical_prices(["SPY", "BND", "GLD"])
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 252
    assert list(df.columns) == ["SPY", "BND", "GLD"]
    assert df.index.tz is not None

    # 2. Treasury yield curve fallback
    curve = await pipeline.fetch_treasury_yield_curve()
    assert isinstance(curve, dict)
    assert "10Y" in curve
    assert "2Y" in curve
    assert curve["10Y"] > 0.0

    # 3. Macro indicators fallback
    macro = await pipeline.fetch_macro_indicators()
    assert isinstance(macro, dict)
    assert "cpi" in macro
    assert "unemployment_rate" in macro
    assert "fed_funds_rate" in macro

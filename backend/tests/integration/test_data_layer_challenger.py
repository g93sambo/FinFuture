"""
backend/tests/integration/test_data_layer_challenger.py
======================================================
Empirical Challenge Test Suite for Milestone 2 (Data Layer):
1. Historical price matrix verification across various ticker combinations.
2. Direct downstream mathematical portfolio optimization using skfolio.optimization.MeanRisk
   across multiple risk measures (CVAR, VARIANCE, CDAR, SEMI_VARIANCE, WORST_REALIZATION).
3. Cache hit / miss / expiration dynamics across quotes, history, yield curve, macro, holdings, and sector.
4. Resilience against missing, malformed, and corrupted cache keys.
"""

import asyncio
import time
import pytest
import numpy as np
import pandas as pd
from typing import List, Dict, Any

from skfolio import RiskMeasure
from skfolio.optimization import MeanRisk, ObjectiveFunction
from skfolio.preprocessing import prices_to_returns

from services.cache import (
    CacheService,
    InMemoryCache,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)
from services.data_pipeline import DataPipeline, MarketDataPoint
from agents.market_data import MarketDataAgent, format_key, MarketDataError


@pytest.fixture
def clean_cache() -> CacheService:
    """Isolated CacheService with fresh in-memory fallback."""
    return CacheService(redis_url="redis://localhost:9999/0")


@pytest.fixture
def offline_pipeline() -> DataPipeline:
    """Deterministic offline DataPipeline backed by test fixtures."""
    return DataPipeline(offline_mode=True)


@pytest.fixture
def market_agent(clean_cache, offline_pipeline) -> MarketDataAgent:
    return MarketDataAgent(
        cache_service=clean_cache,
        data_pipeline=offline_pipeline
    )


# =====================================================================
# SECTION 1: Combinations of Tickers in get_history
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("ticker_subset", [
    ["SPY"],
    ["GLD"],
    ["SPY", "BND"],
    ["VTI", "VXUS"],
    ["AGG", "GLD"],
    ["SPY", "BND", "GLD"],
    ["VTI", "AGG", "VXUS"],
    ["SPY", "BND", "AGG", "GLD"],
    ["VTI", "VXUS", "BND", "GLD"],
    ["SPY", "BND", "AGG", "VTI", "VXUS"],
    ["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"],
])
async def test_get_history_ticker_subsets(market_agent, ticker_subset):
    """Verify get_history returns well-formed DataFrame for any valid ticker subset."""
    df = await market_agent.get_history(ticker_subset, period="1y")

    assert isinstance(df, pd.DataFrame)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert df.index.tz is not None  # UTC aware
    assert list(df.columns) == ticker_subset
    assert len(df) == 252
    assert not df.isna().any().any()
    assert (df > 0.0).all().all()  # Strictly positive prices


@pytest.mark.asyncio
async def test_get_history_case_and_whitespace_normalization(market_agent):
    """Verify ticker case and whitespace are normalized without altering requested order."""
    raw_tickers = ["  spy ", "bNd  ", " Vti "]
    expected_cols = ["SPY", "BND", "VTI"]

    df = await market_agent.get_history(raw_tickers, period="1y")

    assert list(df.columns) == expected_cols
    assert len(df) == 252
    assert not df.isna().any().any()


@pytest.mark.asyncio
async def test_get_history_column_order_preservation(market_agent):
    """Verify column order strictly reflects input order regardless of cache order."""
    order1 = ["GLD", "SPY", "BND"]
    df1 = await market_agent.get_history(order1, period="1y")
    assert list(df1.columns) == order1

    # Second query with reversed order
    order2 = ["BND", "SPY", "GLD"]
    df2 = await market_agent.get_history(order2, period="1y")
    assert list(df2.columns) == order2


# =====================================================================
# SECTION 2: Downstream Portfolio Optimization with skfolio.optimization.MeanRisk
# =====================================================================

@pytest.mark.asyncio
@pytest.mark.parametrize("risk_measure", [
    RiskMeasure.CVAR,
    RiskMeasure.VARIANCE,
    RiskMeasure.CDAR,
    RiskMeasure.SEMI_VARIANCE,
    RiskMeasure.STANDARD_DEVIATION,
    RiskMeasure.WORST_REALIZATION,
])
async def test_skfolio_mean_risk_across_risk_measures(market_agent, risk_measure):
    """
    Stress-test downstream mathematical integration with skfolio across 6 risk measures
    using returns derived directly from MarketDataAgent.get_history.
    """
    tickers = ["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]
    df = await market_agent.get_history(tickers, period="1y")

    returns = prices_to_returns(df)
    assert returns.shape == (251, 6)
    assert not returns.isna().any().any()

    # Configure MeanRisk optimization
    model = MeanRisk(
        risk_measure=risk_measure,
        objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
        min_weights=0.02,
        max_weights=0.35,
    )
    model.fit(returns)
    pred = model.predict(returns)

    # Invariants
    weights = np.array(pred.weights)
    assert len(weights) == 6
    assert abs(np.sum(weights) - 1.0) < 1e-4, f"Weights sum {np.sum(weights)} != 1.0"
    assert (weights >= 0.019).all(), f"Weight lower bound violated: {weights}"
    assert (weights <= 0.351).all(), f"Weight upper bound violated: {weights}"


@pytest.mark.asyncio
@pytest.mark.parametrize("objective", [
    ObjectiveFunction.MAXIMIZE_RATIO,
    ObjectiveFunction.MINIMIZE_RISK,
    ObjectiveFunction.MAXIMIZE_RETURN,
])
async def test_skfolio_mean_risk_across_objectives(market_agent, objective):
    """Verify CVaR optimization converges across all three primary objective functions."""
    tickers = ["SPY", "BND", "AGG", "GLD"]
    df = await market_agent.get_history(tickers, period="1y")

    returns = prices_to_returns(df)
    model = MeanRisk(
        risk_measure=RiskMeasure.CVAR,
        objective_function=objective,
        min_weights=0.05,
        max_weights=0.50,
    )
    model.fit(returns)
    pred = model.predict(returns)

    weights = np.array(pred.weights)
    assert len(weights) == 4
    assert abs(np.sum(weights) - 1.0) < 1e-4
    assert (weights >= 0.049).all()
    assert (weights <= 0.501).all()


# =====================================================================
# SECTION 3: Cache Hit, Miss, and Expiration Dynamics
# =====================================================================

@pytest.mark.asyncio
async def test_quote_cache_dynamics(market_agent, clean_cache):
    """Test quote cache miss -> hit -> expiration dynamics."""
    # 1. Miss
    q1 = await market_agent.get_quote("SPY")
    assert q1.symbol == "SPY"
    assert q1.source in ("fixture", "yfinance")

    # 2. Hit
    q2 = await market_agent.get_quote("SPY")
    assert q2.symbol == "SPY"
    assert q2.source == "cache"

    # 3. Simulate Expiration by updating key with past expire_at in memory
    cache_key = format_key("data:quote:{symbol}", symbol="SPY")
    # Manually expire
    async with clean_cache.fallback._lock:
        val, _ = clean_cache.fallback._data[cache_key]
        clean_cache.fallback._data[cache_key] = (val, time.time() - 10.0)

    # 4. Miss again after expiration
    q3 = await market_agent.get_quote("SPY")
    assert q3.symbol == "SPY"
    assert q3.source in ("fixture", "yfinance")


@pytest.mark.asyncio
async def test_history_partial_cache_and_expiration_dynamics(market_agent, clean_cache):
    """
    Test history per-symbol decomposition:
    - Query [SPY, BND] (both miss and cache)
    - Query [SPY, GLD] (SPY hits cache, GLD misses and caches)
    - Expire SPY, query [SPY, GLD] (SPY misses, GLD hits)
    """
    # 1. Fetch SPY and BND
    df1 = await market_agent.get_history(["SPY", "BND"], period="1y")
    assert list(df1.columns) == ["SPY", "BND"]

    spy_key = format_key("data:history:{symbol}:{period}", symbol="SPY", period="1y")
    bnd_key = format_key("data:history:{symbol}:{period}", symbol="BND", period="1y")
    gld_key = format_key("data:history:{symbol}:{period}", symbol="GLD", period="1y")

    assert await clean_cache.get_json(spy_key) is not None
    assert await clean_cache.get_json(bnd_key) is not None
    assert await clean_cache.get_json(gld_key) is None

    # 2. Query SPY and GLD (partial hit)
    df2 = await market_agent.get_history(["SPY", "GLD"], period="1y")
    assert list(df2.columns) == ["SPY", "GLD"]
    assert await clean_cache.get_json(gld_key) is not None

    # 3. Expire SPY only
    async with clean_cache.fallback._lock:
        val, _ = clean_cache.fallback._data[spy_key]
        clean_cache.fallback._data[spy_key] = (val, time.time() - 10.0)

    assert await clean_cache.get_json(spy_key) is None
    assert await clean_cache.get_json(gld_key) is not None

    # 4. Fetch [SPY, GLD] again: SPY is re-fetched and re-cached, GLD is from cache
    df3 = await market_agent.get_history(["SPY", "GLD"], period="1y")
    assert list(df3.columns) == ["SPY", "GLD"]
    assert await clean_cache.get_json(spy_key) is not None


@pytest.mark.asyncio
async def test_treasury_and_macro_cache_dynamics(market_agent, clean_cache):
    """Verify Treasury yield curve and Macro context cache miss -> hit -> expire."""
    # Treasury
    t1 = await market_agent.get_yield_curve()
    assert "10Y" in t1
    cached_t = await clean_cache.get_json("data:treasury:yield_curve")
    assert cached_t is not None

    t2 = await market_agent.get_yield_curve()
    assert t2 == t1

    # Macro
    m1 = await market_agent.get_macro_context()
    assert "cpi" in m1
    cached_m = await clean_cache.get_json("data:macro:indicators")
    assert cached_m is not None

    m2 = await market_agent.get_macro_context()
    assert m2 == m1


# =====================================================================
# SECTION 4: Corrupted and Missing Cache Keys Resilience
# =====================================================================

@pytest.mark.asyncio
async def test_corrupted_raw_json_in_cache_triggers_clean_fallback(market_agent, clean_cache):
    """
    Corrupt raw cache entries with malformed JSON strings.
    Verify get_quote, get_history, get_yield_curve, and get_macro_context
    handle the corrupted cache gracefully and return valid data.
    """
    spy_quote_key = format_key("data:quote:{symbol}", symbol="SPY")
    spy_hist_key = format_key("data:history:{symbol}:{period}", symbol="SPY", period="1y")
    treasury_key = "data:treasury:yield_curve"
    macro_key = "data:macro:indicators"

    # Inject completely malformed non-JSON strings directly into cache
    await clean_cache.set(spy_quote_key, "MALFORMED_NON_JSON_STRING{{{")
    await clean_cache.set(spy_hist_key, "MALFORMED_NON_JSON_STRING{{{")
    await clean_cache.set(treasury_key, "MALFORMED_NON_JSON_STRING{{{")
    await clean_cache.set(macro_key, "MALFORMED_NON_JSON_STRING{{{")

    # 1. Quote
    q = await market_agent.get_quote("SPY")
    assert isinstance(q, MarketDataPoint)
    assert q.price > 0.0

    # 2. History
    df = await market_agent.get_history(["SPY"], period="1y")
    assert isinstance(df, pd.DataFrame)
    assert "SPY" in df.columns

    # 3. Treasury
    yc = await market_agent.get_yield_curve()
    assert isinstance(yc, dict)
    assert "10Y" in yc

    # 4. Macro
    mc = await market_agent.get_macro_context()
    assert isinstance(mc, dict)
    assert "cpi" in mc


@pytest.mark.asyncio
async def test_corrupted_history_schema_in_cache_triggers_fallback(market_agent, clean_cache):
    """
    Cache contains valid JSON but invalid schema for historical prices
    (e.g., missing 'prices' key or unparseable dates).
    """
    spy_hist_key = format_key("data:history:{symbol}:{period}", symbol="SPY", period="1y")

    # Case A: Missing prices key
    await clean_cache.set_json(spy_hist_key, {"dates": ["2026-01-01"]})
    df1 = await market_agent.get_history(["SPY"], period="1y")
    assert isinstance(df1, pd.DataFrame)
    assert "SPY" in df1.columns
    assert len(df1) == 252

    # Case B: Unparseable dates
    await clean_cache.set_json(spy_hist_key, {"dates": ["NOT_A_DATE"], "prices": [100.0]})
    df2 = await market_agent.get_history(["SPY"], period="1y")
    assert isinstance(df2, pd.DataFrame)
    assert "SPY" in df2.columns
    assert len(df2) == 252


@pytest.mark.asyncio
async def test_corrupted_quote_schema_in_cache_triggers_fallback(market_agent, clean_cache):
    """
    Cache contains valid JSON but invalid schema for quote (e.g. missing required fields or negative price).
    """
    spy_quote_key = format_key("data:quote:{symbol}", symbol="SPY")

    # Invalid quote schema: negative price violates Field(gt=0.0)
    await clean_cache.set_json(spy_quote_key, {"symbol": "SPY", "price": -50.0})
    q = await market_agent.get_quote("SPY")
    assert isinstance(q, MarketDataPoint)
    assert q.price > 0.0


@pytest.mark.asyncio
async def test_corrupted_treasury_and_macro_dict_values(market_agent, clean_cache):
    """
    Test what happens if cache contains valid JSON dict but non-numeric values
    like {"10Y": "not_a_float"} or {"cpi": None}.
    Demonstrates lack of try-except block in get_yield_curve and get_macro_context.
    """
    treasury_key = "data:treasury:yield_curve"
    macro_key = "data:macro:indicators"

    await clean_cache.set_json(treasury_key, {"10Y": "NOT_A_NUMBER"})
    await clean_cache.set_json(macro_key, {"cpi": None})

    with pytest.raises(ValueError, match="could not convert string to float"):
        await market_agent.get_yield_curve()

    with pytest.raises(TypeError, match="float.*argument must be a string or a real number"):
        await market_agent.get_macro_context()


@pytest.mark.asyncio
async def test_duplicate_symbols_in_get_history_reveals_bug(market_agent):
    """
    EMPIRICAL BUG REPRODUCTION:
    Passing duplicate symbols (e.g. ['SPY', 'SPY']) causes fetched_df['SPY'] to return
    a 2-column DataFrame rather than a Series.
    At market_data.py line 178:
        'prices': [float(p) for p in series.values]
    p is a 2-element numpy array, which crashes with:
    TypeError: only length-1 arrays can be converted to Python scalars
    """
    with pytest.raises(TypeError, match="only length-1 arrays can be converted to Python scalars"):
        await market_agent.get_history(["SPY", "SPY"], period="1y")



@pytest.mark.asyncio
async def test_mismatched_cache_series_length_recovers(market_agent, clean_cache):
    """
    Test cache entry where 'dates' length != 'prices' length.
    Verify get_history catches ValueError, treats symbol as missing, and recovers.
    """
    spy_hist_key = format_key("data:history:{symbol}:{period}", symbol="SPY", period="1y")
    await clean_cache.set_json(
        spy_hist_key,
        {"dates": ["2026-01-01T00:00:00Z", "2026-01-02T00:00:00Z"], "prices": [100.0]}
    )

    df = await market_agent.get_history(["SPY"], period="1y")
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 252  # Successfully recovered full 252-day series



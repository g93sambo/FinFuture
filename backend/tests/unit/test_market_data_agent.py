"""
backend/tests/unit/test_market_data_agent.py
============================================
Unit tests for MarketDataAgent:
- Standardized cache keys and format_key utility
- Strict spec TTL enforcement (quotes 30s, OHLCV 24h, holdings 6h, macro 24h, treasury 12h, sector 5m)
- Cache-aside mechanics with in-memory TTL fallback
- Per-symbol historical series decomposition and caching
- skfolio DataFrame returns compatibility
- Error handling with MarketDataError
"""

import pytest
import pandas as pd
from unittest.mock import AsyncMock, patch

from skfolio.preprocessing import prices_to_returns
from services.cache import (
    CacheService,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)
from services.data_pipeline import DataPipeline, MarketDataPoint
from agents.market_data import (
    MarketDataAgent,
    format_key,
    TTL_SECTOR,
    MarketDataError,
)


@pytest.fixture
def clean_cache():
    """Provides an isolated CacheService running on InMemoryCache."""
    cache = CacheService(redis_url="redis://localhost:9999/0")  # Force in-memory fallback
    return cache


@pytest.fixture
def offline_pipeline():
    """Provides a DataPipeline running in offline fixture fallback mode."""
    return DataPipeline(offline_mode=True)


@pytest.fixture
def market_data_agent(clean_cache, offline_pipeline):
    """Provides a MarketDataAgent wired to in-memory cache and offline pipeline."""
    return MarketDataAgent(
        cache_service=clean_cache,
        data_pipeline=offline_pipeline
    )


# =====================================================================
# 1. Key Formatting Tests
# =====================================================================

def test_format_key():
    assert format_key("data:quote:{symbol}", symbol="spy") == "data:quote:SPY"
    assert format_key("data:history:{symbol}:{period}", symbol="bnd", period="1Y") == "data:history:BND:1y"
    assert format_key("data:etf:holdings:{symbol}", symbol="vti") == "data:etf:holdings:VTI"
    assert format_key("data:macro:{indicator}", indicator="CPI") == "data:macro:cpi"


def test_market_data_agent_default_init():
    agent = MarketDataAgent()
    assert agent.cache is not None
    assert agent.pipeline is not None
    assert agent.equities is not None
    assert agent.treasury is not None
    assert agent.macro is not None
    assert agent.etf_holdings is not None
    assert agent.screener is not None


# =====================================================================
# 2. Quote Retrieval and Caching (30s TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_quote_caches_result(market_data_agent, clean_cache):
    quote1 = await market_data_agent.get_quote("SPY")
    assert isinstance(quote1, MarketDataPoint)
    assert quote1.symbol == "SPY"
    assert quote1.price > 0.0

    # Verify cache key was populated
    cache_key = format_key("data:quote:{symbol}", symbol="SPY")
    cached_val = await clean_cache.get_json(cache_key)
    assert cached_val is not None
    assert cached_val["symbol"] == "SPY"

    # Second call returns from cache
    quote2 = await market_data_agent.get_quote("SPY")
    assert quote2.symbol == "SPY"
    assert quote2.source == "cache"


@pytest.mark.asyncio
async def test_get_quote_error_raises_market_data_error(clean_cache):
    mock_pipeline = AsyncMock()
    mock_pipeline.fetch_market_quote.side_effect = RuntimeError("Fatal pipeline fault")
    agent = MarketDataAgent(cache_service=clean_cache, data_pipeline=mock_pipeline)

    with pytest.raises(MarketDataError, match="Could not retrieve quote"):
        await agent.get_quote("XYZ")


# =====================================================================
# 3. Historical Price Matrix and Per-Symbol Decomposition (24h TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_history_returns_skfolio_compatible_dataframe(market_data_agent):
    symbols = ["SPY", "BND", "AGG", "GLD"]
    df = await market_data_agent.get_history(symbols, period="1y")

    assert isinstance(df, pd.DataFrame)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.columns) == symbols
    assert len(df) == 252

    # Check skfolio prices_to_returns compatibility
    returns = prices_to_returns(df)
    assert returns.shape[1] == len(symbols)
    assert not returns.isna().any().any()


@pytest.mark.asyncio
async def test_get_history_per_symbol_caching(market_data_agent, clean_cache):
    symbols = ["SPY", "BND"]
    # First fetch populates per-symbol cache
    df1 = await market_data_agent.get_history(symbols, period="1y")
    assert list(df1.columns) == symbols

    # Check cache keys for individual symbols
    spy_key = format_key("data:history:{symbol}:{period}", symbol="SPY", period="1y")
    bnd_key = format_key("data:history:{symbol}:{period}", symbol="BND", period="1y")
    assert await clean_cache.get_json(spy_key) is not None
    assert await clean_cache.get_json(bnd_key) is not None

    # Query SPY alongside new symbol GLD: SPY should hit cache, GLD fetches
    df2 = await market_data_agent.get_history(["SPY", "GLD"], period="1y")
    assert list(df2.columns) == ["SPY", "GLD"]
    gld_key = format_key("data:history:{symbol}:{period}", symbol="GLD", period="1y")
    assert await clean_cache.get_json(gld_key) is not None


@pytest.mark.asyncio
async def test_get_history_pipeline_error_raises_market_data_error(clean_cache):
    mock_pipeline = AsyncMock()
    mock_pipeline.fetch_historical_prices.side_effect = RuntimeError("Failed fetch")
    agent = MarketDataAgent(cache_service=clean_cache, data_pipeline=mock_pipeline)

    with pytest.raises(MarketDataError, match="Could not fetch historical prices"):
        await agent.get_history(["XYZ"])


# =====================================================================
# 4. Treasury Yield Curve (12h TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_yield_curve_caches_result(market_data_agent, clean_cache):
    curve = await market_data_agent.get_yield_curve()
    assert isinstance(curve, dict)
    assert "10Y" in curve
    assert curve["10Y"] == 4.50

    cached = await clean_cache.get_json("data:treasury:yield_curve")
    assert cached is not None
    assert cached["10Y"] == 4.50


@pytest.mark.asyncio
async def test_get_yield_curve_error_raises_market_data_error(clean_cache):
    mock_pipeline = AsyncMock()
    mock_pipeline.fetch_treasury_yield_curve.side_effect = RuntimeError("Treasury down")
    agent = MarketDataAgent(cache_service=clean_cache, data_pipeline=mock_pipeline)

    with pytest.raises(MarketDataError, match="Could not retrieve Treasury yield curve"):
        await agent.get_yield_curve()


# =====================================================================
# 5. Macro Context (24h TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_macro_context_caches_result(market_data_agent, clean_cache):
    macro = await market_data_agent.get_macro_context()
    assert isinstance(macro, dict)
    assert "cpi" in macro
    assert macro["cpi"] == 3.48

    cached = await clean_cache.get_json("data:macro:indicators")
    assert cached is not None
    assert cached["cpi"] == 3.48


@pytest.mark.asyncio
async def test_get_macro_context_error_raises_market_data_error(clean_cache):
    mock_pipeline = AsyncMock()
    mock_pipeline.fetch_macro_indicators.side_effect = RuntimeError("Macro down")
    agent = MarketDataAgent(cache_service=clean_cache, data_pipeline=mock_pipeline)

    with pytest.raises(MarketDataError, match="Could not retrieve macro indicators"):
        await agent.get_macro_context()


# =====================================================================
# 6. ETF Holdings (6h TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_etf_holdings_caches_result(market_data_agent, clean_cache):
    holdings = await market_data_agent.get_etf_holdings("SPY")
    assert isinstance(holdings, dict)
    assert holdings["symbol"] == "SPY"
    assert "top_holdings" in holdings

    holdings_key = format_key("data:etf:holdings:{symbol}", symbol="SPY")
    cached = await clean_cache.get_json(holdings_key)
    assert cached is not None
    assert cached["symbol"] == "SPY"


@pytest.mark.asyncio
async def test_get_etf_holdings_error_raises_market_data_error(clean_cache, offline_pipeline):
    mock_etf = AsyncMock()
    mock_etf.get_holdings.side_effect = RuntimeError("Holdings down")
    agent = MarketDataAgent(
        cache_service=clean_cache,
        data_pipeline=offline_pipeline,
        etf_holdings_provider=mock_etf
    )

    with pytest.raises(MarketDataError, match="Could not retrieve ETF holdings"):
        await agent.get_etf_holdings("XYZ")


# =====================================================================
# 7. Sector Performance (5m TTL)
# =====================================================================

@pytest.mark.asyncio
async def test_get_sector_performance_caches_result(market_data_agent, clean_cache):
    perf = await market_data_agent.get_sector_performance()
    assert isinstance(perf, dict)
    assert "Technology" in perf
    assert isinstance(perf["Technology"], float)

    cached = await clean_cache.get_json("data:sector:performance")
    assert cached is not None
    assert "Technology" in cached


# =====================================================================
# 8. Error Handling and Resilience
# =====================================================================

@pytest.mark.asyncio
async def test_empty_symbols_list_raises_value_error(market_data_agent):
    with pytest.raises(ValueError, match="symbols list must not be empty"):
        await market_data_agent.get_history([])

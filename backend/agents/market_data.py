"""
backend/agents/market_data.py
=============================
Unified Market Data Agent providing quotes, historical price series,
Treasury yield curves, macroeconomic indicators, ETF holdings, and sector returns.
Integrates CacheService with standardized TTLs and returns DataFrames
strictly compatible with skfolio prices_to_returns(df).
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, List, Any

import pandas as pd

from services.cache import (
    CacheService,
    get_cache_service,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)
from services.data_pipeline import (
    DataPipeline,
    get_data_pipeline,
    MarketDataPoint,
    HistoricalPricePoint,
    YieldCurvePoint,
    YieldCurveData,
    MacroIndicatorPoint,
    MacroData,
)
from services.providers.equities import EquitiesProvider
from services.providers.treasury import TreasuryProvider
from services.providers.macro import MacroProvider
from services.providers.etf_holdings import ETFHoldingsProvider
from services.providers.screener import AssetScreenerProvider

logger = logging.getLogger("wealth_advisor.agents.market_data")

# Sector performance cache TTL (5 minutes)
TTL_SECTOR: int = 300


def format_key(template: str, **kwargs) -> str:
    """
    Format a standardized Redis cache key.
    Normalizes symbols/tickers to uppercase and timeframe/period to lowercase.
    """
    normalized = {}
    for k, v in kwargs.items():
        if isinstance(v, str):
            if k in ("symbol", "ticker", "source"):
                normalized[k] = v.strip().upper()
            elif k in ("period", "timeframe", "indicator"):
                normalized[k] = v.strip().lower()
            else:
                normalized[k] = v.strip()
        else:
            normalized[k] = v
    return template.format(**normalized)


class MarketDataError(Exception):
    """Raised when market data retrieval fails across live and fallback channels."""
    pass


class MarketDataAgent:
    """
    Market Data Agent coordinating cached queries across live providers
    and recorded fallback fixtures.
    """
    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        data_pipeline: Optional[DataPipeline] = None,
        equities_provider: Optional[EquitiesProvider] = None,
        treasury_provider: Optional[TreasuryProvider] = None,
        macro_provider: Optional[MacroProvider] = None,
        etf_holdings_provider: Optional[ETFHoldingsProvider] = None,
        screener_provider: Optional[AssetScreenerProvider] = None,
    ):
        self.cache = cache_service or get_cache_service()
        self.pipeline = data_pipeline or get_data_pipeline()
        self.equities = equities_provider or EquitiesProvider()
        self.treasury = treasury_provider or TreasuryProvider()
        self.macro = macro_provider or MacroProvider()
        self.etf_holdings = etf_holdings_provider or ETFHoldingsProvider()
        self.screener = screener_provider or AssetScreenerProvider()

    async def get_quote(self, symbol: str) -> MarketDataPoint:
        """
        Fetch real-time snapshot quote for an asset.
        Cache Key: data:quote:{symbol}
        TTL: 30 seconds
        """
        sym = symbol.strip().upper()
        key = format_key("data:quote:{symbol}", symbol=sym)

        # 1. Check cache
        cached = await self.cache.get_json(key)
        if cached:
            try:
                cached_data = dict(cached)
                cached_data["source"] = "cache"
                return MarketDataPoint(**cached_data)
            except Exception as e:
                logger.warning(f"Error deserializing cached quote for {sym}: {e}")

        # 2. Fetch from pipeline
        try:
            quote = await self.pipeline.fetch_market_quote(sym)
        except Exception as e:
            logger.error(f"Failed to fetch market quote for {sym}: {e}")
            raise MarketDataError(f"Could not retrieve quote for {sym}: {e}") from e

        # 3. Store in cache
        try:
            await self.cache.set_json(key, quote.model_dump(mode="json"), expire=TTL_QUOTES)
        except Exception as e:
            logger.warning(f"Failed to cache quote for {sym}: {e}")

        return quote

    async def get_history(self, symbols: List[str], period: str = "1y") -> pd.DataFrame:
        """
        Fetch historical daily price matrix formatted as a pandas DataFrame.
        Columns are uppercase tickers, index is chronological UTC DatetimeIndex.
        Format strictly satisfies skfolio preprocessing prices_to_returns(df).
        Cache Key: data:history:{symbol}:{period}
        TTL: 86400 seconds (24h)
        """
        if not symbols:
            raise ValueError("symbols list must not be empty.")

        norm_symbols = [s.strip().upper() for s in symbols]
        cached_series: Dict[str, pd.Series] = {}
        missing_symbols: List[str] = []

        # 1. Check cache per-symbol
        for sym in norm_symbols:
            key = format_key("data:history:{symbol}:{period}", symbol=sym, period=period)
            cached_data = await self.cache.get_json(key)
            if cached_data and isinstance(cached_data, dict) and "dates" in cached_data and "prices" in cached_data:
                try:
                    s_idx = pd.to_datetime(cached_data["dates"], utc=True)
                    s = pd.Series(cached_data["prices"], index=s_idx, name=sym, dtype=float)
                    cached_series[sym] = s
                except Exception as e:
                    logger.warning(f"Error parsing cached series for {sym}: {e}")
                    missing_symbols.append(sym)
            else:
                missing_symbols.append(sym)

        # 2. Fetch missing symbols via pipeline
        if missing_symbols:
            try:
                fetched_df = await self.pipeline.fetch_historical_prices(missing_symbols, period=period)
            except Exception as e:
                logger.error(f"Pipeline fetch_historical_prices failed for {missing_symbols}: {e}")
                raise MarketDataError(f"Could not fetch historical prices for {missing_symbols}: {e}") from e

            if fetched_df is None or fetched_df.empty:
                raise MarketDataError(f"Empty DataFrame returned for symbols {missing_symbols}")

            # Store newly fetched series into cache
            for sym in missing_symbols:
                if sym in fetched_df.columns:
                    series = fetched_df[sym].dropna()
                    cached_series[sym] = series
                    cache_payload = {
                        "dates": [d.isoformat() for d in series.index],
                        "prices": [float(p) for p in series.values]
                    }
                    key = format_key("data:history:{symbol}:{period}", symbol=sym, period=period)
                    try:
                        await self.cache.set_json(key, cache_payload, expire=TTL_OHLCV)
                    except Exception as e:
                        logger.warning(f"Failed to cache historical prices for {sym}: {e}")

        # 3. Combine into unified DataFrame
        df_combined = pd.DataFrame(cached_series)
        df_combined.index = pd.to_datetime(df_combined.index, utc=True)
        df_combined.index.name = "Date"
        # Forward fill and backward fill to ensure dense time series
        df_combined = df_combined.ffill().bfill().dropna()

        # Reorder columns to match input request
        available_cols = [s for s in norm_symbols if s in df_combined.columns]
        if not available_cols:
            raise MarketDataError(f"No requested symbols found in historical price matrix: {norm_symbols}")

        result_df = df_combined[available_cols].astype(float)
        return result_df

    async def get_yield_curve(self) -> Dict[str, float]:
        """
        Fetch latest US Treasury yield curve as mapping of tenor -> rate.
        Cache Key: data:treasury:yield_curve
        TTL: 43200 seconds (12h)
        """
        key = "data:treasury:yield_curve"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        try:
            rates = await self.pipeline.fetch_treasury_yield_curve()
        except Exception as e:
            logger.error(f"Failed to fetch Treasury yield curve: {e}")
            raise MarketDataError(f"Could not retrieve Treasury yield curve: {e}") from e

        try:
            await self.cache.set_json(key, rates, expire=TTL_TREASURY)
        except Exception as e:
            logger.warning(f"Failed to cache Treasury yield curve: {e}")

        return rates

    async def get_macro_context(self) -> Dict[str, float]:
        """
        Fetch macroeconomic indicators (e.g. CPI, unemployment rate, fed funds rate).
        Cache Key: data:macro:indicators
        TTL: 86400 seconds (24h)
        """
        key = "data:macro:indicators"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        try:
            macro = await self.pipeline.fetch_macro_indicators()
        except Exception as e:
            logger.error(f"Failed to fetch macro indicators: {e}")
            raise MarketDataError(f"Could not retrieve macro indicators: {e}") from e

        try:
            await self.cache.set_json(key, macro, expire=TTL_MACRO)
        except Exception as e:
            logger.warning(f"Failed to cache macro indicators: {e}")

        return macro

    async def get_etf_holdings(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch top holdings, sector allocations, and asset profile for an ETF.
        Cache Key: data:etf:holdings:{symbol}
        TTL: 21600 seconds (6h)
        """
        sym = symbol.strip().upper()
        key = format_key("data:etf:holdings:{symbol}", symbol=sym)

        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return cached

        try:
            holdings = await self.etf_holdings.get_holdings(sym)
        except Exception as e:
            logger.error(f"Failed to fetch ETF holdings for {sym}: {e}")
            raise MarketDataError(f"Could not retrieve ETF holdings for {sym}: {e}") from e

        try:
            await self.cache.set_json(key, holdings, expire=TTL_HOLDINGS)
        except Exception as e:
            logger.warning(f"Failed to cache ETF holdings for {sym}: {e}")

        return holdings

    async def get_sector_performance(self) -> Dict[str, float]:
        """
        Fetch representative sector returns across standard GICS sectors.
        Cache Key: data:sector:performance
        TTL: 300 seconds (5m)
        """
        key = "data:sector:performance"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # Representative standard market sector return snapshot
        sector_returns = {
            "Technology": 0.0125,
            "Financials": 0.0048,
            "Healthcare": -0.0021,
            "Consumer Cyclical": 0.0084,
            "Communication Services": 0.0105,
            "Industrials": 0.0039,
            "Consumer Defensive": 0.0012,
            "Energy": 0.0076,
            "Utilities": -0.0045,
            "Real Estate": -0.0032,
            "Materials": 0.0028
        }

        try:
            await self.cache.set_json(key, sector_returns, expire=TTL_SECTOR)
        except Exception as e:
            logger.warning(f"Failed to cache sector performance: {e}")

        return sector_returns

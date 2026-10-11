# Milestone 2 Analysis Report: MarketDataAgent Design & Integration

**Target Component:** `backend/agents/market_data.py`  
**Author:** Explorer 3 (`teamwork_preview_explorer_m2_3`)  
**Milestone:** Milestone 2 (Data Layer)  
**Parent Orchestrator:** `498f461a-015a-42ad-98d2-3a9070fe1d9a`  
**Date:** 2026-10-10  

---

## 1. Executive Summary & Architectural Overview

The **MarketDataAgent** serves as the unified data access gateway for all quantitative, advisory, and execution agents in the Wealth Advisory System. It abstracts the complexities of heterogeneous external financial APIs (yfinance, US Treasury FiscalData REST API, FRED/CalcFi macro data, ETF providers) and provides high-performance, resilient, and type-safe data access.

### 1.1 Architectural Role & Interactions
In the system topology:
- **Upstream Consumers:**
  - `agents/allocation_engine.py`: Consumes historical price DataFrames (`get_history`) for skfolio CVaR optimization, covariance matrices, and efficient frontier calculations.
  - `agents/product_comparison.py`: Consumes live quotes (`get_quote`), ETF holdings (`get_etf_holdings`), and historical price series to evaluate six-factor composite scores ($w = 0.30, 0.15, 0.20, 0.10, 0.15, 0.10$).
  - `services/health_report.py`: Consumes live quotes (`get_quote`) and macro context (`get_macro_context`) to evaluate the 5% portfolio drift threshold, benchmark relative performance, and macro shift triggers.
  - `agents/orchestrator.py` & `api/routes/market.py`: Exposes REST endpoints (`GET /api/v1/market/quote/{symbol}`, `GET /api/v1/market/macro`, `GET /api/v1/market/yield-curve`, `GET /api/v1/market/sector-performance`) and injects real-time market context into client chat sessions.
- **Downstream Collaborators:**
  - `services/cache.py` (`CacheService`): Dual-layer caching (Redis with transparent in-memory TTL dictionary fallback) using standard key formatting templates and strict TTL enforcement.
  - `services/data_pipeline.py` (`DataPipeline`): Rate-limited async HTTP transport, exponential backoff (3 retries, 1s base interval), and circuit breaker (5 failures / 60s cooldown).
  - `services/providers/` (`EquitiesProvider`, `TreasuryProvider`, `MacroProvider`, `ETFHoldingsProvider`): Domain-specific fetching logic with automated fallback to recorded test fixtures in `backend/tests/fixtures/`.

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Consumers of Market Data                        │
│   AllocationEngine  │  ProductComparison  │  HealthReport  │  Routes   │
└──────────────────────────────────┬─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 backend/agents/market_data.py                         │
│                     class MarketDataAgent                              │
│                                                                        │
│  - get_quote(symbol)                     -> MarketDataPoint (TTL 30s)  │
│  - get_history(symbols, period)          -> pd.DataFrame    (TTL 24h)  │
│  - get_yield_curve()                     -> Dict[str, float] (TTL 12h) │
│  - get_macro_context()                   -> Dict[str, float] (TTL 24h) │
│  - get_etf_holdings(symbol)              -> Dict[str, float] (TTL 6h)  │
│  - get_sector_performance()              -> Dict[str, float] (TTL 5m)  │
└──────────────┬──────────────────────────────────────────┬──────────────┘
               │ Cache-Aside                              │ Miss / Fetch
               ▼                                          ▼
┌──────────────────────────────┐        ┌────────────────────────────────┐
│   services/cache.py          │        │ services/data_pipeline.py      │
│   CacheService               │        │   Rate Limit + Exponential     │
│   - Redis                    │        │   Backoff + Circuit Breaker    │
│   - In-Memory Fallback       │        └──────────────┬─────────────────┘
│   - format_key(...)          │                       │
└──────────────────────────────┘                       ▼
                                        ┌────────────────────────────────┐
                                        │ services/providers/            │
                                        │ - equities.py (yfinance)       │
                                        │ - treasury.py (FiscalData)     │
                                        │ - macro.py (FRED / CalcFi)     │
                                        │ - etf_holdings.py              │
                                        │ - offline fixtures fallback    │
                                        └────────────────────────────────┘
```

---

## 2. Interface Contracts & Data Schemas

### 2.1 Pydantic Model: `MarketDataPoint`
Defined canonically in `backend/models/market.py` (and re-exported by `services/data_pipeline.py` and `agents/market_data.py`):

```python
from datetime import datetime, timezone
from typing import Optional
from pydantic import BaseModel, Field

class MarketDataPoint(BaseModel):
    """
    Standardized live market quote data point with UTC timestamp canonicalization.
    """
    symbol: str = Field(..., description="Normalized uppercase ticker symbol, e.g. SPY")
    price: float = Field(..., gt=0.0, description="Current market price in USD")
    change: float = Field(default=0.0, description="Absolute price change since previous close")
    change_percent: float = Field(default=0.0, description="Percentage change in price (e.g. 0.015 for +1.5%)")
    volume: Optional[int] = Field(default=None, description="Trading volume for current session")
    high: Optional[float] = Field(default=None, description="Session high price")
    low: Optional[float] = Field(default=None, description="Session low price")
    open: Optional[float] = Field(default=None, description="Session opening price")
    previous_close: Optional[float] = Field(default=None, description="Previous session closing price")
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC canonicalized timestamp of quote generation"
    )
    currency: str = Field(default="USD", description="Currency ISO code")
    source: str = Field(default="live", description="Data origin: live, yfinance, cache, or fixture")
```

### 2.2 Historical Price DataFrame Specification
The return type of `get_history(symbols: List[str], period: str = "1y") -> pd.DataFrame` must adhere to strict invariants required by quantitative libraries (`skfolio`, `scikit-learn`, `numpy`):
- **Index**: Chronological `pd.DatetimeIndex` (UTC, daily frequency, sorted in ascending order).
- **Columns**: Normalized uppercase ticker symbols matching `symbols` (e.g. `['SPY', 'BND', 'AGG', 'VTI', 'VXUS', 'GLD']`).
- **Values**: Floating point adjusted close prices (or close prices), with zero negative values.
- **Missing Data Handling**: Forward-filled (`ffill()`) then back-filled (`bfill()`) to align varying asset trading calendars (e.g. bond market holidays vs equity market holidays).

---

## 3. Standard Key Formatting & `services.cache.format_key`

### 3.1 Standard Key Templates & TTL Constants
Per the authoritative specification, the following key formats and TTLs are required:

| Data Element | Cache Key Pattern | TTL (Seconds) | TTL (Human) | Constant Name |
|---|---|---|---|---|
| Live Quote | `data:quote:{symbol}` | 30 | 30s | `TTL_QUOTES` |
| Historical Prices | `data:history:{symbol}:{period}` | 86400 | 24h | `TTL_OHLCV` |
| Treasury Yield Curve | `data:treasury:yield_curve` | 43200 | 12h | `TTL_TREASURY` |
| Macro Indicators | `data:macro:indicators` | 86400 | 24h | `TTL_MACRO` |
| ETF Holdings | `data:etf:holdings:{symbol}` | 21600 | 6h | `TTL_HOLDINGS` |
| Sector Performance | `data:sector:performance` | 300 | 5m | `TTL_SECTOR` |

### 3.2 Key Formatter Function in `backend/services/cache.py`
To satisfy the requirement `Standard key formatting using services.cache.format_key`, the following utility function is specified for addition to `backend/services/cache.py`:

```python
def format_key(template: str, **kwargs) -> str:
    """
    Format a standardized Redis cache key.
    Automatically normalizes symbols/tickers to uppercase and indicators/periods to lowercase.
    
    Examples:
        format_key("data:quote:{symbol}", symbol="spy") -> "data:quote:SPY"
        format_key("data:history:{symbol}:{period}", symbol="bnd", period="1Y") -> "data:history:BND:1y"
        format_key("data:etf:holdings:{symbol}", symbol="vti") -> "data:etf:holdings:VTI"
        format_key("data:macro:{indicator}", indicator="CPI") -> "data:macro:cpi"
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
```

In `backend/agents/market_data.py`, this function is imported directly:
```python
from services.cache import (
    CacheService,
    get_cache_service,
    format_key,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)
```

---

## 4. Complete Design of `backend/agents/market_data.py`

Below is the complete, production-ready design for `backend/agents/market_data.py`.

```python
"""
backend/agents/market_data.py
=============================
Market Data Agent: Unified interface for quotes, price history, yield curve,
macro context, ETF holdings, and sector performance.
Integrates DataPipeline, domain providers, and dual-layer CacheService.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Any, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

# Cache service imports
from services.cache import (
    CacheService,
    get_cache_service,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)

# Robust import of format_key with internal fallback
try:
    from services.cache import format_key
except ImportError:
    def format_key(template: str, **kwargs) -> str:
        normalized = {
            k: (v.strip().upper() if k in ("symbol", "ticker") and isinstance(v, str) else 
                v.strip().lower() if k in ("period", "timeframe", "indicator") and isinstance(v, str) else v)
            for k, v in kwargs.items()
        }
        return template.format(**normalized)

logger = logging.getLogger("wealth_advisor.agents.market_data")

# --- Standard Cache Key Templates ---
KEY_QUOTE = "data:quote:{symbol}"
KEY_HISTORY = "data:history:{symbol}:{period}"
KEY_TREASURY_YIELD_CURVE = "data:treasury:yield_curve"
KEY_MACRO_INDICATORS = "data:macro:indicators"
KEY_ETF_HOLDINGS = "data:etf:holdings:{symbol}"
KEY_SECTOR_PERFORMANCE = "data:sector:performance"
TTL_SECTOR = 300  # 5 minutes for sector performance


class MarketDataPoint(BaseModel):
    """
    Normalized live quote structure with UTC timestamp canonicalization.
    """
    symbol: str
    price: float
    change: float = 0.0
    change_percent: float = 0.0
    volume: Optional[int] = None
    high: Optional[float] = None
    low: Optional[float] = None
    open: Optional[float] = None
    previous_close: Optional[float] = None
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    currency: str = "USD"
    source: str = "live"


class MarketDataError(Exception):
    """Base exception for MarketDataAgent operations."""
    pass


class MarketDataAgent:
    """
    Unified Market Data Agent.
    
    Coordinates between external data pipelines, domain providers, and caching.
    Guarantees resilient fallback to offline recorded fixtures when providers are offline.
    """

    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        data_pipeline: Optional[Any] = None,
        equities_provider: Optional[Any] = None,
        treasury_provider: Optional[Any] = None,
        macro_provider: Optional[Any] = None,
        etf_provider: Optional[Any] = None,
        fixtures_dir: Optional[Union[str, Path]] = None,
    ):
        """
        Initialize the MarketDataAgent with optional dependency injection.
        """
        self.cache: CacheService = cache_service or get_cache_service()
        self.pipeline = data_pipeline
        self.equities = equities_provider
        self.treasury = treasury_provider
        self.macro = macro_provider
        self.etf = etf_provider
        
        # Fixtures directory for offline fallback
        if fixtures_dir:
            self.fixtures_dir = Path(fixtures_dir)
        else:
            self.fixtures_dir = Path(__file__).resolve().parent.parent / "tests" / "fixtures"

    # -------------------------------------------------------------------------
    # Helper: Fixture Loader
    # -------------------------------------------------------------------------
    def _load_fixture(self, filename: str) -> Optional[Any]:
        """Load a JSON fixture from the fixtures directory."""
        path = self.fixtures_dir / filename
        if not path.is_file():
            logger.debug(f"Fixture file not found: {path}")
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.warning(f"Failed to load fixture {filename}: {e}")
            return None

    # -------------------------------------------------------------------------
    # 1. get_quote
    # -------------------------------------------------------------------------
    async def get_quote(self, symbol: str) -> MarketDataPoint:
        """
        Retrieve live market quote for a symbol.
        Cached with 30s TTL under key 'data:quote:{symbol}'.
        Falls back to recorded fixtures on provider failure.
        """
        if not symbol or not symbol.strip():
            raise MarketDataError("Symbol cannot be empty.")
            
        sym = symbol.strip().upper()
        cache_key = format_key(KEY_QUOTE, symbol=sym)

        # 1. Check Cache
        cached_raw = await self.cache.get(cache_key)
        if cached_raw is not None:
            try:
                data = json.loads(cached_raw)
                return MarketDataPoint.model_validate(data)
            except Exception as e:
                logger.warning(f"Failed to deserialize cached quote for {sym}: {e}")

        # 2. Cache Miss - Fetch from Pipeline / Provider
        data_point: Optional[MarketDataPoint] = None
        
        try:
            if self.pipeline and hasattr(self.pipeline, "fetch_market_quote"):
                data_point = await self.pipeline.fetch_market_quote(sym)
            elif self.equities and hasattr(self.equities, "get_quote"):
                data_point = await self.equities.get_quote(sym)
            else:
                # Lazy instantiation fallback if pipeline not injected
                from services.data_pipeline import DataPipeline
                pipeline = DataPipeline()
                data_point = await pipeline.fetch_market_quote(sym)
        except Exception as e:
            logger.warning(f"Error fetching quote for {sym} from external pipeline: {e}. Attempting fixture fallback.")

        # 3. Fixture Fallback if fetch failed or returned None
        if data_point is None:
            data_point = self._fallback_quote(sym)

        # 4. Populate Cache (30s TTL)
        if data_point is not None:
            try:
                payload = data_point.model_dump_json()
                await self.cache.set(cache_key, payload, expire=TTL_QUOTES)
            except Exception as e:
                logger.warning(f"Failed to cache quote for {sym}: {e}")
            return data_point

        raise MarketDataError(f"Market quote unavailable for symbol '{sym}'")

    def _fallback_quote(self, symbol: str) -> Optional[MarketDataPoint]:
        """Extract quote from offline fixtures or baseline catalog."""
        fixtures = self._load_fixture("market_quotes.json")
        if fixtures and symbol in fixtures:
            item = fixtures[symbol]
            return MarketDataPoint(
                symbol=symbol,
                price=float(item.get("price", 100.0)),
                change=float(item.get("change", 0.0)),
                change_percent=float(item.get("change_percent", 0.0)),
                volume=item.get("volume"),
                high=item.get("high"),
                low=item.get("low"),
                open=item.get("open"),
                previous_close=item.get("previous_close"),
                currency=item.get("currency", "USD"),
                source="fixture"
            )

        # Default fallback prices for standard core portfolio universe
        baseline_prices = {
            "SPY": 510.50,
            "BND": 72.80,
            "AGG": 98.25,
            "VTI": 255.40,
            "VXUS": 58.60,
            "GLD": 215.10,
        }
        if symbol in baseline_prices:
            return MarketDataPoint(
                symbol=symbol,
                price=baseline_prices[symbol],
                change=0.0,
                change_percent=0.0,
                source="fixture_baseline"
            )
        return None

    # -------------------------------------------------------------------------
    # 2. get_history
    # -------------------------------------------------------------------------
    async def get_history(self, symbols: List[str], period: str = "1y") -> pd.DataFrame:
        """
        Retrieve historical price DataFrame for a list of symbols over a period.
        Cached per symbol with 24h TTL under 'data:history:{symbol}:{period}'.
        Returns a DataFrame indexed by date with columns matching symbols.
        """
        if not symbols:
            return pd.DataFrame()

        clean_symbols = list(dict.fromkeys(s.strip().upper() for s in symbols if s.strip()))
        period_clean = period.strip().lower()

        cached_series: Dict[str, pd.Series] = {}
        missing_symbols: List[str] = []

        # 1. Per-Symbol Cache Check
        for sym in clean_symbols:
            cache_key = format_key(KEY_HISTORY, symbol=sym, period=period_clean)
            cached_data = await self.cache.get_json(cache_key)
            if cached_data and isinstance(cached_data, dict):
                try:
                    dates = pd.to_datetime(cached_data["dates"])
                    prices = np.array(cached_data["prices"], dtype=float)
                    series = pd.Series(prices, index=dates, name=sym)
                    cached_series[sym] = series
                except Exception as e:
                    logger.warning(f"Failed to reconstruct cached history for {sym}: {e}")
                    missing_symbols.append(sym)
            else:
                missing_symbols.append(sym)

        # 2. Fetch Missing Symbols
        if missing_symbols:
            fetched_df: Optional[pd.DataFrame] = None
            try:
                if self.pipeline and hasattr(self.pipeline, "fetch_historical_prices"):
                    fetched_df = await self.pipeline.fetch_historical_prices(missing_symbols, period=period_clean)
                elif self.equities and hasattr(self.equities, "get_history"):
                    fetched_df = await self.equities.get_history(missing_symbols, period=period_clean)
                else:
                    from services.data_pipeline import DataPipeline
                    pipeline = DataPipeline()
                    fetched_df = await pipeline.fetch_historical_prices(missing_symbols, period=period_clean)
            except Exception as e:
                logger.warning(f"Error fetching historical prices for {missing_symbols}: {e}. Trying fixture fallback.")

            # Fallback to fixtures for missing symbols
            if fetched_df is None or fetched_df.empty:
                fetched_df = self._fallback_history(missing_symbols, period_clean)

            # Process and cache each fetched symbol
            if fetched_df is not None and not fetched_df.empty:
                for sym in missing_symbols:
                    if sym in fetched_df.columns:
                        s = fetched_df[sym].dropna()
                        cached_series[sym] = s
                        # Store in cache with 24h TTL
                        try:
                            payload = {
                                "dates": [d.strftime("%Y-%m-%d") for d in s.index],
                                "prices": [float(p) for p in s.values]
                            }
                            cache_key = format_key(KEY_HISTORY, symbol=sym, period=period_clean)
                            await self.cache.set_json(cache_key, payload, expire=TTL_OHLCV)
                        except Exception as e:
                            logger.warning(f"Failed to cache history for {sym}: {e}")

        # 3. Assemble Unified DataFrame
        if not cached_series:
            logger.error(f"No historical price data could be resolved for symbols: {clean_symbols}")
            return pd.DataFrame()

        df = pd.DataFrame(cached_series)
        df.sort_index(inplace=True)
        # Ensure DatetimeIndex
        if not isinstance(df.index, pd.DatetimeIndex):
            df.index = pd.to_datetime(df.index)
        
        # Fill trading calendar mismatches (e.g. bonds vs stocks)
        df = df.ffill().bfill()
        return df

    def _fallback_history(self, symbols: List[str], period: str) -> pd.DataFrame:
        """Load historical price series from offline fixtures."""
        fixtures = self._load_fixture("historical_prices.json")
        if not fixtures or not isinstance(fixtures, dict):
            # Generate synthetic realistic random walk fallback if no fixture exists
            return self._generate_synthetic_history(symbols, days=252)

        data = {}
        for sym in symbols:
            if sym in fixtures:
                item = fixtures[sym]
                dates = pd.to_datetime(item.get("dates", []))
                prices = np.array(item.get("prices", []), dtype=float)
                data[sym] = pd.Series(prices, index=dates)

        if data:
            return pd.DataFrame(data).ffill().bfill()
        return self._generate_synthetic_history(symbols, days=252)

    def _generate_synthetic_history(self, symbols: List[str], days: int = 252) -> pd.DataFrame:
        """Deterministic baseline historical prices for testing and offline resilience."""
        dates = pd.date_range(end=datetime.now(timezone.utc), periods=days, freq="B")
        np.random.seed(42)
        data = {}
        base_prices = {"SPY": 500.0, "BND": 75.0, "AGG": 100.0, "VTI": 250.0, "VXUS": 60.0, "GLD": 200.0}
        for sym in symbols:
            start_p = base_prices.get(sym, 100.0)
            daily_returns = np.random.normal(0.0003, 0.01, size=days)
            price_curve = start_p * np.exp(np.cumsum(daily_returns))
            data[sym] = pd.Series(price_curve, index=dates)
        return pd.DataFrame(data)

    # -------------------------------------------------------------------------
    # 3. get_yield_curve
    # -------------------------------------------------------------------------
    async def get_yield_curve(self) -> Dict[str, float]:
        """
        Retrieve current US Treasury Par Yield Curve rates (maturities -> yield percent).
        Cached with 12h TTL under 'data:treasury:yield_curve'.
        """
        cache_key = KEY_TREASURY_YIELD_CURVE

        # 1. Check Cache
        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # 2. Fetch from Pipeline / Provider
        yield_data: Optional[Dict[str, float]] = None
        try:
            if self.pipeline and hasattr(self.pipeline, "fetch_treasury_yield_curve"):
                yield_data = await self.pipeline.fetch_treasury_yield_curve()
            elif self.treasury and hasattr(self.treasury, "get_yield_curve"):
                yield_data = await self.treasury.get_yield_curve()
            else:
                from services.data_pipeline import DataPipeline
                pipeline = DataPipeline()
                yield_data = await pipeline.fetch_treasury_yield_curve()
        except Exception as e:
            logger.warning(f"Error fetching Treasury yield curve: {e}. Falling back to fixtures.")

        # 3. Fixture Fallback
        if not yield_data:
            fixture = self._load_fixture("yield_curve.json")
            if fixture and isinstance(fixture, dict):
                yield_data = {str(k): float(v) for k, v in fixture.items()}
            else:
                # Baseline 2026 Treasury par rates
                yield_data = {
                    "1M": 5.40,
                    "3M": 5.38,
                    "6M": 5.25,
                    "1Y": 4.95,
                    "2Y": 4.60,
                    "5Y": 4.25,
                    "10Y": 4.30,
                    "30Y": 4.45
                }

        # 4. Cache (12h TTL)
        try:
            await self.cache.set_json(cache_key, yield_data, expire=TTL_TREASURY)
        except Exception as e:
            logger.warning(f"Failed to cache Treasury yield curve: {e}")

        return yield_data

    # -------------------------------------------------------------------------
    # 4. get_macro_context
    # -------------------------------------------------------------------------
    async def get_macro_context(self) -> Dict[str, float]:
        """
        Retrieve macroeconomic indicators (CPI, unemployment rate, fed funds rate, GDP).
        Cached with 24h TTL under 'data:macro:indicators'.
        """
        cache_key = KEY_MACRO_INDICATORS

        # 1. Check Cache
        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # 2. Fetch from Pipeline / Provider
        macro_data: Optional[Dict[str, float]] = None
        try:
            if self.pipeline and hasattr(self.pipeline, "fetch_macro_indicators"):
                macro_data = await self.pipeline.fetch_macro_indicators()
            elif self.macro and hasattr(self.macro, "get_macro_context"):
                macro_data = await self.macro.get_macro_context()
            else:
                from services.data_pipeline import DataPipeline
                pipeline = DataPipeline()
                macro_data = await pipeline.fetch_macro_indicators()
        except Exception as e:
            logger.warning(f"Error fetching macro indicators: {e}. Falling back to fixtures.")

        # 3. Fixture Fallback
        if not macro_data:
            fixture = self._load_fixture("macro_indicators.json")
            if fixture and isinstance(fixture, dict):
                macro_data = {str(k): float(v) for k, v in fixture.items()}
            else:
                macro_data = {
                    "cpi": 3.2,
                    "unemployment_rate": 4.1,
                    "fed_funds_rate": 5.25,
                    "gdp_growth": 2.1,
                    "inflation_expectation": 2.8
                }

        # 4. Cache (24h TTL)
        try:
            await self.cache.set_json(cache_key, macro_data, expire=TTL_MACRO)
        except Exception as e:
            logger.warning(f"Failed to cache macro context: {e}")

        return macro_data

    # -------------------------------------------------------------------------
    # 5. get_etf_holdings
    # -------------------------------------------------------------------------
    async def get_etf_holdings(self, symbol: str) -> Dict[str, float]:
        """
        Retrieve top holdings and portfolio weights for an ETF ticker.
        Cached with 6h TTL under 'data:etf:holdings:{symbol}'.
        """
        if not symbol or not symbol.strip():
            raise MarketDataError("Symbol cannot be empty.")

        sym = symbol.strip().upper()
        cache_key = format_key(KEY_ETF_HOLDINGS, symbol=sym)

        # 1. Check Cache
        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # 2. Fetch from Pipeline / Provider
        holdings: Optional[Dict[str, float]] = None
        try:
            if self.etf and hasattr(self.etf, "get_holdings"):
                holdings = await self.etf.get_holdings(sym)
            elif self.pipeline and hasattr(self.pipeline, "fetch_etf_holdings"):
                holdings = await self.pipeline.fetch_etf_holdings(sym)
            else:
                # Provider lookup
                from services.providers.etf_holdings import ETFHoldingsProvider
                provider = ETFHoldingsProvider()
                holdings = await provider.get_holdings(sym)
        except Exception as e:
            logger.warning(f"Error fetching ETF holdings for {sym}: {e}. Falling back to fixtures.")

        # 3. Fixture Fallback
        if not holdings:
            fixture = self._load_fixture("etf_holdings.json")
            if fixture and isinstance(fixture, dict) and sym in fixture:
                holdings = {str(k): float(v) for k, v in fixture[sym].items()}
            else:
                # Default baseline holdings for major ETFs
                holdings = self._baseline_holdings(sym)

        # 4. Cache (6h TTL)
        try:
            await self.cache.set_json(cache_key, holdings, expire=TTL_HOLDINGS)
        except Exception as e:
            logger.warning(f"Failed to cache ETF holdings for {sym}: {e}")

        return holdings

    def _baseline_holdings(self, symbol: str) -> Dict[str, float]:
        """Baseline portfolio weight distributions for key ETFs."""
        if symbol == "SPY":
            return {
                "MSFT": 0.071,
                "AAPL": 0.065,
                "NVDA": 0.052,
                "AMZN": 0.038,
                "META": 0.024,
                "GOOGL": 0.021,
                "GOOG": 0.018,
                "BRK.B": 0.017,
                "AVGO": 0.016,
                "JPM": 0.013
            }
        elif symbol == "BND":
            return {
                "US_TREASURY_NOTE": 0.450,
                "US_TREASURY_BOND": 0.220,
                "MORTGAGE_BACKED_PASS_THROUGH": 0.210,
                "CORPORATE_AAA_AA": 0.080,
                "CORPORATE_A_BBB": 0.040
            }
        elif symbol == "GLD":
            return {"PHYSICAL_GOLD_BULLION": 1.00}
        return {}

    # -------------------------------------------------------------------------
    # 6. get_sector_performance
    # -------------------------------------------------------------------------
    async def get_sector_performance(self) -> Dict[str, float]:
        """
        Retrieve daily percentage performance across all major US S&P sectors.
        Cached with 5m TTL under 'data:sector:performance'.
        """
        cache_key = KEY_SECTOR_PERFORMANCE

        # 1. Check Cache
        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # 2. Fetch from Pipeline / Provider or Calculate from Sector ETFs
        sector_perf: Optional[Dict[str, float]] = None
        try:
            if self.pipeline and hasattr(self.pipeline, "fetch_sector_performance"):
                sector_perf = await self.pipeline.fetch_sector_performance()
            else:
                # Calculate from sector SPDR ETFs
                sector_etf_map = {
                    "technology": "XLK",
                    "financials": "XLF",
                    "healthcare": "XLV",
                    "consumer_discretionary": "XLY",
                    "communication_services": "XLC",
                    "industrials": "XLI",
                    "consumer_staples": "XLP",
                    "energy": "XLE",
                    "utilities": "XLU",
                    "real_estate": "XLRE",
                    "materials": "XLB",
                }
                computed = {}
                for sector, ticker in sector_etf_map.items():
                    try:
                        q = await self.get_quote(ticker)
                        computed[sector] = q.change_percent
                    except Exception:
                        pass
                if len(computed) >= 5:
                    sector_perf = computed
        except Exception as e:
            logger.warning(f"Error resolving sector performance: {e}. Falling back to fixtures.")

        # 3. Fixture Fallback
        if not sector_perf:
            fixture = self._load_fixture("sector_performance.json")
            if fixture and isinstance(fixture, dict):
                sector_perf = {str(k): float(v) for k, v in fixture.items()}
            else:
                sector_perf = {
                    "technology": 0.014,
                    "financials": -0.003,
                    "healthcare": 0.005,
                    "consumer_discretionary": 0.008,
                    "communication_services": 0.011,
                    "industrials": 0.002,
                    "consumer_staples": -0.001,
                    "energy": -0.012,
                    "utilities": -0.004,
                    "real_estate": 0.003,
                    "materials": 0.001
                }

        # 4. Cache (5m TTL)
        try:
            await self.cache.set_json(cache_key, sector_perf, expire=TTL_SECTOR)
        except Exception as e:
            logger.warning(f"Failed to cache sector performance: {e}")

        return sector_perf
```

---

## 5. Integration with DataPipeline and Providers

### 5.1 Pipeline Contract
`backend/services/data_pipeline.py` (designed by Explorer 1) exposes the following asynchronous signatures:
- `fetch_market_quote(symbol: str) -> MarketDataPoint`:
  - Executes rate-limited async HTTP request.
  - Applies 3 retries with 1s exponential backoff (`tenacity` or custom async retry).
  - Subject to circuit breaker: 5 consecutive failures trips breaker to `OPEN` for 60s cooldown.
  - Returns `MarketDataPoint` validated with Pydantic.
- `fetch_historical_prices(symbols: List[str], period: str = "1y") -> pd.DataFrame`:
  - Returns a multi-asset `pd.DataFrame` with daily dates as index and tickers as columns.
- `fetch_treasury_yield_curve() -> Dict[str, float]`:
  - Queries US Treasury FiscalData REST endpoint or Treasury provider.
- `fetch_macro_indicators() -> Dict[str, float]`:
  - Queries FRED API or CalcFi datasets.

### 5.2 Pluggable Provider Architecture
`backend/services/providers/` (designed by Explorer 2) contains specialized providers:
- `equities.py`: `EquitiesProvider` using `yfinance` in an `asyncio.to_thread` executor for non-blocking I/O.
- `treasury.py`: `TreasuryProvider` handling FiscalData REST pagination and rate limits.
- `macro.py`: `MacroProvider` querying FRED or CalcFi series.
- `etf_holdings.py`: `ETFHoldingsProvider` querying top constituent weights and sector distributions.

`MarketDataAgent` accepts any of these providers via its constructor (`__init__`), making unit testing, mock injection, and live operation cleanly decoupled.

---

## 6. Caching Strategy & Redis/InMemory Dual Fallback

### 6.1 Multi-Tier Transparent Caching
1. **Tier 1 (Redis)**: When `REDIS_URL` is accessible, `CacheService` performs atomic `get`, `set` with TTL, and JSON operations directly against Redis.
2. **Tier 2 (In-Memory Fallback)**: If Redis is offline, unreachable, or fails with a socket error, `CacheService` seamlessly switches to `InMemoryCache` without throwing errors or dropping requests.
3. **Cache-Aside Pattern**:
   - `MarketDataAgent` checks the cache first using normalized keys (`format_key`).
   - On cache hit: Return immediately, avoiding external network overhead and rate limit exhaustion.
   - On cache miss: Query external pipeline/provider, store result in cache with specified TTL, and return.

### 6.2 Granular History Caching Design
A critical design achievement is the **per-symbol decomposition** in `get_history(symbols: List[str], period: str)`:
- Instead of caching the joint query `data:history:SPY_BND_GLD:1y` (which cannot be reused if another query asks for `SPY_AGG:1y`), each asset is cached independently under `data:history:{symbol}:{period}`.
- If a client requests `["SPY", "BND", "GLD"]` and `SPY` was previously queried, `MarketDataAgent`:
  1. Retrieves `SPY` from cache instantly.
  2. Queries the pipeline only for missing assets `["BND", "GLD"]`.
  3. Caches `BND` and `GLD` individually.
  4. Merges all three series into the unified `pd.DataFrame`.
This maximizes cache hit ratios and minimizes external API calls across diverse client portfolios.

---

## 7. Error Handling, Resilience & Offline Fixture Fallback

### 7.1 Resilience Hierarchy
```
1. Cache Hit (Redis or InMemory) ──> Return Valid Data
       │
       ▼ (Cache Miss)
2. External Pipeline / Provider ────> Return & Cache
       │
       ▼ (Timeout, Rate Limit, Circuit Breaker OPEN, 5xx HTTP)
3. Offline Fixture Fallback ───────> Load tests/fixtures/*.json ──> Return & Cache
       │
       ▼ (Fixture Missing or Unknown Symbol)
4. Baseline Catalog ───────────────> Return Known Baseline / Raise MarketDataError
```

### 7.2 Offline Recorded Fixtures in `backend/tests/fixtures/`
Explorer 2 specifies the fixture files; `MarketDataAgent` consumes them via `_load_fixture`:
- `market_quotes.json`: Contains pre-recorded quotes for `SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`.
- `historical_prices.json`: Contains 1-year daily close series for the same core universe.
- `yield_curve.json`: US Treasury curve maturities (`1M` to `30Y`).
- `macro_indicators.json`: `cpi`, `unemployment_rate`, `fed_funds_rate`, `gdp_growth`.
- `etf_holdings.json`: Top 10 holdings for `SPY`, `BND`, `VTI`.
- `sector_performance.json`: 11 S&P sector daily percentage changes.

---

## 8. Unit Test Specifications

The unit test suite for `MarketDataAgent` will be located in `backend/tests/unit/test_market_data_agent.py`. Below is the complete test specification:

### Test Cases
1. `test_quote_cache_hit`: Verifies that a pre-cached quote returns immediately without invoking the data pipeline.
2. `test_quote_cache_miss_and_sets_ttl`: Verifies that on cache miss, the pipeline is queried, the returned `MarketDataPoint` is cached with a 30s TTL (`TTL_QUOTES`), and subsequent calls hit the cache.
3. `test_quote_symbol_normalization`: Verifies that `"spy"`, `"SPY"`, and `" SPY "` all map to the cache key `data:quote:SPY`.
4. `test_quote_fixture_fallback_on_pipeline_failure`: Mocks the pipeline raising `RuntimeError("Circuit Breaker OPEN")` and verifies that `MarketDataAgent` falls back to the recorded fixture without raising an unhandled exception.
5. `test_history_per_symbol_caching`: Verifies that `get_history(["SPY", "BND"], "1y")` generates distinct cache keys `data:history:SPY:1y` and `data:history:BND:1y` with 24h TTL.
6. `test_history_partial_cache_hit`: Verifies that when `SPY` is cached and `BND` is missing, only `BND` is fetched from the pipeline, and the returned DataFrame contains both.
7. `test_history_dataframe_invariants`: Verifies that the returned DataFrame has a `pd.DatetimeIndex`, float values, no NaNs, and matches the format required by `AllocationEngine`.
8. `test_yield_curve_caching_and_ttl`: Verifies that `get_yield_curve()` caches under `data:treasury:yield_curve` with 12h TTL (`TTL_TREASURY`).
9. `test_macro_context_caching_and_ttl`: Verifies that `get_macro_context()` caches under `data:macro:indicators` with 24h TTL (`TTL_MACRO`).
10. `test_etf_holdings_caching_and_normalization`: Verifies that `get_etf_holdings("spy")` queries `data:etf:holdings:SPY` with 6h TTL (`TTL_HOLDINGS`).
11. `test_sector_performance_caching`: Verifies caching under `data:sector:performance` with 5m TTL.
12. `test_in_memory_cache_fallback`: Tests full agent operation using `CacheService` with an invalid Redis URL to guarantee 100% operation on in-memory fallback.

---

## 9. Verification & Migration Checklist for Implementers

- [ ] Add `format_key` function and standard key templates to `backend/services/cache.py`.
- [ ] Implement `MarketDataAgent` in `backend/agents/market_data.py` according to this specification.
- [ ] Ensure `backend/tests/fixtures/` contains `market_quotes.json`, `historical_prices.json`, `yield_curve.json`, `macro_indicators.json`, `etf_holdings.json`, `sector_performance.json`.
- [ ] Implement `backend/tests/unit/test_market_data_agent.py` covering all 12 test specifications.
- [ ] Verify seamless interoperability with `backend/agents/allocation_engine.py` (`prices_to_returns(df)`).
- [ ] Wire `MarketDataAgent` into `backend/api/routes/market.py` to replace placeholder mocks.

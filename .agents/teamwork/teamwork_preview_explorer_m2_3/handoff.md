# Handoff Report: MarketDataAgent Design & Integration Specification

**Role:** Explorer 3 (`teamwork_preview_explorer_m2_3`)  
**Milestone:** Milestone 2 (Data Layer)  
**Parent Orchestrator:** `498f461a-015a-42ad-98d2-3a9070fe1d9a`  
**Date:** 2026-10-10  
**Type:** Hard Handoff (Investigation & Design Complete)

---

## 1. Observation

1. **System & Requirements Directives**:
   - `ORIGINAL_REQUEST.md` (lines 13-14): Specifies Milestone 2 Data Layer as: *"Rate-limited, retrying, circuit-broken pipeline with providers for equities/ETFs (yfinance), Treasury (FiscalData), macro (FRED/CalcFi) and recorded-fixture fallback; unified schemas; TTLs per spec."*
   - `orchestrator/PROJECT.md` (lines 83-89): Defines interface contract between `services/data_pipeline.py` and `agents/market_data.py`:
     - `async fetch_market_quote(symbol: str) -> MarketDataPoint`
     - `async fetch_historical_prices(symbols: List[str], period: str = "1y") -> pd.DataFrame`
     - `async fetch_treasury_yield_curve() -> Dict[str, float]`
     - `async fetch_macro_indicators() -> Dict[str, float]`
     - All methods implement 3 retries (1s backoff), circuit breaker (5 failures / 60s cooldown), and fallback to `tests/fixtures/`.
   - `orchestrator/PROJECT.md` (lines 12, 148-158): Shows existing `main.py` routes currently return hard-coded mocks (`GET /api/v1/market/quote/{symbol}` returning price 150.0; `GET /api/v1/market/macro` returning fixed CPI 3.2), which must be replaced by real agent queries.

2. **Cache Service Implementation (`backend/services/cache.py`)**:
   - Lines 27-35 define standard TTL constants:
     - `TTL_QUOTES: int = 30` (30s)
     - `TTL_TRADE_LOCK: int = 30` (30s)
     - `TTL_PROFILE_DRAFT: int = 3600` (1h)
     - `TTL_HOLDINGS: int = 21600` (6h)
     - `TTL_TREASURY: int = 43200` (12h)
     - `TTL_OHLCV: int = 86400` (24h)
     - `TTL_MACRO: int = 86400` (24h)
     - `TTL_SESSION: int = 86400` (24h)
   - Lines 122-269 implement `CacheService` with dual-backend support: attempts Redis first; falls back transparently to `InMemoryCache` with TTL expiration dictionary when Redis is offline or throws connection errors.
   - Lines 240-252 provide built-in `get_json(key)` and `set_json(key, value, expire)`.
   - Lines 38-68 implement individual key functions (`key_quote`, `key_ohlcv`, `key_holdings`, etc.), but `format_key(template, **kwargs)` is not yet defined in `cache.py`.

3. **Downstream Consumer Requirements (`backend/agents/allocation_engine.py`)**:
   - Lines 26-28:
     ```python
     returns = prices_to_returns(price_dataframe)
     asset_symbols = returns.columns.tolist()
     ```
     Demands that `get_history(...)` returns a `pd.DataFrame` indexed chronologically by `pd.DatetimeIndex` with column names matching asset ticker strings and non-null numeric prices.

---

## 2. Logic Chain

1. **Cache-Aside Architecture & TTL Alignment**:
   - From Observation 1 & 2, `MarketDataAgent` must enforce strict caching rules:
     - Quotes: 30s TTL (`TTL_QUOTES`), key `data:quote:{symbol}`
     - History: 24h TTL (`TTL_OHLCV`), key `data:history:{symbol}:{period}`
     - Yield Curve: 12h TTL (`TTL_TREASURY`), key `data:treasury:yield_curve`
     - Macro Context: 24h TTL (`TTL_MACRO`), key `data:macro:indicators`
     - ETF Holdings: 6h TTL (`TTL_HOLDINGS`), key `data:etf:holdings:{symbol}`
     - Sector Performance: 5m TTL (`TTL_SECTOR` = 300s), key `data:sector:performance`
   - Key formatting must use a standardized formatter. Because `format_key` is specified in dispatch but currently absent in `cache.py`, the design defines `format_key(template: str, **kwargs)` with automatic uppercase ticker and lowercase parameter normalization, and embeds an internal fallback in `market_data.py` to ensure zero import fragility.

2. **Per-Symbol Decomposition in `get_history`**:
   - A naive implementation would cache multi-symbol queries together under `data:history:SPY_BND:1y`.
   - However, diverse portfolio queries (e.g. `[SPY, BND]`, `[SPY, GLD]`, `[VTI, BND]`) would result in cache misses and redundant external fetches for repeated assets like `SPY`.
   - By decomposing `get_history(symbols, period)` to inspect and cache each symbol individually under `data:history:{symbol}:{period}`:
     - Cached symbols are retrieved instantly from `CacheService.get_json`.
     - Only missing symbols trigger `data_pipeline.fetch_historical_prices(missing_symbols, period)`.
     - Newly fetched symbols are cached with 24h TTL.
     - All series are joined into a clean `pd.DataFrame` with `DatetimeIndex`, satisfying `AllocationEngine` (Observation 3).

3. **Multi-Layer Fault Tolerance**:
   - Layer 1: Cache hit (Redis or in-memory) returns immediately.
   - Layer 2: On miss, query `DataPipeline`, which has 3 retries, exponential backoff, and circuit breaker.
   - Layer 3: If external pipeline fails (e.g. circuit breaker is OPEN, network offline, API rate limit exceeded), catch exception and load from offline recorded fixtures in `backend/tests/fixtures/` (`market_quotes.json`, `historical_prices.json`, `yield_curve.json`, `macro_indicators.json`, `etf_holdings.json`).
   - Layer 4: If symbol is missing from fixtures, fall back to calibrated baseline constants for the core portfolio universe (`SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`) or raise explicit `MarketDataError`.
   - System never crashes on external network unavailability.

---

## 3. Caveats

1. **Dependency on Sibling Milestone 2 Explorers**:
   - `MarketDataAgent` relies on `DataPipeline` (designed by Explorer 1) and provider modules/fixtures (designed by Explorer 2). To decouple implementation order, `MarketDataAgent` is designed with dependency injection (`__init__(cache_service, data_pipeline, equities_provider, ...)`) and lazy fallback instantiation.
2. **Recorded Fixture Coverage**:
   - Offline fixture fallback guarantees 100% reliability for the primary asset universe defined in the project plan (`SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`). Arbitrary tickers not present in fixtures will raise `MarketDataError` if external APIs are unreachable.
3. **Threading Model for `yfinance`**:
   - `yfinance` is synchronous. Downstream provider implementation (`EquitiesProvider`) must execute yfinance calls inside `asyncio.to_thread` to prevent event loop blocking. `MarketDataAgent` awaits all calls asynchronously.

---

## 4. Conclusion

The architecture, class interface, method signatures, error handling mechanisms, caching layer, and test suite for `backend/agents/market_data.py` are fully designed and documented in:
`c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_3\analysis.md`

All six required methods are specified:
1. `get_quote(symbol: str) -> MarketDataPoint` (30s TTL, `data:quote:{symbol}`)
2. `get_history(symbols: List[str], period: str = "1y") -> pd.DataFrame` (24h TTL, `data:history:{symbol}:{period}`)
3. `get_yield_curve() -> Dict[str, float]` (12h TTL, `data:treasury:yield_curve`)
4. `get_macro_context() -> Dict[str, float]` (24h TTL, `data:macro:indicators`)
5. `get_etf_holdings(symbol: str) -> Dict[str, float]` (6h TTL, `data:etf:holdings:{symbol}`)
6. `get_sector_performance() -> Dict[str, float]` (5m TTL, `data:sector:performance`)

The design is ready for immediate implementation by the Milestone 2 worker agent.

---

## 5. Verification Method

To independently verify this design during implementation:

1. **File Review**:
   - Inspect `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_3\analysis.md` for complete class definition and code blocks.
   
2. **Implementation Verification Command**:
   Once implemented in `backend/agents/market_data.py` and `backend/tests/unit/test_market_data_agent.py`, run:
   ```bash
   cd c:\Users\HP VICTUS\Documents\wealth_agent\backend
   pytest -v tests/unit/test_market_data_agent.py
   ```

3. **In-Memory Fallback Invalidation Test**:
   Execute the test suite with Redis disconnected (`redis_url="redis://localhost:9999/0"`) to confirm that all six methods succeed and enforce TTL expiration using `InMemoryCache`.

4. **Quantitative Downstream Compatibility Test**:
   ```python
   # Verify compatibility with AllocationEngine
   from agents.market_data import MarketDataAgent
   from agents.allocation_engine import AllocationEngine
   
   agent = MarketDataAgent()
   df = await agent.get_history(["SPY", "BND", "GLD"], period="1y")
   assert isinstance(df.index, pd.DatetimeIndex)
   assert list(df.columns) == ["SPY", "BND", "GLD"]
   
   engine = AllocationEngine()
   # Must pass without schema errors
   from skfolio.preprocessing import prices_to_returns
   returns = prices_to_returns(df)
   assert returns.shape[1] == 3
   ```

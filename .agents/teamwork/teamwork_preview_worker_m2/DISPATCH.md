# Dispatch: Milestone 2 Worker (Data Layer Implementation)
Files owned:
- `backend/services/data_pipeline.py`
- `backend/services/providers/__init__.py`
- `backend/services/providers/equities.py`
- `backend/services/providers/treasury.py`
- `backend/services/providers/macro.py`
- `backend/services/providers/etf_holdings.py`
- `backend/services/providers/screener.py`
- `backend/agents/market_data.py`
- `backend/tests/fixtures/` (`market_quotes.json`, `historical_prices.json`, `treasury_yield_curve.json`, `macro_indicators.json`, `etf_holdings.json`)
- Unit tests: `backend/tests/unit/test_data_pipeline.py`, `backend/tests/unit/test_providers.py`, `backend/tests/unit/test_market_data_agent.py`

Requirements: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md`
Project Plan: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md`
Explorer handoffs:
- M2_1: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_1\handoff.md`
- M2_2: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_2\handoff.md`
- M2_3: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_3\handoff.md`


## 2026-10-10T13:18:54Z
You are the Worker for Milestone 2 (Data Layer) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m2
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Explorer findings:
- Explorer 1: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_1\handoff.md (and analysis.md)
- Explorer 2: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_2\handoff.md (and analysis.md)
- Explorer 3: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_3\handoff.md (and analysis.md)

Write Ownership:
You own exclusively:
- backend/services/data_pipeline.py
- backend/services/providers/__init__.py, backend/services/providers/equities.py, backend/services/providers/treasury.py, backend/services/providers/macro.py, backend/services/providers/etf_holdings.py, backend/services/providers/screener.py
- backend/agents/market_data.py
- backend/tests/fixtures/ (market_quotes.json, historical_prices.json, treasury_yield_curve.json, macro_indicators.json, etf_holdings.json)
- backend/tests/unit/ (test_data_pipeline.py, test_providers.py, test_market_data_agent.py)

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Implementation Requirements:
1. Implement backend/services/data_pipeline.py with:
   - AsyncRateLimiter (token bucket, 5 req/s).
   - CircuitBreaker (CLOSED -> OPEN after 5 consecutive failures, 60s cooldown, HALF_OPEN test).
   - Exponential backoff retry (3 retries, 1s base interval).
   - Strict Pydantic v2 schemas: MarketDataPoint, HistoricalPricePoint, YieldCurvePoint, MacroIndicatorPoint.
   - Automatic fallback to recorded fixtures in backend/tests/fixtures/ when external network/APIs fail or are offline.
2. Implement backend/tests/fixtures/ with authentic, well-conditioned fixture files:
   - market_quotes.json (quotes for SPY, BND, AGG, VTI, VXUS, GLD).
   - historical_prices.json (252 business days of daily prices for SPY, BND, AGG, VTI, VXUS, GLD, mathematically well-conditioned and tested to solve MeanRisk CVaR without solver errors).
   - treasury_yield_curve.json (1M through 30Y par yields).
   - macro_indicators.json (cpi, unemployment_rate, fed_funds_rate).
   - etf_holdings.json (top holdings and sector allocations for major ETFs).
3. Implement backend/services/providers/:
   - equities.py: EquitiesProvider wrapping yfinance in asyncio.to_thread with fixture fallback.
   - treasury.py: TreasuryProvider querying FiscalData REST API with fixture fallback.
   - macro.py: MacroProvider querying FRED or CalcFi CSV with fixture fallback.
   - etf_holdings.py: ETF holdings provider with fixture fallback.
   - screener.py: Asset screener provider.
4. Implement backend/agents/market_data.py:
   - MarketDataAgent with get_quote, get_history, get_yield_curve, get_macro_context, get_etf_holdings, get_sector_performance.
   - Full integration with CacheService using standardized key templates and spec TTLs (quotes 30s, OHLCV 24h, holdings 6h, macro 24h, treasury 12h).
   - DataFrame return format strictly compatible with skfolio prices_to_returns(df).
5. Implement unit tests in backend/tests/unit/ (test_data_pipeline.py, test_providers.py, test_market_data_agent.py).
6. Run the test suite with pytest to ensure 100% of new and existing unit tests pass.
7. Write your handoff report to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m2\handoff.md and notify the orchestrator.

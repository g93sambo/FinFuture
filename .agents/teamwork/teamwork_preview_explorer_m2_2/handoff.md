# Handoff Report: Milestone 2 Data Providers & Offline Fixtures

**Role**: Explorer 2 (Milestone 2 - Data Layer)  
**Date**: 2026-10-10  
**Target Package**: `backend/services/providers/`  
**Target Fixtures Directory**: `backend/tests/fixtures/`  
**Recipient**: Orchestrator / Implementer  

---

## 1. Observation

1. **Repository & Directory Status**:
   - `backend/services/` contains `cache.py`, `audit_logger.py`, `anchoring.py`.
   - `backend/services/providers/` does **not** exist yet.
   - `backend/tests/fixtures/` does **not** exist yet.
   - Core installed libraries in the active Python environment:
     - `pandas`: 3.0.3
     - `yfinance`: 1.7.0
     - `httpx`: 0.28.1
     - `skfolio`: 0.1.0

2. **Downstream Engine Optimization Invariant**:
   - In `backend/agents/allocation_engine.py` (lines 32-38):
     ```python
     model = MeanRisk(
         risk_measure=RiskMeasure.CVAR,
         objective_function="maximize_ratio",
         max_weight=0.30,
         min_weight=0.02,
         transaction_costs=0.001
     )
     ```
   - Running this configuration generated verbatim errors:
     `TypeError: MeanRisk.__init__() got an unexpected keyword argument 'max_weight'`
     `TypeError: objective_function must be of type ObjectiveFunction`
   - Verified that `skfolio.optimization.MeanRisk` requires:
     `objective_function=ObjectiveFunction.MAXIMIZE_RATIO`, `max_weights=0.30`, `min_weights=0.02`.
   - Tested 252 business days price returns on `['SPY', 'BND', 'AGG', 'VTI', 'VXUS', 'GLD']` with solver 'CLARABEL':
     `Weights: {'SPY': 0.1174, 'BND': 0.1524, 'AGG': 0.3, 'VTI': 0.02, 'VXUS': 0.2042, 'GLD': 0.206}`.
     The price data in `historical_prices.json` must be mathematically non-singular and well-conditioned to prevent CVaR solver failure.

3. **External API Endpoint Constraints**:
   - US Treasury FiscalData API: `https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/accounting/od/avg_interest_rates` is an open endpoint requiring no API key.
   - FRED API (`https://api.stlouisfed.org/fred/series/observations`) requires an API key (`fred_api_key` in `backend/core/config.py`). When unconfigured, macro provider must fall back to CalcFi or offline fixture without crashing.
   - `yfinance` is synchronous and blocking; all calls must run in `asyncio.to_thread`.

4. **Cache Constants in `backend/services/cache.py`**:
   - `TTL_QUOTES = 30` (30s)
   - `TTL_OHLCV = 86400` (24h)
   - `TTL_TREASURY = 43200` (12h)
   - `TTL_MACRO = 86400` (24h)
   - `TTL_HOLDINGS = 21600` (6h)

---

## 2. Logic Chain

1. **Step 1 (Offline Startup Guarantee)**:
   - *Observation 1* shows that `python main.py` must run with zero required external network services or API keys.
   - *Therefore*: All data providers must implement a reliable local fixture fallback mechanism pointing to `backend/tests/fixtures/`. If network calls fail, timeout, or if `offline_mode=True`, providers gracefully return recorded fixture data without throwing unhandled exceptions.

2. **Step 2 (Non-blocking Event Loop)**:
   - *Observation 3* shows `yfinance` executes blocking socket I/O.
   - *Therefore*: `EquitiesProvider` and `ETFHoldingsProvider` must wrap all `yfinance` calls in `asyncio.to_thread` to maintain FastAPI asynchronous event loop throughput.

3. **Step 3 (Solver Compatibility for Historical Data)**:
   - *Observation 2* shows that `skfolio` MeanRisk CVaR optimization is sensitive to data conditioning and requires exact DataFrame format (DatetimeIndex rows, symbol columns).
   - *Therefore*: `historical_prices.json` must contain 252 business days across all 6 target assets (`SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`) with realistic, non-collinear returns that allow the 'CLARABEL' convex optimization solver to reach a stable optimal solution.

4. **Step 4 (Provider Specialization & Modularity)**:
   - The required data encompasses equities/ETFs, Treasuries, macroeconomics, fund holdings, and asset universe screening.
   - *Therefore*: Structure the implementation into five dedicated provider classes:
     - `EquitiesProvider` (`equities.py`): Real-time quotes and historical price matrices.
     - `TreasuryProvider` (`treasury.py`): Daily Treasury par yield curves and inversion spreads.
     - `MacroProvider` (`macro.py`): CPI, unemployment rate, fed funds rate via FRED / CalcFi.
     - `ETFHoldingsProvider` (`etf_holdings.py`): Top 10 holdings, sector weights, fixed income duration.
     - `AssetScreenerProvider` (`screener.py`): Universe catalog, multi-criteria screening.

---

## 3. Caveats

1. **External Network Availability in Test/CI**: Upstream endpoints (`api.fiscaldata.treasury.gov`, `yfinance`, `api.stlouisfed.org`) may throttle, rate-limit (HTTP 429), or experience downtime. Test suites MUST run with `offline_mode=True` or mocked responses to ensure test determinism.
2. **FRED API Key**: In development/testing environments without a valid `FRED_API_KEY`, `MacroProvider` will systematically trigger the fixture fallback. This is the expected design behavior.
3. **ETF Bond Quality Data in yfinance**: `yfinance` has variable coverage for fixed-income duration and credit ratings across different bond tickers. The fixture fallback (`etf_holdings.json`) provides guaranteed high-fidelity fixed-income profiles for `BND` and `AGG`.

---

## 4. Conclusion

1. **Modules to Implement in `backend/services/providers/`**:
   - `equities.py`: `EquitiesProvider` with `get_quote()` and `get_historical_prices()` using `asyncio.to_thread(yfinance)`.
   - `treasury.py`: `TreasuryProvider` with `get_yield_curve()` and `get_yield_curve_details()` querying FiscalData REST API.
   - `macro.py`: `MacroProvider` with `get_macro_indicators()` and `get_macro_context()` querying FRED / CalcFi.
   - `etf_holdings.py`: `ETFHoldingsProvider` with `get_holdings()` returning top holdings, sector allocations, and credit metrics.
   - `screener.py`: `AssetScreenerProvider` providing a 15+ asset catalog with filtering by asset class, expense ratio, AUM, yield, and risk level.
   - `__init__.py`: Clean export of all provider classes and factory functions.

2. **Fixtures to Create in `backend/tests/fixtures/`**:
   - `market_quotes.json`: Live quotes for `SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`, `QQQ`.
   - `historical_prices.json`: 252 business days (2023-04-12 to 2024-03-28) of daily close prices for `SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`.
   - `yield_curve.json`: Full term structure (`1M` to `30Y`) and inversion metrics.
   - `macro_indicators.json`: `cpi=3.48`, `unemployment_rate=3.9`, `fed_funds_rate=5.33`.
   - `etf_holdings.json`: Comprehensive holdings, sector weights, and fixed-income duration for `SPY`, `BND`, `AGG`, `VTI`, `VXUS`, `GLD`.

3. **Full Details**: Complete specifications, class skeletons, and fixture data samples are documented in:
   `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_2\analysis.md`.

---

## 5. Verification Method

1. **Verify Fixture File Existence & Integrity**:
   - Inspect files in `backend/tests/fixtures/`:
     ```powershell
     Test-Path backend\tests\fixtures\market_quotes.json
     Test-Path backend\tests\fixtures\historical_prices.json
     Test-Path backend\tests\fixtures\yield_curve.json
     Test-Path backend\tests\fixtures\macro_indicators.json
     Test-Path backend\tests\fixtures\etf_holdings.json
     ```
   - Verify valid JSON syntax for all fixture files:
     ```powershell
     python -c "import json, glob; [json.load(open(f, encoding='utf-8')) for f in glob.glob('backend/tests/fixtures/*.json')]; print('All fixtures valid JSON')"
     ```

2. **Verify Provider Functionality with Offline Fixtures**:
   - Run unit test suite:
     ```powershell
     pytest -v backend/tests/unit/test_providers.py
     ```
   - Verify `historical_prices.json` seamlessly loads into pandas and fits `skfolio.optimization.MeanRisk`:
     ```powershell
     python -c "import json, pandas as pd; from skfolio import RiskMeasure; from skfolio.optimization import MeanRisk, ObjectiveFunction; from skfolio.preprocessing import prices_to_returns; data = json.load(open('backend/tests/fixtures/historical_prices.json')); df = pd.DataFrame(data['records']).set_index('date'); df.index = pd.to_datetime(df.index); r = prices_to_returns(df.astype(float)); m = MeanRisk(risk_measure=RiskMeasure.CVAR, objective_function=ObjectiveFunction.MAXIMIZE_RATIO, max_weights=0.30, min_weights=0.02); m.fit(r); print('skfolio MeanRisk solved successfully! Weights:', {k: round(float(v), 3) for k, v in zip(df.columns, m.predict(r).weights)})"
     ```

3. **Invalidation Conditions**:
   - `historical_prices.json` has missing dates or non-positive-definite covariance causing `ConvexOptimizationError: Solver 'CLARABEL' failed`.
   - `yfinance` called synchronously on the main thread causing event loop lag.
   - `TreasuryProvider` or `MacroProvider` fails when external network is offline instead of returning fixture data.

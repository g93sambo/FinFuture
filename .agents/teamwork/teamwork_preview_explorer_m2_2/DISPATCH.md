# Dispatch: Milestone 2 Explorer 2 (Providers & Offline Fixtures)
Requirements: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md`
Project Plan: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md`
Focus: `backend/services/providers/` (`equities.py`, `treasury.py`, `macro.py`, `etf_holdings.py`, `screener.py`) and recorded fixtures in `backend/tests/fixtures/` (SPY, BND, AGG, VTI, VXUS, GLD, yield curve, macro).

## 2026-10-10T13:11:21Z
You are Explorer 2 for Milestone 2 (Data Layer) of the Wealth Advisory Agent backend.
Working directory: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_2
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Scope & Tasks:
1. Read ORIGINAL_REQUEST.md and PROJECT.md.
2. Design backend/services/providers/:
   - equities.py: EquitiesProvider using yfinance (and async thread executor) for live quotes and historical daily OHLCV for SPY, BND, AGG, VTI, VXUS, GLD. Fallback to offline fixtures.
   - treasury.py: TreasuryProvider querying US Treasury FiscalData REST API for daily treasury par yield curve rates. Fallback to offline fixtures.
   - macro.py: MacroProvider querying FRED API (if key configured) or CalcFi CSV data for CPI, unemployment rate, federal funds rate. Fallback to offline fixtures.
   - etf_holdings.py: Provider for ETF top holdings and sector weights (e.g., SPY, BND, VTI).
   - screener.py: Screening and asset universe querying.
3. Specify exact structure and content of offline recorded fixture files to create in backend/tests/fixtures/ (market_quotes.json, historical_prices.json, yield_curve.json, macro_indicators.json, etf_holdings.json).
4. Write analysis report to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m2_2\analysis.md and deliver structured handoff.md.
5. Send message to orchestrator upon completion.

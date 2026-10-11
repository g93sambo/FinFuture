# Handoff Report: Milestone 4 Health Report Service Architecture & Implementation Specification

- **Role**: Explorer 3 (Milestone 4: Health Report Service)
- **Directory**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_3`
- **Target File for Implementation**: `c:\Users\HP VICTUS\Documents\wealth_agent\backend\services\health_report.py`
- **Timestamp**: 2026-10-10T17:52:00Z
- **Handoff Type**: Hard (Investigation & Specification Complete)

---

## 1. Observation

1. **Missing Service File**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\services\health_report.py` does not currently exist.
   - Verified via `list_dir` on `backend/services/`: contains `__init__.py`, `anchoring.py`, `audit_logger.py`, `cache.py`, `data_pipeline.py`, and `providers/`.

2. **Existing Models**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\db\models.py`:
     - Line 55: `class DBClientProfile(Base):` defines client suitability, `risk_tolerance_score`, `investment_horizon_years`, `suitability_category`, and goals.
     - Line 119: `class DBPortfolioSnapshot(Base):` defines `id`, `client_id`, `total_value` (Float), `positions` (JSON dict), `cash` (Float), `timestamp` (DateTime).

3. **Existing Market Data & Optimization Infrastructure**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\agents\allocation_engine.py`:
     - Lines 48-68: defines `RebalanceOrder` and `RebalancePlan`.
     - Lines 467-586: `generate_rebalancing_trades(...)` computes portfolio turnover and SELL-before-BUY rebalance orders.
     - Lines 233-247: defines benchmark rule-based allocations for profiles: Conservative (`SPY: 0.20, BND: 0.80`), Moderate (`SPY: 0.60, BND: 0.40`), Growth (`SPY: 0.80, BND: 0.20`), Aggressive (`SPY: 0.90, BND: 0.10`).
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\agents\market_data.py`:
     - Line 73: `MarketDataAgent` provides cached quotes, historical prices (`get_historical_prices`), yield curves, and macro data.
     - Lines 20-26: imports standard cache TTLs and fixture fallbacks.

4. **API Route Placement**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\main.py`:
     - Lines 77-79: `class HealthReportRequest(BaseModel): client_id: str`.
     - Lines 157-165: placeholder route `POST /api/v1/portfolio/health-report` returning static mock response pending real service integration.

5. **Test Fixtures & Execution**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend\tests\fixtures\`: Contains `historical_prices.json` (359 KB) and `market_quotes.json` (2.9 KB) with complete price series for `SPY`, `BND`, `AGG`, `VTI`, `QQQ`, `SHY`.
   - Running `pytest tests/unit/test_allocation_engine.py` passed all 19 tests in 6.43s.

---

## 2. Logic Chain

1. **Drift Calculation Logic**:
   - From Observation (3), `AllocationEngine` computes raw absolute weight differences, but the Health Report requires detailed asset-level drift analysis, directional labels (`OVERWEIGHT`/`UNDERWEIGHT`), percentage drifts, and an explicit 5% ($0.05$) trigger threshold.
   - Therefore, `DriftAnalysisResult` and `AssetDriftDetail` calculate $\Delta_i = |w_{cur, i} - w_{tgt, i}|$ and $\% \Delta_i = \frac{w_{cur, i} - w_{tgt, i}}{w_{tgt, i}} \times 100\%$, flagging `exceeds_threshold = True` whenever $\Delta_i \ge 0.05$.

2. **Portfolio Health Score Composite Logic**:
   - A single 0-100 score is required that incorporates drift, concentration, risk alignment, and diversification.
   - Using a base potential of 80 points:
     - Diversification reward $R_{div} \in [0, 20]$ based on $N_{eff} = 1 / HHI$ rewards multi-asset exposure.
     - Drift penalty $P_{drift} \in [0, 40]$ scales linearly from 2% deadband up to 20% max drift.
     - Concentration penalty $P_{conc} \in [0, 20]$ penalizes any position weight $> 0.20$.
     - Risk misalignment penalty $P_{risk} \in [0, 20]$ penalizes equity proportion divergence from client suitability.
   - Clamping $\max(0.0, \min(100.0, \text{RawScore}))$ mathematically guarantees the score remains within $[0, 100]$.

3. **Rebalancing Trade Order Logic**:
   - Observation (3) demonstrates that executing SELLs before BUYs guarantees liquidity in paper and live brokerage execution.
   - In `health_report.py`, orders must also respect a $\pm 1\%$ tolerance band (suppressing trades where $|\Delta w_i| \le 0.01$) and a $\$10.00$ minimum dollar threshold to prevent small dusting transactions.

4. **Narrative & Regulatory Compliance Logic**:
   - To ensure CI testability and zero reliance on external network calls, a dual-mode narrative generator is required.
   - Mode 1 queries OpenAI if `openai_api_key` is present. Mode 2 generates deterministic templated markdown across 6 standard sections.
   - Both modes strictly avoid guarantee language per `REG-001` and enforce mandatory risk disclosures per `REG-002`.

---

## 3. Caveats

1. **Price Data in DB Snapshots**: `DBPortfolioSnapshot.positions` can store either unit share counts (e.g. `{"SPY": 100}`) or pre-calculated dollar values/weights. The implementation must detect whether position values represent quantities or weights and retrieve prices from `MarketDataAgent` accordingly.
2. **Missing DB Records**: If `client_id` is not found in `DBClientProfile`, the service should raise an explicit `ValueError` (which routes in Milestone 5 will translate to HTTP 404).
3. **OpenAI SDK Availability**: The codebase uses Python 3.12 with optional OpenAI dependencies; all LLM invocations must be wrapped in try/except blocks to fall back instantly to the deterministic template.

---

## 4. Conclusion

The architectural design, mathematical formulations, Pydantic schemas, and test scenarios for `backend/services/health_report.py` are fully documented in `analysis.md`. The implementer can directly translate this specification into code without ambiguity.

Core components specified:
- `HealthReportService` public API (`generate_health_report`, `calculate_drift`, `compute_health_score`, `evaluate_concentration`, `compare_to_benchmark`, `evaluate_alerts`, `generate_rebalancing_orders`, `generate_narrative`).
- 5% drift threshold trigger and turnover metric.
- 60/40 benchmark comparison engine.
- 0-100 bounded composite health score.
- Structured alerts (`DRIFT_ALERT`, `CONCENTRATION_ALERT`, `VOLATILITY_ALERT`, `REBALANCE_RECOMMENDED`, `MISALIGNMENT_ALERT`).
- SELL-first rebalance trade plan with $\pm 1\%$ tolerance band.
- Dual-mode narrative generator with `REG-001`/`REG-002` compliance.

---

## 5. Verification Method

1. **Review Specification Document**:
   - Inspect `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_3\analysis.md`.
2. **Post-Implementation Unit Tests**:
   - Implement `backend/services/health_report.py` per the specification.
   - Run unit test suite:
     ```powershell
     pytest backend/tests/unit/test_health_report.py -v
     ```
   - Verify all test scenarios in `analysis.md` Section 5 pass (drift threshold at 0.05, score bounded in [0, 100], SELLs precede BUYs, offline narrative execution).
3. **Integration Test Verification**:
   - Run integration tests with database sessions:
     ```powershell
     pytest backend/tests/integration/test_health_report_service.py -v
     ```

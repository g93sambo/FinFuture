# Milestone 3 Handoff Report: Core Agents

**Role**: Worker (`teamwork_preview_worker_m3`)  
**Milestone**: Milestone 3 (Core Agents: Risk Profiler, Behavioral Bias, Product Comparison, Allocation Engine)  
**Parent Conversation ID**: `498f461a-015a-42ad-98d2-3a9070fe1d9a`  
**Date**: 2026-10-10  
**Handoff Type**: Hard (Task Complete)  

---

## 1. Observation

1. **Initial Codebase Deficiencies & Explorer Findings**:
   - `backend/agents/risk_profiler.py` (originally 76 lines) was an unconstrained single-turn prompt loop lacking FSM states, session draft caching, quantitative scoring, KYC/AML validation, and database persistence.
   - `backend/agents/behavioral_bias.py` (originally 55 lines) had a direct `gpt-4o` call that failed completely when `OPENAI_API_KEY` was missing, without heuristic scoring, behavioral telemetry signals, or `behavioral_memory` persistence.
   - `backend/agents/product_comparison.py` was completely missing from the codebase.
   - `backend/agents/allocation_engine.py` suffered from severe defects:
     * Line 35-36: singular parameter names `max_weight=0.30, min_weight=0.02` which raised `TypeError: MeanRisk.__init__() got an unexpected keyword argument 'max_weight'`.
     * Line 50: queried non-existent `portfolio.std`, raising `AttributeError: 'Portfolio' object has no attribute 'std'`.
     * CVaR ratio optimization with CLARABEL failed on non-positive or negative return drift without fallback.
   - Baseline M1/M2 test suite had 222 passing tests in 113.32s (`pytest -q`).

2. **Implemented Production Modules**:
   - `backend/agents/risk_profiler.py` (864 lines):
     * Implemented 6-state FSM (`DEMOGRAPHICS` -> `FINANCIAL_SITUATION` -> `TIME_HORIZON` -> `RISK_TOLERANCE` -> `EXPERIENCE` -> `PROFILE_SYNTHESIS` -> `COMPLETE`).
     * Session draft caching under `profile:draft:{session_id}` with 1-hour TTL (`TTL_PROFILE_DRAFT = 3600`) via `CacheService`.
     * Quantitative scoring: composite `suitability_category` score $S \in [1.0, 10.0]$ with FINRA/Reg BI regulatory caps ($H < 3$y capped at Moderate Conservative, low loss capacity capped at Moderate); `emotional_risk_score` ($0-100$ scale); calibrated logistic `panic_sell_likelihood` ($0.0-1.0$ probability).
     * KYC verification (`kyc_verified`) and AML red flag typology rules (`aml_flag`: PEP status, high-risk jurisdiction, suspicious funds, income/asset anomaly).
     * Dual extraction engine: deterministic regex/heuristic + LLM with graceful offline fallback.
     * Async DB persistence to `DBClientProfile` (`save_profile`, `get_profile`) and backwards-compatible `process_conversation`.
   - `backend/agents/behavioral_bias.py` (650 lines):
     * Dual-layer bias detection across 5 biases (`loss_aversion`, `recency_bias`, `overconfidence`, `herd_mentality`, `disposition_effect`).
     * Layer 1: Pre-compiled regex catalog with calibrated weights and threshold $\ge 0.60$.
     * Layer 2: LLM contextual confirmation with automatic fallback to Layer 1 when `OPENAI_API_KEY` is missing or network fails.
     * 4 behavioral telemetry signals: rapid portfolio checks ($\ge 3$ in 10m), panic dip selling (sell on $\le -3.0\%$ drop), concentration risk ($> 25\%$ single asset), excessive trading ($\ge 5$ in 24h).
     * Async persistence to `DBBehavioralMemory` and `DBClientProfile` synchronization (updating `detected_biases`, `emotional_risk_score`, and `panic_sell_likelihood`).
     * Educational reframing interventions and 24h cool-off recommendations.
     * Backwards-compatible `analyze_message`.
   - `backend/agents/product_comparison.py` (477 lines):
     * Six-factor composite scoring engine: Expense ratio ($0.30$), Tracking error ($0.15$), Liquidity / spread ($0.20$), AUM scale ($0.10$), Historical return ($0.15$), Manager reputation ($0.10$).
     * Pre-filtering suitability engine enforcing `SUIT-001` (quarantining unsuitable high-risk products or duration mismatches into `unsuitable_products`).
     * Dedicated ETF and Bond comparison pipelines (`compare_etfs`, `compare_bonds`).
     * Factor breakdown (`FactorScores`), key advantages, key risks, winner symbol, and natural language comparative rationale with deterministic fallback.
   - `backend/agents/allocation_engine.py` (685 lines):
     * Fixed skfolio plural parameters `max_weights` and `min_weights` in `MeanRisk(...)`.
     * Fixed portfolio standard deviation access via `portfolio.standard_deviation` and `portfolio.annualized_standard_deviation`.
     * Profile-driven optimization constraints mapping risk score to CVaR bounds and liquidity floors.
     * 5-tier resilient solver fallback cascade: CVaR Ratio -> Minimum Variance QP -> Inverse Volatility -> Equal Weighted -> Profile Benchmark Heuristic.
     * Efficient frontier generator producing $N$-point risk/return curve with Sharpe and CVaR.
     * Rebalancing trade generator with strict SELL-before-BUY sequencing to preserve cash liquidity.
     * Closed-form Euler analytical percentage risk attribution ($\%RC_i = \frac{w_i (\Sigma w)_i}{\sigma_p^2}$) and SHAP KernelExplainer with deterministic narrative fallback.
     * Overloaded public signatures supporting `(price_dataframe, profile)` and `(profile_or_client_id, current_positions, db)`.
   - `backend/models/client_profile.py`:
     * Enhanced Pydantic schema with sensible defaults for robust validation.
   - `backend/tests/fixtures/behavioral_scenarios.json`:
     * 12 calibrated scenarios covering all 5 biases, boundary cases, neutral queries, and telemetry signals.

3. **Test Execution & Coverage Metrics**:
   - `backend/tests/unit/test_risk_profiler.py`: 19 passed in 12.96s.
   - `backend/tests/unit/test_behavioral_bias.py`: 22 passed in 1.80s.
   - `backend/tests/unit/test_product_comparison.py`: 13 passed in 13.92s.
   - `backend/tests/unit/test_allocation_engine.py`: 19 passed in 3.50s.
   - **Total M3 Unit Tests**: 73 passed in 34.58s (100% pass rate).
   - **Coverage Metrics** (`pytest -q --cov=...`):
     * `agents/risk_profiler.py`: **85%**
     * `agents/behavioral_bias.py`: **90%**
     * `agents/product_comparison.py`: **88%**
     * `agents/allocation_engine.py`: **85%**
     * **Combined Milestone 3 Coverage**: **86%** (exceeds $\ge 80\%$ gate).

---

## 2. Logic Chain

1. **State Machine & Draft Resilience**:
   - Because financial advisory consultations span multiple conversation turns and can be interrupted, implementing the 6-state FSM with Redis/InMemory caching under `profile:draft:{session_id}` guarantees conversational continuity. Evicting the draft upon reaching `COMPLETE` ensures zero state leakage.
2. **Quantitative Scoring & Prudential Guardrails**:
   - Under FINRA Rule 2111 and SEC Reg BI, suitability cannot rely solely on self-reported risk tolerance. Combining risk tolerance, loss capacity, time horizon, goal, and experience with hard prudential caps (e.g. short horizons $< 3$y cannot exceed Moderate Conservative) prevents over-allocation to volatile equities.
3. **Dual-Layer Bias Architecture**:
   - Combining Layer 1 pre-compiled regex scoring ($\ge 0.60$ threshold) with Layer 2 LLM contextual confirmation guarantees fast, deterministic execution during automated offline CI testing while allowing rich LLM reasoning in production.
4. **Solver Fallback Resilience**:
   - Real-world convex optimization solvers (`CLARABEL`, `OSQP`) frequently raise `ConvexOptimizationError` or `ValueError` when asset drift is non-positive or covariance is ill-conditioned. The 5-tier fallback hierarchy (CVaR Ratio $\to$ Minimum Variance $\to$ Inverse Volatility $\to$ Equal Weighted $\to$ Profile Benchmark) ensures zero unhandled exceptions under any market regime.
5. **Rebalancing Liquidity Invariant**:
   - In trading execution, executing BUY orders before SELL orders creates negative cash overdrafts. Enforcing SELL-before-BUY ordering ensures cash is freed before purchasing target assets.

---

## 3. Caveats

- **OpenAI Live Keys in CI**:
  The dual extraction, bias confirmation, comparison rationale, and portfolio narrative engines were purposefully built with deterministic heuristic fallbacks so that the entire test suite runs offline without OpenAI API keys, token costs, or network flakiness.
- **Paper Trading Invariant**:
  Live broker execution is not handled directly by the allocation engine; generated trade orders are passed downstream to the Execution Module (M4) subject to paper trading guardrails.
- **No Other Caveats**: All milestone requirements and write ownership constraints have been strictly satisfied.

---

## 4. Conclusion

All deliverables for Milestone 3 (Core Agents) are complete, fully tested, and verified:
1. `RiskProfilerAgent` implements complete 6-state FSM, quantitative scoring, draft caching, KYC/AML validation, and DB persistence.
2. `BehavioralBiasAgent` implements dual-layer detection across 5 biases, 4 telemetry channels, DB persistence, profile synchronization, and 12 fixture scenarios.
3. `ProductComparisonAgent` implements six-factor composite scoring ($w = 0.30, 0.15, 0.20, 0.10, 0.15, 0.10$), `SUIT-001` pre-filtering, ETF/Bond pipelines, and comparative rationales.
4. `AllocationEngine` fixes skfolio plural parameters and standard deviation access, provides profile-driven convex constraints, 5-tier solver fallback cascade, efficient frontier generation, SELL-first rebalancing trades, and Euler percentage risk attribution.
5. All 73 new unit tests pass with **86% aggregate coverage** (each agent $\ge 85\%$, exceeding the $\ge 80\%$ gate).

---

## 5. Verification Method

To independently verify the implementation and test coverage:

1. **Run All Milestone 3 Unit Tests**:
   ```bash
   cd backend
   pytest -v tests/unit/test_risk_profiler.py tests/unit/test_behavioral_bias.py tests/unit/test_product_comparison.py tests/unit/test_allocation_engine.py
   ```
   *Expected Result*: 73 passed in ~35 seconds.

2. **Verify Code Coverage Gate ($\ge 80\%$)**:
   ```bash
   cd backend
   pytest -q --cov=agents.risk_profiler --cov=agents.behavioral_bias --cov=agents.product_comparison --cov=agents.allocation_engine tests/unit/test_risk_profiler.py tests/unit/test_behavioral_bias.py tests/unit/test_product_comparison.py tests/unit/test_allocation_engine.py
   ```
   *Expected Result*: Overall coverage $\ge 86\%$ with all 4 modules $\ge 85\%$.

3. **Verify Full Repository Regression**:
   ```bash
   cd backend
   pytest -q
   ```
   *Expected Result*: All 295 tests pass with zero regressions (verified: 295 passed in 136.92s).

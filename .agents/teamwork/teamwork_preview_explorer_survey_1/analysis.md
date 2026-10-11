# Comprehensive Codebase Scaffold Analysis: Wealth Advisory Agent Backend

**Author:** Survey Explorer 1  
**Target:** Wealth Advisory Agent Backend (`c:\Users\HP VICTUS\Documents\wealth_agent\backend`)  
**Date:** 2026-10-10  
**Status:** Completed  

---

## 1. Executive Summary

A comprehensive investigation was conducted across the `backend/` codebase to determine the exact state of implementation, assess scaffold stubs and mock behaviors, and identify all missing architectural components required by the authoritative requirements (`ORIGINAL_REQUEST.md`) and approved plan (`implementation_plan.md`).

### High-Level Verdict
The existing codebase is a **preliminary proof-of-concept scaffold**. While a few core mathematical and API concepts are demonstrated (notably `skfolio` optimization in `allocation_engine.py`, basic order submission in `execution_module.py`, and a simple LLM interview loop in `risk_profiler.py`), **critical architectural foundations are completely absent**:
1. **Security & Authentication**: Zero authentication exists. No JWT tokens, no password hashing, no user models, no ownership checks, and WebSocket endpoints are open to unauthenticated connections.
2. **Configuration & Governance**: No `core/config.py` exists; environment variables are loaded ad-hoc via `load_dotenv`. No paper-trading startup safety guard exists.
3. **Data Layer**: There is no data ingestion pipeline, no provider abstractions (yfinance, Treasury FiscalData, FRED), no circuit breakers, and no caching.
4. **Audit & Compliance**: Only 2 trivial in-memory compliance rules exist out of the required 12-rule catalog. The audit log is not hash-chained, not HMAC-signed, has no Merkle tree or Sepolia anchoring, and has no verification endpoint.
5. **API & Orchestration**: Almost all REST endpoints return hard-coded mock dictionary responses. The WebSocket has no stateful orchestration, does not emit standard event schemas, and lacks compliance gating on output text.
6. **Testing**: There is no `tests/` directory and zero test files exist.

---

## 2. File-by-File Detailed Investigation

### 2.1 `backend/main.py` (297 lines)
- **Role:** Main FastAPI application entrypoint and monolith holding all REST endpoints, DB initialization, and WebSocket loop.
- **Observed Implementation:**
  - **FastAPI Lifecycle:** Uses `@app.on_event("startup")` (lines 47-51) instead of modern FastAPI `lifespan` context manager.
  - **Agent Instantiation:** Module-level global singletons (lines 41-45): `execution_module`, `compliance_guard`, `allocation_engine`, `risk_profiler`, `bias_agent`.
  - **REST Endpoints Status:**
    - `GET /` (line 82): Real health status check.
    - `POST /api/v1/session/start` (lines 86-92): **STUB/MOCK**. Returns hard-coded `session_id="dummy-session-uuid-1234"`. No Redis or in-memory session persistence.
    - `POST /api/v1/chat/message` (lines 94-101): **STUB/MOCK**. Returns hard-coded static string.
    - `POST /api/v1/compare/etfs` (lines 103-109): **STUB/MOCK**. Returns hard-coded scores `8.5` and fixed mock rationale.
    - `POST /api/v1/compare/bonds` (lines 111-117): **STUB/MOCK**. Returns hard-coded scores `7.2` and fixed mock rationale.
    - `GET /api/v1/portfolio/{client_id}` (lines 119-127): **STUB/MOCK**. Returns hard-coded static dictionary (`total_value: 10000.0`, BND position).
    - `GET /api/v1/audit/{client_id}` (lines 129-137): **STUB/MOCK**. Returns static list with a single dummy entry.
    - `GET /api/v1/compliance/rules` (lines 139-145): Queries in-memory `compliance_guard.rules`. Returns only the 2 hardcoded rules. Does not read from DB.
    - `GET /api/v1/market/quote/{symbol}` (lines 147-150): **STUB/MOCK**. Returns hardcoded price `150.0`.
    - `GET /api/v1/market/macro` (lines 152-155): **STUB/MOCK**. Returns hardcoded `{cpi: 3.2, unemployment_rate: 4.1, fed_funds_rate: 5.25}`.
    - `POST /api/v1/portfolio/health-report` (lines 157-165): **STUB/MOCK**. Returns hardcoded static drift percentage `2.1` and mock narrative.
    - `GET /api/v1/profile/{client_id}` (lines 167-173): **PARTIAL REAL**. Queries SQLite/Postgres DB for `DBClientProfile`. However, lacks user authentication and user ownership checks (cross-user data leak risk).
    - `POST /api/v1/trade/execute` (lines 175-219): **PARTIAL REAL WITH MOCKS**. Queries DB for profile, but invokes `compliance_guard.check_recommendation` with a hardcoded mock recommendation `{"risk_level": 3, "avg_duration": 4.0}`. Places order via `execution_module` and saves record in `DBTrade`.
  - **WebSocket Implementation (`/ws/chat/{session_id}`)** (lines 237-293):
    - Path parameter `/ws/chat/{session_id}` instead of query token `/ws/chat?token=...`.
    - Lacks JWT authentication and user verification.
    - Maintains in-memory dictionary `manager.conversations` with no Redis or TTL backing.
    - Sequential flow: runs `bias_agent.analyze_message` (OpenAI call), sends bias alert if any, appends message to history, runs `risk_profiler.process_conversation` (OpenAI call). If profile complete, saves `DBClientProfile` and sends success message.
    - Does not emit required event types: `user_message`, `agent_response`, `trade_proposal`, `trade_approved`, `trade_filled`, `portfolio_update`, `bias_alert`, `compliance_check`.
    - Does not filter agent output through Compliance Guard (REG-001 guarantee check or REG-002 risk disclosure check).

### 2.2 `backend/db/database.py` (31 lines)
- **Role:** SQLAlchemy async engine and session factory.
- **Observed Implementation:**
  - Uses `create_async_engine` with fallback to `sqlite+aiosqlite:///./wealth_advisor.db`.
  - Converts `postgresql://` to `postgresql+asyncpg://` if Postgres URL is provided.
  - Implements `get_db()` async generator dependency.
  - Implements `init_db()` which executes `Base.metadata.create_all`.
- **Gaps:** No connection pool tuning, no read-replica awareness, no Alembic migration hookup.

### 2.3 `backend/db/models.py` (66 lines)
- **Role:** SQLAlchemy declarative models.
- **Observed Implementation:**
  - `DBClientProfile` (`client_profiles` table): Defines basic columns (`client_id`, `age`, `employment_status`, `annual_income`, `net_worth`, `risk_tolerance_score`, `investment_horizon_years`, `liquidity_needs`, `primary_goal`, `suitability_category`, `detected_biases`, `kyc_verified`, `aml_flag`, `created_at`, `updated_at`).
  - `DBAuditLog` (`audit_log` table): Defines `entry_id`, `timestamp`, `event_type`, `client_id`, `session_id`, `agent_id`, `action`, `entry_hash`, `previous_hash`, `hmac_signature`.
  - `DBTrade` (`trades` table): Defines `trade_id`, `client_id`, `alpaca_order_id`, `symbol`, `side`, `quantity`, `order_type`, `status`, `filled_price`, `filled_at`, `compliance_report`, `user_approved_at`, `created_at`.
- **Gaps & Defects:**
  1. **Missing `users` Table**: No table for user accounts (`id`, `email`, `hashed_password`, `is_active`, `created_at`, etc.).
  2. **Missing `user_id` Foreign Key**: `client_profiles` has no relationship to users, making per-user ownership enforcement impossible.
  3. **Missing `portfolio_snapshots` Table**: Spec requires snapshots of portfolio positions, valuations, cash, and weights over time.
  4. **Missing `behavioral_memory` Table**: Spec requires tracking client bias history and interventions across sessions.
  5. **Missing `compliance_rules` Table**: Compliance rules must be DB-configurable; currently rules are hardcoded in python code.
  6. **Incomplete Client Profile**: Missing fields present in `models/client_profile.py`: `dependents`, `liquid_assets`, `monthly_expenses`, `existing_debts`, `investment_experience`, `loss_capacity`, `target_return`, `specific_goals`, `emotional_risk_score`, `panic_sell_likelihood`, `profiling_session_transcript`.
  7. **Missing Append-Only / Immutability Guard**: No database trigger (Postgres) or ORM event hook (SQLite) preventing updates/deletions in `audit_log`.

### 2.4 `backend/models/client_profile.py` (39 lines)
- **Role:** Pydantic domain model for `ClientProfile`.
- **Observed Implementation:**
  - Richer schema than `db/models.py`, including fields like `dependents`, `liquid_assets`, `monthly_expenses`, `loss_capacity`, `target_return`, `emotional_risk_score`, `panic_sell_likelihood`.
- **Gaps:** Out of sync with database entity `DBClientProfile`. Does not include `user_id`.

### 2.5 `backend/agents/execution_module.py` (66 lines)
- **Role:** Order execution via Alpaca Trading API.
- **Observed Implementation:**
  - Attempts import of `alpaca-py`.
  - Initializes `TradingClient` if keys are present; otherwise sets `self.client = None`.
  - In `place_order(symbol, qty, side, user_approved)`:
    - Checks `if not user_approved: raise ValueError(...)`.
    - If `self.client is None`: returns mock dict with `status: "mock_filled"` and dummy order ID.
    - If `self.client` exists: submits `MarketOrderRequest(time_in_force=TimeInForce.DAY)`.
- **Gaps & Critical Defects:**
  1. **No Live URL Guard**: Sets `self.paper = True`, but does not inspect the Alpaca base URL. Live credentials or production endpoints could accidentally execute real trades.
  2. **Silent Mock Fills**: Silently falls back to mock fills if keys are absent, without requiring an explicit `DRY_RUN` configuration flag.
  3. **No Approval Freshness Check**: Does not verify when approval was granted or check for expired approval windows.
  4. **No Double-Submit Lock**: Missing Redis lock to prevent duplicate orders submitted within 30 seconds.
  5. **No KYC / AML Check**: Does not check client KYC verification or AML status prior to order submission.
  6. **No Fill Polling**: Submits order and immediately returns without polling Alpaca order fill status.
  7. **No DB / Audit Logging**: Does not record the trade in DB or generate audit log entries within the module.
  8. **No Position Sync**: Lacks methods to synchronize Alpaca account cash and open positions.

### 2.6 `backend/agents/allocation_engine.py` (124 lines)
- **Role:** Modern Portfolio Theory (MPT) asset allocation optimization using `skfolio`, with SHAP and OpenAI explanations.
- **Observed Implementation:**
  - Converts historical price dataframe to returns using `skfolio.preprocessing.prices_to_returns`.
  - Configures `skfolio.optimization.MeanRisk(risk_measure=RiskMeasure.CVAR, objective_function="maximize_ratio", max_weight=0.30, min_weight=0.02, transaction_costs=0.001)`.
  - Fits model, extracts portfolio metrics (`expected_return`, `volatility`, `sharpe_ratio`, `cvar_95`, `max_drawdown`).
  - Calls `_explain_allocation()`: uses `shap.KernelExplainer` on returns background, computes SHAP values for the most recent day, constructs prompt for `gpt-4o` to generate narrative.
- **Gaps & Bugs:**
  1. **Weight Attribute Bug/Fragility**: Mixes `model.weights_` and `portfolio.weights`. In `skfolio`, depending on version and return types, `portfolio.weights` format can vary.
  2. **Static Constraints**: Optimization parameters (`max_weight=0.30`, `min_weight=0.02`, `risk_measure=CVAR`) are hardcoded; they do not adapt to client profile risk scores, horizon, or liquidity constraints.
  3. **Missing Efficient Frontier**: Does not generate frontier curve points across risk-return spectrum.
  4. **Missing Rebalance Generator**: Does not calculate difference between current portfolio holdings and target weights or generate actionable trade orders.
  5. **SHAP Performance & Fallback**: `shap.KernelExplainer` is computationally heavy and can cause request timeouts; exception fallback only returns a single generic sentence. Needs robust mathematical heuristic fallback when SHAP or OpenAI fails.

### 2.7 `backend/agents/risk_profiler.py` (76 lines)
- **Role:** Interactive client risk profiling conversational agent.
- **Observed Implementation:**
  - Directly prompts `gpt-4o` with a system prompt asking to extract 6 parameters (`age`, `employment_status`, `annual_income`, `risk_tolerance_score`, `investment_horizon_years`, `primary_goal`).
  - Expects the LLM to output a JSON object containing `"PROFILE_COMPLETE": true`.
- **Gaps & Defects:**
  1. **Not a State Machine**: Has no formal state machine or structured state transitions (`DEMOGRAPHICS` -> `FINANCIAL_SITUATION` -> `RISK_TOLERANCE` -> `GOALS` -> `KYC_AML` -> `PROFILE_SYNTHESIS`).
  2. **No Draft Persistence**: If the connection drops or user refreshes, interview progress is lost; drafts are not saved to Redis or cache.
  3. **Missing Quantitative Calculations**: Does not compute `suitability_category`, `emotional_risk_score`, or `panic_sell_likelihood`.
  4. **No KYC / AML Typology**: Does not conduct KYC verification or evaluate AML risk typology rules.
  5. **Incomplete Field Extraction**: Fails to capture `dependents`, `liquid_assets`, `monthly_expenses`, `existing_debts`, `investment_experience`, `loss_capacity`, `target_return`, `specific_goals`.

### 2.8 `backend/agents/behavioral_bias.py` (55 lines)
- **Role:** Cognitive bias detection in user communication.
- **Observed Implementation:**
  - Passes user message directly to `gpt-4o` with temperature 0.2 to detect `loss_aversion`, `overconfidence`, `herding`, `recency_bias`.
- **Gaps & Defects:**
  1. **No Keyword / Pattern Pre-scoring**: Lacks deterministic regex/keyword scoring (threshold 0.6) before or alongside LLM calls.
  2. **No Behavioral Signal Analysis**: Ignores actual user behavioral telemetry (portfolio check frequency, sell-after-dip tendencies, concentration spikes, high trade frequency).
  3. **No Behavioral Memory**: Does not persist detected biases or track intervention history in database table `behavioral_memory`.
  4. **No HuggingFace Dataset Calibration**: Missing calibration against behavioral finance datasets.
  5. **Advisory-Only Enforcement**: Needs explicit contract ensuring bias alerts never block trades or allocations.

### 2.9 `backend/agents/compliance_guard.py` (72 lines)
- **Role:** Regulatory and suitability compliance gatekeeper.
- **Observed Implementation:**
  - Defines `Rule` and `ComplianceCheckResult`.
  - Contains only **two hardcoded rules**:
    - `SUIT-001` (Risk Profile Alignment): `rec.risk_level <= profile.risk_tolerance_score + 1`
    - `REG-003` (Non-Discretionary Confirmation): `trade.user_approved == True`
  - In `check_recommendation`: evaluates rules matching `"SUIT"`, raises `ComplianceViolationError` if any `BLOCK` severity fails.
- **Gaps & Defects:**
  1. **Missing 10 of 12 Required Rules**:
     - Suitability: Missing `SUIT-002` (Horizon Duration Match), `SUIT-003` (Liquidity Needs Match).
     - Concentration: Missing `CONC-001` (Single asset <= 30%), `CONC-002` (Sector/Class <= 50%), `CONC-003` (Illiquid <= 10%).
     - Regulatory: Missing `REG-001` (Prohibited guarantee claims), `REG-002` (Mandatory risk disclosure), `REG-004` (Paper trading guard).
     - AML: Missing `AML-001` (Unusual transaction volume/velocity), `AML-002` (KYC incomplete / sanctions flag).
  2. **Not DB-Configurable**: Rules are hardcoded in python; not loaded from `compliance_rules` table.
  3. **No Text Output Gating**: Lacks `gate_output()` method to check outbound agent text for guarantee language (`REG-001`) or risk disclosure (`REG-002`).
  4. **No Audit Logging**: Rule evaluations are not recorded into `audit_log`.

---

## 3. Missing Infrastructure and Modules

| Component / File | Status | Description & Requirements |
|---|---|---|
| **`core/config.py`** | **MISSING** | `pydantic-settings` Settings class. Loads `.env`, validates paper-only guard (refuses startup if Alpaca base URL is live), defines default keys, TTLs, and limits. |
| **`core/security.py`** | **MISSING** | Password hashing (`bcrypt`), JWT token generation/validation (`python-jose`), FastAPI dependency `get_current_user`, per-user ownership check (`client_id` vs `user.id`), WebSocket token authenticator. |
| **`db/init.sql`** | **MISSING** | SQL initialization script defining all 7 tables, constraints, foreign keys, and default compliance rule seed data. |
| **`db/migrations/` (Alembic)** | **MISSING** | Alembic migration environment (`alembic.ini`, `env.py`, initial revision script) for PostgreSQL and SQLite compatibility. |
| **`services/cache.py`** | **MISSING** | Unified caching interface with Redis client and automatic in-memory TTL dictionary fallback. Supports locks (30s trade submit), sessions (24h), drafts (1h), and market data TTLs. |
| **`services/audit_logger.py`** | **MISSING** | Append-only audit logger using SHA-256 hash chains and HMAC-SHA256 signatures (`AUDIT_SECRET_KEY`). Includes mutex for serialized writes, chain verification (`verify_audit_chain`), and tamper detection. |
| **`services/anchoring.py`** | **MISSING** | Computes Merkle roots over audit batches. Interacts with Sepolia testnet smart contract. Has chain ID 1 guard (refuses mainnet) and safe dry-run fallback if unconfigured. |
| **`services/data_pipeline.py`** | **MISSING** | Async HTTP client with rate limiting, exponential backoff (3 retries, 1s base), circuit breaker (5 failures, 60s cooldown), schema validation, and fixture fallback. |
| **`services/providers/`** | **MISSING** | Modular data providers: `equities.py` (yfinance / recorded samples), `treasury.py` (FiscalData REST API), `macro.py` (FRED/CalcFi series), `etf_holdings.py`, `screener.py`. |
| **`services/health_report.py`** | **MISSING** | Computes portfolio drift (>5% threshold), benchmark comparisons, alert rules (underperformance >10%, volatility >20% over tolerance), rebalancing trades, and LLM summary narrative. |
| **`agents/orchestrator.py`** | **MISSING** | Multi-agent orchestrator: stateful session router, coordinates interview -> analysis -> proposal -> approval -> execution, gates output through compliance guard, and records audit logs. |
| **`agents/market_data.py`** | **MISSING** | Market data agent providing real-time quotes, historical OHLCV, Treasury yield curves, macro indicators, and sector performance using pipeline and cache. |
| **`agents/product_comparison.py`** | **MISSING** | Six-factor scoring model (.30 expense ratio, .15 tracking/credit, .20 liquidity, .10 Sharpe/yield, .15 duration/spread, .10 ESG/diversity), suitability pre-filters, ranked output with rationale. |
| **`api/routes/`** | **MISSING** | Modular routers replacing monolith `main.py`: `auth.py`, `session.py`, `chat.py`, `profile.py`, `compare.py`, `portfolio.py`, `market.py`, `compliance.py`, `trade.py`, `audit.py`, `ws.py`. |
| **`tests/`** | **MISSING** | Comprehensive test directory containing `unit/`, `integration/`, `e2e/`, and `fixtures/` covering the 10 spec scenarios in Section 8.2 with >= 80% coverage. |

---

## 4. Gap Analysis Matrix

| Feature / Requirement | Current Code Status | Required Target State | Severity |
|---|---|---|---|
| **User Authentication** | ❌ Completely absent | `POST /register`, `POST /login`, `GET /me`, bcrypt hashing, JWT auth | **Critical** |
| **User Ownership Guard** | ❌ Completely absent | Verify `current_user.id` owns requested `client_id`, return 403 on mismatch | **Critical** |
| **Paper-Only Startup Guard** | ❌ Absent (`paper=True` hardcoded without URL check) | Refuse startup if Alpaca base URL is live / not paper | **Critical** |
| **Database Schema** | ⚠️ 3 tables exist; incomplete columns | 7 full tables (`users`, `client_profiles`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`, `audit_log`, `trades`) + Alembic migrations | **High** |
| **Cache & Session Service** | ❌ In-memory dict only in `main.py` | Redis client with in-memory TTL fallback; key format `data:{source}:{symbol}:{timeframe}`; trade lock (30s) | **High** |
| **Audit Hash Chaining & HMAC** | ⚠️ DB columns exist, but values are not generated or verified | SHA-256 chain + HMAC signatures, append-only enforcement, verification algorithm, `GET /audit/{client_id}/verify` | **Critical** |
| **Sepolia Merkle Anchoring** | ❌ Completely absent | Batch Merkle root computation, Sepolia testnet contract call, dry-run fallback, chain ID 1 guard | **Medium** |
| **Market Data Pipeline** | ❌ Hardcoded mock prices in `main.py` | Pluggable providers (yfinance, FiscalData, FRED), circuit breaker, retries, fixture fallback | **High** |
| **Product Comparison Agent** | ❌ Hardcoded responses in `main.py` | Six-factor scoring engine, ETF and Bond pipelines, suitability pre-filters | **High** |
| **Allocation Engine Constraints** | ⚠️ Hardcoded MPT in `allocation_engine.py` | Profile-driven constraints (risk tolerance, horizon, liquidity), efficient frontier generator, rebalance trade generator | **High** |
| **Risk Profiler Agent** | ⚠️ One-shot LLM prompt in `risk_profiler.py` | Formal state machine (6 states), draft caching, suitability category, emotional risk & panic sell scores, KYC/AML | **High** |
| **Behavioral Bias Agent** | ⚠️ One-shot LLM prompt in `behavioral_bias.py` | Keyword heuristics (threshold 0.6) + LLM, behavioral signal telemetry, memory persistence, advisory-only | **Medium** |
| **Compliance Rule Catalog** | ⚠️ 2 hardcoded rules in `compliance_guard.py` | 12 rules (SUIT 1-3, CONC 1-3, REG 1-4, AML 1-2) in DB, BLOCK/WARN semantics, audit logging, text output filter | **Critical** |
| **Execution Module Safeguards** | ⚠️ Basic Alpaca place order | 30s double-submit lock, approval timestamp freshness, KYC & AML verification, fill polling, audit entry | **High** |
| **Multi-Agent Orchestrator** | ❌ Monolith WebSocket logic in `main.py` | Stateful Orchestrator agent coordinating all agents, output compliance gating, trade approval flow | **Critical** |
| **REST API Modularization** | ❌ Monolith in `main.py` | Split into 11 distinct routers in `api/routes/`, lifespan context manager, remove all hardcoded mock responses | **High** |
| **WebSocket Events** | ⚠️ Ad-hoc JSON messages in `main.py` | JWT-protected `/ws/chat?token=...`, structured event schemas (`user_message`, `agent_response`, `trade_proposal`, etc.) | **High** |
| **Health Report Service** | ❌ Hardcoded mock in `main.py` | 5% drift calculation, benchmark comparison, alert rules, LLM narrative, rebalance orders | **Medium** |
| **Test Suite** | ❌ Zero test files exist | Unit, integration, E2E, and compliance tests covering 10 spec scenarios; >=80% coverage | **Critical** |

---

## 5. Technical Debt, Fragilities, and Security Risks

1. **Exposure of Secrets Risk**:
   - The root `.env` file contains keys. While `.gitignore` includes `.env`, all codebase config must load secrets safely through `pydantic-settings` without leaking into logs or exception traces.
2. **Missing Input Validation & Cross-User Authorization**:
   - Any client ID passed to `GET /api/v1/profile/{client_id}` or `POST /api/v1/trade/execute` currently processes without verifying whether the authenticated caller owns that profile. This violates privacy and regulatory rules.
3. **Unvalidated Execution**:
   - `POST /api/v1/trade/execute` currently fabricates a mock recommendation and approves execution without checking if the client was KYC verified or AML cleared, and without verifying when the user approved the trade.
4. **Fragile AI Dependency**:
   - All existing agent interactions rely on synchronous-style calls to OpenAI without structured JSON schemas, timeouts, or fallback handlers, risking unhandled exceptions if the OpenAI API is rate-limited or fails.
5. **No Local Redis/Postgres Requirement**:
   - Local system check indicates Redis is **not running** (`Redis running: False`). The cache and locking layer must implement an in-memory fallback that operates smoothly without requiring external Docker services.

---

## 6. Synthesis & Recommended Implementation Order

To execute the transformation from scaffold to fully compliant backend, the work naturally breaks down into the following implementation sequence:

1. **Milestone 1: Foundation (Core, Security, DB, Caching, Audit)**
   - Implement `core/config.py` with paper-only guard.
   - Implement `core/security.py` (bcrypt, JWT, dependencies).
   - Complete `db/models.py` (all 7 tables, full fields), `db/init.sql`, and Alembic migrations.
   - Implement `services/cache.py` (Redis + in-memory fallback, lock, session, draft).
   - Implement `services/audit_logger.py` (hash chain + HMAC + verification).
   - Implement `services/anchoring.py` (Merkle tree + Sepolia dry-run).
2. **Milestone 2: Data Pipeline & Market Data**
   - Implement `services/data_pipeline.py` (rate limiter, retries, circuit breaker).
   - Implement providers in `services/providers/` (yfinance, FiscalData, FRED, fixtures).
   - Implement `agents/market_data.py`.
3. **Milestone 3: Core Analytical Agents**
   - Refactor `agents/risk_profiler.py` into formal state machine with scoring and draft caching.
   - Refactor `agents/behavioral_bias.py` with heuristics, telemetry, and memory.
   - Implement `agents/product_comparison.py` with six-factor scoring.
   - Refactor `agents/allocation_engine.py` with dynamic constraints, efficient frontier, and rebalancing.
4. **Milestone 4: Compliance, Execution & Health Report**
   - Expand `agents/compliance_guard.py` to full 12-rule catalog with DB loading and text gating.
   - Harden `agents/execution_module.py` (30s lock, KYC/AML check, approval check, fill tracking).
   - Implement `services/health_report.py` (drift, alerts, rebalance trades).
5. **Milestone 5: Orchestration & API Routing**
   - Implement `agents/orchestrator.py`.
   - Break `main.py` into modular routers in `api/routes/` with lifespan context manager.
   - Implement authenticated `/ws/chat?token=...` with full event lifecycle.
   - Remove all mock responses from REST endpoints.
6. **Milestone 6: Verification, Testing & Spec Scenarios**
   - Build unit test suite (compliance rules, scoring, hash chain verification).
   - Build integration test suite (data pipeline with recorded fixtures, API auth).
   - Build E2E test suite covering the 10 spec scenarios in Section 8.2.
   - Verify coverage >= 80% via `pytest -q --cov=. --cov-fail-under=80`.

---
*End of Analysis Report.*

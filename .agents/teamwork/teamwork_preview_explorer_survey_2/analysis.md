# Backend Survey & Environmental Assessment: Wealth Advisory Agent

**Date**: 2026-10-10  
**Author**: Survey Explorer 2  
**Target Directory**: `c:\Users\HP VICTUS\Documents\wealth_agent\backend`  
**Authoritative Plan**: `C:\Users\HP VICTUS\.gemini\antigravity\brain\9f1c4f1d-ef21-4c12-aa8c-d125e3bed282\implementation_plan.md`  
**Authoritative Requirements**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md`

---

## 1. Executive Summary

A comprehensive investigation of the Wealth Advisory Agent backend was performed to assess runtime environment viability, package dependencies, database schemas, test harnesses, external provider integrations, and migration requirements.

The current backend is a minimal scaffold:
- Core agents are incomplete or unconstrained prompts (e.g. `RiskProfilerAgent` is a basic chat prompt rather than a state machine, `BehavioralBiasAgent` lacks heuristics/signals/memory, `ComplianceGuard` only has 2 hardcoded rules, and `ExecutionModule` lacks Redis locks, fresh approval checks, and KYC verification).
- Missing critical agent modules: `Orchestrator`, `MarketData`, and `ProductComparison`.
- `main.py` is a monolithic 297-line file using deprecated `@app.on_event("startup")` and returning hard-coded mock responses on almost all endpoints.
- Database contains only 3 incomplete tables (`client_profiles`, `audit_log`, `trades`) with 0 rows, lacking `users`, `portfolio_snapshots`, `behavioral_memory`, and `compliance_rules`. No Alembic migration configuration exists.
- Crucial dependencies (`pytest-cov`, `yfinance`, `web3`, `pyarrow`) are missing from the environment or encounter runtime import failures (`datasets` requires `pyarrow`).
- There is currently no `tests/` directory, no `pytest.ini`, and no recorded data fixtures.

This report establishes the baseline facts and actionable blueprints for the builder agents.

---

## 2. Environment & Dependency Analysis

### 2.1 Python Runtime
- **Python Version**: `3.12.4` (Windows AMD64)
- **Local Database**: SQLite 3 (`wealth_advisor.db`) via `aiosqlite`
- **Network / Services**: Local Redis port 6379 is **closed** (in-memory TTL fallback is active/mandatory).

### 2.2 `backend/requirements.txt` vs. Installed vs. Required
Current `backend/requirements.txt` (16 lines, 261 bytes):
```txt
fastapi>=0.104.1
uvicorn>=0.24.0
pydantic>=2.5.2
pydantic-settings>=2.1.0
SQLAlchemy>=2.0.23
asyncpg>=0.29.0
redis>=5.0.1
alpaca-py>=0.30.0
langchain>=0.0.344
shap>=0.44.0
scikit-learn>=1.3.2
skfolio>=0.1.0
openai>=1.13.3
python-dotenv>=1.0.0
aiosqlite>=0.19.0
```

#### Package Status Audit Matrix

| Package | In `requirements.txt`? | Installed in Python? | Runtime Verification | Status / Recommendation |
| :--- | :---: | :---: | :---: | :--- |
| `fastapi` | Yes (`>=0.104.1`) | `0.141.1` | Imports OK | Compatible |
| `uvicorn` | Yes (`>=0.24.0`) | `0.52.4` | Imports OK | Compatible |
| `pydantic` | Yes (`>=2.5.2`) | `2.13.4` | Imports OK | Compatible |
| `pydantic-settings` | Yes (`>=2.1.0`) | `2.14.2` | Imports OK | Compatible |
| `SQLAlchemy` | Yes (`>=2.0.23`) | `2.0.52` | Imports OK | Compatible (Asyncio 2.0 API) |
| `asyncpg` | Yes (`>=0.29.0`) | `0.32.0` | Imports OK | Compatible |
| `aiosqlite` | Yes (`>=0.19.0`) | `0.22.1` | Imports OK | Compatible |
| `redis` | Yes (`>=5.0.1`) | `5.0.4` | Imports OK | Needs graceful in-memory fallback |
| `alpaca-py` | Yes (`>=0.30.0`) | `0.44.0` | Imports OK | Compatible (`paper=True` enforced) |
| `skfolio` | Yes (`>=0.1.0`) | `1.8.0` | Imports OK | Verified: `m.weights_` and `p.weights` present |
| `shap` | Yes (`>=0.44.0`) | `0.53.0` | Imports OK | Verified: KernelExplainer needs fallback |
| `openai` | Yes (`>=1.13.3`) | `3.8.0` | Imports OK | AsyncOpenAI client used |
| **`passlib` / `bcrypt`** | **Missing** | `1.7.4` / `4.0.1` | Imports OK | **Must add to `requirements.txt`** |
| **`python-jose`** | **Missing** | `3.5.0` | Imports OK | **Must add to `requirements.txt`** |
| **`python-multipart`**| **Missing** | `0.0.32` | Imports OK | **Must add to `requirements.txt`** (Auth forms) |
| **`httpx`** | **Missing** | `0.28.1` | Imports OK | **Must add to `requirements.txt`** (Data pipeline & tests) |
| **`alembic`** | **Missing** | `1.19.2` | Imports OK | **Must add to `requirements.txt`** |
| **`pytest`** | **Missing** | `9.1.1` | Imports OK | **Must add to `requirements.txt`** |
| **`pytest-asyncio`** | **Missing** | `1.4.0` | Imports OK | **Must add to `requirements.txt`** |
| **`pytest-cov`** | **Missing** | **NOT INSTALLED** | `ModuleNotFoundError` | **Must install & add to `requirements.txt`** (`--cov` fails without it) |
| **`yfinance`** | **Missing** | **NOT INSTALLED** | `ModuleNotFoundError` | **Must install & add to `requirements.txt`** (and implement fixture fallback) |
| **`web3`** | **Missing** | **NOT INSTALLED** | `ModuleNotFoundError` | **Must install & add to `requirements.txt`** (anchoring must dry-run if absent) |
| **`huggingface-hub`**| **Missing** | `0.33.0` | Imports OK | Installed; can fetch HuggingFace datasets |
| **`datasets`** | **Missing** | `3.6.0` | **Broken Import** | `ModuleNotFoundError: No module named 'pyarrow'`. Needs `pyarrow` or local JSON fixture fallback |

### 2.3 Dependency Conflicts Detected via `pip check`
Running `pip check` revealed:
1. `datasets 3.6.0 requires pyarrow, which is not installed.`
2. `datasets 3.6.0 requires dill, which is not installed.`
3. `datasets 3.6.0 has requirement fsspec[http]<=2025.3.0,>=2023.1.0, but you have fsspec 2026.9.0.`

**Key Takeaway**: The `BehavioralBiasAgent` grounding implementation must NOT rely unconditionally on the `datasets` library directly. It should use `huggingface_hub` or load local calibrated behavioral scenario fixtures (`tests/fixtures/behavioral_datasets.json`), making external download optional with deterministic fallback.

---

## 3. Environment Variables & Secret Configuration

### 3.1 Existing `.env` Inspection
Keys found in root `.env`:
```
ALPACA_API_KEY
ALPACA_SECRET_KEY
OPENAI_API_KEY
DATABASE_URL
REDIS_URL
AUDIT_SECRET_KEY
SEPOLIA_RPC_URL
LOG_LEVEL
```

### 3.2 Required Environment Variables & Gaps
The following variables are required by the implementation plan and must be defined in `core/config.py` with pydantic-settings:

| Variable | Current State in `.env` | Purpose & Validation Rules |
| :--- | :--- | :--- |
| `ALPACA_API_KEY` | Present | Alpaca paper trading API key |
| `ALPACA_SECRET_KEY` | Present | Alpaca paper trading secret |
| `ALPACA_BASE_URL` | **Missing** | Default: `https://paper-api.alpaca.markets`. Must reject `https://api.alpaca.markets` (live URL guard). |
| `OPENAI_API_KEY` | Present | OpenAI API key for agents |
| `OPENAI_MODEL` | **Missing** | Default `gpt-4o`. Configurable via env. |
| `DATABASE_URL` | Present | Default: `sqlite+aiosqlite:///./wealth_advisor.db`. Normalizes postgres URL to `postgresql+asyncpg://`. |
| `REDIS_URL` | Present | Default: `redis://localhost:6379/0`. Fallback to in-memory store if unreachable. |
| `AUDIT_SECRET_KEY` | Present | Secret HMAC key for SHA-256 HMAC audit entry signing. |
| `SEPOLIA_RPC_URL` | Present | Sepolia Ethereum RPC URL. Must refuse Ethereum Mainnet (chain ID 1). |
| `SEPOLIA_PRIVATE_KEY`| **Missing** | Testnet private key for on-chain anchoring. If unset, anchoring runs in dry-run mode. |
| `AUDIT_CONTRACT_ADDRESS`| **Missing**| Testnet contract address for Merkle root anchoring. Dry-run if unset. |
| `FRED_API_KEY` | **Missing** | FRED API key. If unset, macro provider falls back to Treasury + sample fixtures. |
| `JWT_SECRET_KEY` | **Missing** | Secret key for JWT auth token signing (HS256). |
| `JWT_ALGORITHM` | **Missing** | Default: `HS256`. |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | **Missing** | Default: `1440` (24 hours). |
| `LOG_LEVEL` | Present | Default `INFO`. |
| `DRY_RUN` | **Missing** | Boolean flag (default `True` when API keys are mock/unset). |

### 3.3 File System Flaws: `.env.example` & `.gitignore`
- `.env.example` does **not exist** anywhere in the repository.
- `.gitignore` currently contains `.env` and `.env.example`. Ignoring `.env.example` is incorrect because example configs must be committed to git.
- **Action Needed**: Create `.env.example` with safe placeholder values, and update `.gitignore` so `.env.example` is tracked.

---

## 4. Database Schema & Migration Analysis

### 4.1 Existing SQLite Database (`wealth_advisor.db`)
Inspection of `wealth_advisor.db` revealed:
- `client_profiles` (15 columns, 0 rows)
- `audit_log` (10 columns, 0 rows)
- `trades` (13 columns, 0 rows)
- `alembic_version` does not exist (Alembic has never been initialized).

### 4.2 SQLAlchemy Models & Schema Discrepancies (`db/models.py`)

1. **`users` Table (MISSING)**:
   - Needed for authentication (`POST /api/v1/auth/register`, `/login`, `GET /auth/me`).
   - Fields needed:
     - `id`: String UUID (PK)
     - `email`: String, unique, indexed, non-null
     - `hashed_password`: String, non-null
     - `full_name`: String, nullable
     - `is_active`: Boolean, default True
     - `created_at`: DateTime (UTC)
     - `updated_at`: DateTime (UTC)

2. **`client_profiles` Table (INCOMPLETE)**:
   - Current columns in `db/models.py`: `client_id`, `age`, `employment_status`, `annual_income`, `net_worth`, `risk_tolerance_score`, `investment_horizon_years`, `liquidity_needs`, `primary_goal`, `suitability_category`, `detected_biases`, `kyc_verified`, `aml_flag`, `created_at`, `updated_at`.
   - Missing fields specified in `models/client_profile.py` and requirements:
     - `user_id`: String FK referencing `users.id` (**Crucial for per-user ownership and 403 authorization checks**)
     - `dependents`: Integer
     - `liquid_assets`: Float
     - `monthly_expenses`: Float
     - `existing_debts`: Float
     - `investment_experience`: String
     - `loss_capacity`: String
     - `target_return`: Float
     - `specific_goals`: JSON
     - `emotional_risk_score`: Float
     - `panic_sell_likelihood`: Float
     - `profiling_session_transcript`: Text/String

3. **`portfolio_snapshots` Table (MISSING)**:
   - Needed for portfolio state tracking, drift monitoring, and health reporting.
   - Fields: `snapshot_id` (PK), `client_id` (FK), `timestamp`, `total_value`, `cash_balance`, `positions` (JSON), `metrics` (JSON), `drift_percentage`, `rebalance_recommended`.

4. **`behavioral_memory` Table (MISSING)**:
   - Needed for `BehavioralBiasAgent` persistent memory across sessions.
   - Fields: `memory_id` (PK), `client_id` (FK), `session_id`, `timestamp`, `bias_type`, `confidence`, `context_quote`, `intervention_offered`, `user_reaction`.

5. **`compliance_rules` Table (MISSING)**:
   - Needed for dynamic rule configuration loaded by `ComplianceGuard`.
   - Fields: `rule_id` (PK, e.g. `SUIT-001`), `category` (SUIT, CONC, REG, AML), `name`, `description`, `rule_type`, `parameters` (JSON), `severity` (BLOCK, WARN), `is_active`, `created_at`.

6. **`audit_log` Table**:
   - Must enforce **append-only** constraint:
     - SQLite: Register SQLAlchemy ORM event listener (`before_update`, `before_delete`) raising `PermissionError("Audit log is append-only")`.
     - PostgreSQL: Add trigger function raising exception on UPDATE or DELETE.
   - Fields: `entry_id`, `timestamp`, `event_type`, `client_id`, `session_id`, `agent_id`, `action` (JSON), `entry_hash`, `previous_hash`, `hmac_signature`.

### 4.3 Alembic Setup Blueprint
- Create `backend/alembic.ini`.
- Create `backend/db/migrations/`:
  - `env.py`: Asynchronous migration runner supporting `aiosqlite` and `asyncpg`, binding to `Base.metadata`.
  - `script.py.mako`: Template for migration files.
  - `versions/0001_initial_schema.py`: Migration creating all 7 tables (`users`, `client_profiles`, `audit_log`, `trades`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`).

---

## 5. Provider Dependencies & Architecture Analysis

### 5.1 Provider Matrix & Fallback Strategies

| Provider | Data Domain | Primary Target | Fallback Strategy | Resiliency Pattern |
| :--- | :--- | :--- | :--- | :--- |
| **`yfinance`** | Equities & ETFs | Real-time quotes, OHLCV history, ETF holdings | Local recorded JSON fixtures in `tests/fixtures/` | Circuit breaker (5 failures / 60s cooldown), 3 retries with exponential backoff (1s base), 30s quote TTL, 24h OHLCV TTL |
| **US Treasury FiscalData** | Fixed Income | Yield curve, Treasury interest rates | Public REST API (`api.fiscaldata.treasury.gov`) / recorded yield curve fixture | Circuit breaker, 12h cache TTL |
| **FRED / CalcFi** | Macro Indicators | CPI, Unemployment Rate, Fed Funds Rate | FRED API (`api.stlouisfed.org`) if `FRED_API_KEY` present; CalcFi CSV / pre-recorded macro fixture | Circuit breaker, 24h cache TTL |
| **Alpaca** | Brokerage & Execution | Market orders, positions, account balance | Paper trading client (`TradingClient(paper=True)`); Mock fill in explicit `DRY_RUN` mode | Strict paper URL guard at startup; 30s Redis duplicate submit lock; fresh approval check; KYC gate |
| **Sepolia Web3** | Merkle Anchoring | Ethereum testnet batch transaction | Web3 RPC client (`eth_sendRawTransaction`); Dry-run mode if unconfigured | Chain-ID guard (refuse chain ID 1); SHA-256 Merkle root computation |
| **Redis** | Cache, Session, Lock | Distributed locks, quote cache, session storage | In-memory asyncio dictionary with TTL eviction | Transparent wrapper: tries Redis connection; if connection fails or Redis down, seamlessly delegates to in-memory store |
| **`skfolio` & `SHAP`**| Portfolio Optimization | MeanRisk (CVaR), Efficient Frontier, Weights | Pure Python optimization with numpy/scipy; Robust heuristic fallback if SHAP fails | Profile-driven constraints (min/max weights); SHAP KernelExplainer with timeout and fallback explanation |
| **HuggingFace** | Behavioral Grounding | Bias prompt calibration & behavioral signals | `huggingface_hub` or local JSON fixture (`fixtures/behavioral_datasets.json`) | Advisory-only bias intervention; rule-based heuristics (threshold 0.6) + LLM confirmation |

### 5.2 Cache & Lock Specification
- Cache key convention: `data:{source}:{symbol}:{timeframe}`
- TTL specification:
  - Quotes: 30 seconds
  - OHLCV: 24 hours
  - Holdings: 6 hours
  - Macro: 24 hours
  - Treasury yield curve: 12 hours
  - Trade execution lock: 30 seconds (`lock:trade:{client_id}:{symbol}`)
  - Session state: 24 hours (`session:{session_id}`)
  - Profile draft: 1 hour (`draft:profile:{user_id}`)

---

## 6. API & WebSocket Architecture Review

### 6.1 `backend/main.py` Current Issues
1. Monolithic structure: All endpoints, models, agent instantiations, and WebSocket handlers are crammed into 297 lines in `main.py`.
2. Deprecated lifecycle: Uses `@app.on_event("startup")` instead of FastAPI `lifespan` context manager.
3. Hardcoded mock responses:
   - `POST /api/v1/session/start`: returns dummy session UUID.
   - `POST /api/v1/chat/message`: returns placeholder text.
   - `POST /api/v1/compare/etfs` & `bonds`: returns dummy scores (8.5, 7.2) and hardcoded rationale.
   - `GET /api/v1/portfolio/{client_id}`: returns hardcoded 10000.0 value and BND.
   - `GET /api/v1/audit/{client_id}`: returns hardcoded dummy entry.
   - `GET /api/v1/market/quote/{symbol}`: returns dummy price 150.0.
   - `GET /api/v1/market/macro`: returns hardcoded CPI 3.2, unemployment 4.1.
   - `POST /api/v1/portfolio/health-report`: returns hardcoded healthy narrative.
4. WebSocket lacks JWT authentication query parameter (`/ws/chat?token=...`).

### 6.2 Router Modularization Plan
Split `main.py` into `api/routes/`:
- `auth.py`: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
- `session.py`: `POST /api/v1/session/start`
- `chat.py`: `POST /api/v1/chat/message`, `WebSocket /ws/chat`
- `profile.py`: `GET /api/v1/profile/{client_id}`, `PUT /api/v1/profile/{client_id}`
- `market.py`: `GET /api/v1/market/quote/{symbol}`, `GET /api/v1/market/history/{symbol}`, `GET /api/v1/market/macro`, `GET /api/v1/market/yield-curve`
- `compare.py`: `POST /api/v1/compare/etfs`, `POST /api/v1/compare/bonds`
- `portfolio.py`: `GET /api/v1/portfolio/{client_id}`, `POST /api/v1/portfolio/health-report`, `POST /api/v1/portfolio/rebalance`
- `trade.py`: `POST /api/v1/trade/propose`, `POST /api/v1/trade/execute`, `GET /api/v1/trade/{trade_id}`
- `compliance.py`: `GET /api/v1/compliance/rules`, `POST /api/v1/compliance/rules`
- `audit.py`: `GET /api/v1/audit/{client_id}`, `GET /api/v1/audit/{client_id}/verify`

---

## 7. Test Configuration & Verification Infrastructure

### 7.1 Existing Test Suite: None
No `tests/` directory exists. No `pytest.ini` exists.

### 7.2 Verification Target: 80% Coverage
The acceptance criteria require:
`pytest -q --cov=. --cov-fail-under=80`

### 7.3 Required Test Fixtures & Structure
```
backend/
├── pytest.ini
└── tests/
    ├── conftest.py               # In-memory async SQLite engine, AsyncClient, auth fixtures
    ├── fixtures/
    │   ├── profiles.json          # Varied client profiles (conservative to aggressive, AML flagged)
    │   ├── market_quotes.json     # SPY, BND, AGG, VTI, VXUS, GLD recorded quotes & OHLCV
    │   ├── treasury_curve.json    # US Treasury yield curve points
    │   ├── macro_indicators.json  # CPI, unemployment rate, fed funds rate
    │   ├── alpaca_responses.json  # Mock order fills and position snapshots
    │   └── behavioral_scenarios.json # HuggingFace behavioral calibration samples
    ├── unit/
    │   ├── test_security.py       # Password hashing, JWT creation/verification, ownership
    │   ├── test_cache.py          # In-memory TTL fallback, Redis connection, lock acquisition
    │   ├── test_audit_logger.py   # Hash-chain over 100 entries, tamper detection, HMAC verification
    │   ├── test_compliance_guard.py # 100% rule catalog (SUIT 1-3, CONC 1-3, REG 1-4, AML 1-2 pass & fail)
    │   ├── test_risk_profiler.py  # State machine flow, suitability scoring, KYC/AML typologies
    │   ├── test_behavioral_bias.py# Pattern matching (threshold 0.6), signal detection, memory
    │   ├── test_product_comparison.py # Six-factor scoring weights (.30/.15/.20/.10/.15/.10)
    │   ├── test_allocation_engine.py  # skfolio optimization, frontier calculation, SHAP explanation
    │   ├── test_execution_module.py   # REG-003 approval check, 30s duplicate lock, KYC gate
    │   └── test_anchoring.py      # Merkle root computation, Sepolia dry-run, chain-ID 1 rejection
    ├── integration/
    │   ├── test_data_pipeline.py  # Rate limiter, retries, circuit breaker, fixture fallback
    │   ├── test_api_auth.py       # 401 unauthenticated, 403 cross-client ownership checks
    │   ├── test_api_routes.py     # All 13 REST endpoints with authentic responses
    │   └── test_websocket_chat.py # /ws/chat?token=..., event protocol verification
    └── e2e/
        └── test_spec_scenarios.py # 10 full user scenarios from specification section 8.2
```

---

## 8. Gap Analysis & Implementer Action Items

1. **Install Missing Packages & Update `requirements.txt`**:
   - Install `pytest-cov`, `yfinance`, `web3`.
   - Update `requirements.txt` to include all runtime dependencies (`alembic`, `passlib[bcrypt]`, `python-jose`, `python-multipart`, `httpx`, `pytest`, `pytest-asyncio`, `pytest-cov`, `yfinance`, `web3`).
2. **Environment & Security**:
   - Create `backend/core/config.py` with pydantic-settings, validating `paper=True` and chain ID.
   - Create `backend/core/security.py` with bcrypt, JWT creation, token decoding, and `get_current_user`.
   - Create `.env.example` in project root and un-ignore it in `.gitignore`.
3. **Database & Migrations**:
   - Complete `backend/db/models.py` with all 7 models.
   - Initialize Alembic with async `env.py` and initial migration `0001_initial_schema.py`.
   - Add append-only ORM event listener on `DBAuditLog`.
4. **Services Layer**:
   - `services/cache.py`: Redis client with seamless in-memory fallback and lock service.
   - `services/audit_logger.py`: SHA-256 hash chaining, HMAC signing, chain verification.
   - `services/anchoring.py`: Merkle tree calculation, Sepolia testnet anchoring with dry-run fallback.
   - `services/data_pipeline.py`: Async HTTP client with circuit breaker, retries, and provider classes.
   - `services/health_report.py`: Portfolio drift calculation, benchmark comparison, rebalance proposals.
5. **Agents Layer**:
   - Implement `agents/orchestrator.py` managing sessions and routing.
   - Refactor `agents/risk_profiler.py` into deterministic state machine with KYC/AML typologies.
   - Refactor `agents/behavioral_bias.py` with pattern matching heuristics, signal analysis, and memory persistence.
   - Implement `agents/product_comparison.py` with six-factor weighted scoring.
   - Refactor `agents/compliance_guard.py` to load all 12 rules, check text outputs for 'guaranteed' and risk disclosures.
   - Refactor `agents/execution_module.py` with 30s duplicate lock, KYC check, fresh approval check.
   - Update `agents/allocation_engine.py` with efficient frontier points and SHAP fallbacks.
6. **API Layer**:
   - Refactor `main.py` to use `lifespan` and mount modular routers from `api/routes/`.
   - Implement JWT-authenticated WebSocket with the 8 specified event types.
7. **Test Suite**:
   - Write `pytest.ini` and all fixtures in `tests/fixtures/`.
   - Implement unit, integration, and e2e test suites to guarantee `>=80%` test coverage.

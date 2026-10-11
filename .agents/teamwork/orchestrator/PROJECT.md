# Project: Wealth Advisory Agent Backend Implementation

## Architecture
- **Framework**: FastAPI (modular routers under `backend/api/routes/`, lifespan management, zero mock responses)
- **Security & Auth**: `backend/core/security.py` (bcrypt hashing, JWT REST bearer auth, WebSocket `?token=` query auth, per-user client ownership enforcement `user.id == client.user_id`)
- **Configuration**: `backend/core/config.py` (pydantic-settings, hard `paper=True` Alpaca guard, Sepolia testnet-only chain ID 11155111 guard refusing mainnet chain ID 1, secrets protected)
- **Database & Persistence**: `backend/db/models.py` (7 tables: `users`, `client_profiles`, `portfolio_snapshots`, `trades`, `audit_log`, `behavioral_memory`, `compliance_rules`), ORM append-only event listeners on `audit_log`, `db/init.sql` seed script, and Alembic migrations (`alembic.ini`, `backend/db/migrations/`)
- **Cache & Locks**: `backend/services/cache.py` (Redis client with automatic, robust in-memory TTL dictionary fallback; standardized key templates `data:{source}:{symbol}:{timeframe}`, `lock:trade:{client_id}`, `profile:draft:{session_id}`)
- **Audit & Cryptography**: `backend/services/audit_logger.py` (SHA-256 hash-chaining, HMAC signatures, serialized writes, verification utility `verify_audit_chain()`) & `backend/services/anchoring.py` (Merkle tree root generation, Sepolia smart contract anchoring with dry-run fallback)
- **Data Pipeline**: `backend/services/data_pipeline.py` (rate-limited async HTTP, 3 retries with 1s exponential backoff, circuit breaker [5 failures -> 60s cooldown], schema validation, offline recorded fixture fallback in `backend/tests/fixtures/`) with provider modules (`equities.py`, `treasury.py`, `macro.py`)
- **Multi-Agent System**:
  - `agents/market_data.py`: Unified quotes, price history, yield curve, macro indicators, sector performance
  - `agents/risk_profiler.py`: 6-state machine (`DEMOGRAPHICS` -> `FINANCIAL_SITUATION` -> `TIME_HORIZON` -> `RISK_TOLERANCE` -> `EXPERIENCE` -> `PROFILE_SYNTHESIS`), draft caching, quantitative scoring (`suitability_category`, `emotional_risk_score`, `panic_sell_likelihood`), KYC status, AML flags
  - `agents/behavioral_bias.py`: Dual-layer bias detection (keyword/regex pattern scoring threshold 0.6 + LLM contextual confirmation), behavioral telemetry signals (check frequency, panic dip selling, concentration, trade frequency), persistent memory in `behavioral_memory` table, calibrated offline scenario fixtures
  - `agents/product_comparison.py`: Six-factor composite scoring ($w = 0.30, 0.15, 0.20, 0.10, 0.15, 0.10$), ETF and bond asset evaluation pipelines, suitability pre-filtering, ranked rationale
  - `agents/allocation_engine.py`: Profile-driven optimization constraints (risk tolerance, liquidity), skfolio CVaR optimization with fallback, efficient frontier curve generation, rebalancing trade generator, robust SHAP attribution
  - `agents/compliance_guard.py`: Full 12-rule catalog (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`) loaded from DB table, `BLOCK` vs `WARN` enforcement, audit-logging of every check, text output filter catching prohibited guarantee language (`REG-001`) and enforcing risk disclosures (`REG-002`)
  - `agents/execution_module.py`: Alpaca paper trading client with explicit `DRY_RUN` flag, 30s double-submit distributed/in-memory lock, 15-minute approval window check (`REG-004`), KYC check, fill polling, DB trade persistence, and audit logging
  - `services/health_report.py`: 5% drift threshold calculation against target allocation, benchmark comparison, alert rules, LLM narrative generator, rebalance trade recommendations
  - `agents/orchestrator.py`: Central dialogue and workflow routing, session state tracking, proposal approval workflow (propose -> user review -> approve/reject/modify), compliance gating on all outgoing messages

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Configuration & Startup Guard | Pydantic-settings, `.env` loading, paper-only Alpaca check, Sepolia chain guard | M1 | R1, plan §1 |
| 2 | Authentication & Ownership Security | Bcrypt hashing, JWT create/verify, `get_current_user`, ownership check (`client_id`) | M1 | R1, plan §1 |
| 3 | Database Models & Invariants | 7 models (`users`, `client_profiles`, `portfolio_snapshots`, `trades`, `audit_log`, `behavioral_memory`, `compliance_rules`), ORM append-only guard | M1 | R1, plan §1 |
| 4 | Database Migrations & Seeds | Alembic configuration, async migration scripts, `db/init.sql` seed script | M1 | R1, plan §1 |
| 5 | Cache & Lock Service | Redis client with in-memory TTL dictionary fallback, 30s trade locks, TTL constants | M1 | R1, plan §1 |
| 6 | Hash-Chained Audit Logger | SHA-256 hash chaining, HMAC-SHA256 signature, `verify_audit_chain` integrity verifier | M1 | R1, plan §1 |
| 7 | Merkle Root & Sepolia Anchoring | Merkle root generator, Sepolia testnet anchor, dry-run when unconfigured, mainnet reject | M1 | R1, plan §1 |
| 8 | Resilient Data Pipeline | Async HTTP client, exponential backoff (3 retries), circuit breaker (5 fails/60s), fixtures | M2 | R2, plan §2 |
| 9 | Data Providers (Equities, Treasury, Macro) | Providers for yfinance (equities), FiscalData (treasury), FRED/CalcFi (macro) + sample data | M2 | R2, plan §2 |
| 10 | Market Data Agent | Unified quotes, historical prices, yield curve, macro context, sector performance | M2 | R2, plan §2 |
| 11 | State-Machine Risk Profiler | 6-state progression, draft caching in Redis/in-memory, scoring, KYC/AML flags | M3 | R3, plan §3 |
| 12 | Behavioral Bias Detection & Memory | Keyword heuristic (0.6 threshold) + LLM, behavioral telemetry, `behavioral_memory` storage | M3 | R3, plan §3 |
| 13 | Six-Factor Product Comparison | 6-factor composite scoring ($w=.30/.15/.20/.10/.15/.10$), ETF & bond pipelines, suitability filters | M3 | R3, plan §3 |
| 14 | Dynamic Allocation & Rebalance Engine | Profile-driven constraints, skfolio CVaR, efficient frontier points, rebalance trade generator | M3 | R3, plan §3 |
| 15 | Full 12-Rule Compliance Guard | `SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002` DB-driven, audit logged | M4 | R3, plan §3 |
| 16 | Regulatory Output Text Filter | Block 'guaranteed' returns (`REG-001`), enforce mandatory risk disclosures (`REG-002`) | M4 | R3, plan §3 |
| 17 | Hardened Execution Module | 30s double-submit lock, 15m approval window (`REG-004`), KYC check, fill polling, audit log | M4 | R3, plan §3 |
| 18 | Portfolio Health & Drift Report | 5% drift threshold calculation, benchmark comparison, alert rules, rebalancing trades | M4 | R3, plan §3 |
| 19 | Multi-Agent Orchestrator | Central dialogue routing, session state machine, trade proposal approval gate, compliance filter | M5 | R3, plan §3 |
| 20 | REST API Routers (13 endpoints) | `auth/` (3), `session/` (1), `chat/` (1), `profile/` (1), `compare/` (2), `portfolio/` (2), `trade/` (1), `audit/` (2) | M5 | R4, plan §4 |
| 21 | Authenticated WebSocket Chat | `/ws/chat?token=...` handling 8 structured event types, full agent flow streaming | M5 | R4, plan §4 |
| 22 | Lifespan & Mock Removal | Replace deprecated startup with FastAPI `lifespan`, remove all mock returns in routes | M5 | R4, plan §4 |
| 23 | E2E Test Suite & 10 Spec Scenarios | Unit, integration, compliance rule suite, 10 spec scenarios (8.2), >=80% coverage gate | M6 | R5, plan §5 |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M1 | Foundation: Config, Security, DB, Cache & Audit | Requirements 1-7: `core/config.py`, `core/security.py`, `db/models.py`, `db/migrations/`, `db/init.sql`, `services/cache.py`, `services/audit_logger.py`, `services/anchoring.py`, `requirements.txt` update | none | DONE (112 tests pass, 86% cov, clean audit) |
| M2 | Data Layer: Pipeline, Providers & Market Data Agent | Requirements 8-10: `services/data_pipeline.py`, `services/providers/`, `agents/market_data.py`, recorded offline fixtures in `tests/fixtures/` | M1 | DONE (222 tests pass, 88% cov, clean audit) |
| M3 | Core Agents: Profiler, Bias, Product Comparison & Allocation | Requirements 11-14: `agents/risk_profiler.py`, `agents/behavioral_bias.py`, `agents/product_comparison.py`, `agents/allocation_engine.py` | M1, M2 | DONE (334 tests pass, 87% cov, clean audit) |
| M4 | Compliance, Execution & Health Report | Requirements 15-18: `agents/compliance_guard.py` (12 rules + text filter), `agents/execution_module.py` (30s lock, KYC, approval), `services/health_report.py` | M1, M3 | DONE (66 M4 tests pass, 61 challenger pass, 93% cov, clean audit) |
| M5 | Orchestration & Full API Layer | Requirements 19-22: `agents/orchestrator.py`, `api/routes/*` (all 13 endpoints), `main.py` lifespan refactor, `/ws/chat?token=...` with 8 events, zero mock responses | M1, M2, M3, M4 | DONE (30 unit pass, 17 e2e pass, 80.12% cov, clean audit) |
| M6 | E2E Verification & Adversarial Coverage Hardening | Requirement 23: Complete test suite execution, 10 spec scenarios, 100-entry audit chain + tamper test, 100% compliance rule coverage, >=80% pytest-cov gate | M1, M2, M3, M4, M5 | IN_PROGRESS |

## Interface Contracts

### `core/security` <-> `api/routes` & `agents`
- `verify_password(plain_password: str, hashed_password: str) -> bool`
- `get_password_hash(password: str) -> str`
- `create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str`
- `decode_access_token(token: str) -> dict`
- `get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> DBUser`
- `verify_client_ownership(user: DBUser, client_id: str, db: AsyncSession) -> DBClientProfile` (raises 403 Forbidden if mismatched)

### `services/cache` <-> `agents` & `services`
- `async get(key: str) -> Optional[str]`
- `async set(key: str, value: str, expire: Optional[int] = None) -> bool`
- `async delete(key: str) -> bool`
- `async acquire_lock(lock_key: str, timeout_seconds: int = 30) -> bool` (returns False if lock held)
- `async release_lock(lock_key: str) -> bool`

### `services/audit_logger` <-> `agents` & `api`
- `async log_audit_entry(db: AsyncSession, client_id: str, event_type: str, actor: str, details: dict, status: str = "PASS", hmac_key: Optional[str] = None) -> DBAuditLog`
  - Computes `prev_hash` from latest entry for `client_id` (or 64 zeros for genesis)
  - `entry_hash = sha256(prev_hash + client_id + event_type + json(details) + timestamp)`
  - `signature = hmac_sha256(hmac_key, entry_hash)`
- `async verify_audit_chain(db: AsyncSession, client_id: str, hmac_key: Optional[str] = None) -> Tuple[bool, Optional[int]]` (returns `(True, None)` if valid, `(False, invalid_entry_id)` if tampered)

### `services/data_pipeline` <-> `agents/market_data`
- `async fetch_market_quote(symbol: str) -> MarketDataPoint`
- `async fetch_historical_prices(symbols: List[str], period: str = "1y") -> pd.DataFrame`
- `async fetch_treasury_yield_curve() -> Dict[str, float]`
- `async fetch_macro_indicators() -> Dict[str, float]`
- All methods implement 3 retries (1s backoff), circuit breaker (5 failures / 60s cooldown), and fallback to `tests/fixtures/`.

### `agents/compliance_guard` <-> `agents/orchestrator` & `agents/execution_module`
- `async check_compliance(db: AsyncSession, client_id: str, transaction_data: dict) -> ComplianceCheckResult`
  - Returns `ComplianceCheckResult(passed: bool, violations: List[ComplianceViolation], warnings: List[str])`
  - Runs all 12 rules (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`)
  - Automatically writes `AUDIT_LOG` entry with check results
- `check_text_output(text: str) -> Tuple[bool, List[str]]`
  - Blocks output if it contains prohibited guarantee phrases (`REG-001`)
  - Blocks output if it lacks required risk disclosure on recommendations (`REG-002`)

### `agents/execution_module` <-> `agents/orchestrator`
- `async execute_trade(db: AsyncSession, client_id: str, proposal_id: str, symbol: str, side: str, qty: float, approved: bool, approval_timestamp: datetime, dry_run: Optional[bool] = None) -> TradeExecutionResult`
  - Enforces `approved == True` (`REG-003`)
  - Enforces `approval_timestamp >= now - 15 minutes` (`REG-004`)
  - Enforces 30s lock `lock:trade:{client_id}` (rejects duplicate submits)
  - Enforces client KYC verification check (`client.kyc_verified == True`)
  - Records trade in `trades` table and logs `TRADE_EXECUTED` in `audit_log`

## Code Layout
```
backend/
├── alembic.ini
├── requirements.txt
├── main.py (lifespan, router mounting, health, docs)
├── core/
│   ├── __init__.py
│   ├── config.py (settings, paper guard, Sepolia guard)
│   └── security.py (bcrypt, JWT, dependencies, ownership)
├── db/
│   ├── __init__.py
│   ├── database.py (sessionmaker, engine, get_db)
│   ├── models.py (7 SQLAlchemy models, append-only listener)
│   ├── init.sql (schema DDL and compliance rule seeds)
│   └── migrations/ (Alembic async migrations)
├── services/
│   ├── __init__.py
│   ├── cache.py (Redis + in-memory fallback, TTLs, locks)
│   ├── audit_logger.py (SHA-256 chain + HMAC signature + verify)
│   ├── anchoring.py (Merkle root + Sepolia testnet dry-run)
│   ├── data_pipeline.py (rate limit, retry, circuit breaker)
│   ├── health_report.py (drift, benchmark compare, rebalancing)
│   └── providers/
│       ├── __init__.py
│       ├── equities.py
│       ├── treasury.py
│       └── macro.py
├── agents/
│   ├── __init__.py
│   ├── orchestrator.py (dialogue, routing, compliance/approval gates)
│   ├── market_data.py (unified data interface)
│   ├── risk_profiler.py (6-state machine, draft caching, scoring)
│   ├── behavioral_bias.py (heuristics + telemetry + memory)
│   ├── product_comparison.py (6-factor composite scoring)
│   ├── allocation_engine.py (skfolio CVaR, frontier, rebalancing)
│   ├── compliance_guard.py (12 rules, output text filter)
│   └── execution_module.py (30s lock, KYC, approval, audit)
├── api/
│   ├── __init__.py
│   └── routes/
│       ├── __init__.py
│       ├── auth.py (register, login, me)
│       ├── session.py (session start)
│       ├── chat.py (chat message REST + WebSocket /ws/chat)
│       ├── profile.py (profile get)
│       ├── compare.py (etfs, bonds)
│       ├── portfolio.py (portfolio get, health-report)
│       ├── trade.py (trade execute)
│       ├── audit.py (audit get, audit verify)
│       └── market.py (quote, macro)
└── tests/
    ├── pytest.ini
    ├── conftest.py
    ├── fixtures/ (sample profiles, market quotes, treasury, CalcFi, Alpaca mocks)
    ├── unit/ (auth, cache, audit_logger, compliance_rules, scoring, risk_machine)
    ├── integration/ (pipeline, providers, db_models, execution_module, health_report)
    └── e2e/ (10 spec scenarios 8.2, full websocket agent flow)
```

# Comprehensive Requirements & Interface Contracts Breakdown
**Project:** Wealth Advisory Agent Backend (v2.0 Implementation)  
**Survey Explorer:** Explorer 3 (Requirements & Spec Miner)  
**Date:** 2026-10-10  
**Sources:** `ORIGINAL_REQUEST.md`, approved `implementation_plan.md`, `generate_tech_doc.py` (v2.0 Technical Specification), and `backend_roadmap.md`.

---

## 1. Feature Requirements Breakdown (R1 – R5)

### R1. Foundation (Config, Security, Persistence, Cache, Audit, Anchoring)
* **Configuration (`core/config.py`)**:
  * Built using `pydantic-settings` (`BaseSettings`).
  * Enforces startup validation with a strict **Paper-Only Guard**:
    * Hard check ensuring `ALPACA_BASE_URL` contains `paper-api.alpaca.markets`.
    * System refuses to start if live trading base URL (`https://api.alpaca.markets`) is detected.
    * Chain ID guard preventing Ethereum Mainnet (Chain ID 1) execution for anchoring.
  * Environment variables supported: `DATABASE_URL`, `REDIS_URL`, `ALPACA_API_KEY`, `ALPACA_SECRET_KEY`, `ALPACA_BASE_URL`, `OPENAI_API_KEY`, `OPENAI_MODEL`, `AUDIT_SECRET_KEY`, `JWT_SECRET_KEY`, `JWT_ALGORITHM`, `ACCESS_TOKEN_EXPIRE_MINUTES`, `SEPOLIA_RPC_URL`, `SEPOLIA_PRIVATE_KEY`, `AUDIT_CONTRACT_ADDRESS`, `DRY_RUN`, `LOG_LEVEL`.
* **Security & Authentication (`core/security.py`, `api/routes/auth.py`)**:
  * Email and password registration/login with bcrypt password hashing (`passlib[bcrypt]` or `bcrypt`).
  * JWT access token generation and verification (`PyJWT` or `python-jose`).
  * Per-user data ownership checks: each user account is bound to their own `client_id`; unauthenticated requests return `401 Unauthorized`; accessing another client's `client_id` returns `403 Forbidden`.
  * FastAPI dependency `get_current_user` for all protected REST endpoints.
  * WebSocket authentication via query parameter `?token=<jwt_token>`.
* **Persistence & Database Models (`db/database.py`, `db/models.py`)**:
  * Async SQLAlchemy 2.0 with driver prefix support (`sqlite+aiosqlite:///` default for zero-container local dev, `postgresql+asyncpg://` when `DATABASE_URL` is set).
  * Alembic migrations directory (`db/migrations/`) and initialization script (`db/init.sql`).
  * Full schema tables:
    1. `users`: User authentication, email, password hash, linked `client_id`.
    2. `client_profiles`: Complete 24-field model matching `ClientProfile` dataclass.
    3. `audit_log`: Append-only immutable log with SHA-256 hash chaining and HMAC signature. Enforced via DB trigger (PostgreSQL) or ORM guard (SQLite).
    4. `trades`: Order ID, client ID, symbol, side, quantity, filled price, status, compliance report snapshot, approval timestamp.
    5. `portfolio_snapshots`: Daily snapshots of holdings, asset allocation, and risk metrics.
    6. `behavioral_memory`: Bias history, check frequency, dip trades, intervention efficacy, composite bias score.
    7. `compliance_rules`: Rule catalog with dynamic parameters, severity, and active flags.
* **Cache, Sessions, & Locks (`services/cache.py`)**:
  * Unified `CacheManager` with Redis connection and transparent **in-memory fallback** if Redis is unreachable.
  * Specified TTL policy:
    * Live Quotes: 30 seconds
    * Daily OHLCV: 24 hours (86,400s)
    * ETF Holdings & Allocation: 6 hours (21,600s)
    * Macro Indicators: 24 hours (86,400s)
    * Treasury Yields: 12 hours (43,200s)
    * Product Comparisons: 6 hours (21,600s)
    * Profile Draft: 1 hour (3,600s)
    * Session State: 24 hours (86,400s)
    * Trade Double-Submit Lock (`lock:trade:{client_id}`): 30 seconds.
  * Key format: `data:{source}:{symbol}:{timeframe}`.
* **Audit Logger (`services/audit_logger.py`)**:
  * SHA-256 hash chaining: `entry_hash = sha256(previous_hash + entry_json)`. Genesis bootstrap hash `"GENESIS"`.
  * HMAC-SHA256 signature: `signature = hmac_sha256(entry_json, AUDIT_SECRET_KEY)`.
  * Serialized thread-safe write locks.
  * Independent verification function `verify_audit_chain(entries) -> Tuple[bool, Optional[str]]`.
* **Sepolia Merkle Anchoring (`services/anchoring.py`)**:
  * Batch aggregation into Merkle root (`compute_merkle_root(hashes)`).
  * Web3 transaction submission to Sepolia testnet. Dry-run mode if unconfigured or offline; rejects Chain ID 1.

---

### R2. Data Layer
* **Resilient Data Pipeline (`services/data_pipeline.py`)**:
  * Async HTTP client (`httpx.AsyncClient`) with rate limiter.
  * Exponential backoff retry logic: 3 retries, base delay 1.0s.
  * Circuit breaker: triggers OPEN state after 5 consecutive failures, cool-off period 60s.
  * Strict schema validation and UTC timestamp normalization.
  * Offline fallback: recorded VCR cassettes / JSON fixtures for deterministic testing.
* **Pluggable Data Providers (`services/providers/`)**:
  * `equities.py`: Equities & ETFs quotes, historical daily OHLCV, basic fundamentals (backed by `yfinance` / recorded fixtures).
  * `treasury.py`: US Treasury FiscalData API client fetching average interest rates, daily yield curves, and auction results.
  * `macro.py`: Macro time series (CPI, unemployment rate, Fed funds rate, VIX, GDP) via FRED / CalcFi Open Data / CSV fallback.
  * `etf_holdings.py`: Sector weights, top 10 holdings, asset class breakdown.
  * `screener.py`: Filtering ETFs/bonds by expense ratio, duration, AUM.
* **Market Data Agent (`agents/market_data.py`)**:
  * Aggregates and normalizes all market data into unified schemas (`MarketDataPoint`, `ETFProfile`, `BondDataPoint`).
  * Integrates with `CacheManager` for TTL caching.

---

### R3. Agents Core
* **Orchestrator Agent (`agents/orchestrator.py`)**:
  * Session-based routing across 5 distinct lifecycle stages: `profiling` -> `comparison` -> `recommendation` -> `awaiting_approval` -> `tracking`.
  * Context & dialogue memory management.
  * **Pre-Output Compliance Gate**: Every LLM message and recommendation must pass `ComplianceGuard` before reaching the user.
  * **Trade Approval Gate**: Generates structured proposal; requires explicit user approval (`[Approve]`, `[Reject]`, `[Modify]`).
  * Audit logging for every agent action and compliance verification.
* **Risk Profiling Agent (`agents/risk_profiler.py`)**:
  * 10-state adaptive State Machine:
    1. `START`
    2. `DEMOGRAPHICS` (age, employment status, dependents)
    3. `FINANCIAL_STATUS` (income, net worth, liquid assets, expenses, debts)
    4. `INVESTMENT_EXPERIENCE` (none, beginner, intermediate, advanced)
    5. `GOALS_AND_HORIZON` (primary goal, target return, horizon years)
    6. `RISK_SCENARIO_TESTING` (hypothetical 20% drawdown reaction)
    7. `EMOTIONAL_PROBING` (fear triggers, emotional volatility)
    8. `BIAS_DETECTION` (signals from dialogue)
    9. `KYC_COMPLIANCE` (identity & source of funds check)
    10. `PROFILE_SYNTHESIS` & `PROFILE_COMPLETE`
  * Computes:
    * `risk_tolerance_score` (1.0 – 10.0)
    * `suitability_category` (`conservative`, `moderate`, `aggressive`)
    * `emotional_risk_score` (0.0 – 10.0)
    * `panic_sell_likelihood` (0.0 – 1.0)
    * `kyc_verified` (boolean)
    * `aml_flag` (boolean)
  * Persists partial drafts in Redis/in-memory (`profile:draft:{session_id}`) and final `ClientProfile` to database.
* **Product Comparison Agent (`agents/product_comparison.py`)**:
  * Curated universe of ETFs and Bonds categorized by risk archetype.
  * Six-Factor Composite Scoring Formula:
    * $w_1 = 0.30$ (Risk Alignment: $|volatility - target\_vol|$)
    * $w_2 = 0.15$ (Cost Efficiency: $1 - normalize(expense\_ratio)$)
    * $w_3 = 0.20$ (Horizon Match: duration vs horizon alignment)
    * $w_4 = 0.10$ (Liquidity: daily volume / AUM threshold)
    * $w_5 = 0.15$ (Diversification: correlation with existing portfolio)
    * $w_6 = 0.10$ (Performance: risk-adjusted return / Sharpe ratio)
  * Suitability pre-filters applied prior to ranking.
  * LLM-generated plain-English comparison rationale citing specific score factors and risk disclosure.
* **Allocation Engine Agent (`agents/allocation_engine.py`)**:
  * Modern Portfolio Theory optimization via `skfolio`:
    * Conservative: `MeanRisk` with `RiskMeasure.CVAR` (focus on downside protection).
    * Aggressive: `MeanRisk` with `RiskMeasure.STANDARD_DEVIATION` or CVaR.
    * Constraints: `max_weight = 0.30` (concentration limit), `min_weight = 0.02`, `transaction_costs = 0.001` (10 bps).
  * Computes portfolio metrics: Expected Return, Volatility, Sharpe Ratio, CVaR 95%, Max Drawdown.
  * Efficient frontier coordinates calculation.
  * Rebalance trade calculation given current vs target allocation.
  * Explainability layer: SHAP (`KernelExplainer`) attribution with fallback, generating both `<SIMPLE>` (client-facing) and `<TECHNICAL>` (advisor-facing) explanations.
* **Behavioral Bias Agent (`agents/behavioral_bias.py`)**:
  * Detects 5 core cognitive biases: `loss_aversion`, `overconfidence`, `herding`, `recency_bias`, `anchoring`.
  * Dual-layer detection: keyword/pattern scoring (threshold > 0.6) + LLM contextual confirmation.
  * Behavioral pattern signals: portfolio check frequency > 3x/day, sell orders after dips < -2%, concentration > 40%, trading frequency > 10 trades/week.
  * Generates evidence-based debiasing interventions.
  * Grounded in Kuvera-PersonalFinance-V2.1 and Psychological Drivers datasets.
  * Persistent tracking in `BehavioralMemory`. **Advisory only — never blocks trades**.
* **Compliance Guard Agent (`agents/compliance_guard.py`)**:
  * Full 12-rule catalog (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`).
  * Dynamic rule loading and configuration from `compliance_rules` table.
  * Dual severity levels: `BLOCK` (raises `ComplianceViolationError` and halts flow) vs `WARN` (flags issue, logs warning, allows flow).
  * Every check generates a verifiable audit log entry.
  * Text output gating: inspects all outgoing text to prevent guarantee language (`REG-001`) and ensure risk disclosure (`REG-002`).
* **Execution Module (`agents/execution_module.py`)**:
  * Alpaca Paper Trading API integration (`alpaca-py` with `paper=True` hard-coded).
  * Non-discretionary execution: verifies explicit user approval timestamp (`REG-003`).
  * Double-submit lock: acquires Redis 30-second lock before execution.
  * KYC gate: verifies `profile.kyc_verified == True` (`REG-004`).
  * Polls order fill status, creates record in `trades` table, writes audit log entry with transaction hash.
  * Synchronizes positions and account balance.
* **Portfolio Health Report Service (`services/health_report.py`)**:
  * Real-time monitoring of holdings and target allocation.
  * Drift detection: deviation > 5% triggers advisory rebalance recommendation.
  * Benchmark comparison against SPY.
  * Automated alerts: underperformance > 10%, volatility > 20% over tolerance, macro indicator changes.
  * Natural language monthly narrative with specific rebalancing trade orders.

---

## 2. All 13 REST API Endpoints & /ws/chat Event Schemas

### 2.1 The 13 REST Endpoints

| # | Method | Path | Router Module | Auth Required | Description & Schema Contract |
|---|--------|------|---------------|---------------|-------------------------------|
| 1 | `POST` | `/api/v1/auth/register` | `api/routes/auth.py` | None | **User Registration**: Body `{email: str, password: str}` -> Response `{user_id: str, email: str, client_id: str, access_token: str}` |
| 2 | `POST` | `/api/v1/auth/login` | `api/routes/auth.py` | None | **User Login**: Body `{email: str, password: str}` (or OAuth2 Form) -> Response `{access_token: str, token_type: "bearer", client_id: str}` |
| 3 | `GET` | `/api/v1/auth/me` | `api/routes/auth.py` | JWT Bearer | **Current User Profile**: Headers `Authorization: Bearer <token>` -> Response `{user_id: str, email: str, client_id: str}` |
| 4 | `POST` | `/api/v1/session/start` | `api/routes/session.py` | Optional / JWT | **Start Advisory Session**: Body `{client_id?: str}` -> Response `{session_id: str, message: str}` |
| 5 | `POST` | `/api/v1/chat/message` | `api/routes/chat.py` | JWT Bearer | **REST Chat Fallback**: Body `{session_id: str, message: str}` -> Response `{text: str, agent: str, type: str}` |
| 6 | `GET` | `/api/v1/profile/{client_id}` | `api/routes/profile.py` | JWT (Owner) | **Get Client Profile**: Path `client_id` (403 if not owner) -> Response `ClientProfile` JSON |
| 7 | `POST` | `/api/v1/compare/etfs` | `api/routes/compare.py` | JWT (Owner) | **Compare ETFs**: Body `{symbols: List[str], client_id: str}` -> Response `{ranked_products: List[ScoredProduct], rationale: str}` |
| 8 | `POST` | `/api/v1/compare/bonds` | `api/routes/compare.py` | JWT (Owner) | **Compare Bonds**: Body `{symbols: List[str], client_id: str}` -> Response `{ranked_products: List[ScoredProduct], rationale: str}` |
| 9 | `GET` | `/api/v1/portfolio/{client_id}` | `api/routes/portfolio.py` | JWT (Owner) | **Get Portfolio**: Path `client_id` -> Response `{total_value: float, cash: float, buying_power: float, positions: List[dict], allocation: dict, metrics: dict}` |
| 10 | `POST` | `/api/v1/trade/execute` | `api/routes/trade.py` | JWT (Owner) | **Execute Trade**: Body `{client_id: str, symbol: str, qty: float, side: str, user_approved: bool, session_id?: str}` -> Response `{status: str, execution: dict, trade_id: str}` |
| 11 | `GET` | `/api/v1/audit/{client_id}` | `api/routes/audit.py` | JWT (Owner) | **Get Audit Trail**: Path `client_id`, query `limit?: int` -> Response `{client_id: str, entries: List[AuditEntry]}` |
| 12 | `GET` | `/api/v1/audit/{client_id}/verify` | `api/routes/audit.py` | JWT (Owner) | **Verify Audit Hash Chain**: Path `client_id` -> Response `{client_id: str, verified: bool, entries_count: int, last_hash: str, tampered_entry_id: Optional[str]}` |
| 13 | `POST` | `/api/v1/portfolio/health-report` | `api/routes/portfolio.py` | JWT (Owner) | **Generate Portfolio Health Report**: Body `{client_id: str}` -> Response `{status: str, drift_percentage: float, rebalance_recommended: bool, narrative: str, performance: dict, alerts: List[str], rebalance_trades: List[dict]}` |

*(Supplementary Market & Compliance Utility Routes)*:
* `GET /api/v1/compliance/rules` (`api/routes/compliance.py`): Lists all active compliance rules and parameters.
* `GET /api/v1/market/quote/{symbol}` (`api/routes/market.py`): Real-time normalized quote.
* `GET /api/v1/market/macro` (`api/routes/market.py`): Macro indicators summary (CPI, Unemployment, Fed Funds, VIX).

---

### 2.2 WebSocket Event Schemas (`/ws/chat?token=<jwt>`)

Connection handshake: Client connects to `/ws/chat?token=<jwt>` (or `/ws/chat/{session_id}?token=<jwt>`). Unauthenticated or invalid tokens are closed with code 4001/4003.

```
       Client                                         Server
         |                                              |
         | -------- (1) user_message -----------------> |
         | <------- (2) agent_response ---------------- |
         | <------- (3) bias_alert -------------------- | (if bias detected)
         | <------- (4) compliance_check -------------- | (during validation)
         | <------- (5) trade_proposal ---------------- | (when action ready)
         | -------- (6) trade_approved ---------------> |
         | <------- (7) trade_filled ------------------ |
         | <------- (8) portfolio_update -------------- |
```

#### Event 1: `user_message` (Client -> Server)
```json
{
  "event": "user_message",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "message": "I'm 35, work in tech, have $50,000 to invest for 10 years."
}
```

#### Event 2: `agent_response` (Server -> Client)
```json
{
  "event": "agent_response",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "agent": "RiskProfiler",
  "type": "profiling",
  "text": "Great! If your portfolio dropped 20% in a month during a market downturn, what would you do? (a) Sell everything, (b) Hold steady, or (c) Buy more?"
}
```

#### Event 3: `trade_proposal` (Server -> Client)
```json
{
  "event": "trade_proposal",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "proposal_id": "prop-550e8400-e29b-41d4-a716-446655440000",
  "trades": [
    {
      "symbol": "BND",
      "side": "BUY",
      "qty": 10.0,
      "estimated_price": 72.05,
      "dollar_amount": 720.50,
      "weight": 0.15
    }
  ],
  "rationale": "Recommended BND to provide stable income matching your 5-year horizon. Past performance does not guarantee future results.",
  "compliance_summary": {"all_passed": true, "checks_count": 4}
}
```

#### Event 4: `trade_approved` (Client -> Server)
```json
{
  "event": "trade_approved",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "proposal_id": "prop-550e8400-e29b-41d4-a716-446655440000",
  "approved": true
}
```

#### Event 5: `trade_filled` (Server -> Client)
```json
{
  "event": "trade_filled",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "order_id": "alpaca-ord-987654",
  "trade_id": "trade-uuid-1234",
  "symbol": "BND",
  "qty": 10.0,
  "side": "BUY",
  "filled_price": 72.05,
  "status": "filled",
  "filled_at": "2026-10-10T12:35:00Z",
  "audit_entry_id": "audit-uuid-5678"
}
```

#### Event 6: `portfolio_update` (Server -> Client)
```json
{
  "event": "portfolio_update",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "total_value": 10720.50,
  "cash": 4279.50,
  "positions": [
    {"symbol": "BND", "qty": 10.0, "market_value": 720.50, "weight": 0.144}
  ],
  "allocation": {"fixed_income": 0.144, "equities": 0.0, "cash": 0.856}
}
```

#### Event 7: `bias_alert` (Server -> Client)
```json
{
  "event": "bias_alert",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "bias_type": "loss_aversion",
  "confidence": 0.88,
  "evidence": "User stated: 'I cannot afford to lose any money at all'",
  "intervention": "I notice you're focused on avoiding losses. Research shows that checking portfolios less frequently reduces anxiety. Let's review your long-term goals."
}
```

#### Event 8: `compliance_check` (Server -> Client)
```json
{
  "event": "compliance_check",
  "session_id": "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d",
  "rule_id": "SUIT-001",
  "rule_name": "Risk Profile Alignment",
  "passed": true,
  "severity": "BLOCK",
  "details": "Product risk level 3 <= client risk score 5.0 + 1"
}
```

---

## 3. Complete Compliance Rule Catalog

All 12 rules are seeded in the database `compliance_rules` table and evaluated dynamically:

| Rule ID | Rule Name | Category | Severity | Description | Exact Validation Logic / Condition |
|---------|-----------|----------|----------|-------------|-------------------------------------|
| **SUIT-001** | Risk Profile Alignment | SUITABILITY | **BLOCK** | Recommendations must match client risk profile | `rec.risk_level <= profile.risk_tolerance_score + 1` (or product volatility $\le 2 \times target\_vol$) |
| **SUIT-002** | Investment Horizon Match | SUITABILITY | **BLOCK** | Product duration must align with investment horizon | `rec.avg_duration <= profile.investment_horizon_years * 1.5` |
| **SUIT-003** | Liquidity Match | SUITABILITY | **WARN** | Product liquidity must meet client needs | If `profile.liquidity_needs == "high"`, require `product.daily_volume_usd >= 1,000,000` |
| **CONC-001** | Single Asset Limit | CONCENTRATION | **BLOCK** | No single asset > 30% of portfolio | `all(weight <= 0.30 for weight in portfolio.weights.values())` and `rec.proposed_weight <= 0.30` |
| **CONC-002** | Sector Concentration | CONCENTRATION | **WARN** | No single sector > 40% of portfolio | `all(weight <= 0.40 for weight in portfolio.sector_weights.values())` |
| **CONC-003** | Asset Class Equity Cap | CONCENTRATION | **WARN** | Conservative profiles: max 30% equities | If `profile.suitability_category == "conservative"`, then `equities_weight <= 0.30` |
| **REG-001** | No Guaranteed Returns | REGULATORY | **BLOCK** | Output must not promise or imply guaranteed returns | `not contains_guarantee_language(text)` (blocks: "guaranteed", "guarantee", "100% safe", "risk-free", "certain return", "will definitely") |
| **REG-002** | Risk Disclosure Required | REGULATORY | **BLOCK** | Every recommendation must include risk disclosure | `contains_risk_disclosure(text)` (requires at least one phrase: "past performance", "does not guarantee", "risk of loss", "investing involves risk") |
| **REG-003** | User Approval Required | REGULATORY | **BLOCK** | Trades require explicit user confirmation | `trade.user_approved == True` and `trade.user_approved_at is not None` |
| **REG-004** | KYC Verification | REGULATORY | **BLOCK** | KYC must be completed before trading | `profile.kyc_verified == True` |
| **AML-001** | Transaction Monitoring | AML | **BLOCK** | Flag unusual transaction patterns or AML risks | `profile.aml_flag == False` and `trade.dollar_amount < 100,000` |
| **AML-002** | Source of Funds | AML | **WARN** | Verify source of investment funds | `profile.source_of_funds not in ["unverified", "suspicious", "unknown"]` |

---

## 4. The 10 Spec Scenarios in Section 8.2

| # | Scenario Name | Test Target & Preconditions | Execution Steps | Expected Outcome & Verification Criteria |
|---|---------------|-----------------------------|-----------------|-------------------------------------------|
| **1** | **Risk Profiling** | State machine interview with conservative user archetype (Age 65, retired, preservation goal, option 'a' on 20% dip). | Process dialogue through `RiskProfilerAgent.process_conversation()`. | Computes `risk_tolerance_score <= 3.0`, sets `suitability_category = "conservative"`, completes profile. |
| **2** | **Product Comparison** | Moderate risk profile (`score = 5.5`), ETF universe `["VTI", "BND", "VXUS", "GLD", "QQQ"]`. | Call `compare_etfs()`. Multi-dimensional scoring computes 6-factor composite scores. | Top recommended products have volatility aligned with target ($\sim 12\text{--}15\%$). Explanatory rationale returned. |
| **3** | **Compliance Blocking (SUIT-001)** | Conservative profile (`risk_tolerance_score = 2.0`). Attempt to recommend high-volatility product (risk level 8, e.g. TQQQ). | Pass recommendation to `ComplianceGuard.check_recommendation()`. | Rule `SUIT-001` fails with severity `BLOCK`. Raises `ComplianceViolationError`. Recommendation blocked from user. |
| **4** | **Concentration Check (CONC-001)** | Proposed allocation with single asset weight of 45% ($0.45 > 0.30$). | Run `ComplianceGuard.check_recommendation()` or portfolio optimization. | Rule `CONC-001` fails with severity `BLOCK`. Optimization automatically clamps weight to $\le 0.30$ or trade is rejected. |
| **5** | **Trade Execution & Paper Fill** | Client profile with KYC verified. Order: BUY 10 BND with `user_approved = True`. | Execute via `ExecutionModule.place_order()` or `/api/v1/trade/execute`. | Order submitted to Alpaca Paper Trading, returns filled status, stores row in `trades`, records SHA-256 hash in `audit_log`. |
| **6** | **Behavioral Bias Detection** | User chat message: *"I can't afford to lose any money at all, what if the market crashes tomorrow?"* | Analyze message with `BehavioralBiasAgent.analyze_message()`. | Detects `loss_aversion` with confidence $> 0.60$. Persists event to `behavioral_memory`. Returns debiasing intervention. |
| **7** | **Audit Chain Integrity & Tampering** | Append 100 sequential audit log entries. | Run `verify_audit_chain()`. Modify payload of entry 42. Re-run verification. | Initial chain verifies (`True`). Tampered entry fails signature and hash chain check (`False`), identifying corrupted row. |
| **8** | **Guaranteed Returns Blocking (REG-001)** | Agent recommendation text contains: *"This ETF is guaranteed to yield 12% annual return."* | Filter output through `ComplianceGuard.filter_output_text()`. | Rule `REG-001` triggers `BLOCK`. Output is suppressed, violation logged, agent forced to rewrite or abort. |
| **9** | **Non-Discretionary Protection (REG-003) & Double-Submit** | Trade submit with `user_approved = False`. Second identical submit within 30s. | Attempt execution via `ExecutionModule` and API route. | Unapproved trade blocked by `REG-003` (400 error). Approved trade succeeds; immediate second attempt within 30s rejected by Redis lock. |
| **10** | **Portfolio Drift & Health Rebalancing** | Portfolio positions have drifted $> 5\%$ from target (e.g. equities expanded to 62% vs 50% target). | Call `/api/v1/portfolio/health-report`. | Service identifies 12% drift ($> 5\%$), triggers alert, outputs rebalancing trade orders and natural language narrative. |

---

## 5. Acceptance Criteria & Verification Commands

### 5.1 Acceptance Criteria
1. **Test Suite & Coverage**: `pytest -q --cov=. --cov-fail-under=80` passes with at least 80% total backend code coverage.
2. **Compliance Rule Coverage**: Every compliance rule (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`) has dedicated, passing unit tests covering both PASS and FAIL/BLOCK conditions.
3. **Audit Chain Proof**: An audit trail of 100 consecutive entries cryptographically verifies; any tampered row fails verification.
4. **Execution Safety**: Trade without explicit user approval is strictly blocked (`REG-003`); duplicate submit within 30 seconds is rejected by the trade lock.
5. **Security Enforced**: Unauthenticated requests receive `401 Unauthorized`; accessing another user's `client_id` receives `403 Forbidden`.
6. **Regulatory Text Safeguard**: Text containing "guaranteed" is blocked (`REG-001`); recommendations lacking risk disclosures are blocked (`REG-002`).
7. **Zero-Container Startup**: `python main.py` boots successfully without Docker, Redis, or Postgres running (in-memory cache fallback, SQLite default database), and `/docs` lists all 13 REST endpoints.
8. **No Mock Routes**: All routes execute real agent, database, and cache logic; zero hard-coded dummy returns remain in API route handlers.

### 5.2 Verification Commands
```bash
# 1. Environment & Dependencies Installation
cd backend
python -m venv venv
# Windows activate:
venv\Scripts\activate
pip install -r requirements.txt

# 2. Automated Test Suite Execution (Unit, Integration, E2E, Compliance)
pytest -q --cov=. --cov-fail-under=80

# 3. Targeted Test Suites
pytest tests/unit/test_compliance.py -v       # 100% compliance rule coverage (12 rules)
pytest tests/unit/test_audit_logger.py -v     # 100 entries + tamper verification
pytest tests/unit/test_security.py -v         # 401/403 ownership and auth guards
pytest tests/unit/test_cache.py -v            # Redis fallback and trade lock
pytest tests/e2e/test_spec_scenarios.py -v   # All 10 Section 8.2 scenarios

# 4. Standalone Service Boot & Docs Inspection
python main.py
# Verify: Navigate to http://localhost:8000/docs
# Verify: All 13 REST endpoints listed and operational
```

---

## 6. Module Interface Contracts

```
+-----------------------------------------------------------------------------------------+
|                                    API ROUTERS & WS                                     |
|           auth.py | session.py | chat.py | profile.py | compare.py | trade.py           |
|           portfolio.py | audit.py | compliance.py | market.py | websocket.py           |
+--------------------------------------------+--------------------------------------------+
                                             | calls
                                             v
+-----------------------------------------------------------------------------------------+
|                                      AGENTS LAYER                                       |
|  OrchestratorAgent  <--->  ComplianceGuardAgent  <--->  RiskProfilerAgent (State Machine) |
|  MarketDataAgent    <--->  ProductComparisonAgent <--->  AllocationEngineAgent (skfolio) |
|  BehavioralBiasAgent<--->  ExecutionModule (Alpaca) <---> HealthReportService           |
+--------------------------------------------+--------------------------------------------+
                                             | uses
                                             v
+-----------------------------------------------------------------------------------------+
|                               SERVICES & FOUNDATION LAYER                               |
|  ResilientDataPipeline (Providers: Equities, Treasury, Macro)                           |
|  CacheManager (Redis + In-Memory Fallback, TTLs, Trade Lock)                            |
|  AuditLogger (SHA-256 Hash Chain, HMAC-SHA256, verify_audit_chain)                      |
|  MerkleAnchor (Sepolia Testnet Batch Anchoring)                                         |
|  Security & Auth (Bcrypt, JWT, get_current_user, Ownership Guard)                       |
|  Database Layer (AsyncSession, SQLite/PostgreSQL, Alembic Migrations)                   |
+-----------------------------------------------------------------------------------------+
```

### 6.1 Foundation & Security Contracts
* `core/config.py`:
  ```python
  class Settings(BaseSettings):
      DATABASE_URL: str = "sqlite+aiosqlite:///./wealth_advisor.db"
      REDIS_URL: Optional[str] = None
      ALPACA_API_KEY: str = ""
      ALPACA_SECRET_KEY: str = ""
      ALPACA_BASE_URL: str = "https://paper-api.alpaca.markets"
      OPENAI_API_KEY: str = ""
      OPENAI_MODEL: str = "gpt-4o"
      AUDIT_SECRET_KEY: str = "default_audit_hmac_secret_key"
      JWT_SECRET_KEY: str = "default_jwt_secret_key"
      JWT_ALGORITHM: str = "HS256"
      ACCESS_TOKEN_EXPIRE_MINUTES: int = 1440
      SEPOLIA_RPC_URL: Optional[str] = None
      SEPOLIA_PRIVATE_KEY: Optional[str] = None
      AUDIT_CONTRACT_ADDRESS: Optional[str] = None
      DRY_RUN: bool = False
      LOG_LEVEL: str = "INFO"

      @field_validator("ALPACA_BASE_URL")
      def validate_paper_trading(cls, v: str) -> str:
          if "api.alpaca.markets" in v and "paper" not in v:
              raise ValueError("LIVE TRADING FORBIDDEN: ALPACA_BASE_URL must point to paper-api.alpaca.markets")
          return v
  ```
* `core/security.py`:
  ```python
  def hash_password(password: str) -> str: ...
  def verify_password(plain_password: str, hashed_password: str) -> bool: ...
  def create_access_token(data: dict, expires_delta: Optional[timedelta] = None) -> str: ...
  def decode_access_token(token: str) -> dict: ...
  async def get_current_user(token: str = Depends(oauth2_scheme), db: AsyncSession = Depends(get_db)) -> DBUser: ...
  def verify_client_ownership(user: DBUser, client_id: str) -> None:
      # Raises HTTPException(status_code=403, detail="Forbidden") if user.client_id != client_id
  ```
* `services/cache.py`:
  ```python
  class CacheManager:
      def __init__(self, redis_url: Optional[str] = None): ...
      async def get(self, key: str) -> Optional[Any]: ...
      async def set(self, key: str, value: Any, ttl: int) -> None: ...
      async def delete(self, key: str) -> None: ...
      async def lock(self, key: str, ttl: int = 30) -> bool: ...
      async def release_lock(self, key: str) -> None: ...
  ```
* `services/audit_logger.py`:
  ```python
  class AuditLogger:
      def __init__(self, secret_key: str): ...
      async def log(self, event_type: str, client_id: str, session_id: str, agent_id: str, action: dict, db: AsyncSession) -> DBAuditLog: ...
      async def verify_audit_chain(self, client_id: Optional[str] = None, db: Optional[AsyncSession] = None) -> Tuple[bool, Optional[str]]: ...
      def compute_hash(self, previous_hash: str, payload_str: str) -> str: ...
      def compute_hmac(self, payload_str: str) -> str: ...
  ```

### 6.2 Data Layer Contracts
* `services/data_pipeline.py`:
  ```python
  class ResilientHTTPClient:
      async def get(self, url: str, params: Optional[dict] = None) -> dict: ...
      # Incorporates tenacity retry (3 attempts) + circuit breaker (5 failures -> 60s OPEN)
  ```
* Unified Data Models (`models/market_data.py`):
  ```python
  class MarketDataPoint(BaseModel):
      symbol: str
      timestamp: datetime
      price: float
      open: Optional[float] = None
      high: Optional[float] = None
      low: Optional[float] = None
      close: Optional[float] = None
      volume: Optional[float] = None
      source: str

  class ETFProfile(BaseModel):
      symbol: str
      name: str
      expense_ratio: float
      aum: float
      holdings_count: int
      top_holdings: List[dict]
      sector_weights: Dict[str, float]
      volatility_1y: float
      sharpe_ratio: float
      max_drawdown: float
      performance: Dict[str, float]
  ```

### 6.3 Agent Layer Contracts
* `models/client_profile.py`:
  ```python
  class ClientProfile(BaseModel):
      client_id: str
      age: int
      employment_status: str
      dependents: int
      annual_income: float
      net_worth: float
      liquid_assets: float
      monthly_expenses: float
      existing_debts: float
      investment_experience: str
      risk_tolerance_score: float = Field(..., ge=1.0, le=10.0)
      investment_horizon_years: int
      liquidity_needs: str
      loss_capacity: str
      primary_goal: str
      target_return: float
      specific_goals: List[str]
      detected_biases: List[str] = []
      emotional_risk_score: float = 0.0
      panic_sell_likelihood: float = 0.0
      kyc_verified: bool = False
      aml_flag: bool = False
      suitability_category: str
      profile_created_at: datetime = Field(default_factory=datetime.utcnow)
      profile_updated_at: datetime = Field(default_factory=datetime.utcnow)
      profiling_session_transcript: str = ""
  ```
* `agents/compliance_guard.py`:
  ```python
  class ComplianceCheckResult(BaseModel):
      rule_id: str
      rule_name: str
      passed: bool
      severity: str   # "BLOCK" | "WARN"
      timestamp: datetime
      details: str

  class ComplianceViolationError(Exception):
      violations: List[ComplianceCheckResult]

  class ComplianceGuard:
      async def check_recommendation(self, recommendation: dict, profile: ClientProfile, portfolio: Optional[dict] = None, db: Optional[AsyncSession] = None) -> dict: ...
      async def check_trade(self, trade_request: Any, profile: ClientProfile, db: Optional[AsyncSession] = None) -> dict: ...
      def filter_output_text(self, text: str) -> None: ...
  ```
* `agents/execution_module.py`:
  ```python
  class ExecutionModule:
      def __init__(self, api_key: str, secret_key: str, paper: bool = True): ...
      async def place_order(self, symbol: str, qty: float, side: str, user_approved: bool, client_id: str, db: AsyncSession, cache: CacheManager) -> Dict[str, Any]: ...
      def get_positions(self) -> List[dict]: ...
      def get_account(self) -> dict: ...
  ```
* `agents/product_comparison.py`:
  ```python
  class ProductComparisonAgent:
      async def compare_etfs(self, symbols: List[str], profile: ClientProfile) -> dict: ...
      async def compare_bonds(self, symbols: List[str], profile: ClientProfile) -> dict: ...
  ```
* `agents/allocation_engine.py`:
  ```python
  class AllocationEngine:
      async def generate_allocation(self, symbols: List[str], profile: ClientProfile, price_df: Optional[pd.DataFrame] = None) -> dict: ...
      async def generate_rebalance(self, current_weights: Dict[str, float], target_weights: Dict[str, float], total_value: float) -> List[dict]: ...
  ```
* `agents/behavioral_bias.py`:
  ```python
  class BehavioralBiasAgent:
      async def analyze_message(self, message: str, client_id: Optional[str] = None, db: Optional[AsyncSession] = None) -> List[dict]: ...
  ```
* `agents/orchestrator.py`:
  ```python
  class OrchestratorAgent:
      async def handle_message(self, session_id: str, message: str, user: DBUser, db: AsyncSession) -> dict: ...
      async def handle_trade_approval(self, session_id: str, trade_id: str, approved: bool, user: DBUser, db: AsyncSession) -> dict: ...
  ```
* `services/health_report.py`:
  ```python
  async def generate_portfolio_health_report(client_id: str, db: AsyncSession) -> dict: ...
  ```

---

## 7. Synthesis & Strategic Guidance for Orchestrator

1. **Scaffold Status**:
   - `backend/main.py` is currently a monolithic file with hard-coded mocks and deprecated `@app.on_event("startup")`.
   - `backend/db/models.py` has only 3 tables (`DBClientProfile`, `DBAuditLog`, `DBTrade`) missing `users`, `portfolio_snapshots`, `behavioral_memory`, and `compliance_rules`.
   - `backend/agents/compliance_guard.py` currently implements only 2 rules (`SUIT-001`, `REG-003`) instead of the full 12-rule catalog.
   - `backend/agents/execution_module.py` has no Redis lock or KYC gate.
   - Auth, Orchestrator, Market Data, Product Comparison, Data Pipeline, Alembic migrations, and tests are completely missing.
2. **Implementation Sequence**:
   - **M1 Foundation**: `core/config.py`, `core/security.py`, complete `db/models.py`, Alembic migrations, `services/cache.py`, `services/audit_logger.py`, `services/anchoring.py`.
   - **M2 Data Layer**: `services/data_pipeline.py`, providers (`equities`, `treasury`, `macro`), `agents/market_data.py`.
   - **M3 Agents Core**: `agents/risk_profiler.py` (state machine), `agents/product_comparison.py`, `agents/allocation_engine.py`, `agents/behavioral_bias.py`.
   - **M4 Compliance, Execution & Health**: Complete 12-rule `compliance_guard.py`, `execution_module.py` (locks, fills, KYC), `services/health_report.py`.
   - **M5 Orchestrator & API**: `agents/orchestrator.py`, split `main.py` into `api/routes/*` routers (13 REST endpoints), `/ws/chat` event loop, lifespan manager.
   - **M6 Testing & Hardening**: `tests/unit/`, `tests/integration/`, `tests/e2e/`, `tests/fixtures/`, verification of 10 spec scenarios and 80%+ coverage.

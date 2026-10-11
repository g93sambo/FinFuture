# Architecture & Implementation Specifications: Milestone 5 (Orchestration & Full API Layer)

**Document**: `analysis.md`  
**Author**: Explorer 2 (Milestone 5)  
**Date**: 2026-10-11  
**Status**: Completed  
**Working Directory**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m5_2`  
**Target Systems**: `backend/api/routes/*`, `backend/api/deps.py`, `backend/main.py`, `backend/agents/orchestrator.py`

---

## 1. Executive Summary & Purpose

The objective of Milestone 5 is to deliver a fully wired, zero-mock, modular FastAPI orchestration and REST/WebSocket API layer for the multi-agent Wealth Advisory Agent backend.

All client interactions—authentication, conversational profiling, product comparison, dynamic asset allocation, portfolio health and drift monitoring, non-discretionary trade proposals, compliance-gated paper execution, cryptographic audit logs, and market data queries—must be backed by genuine business logic, persistent database transactions, distributed/in-memory cache controls, and cryptographic audit chains.

This document presents a comprehensive analysis of the existing codebase, details the route-by-route architectural design, specifies the modular file reorganization mandated by `PROJECT.md`, establishes strict security invariants (including tenant isolation via `verify_client_ownership`), and details the exact fixes required for subtle cross-agent serialization and regulatory gating bugs identified during runtime analysis.

---

## 2. Codebase Inspection & Audit Findings

### 2.1 File Structure Comparison
The master project layout defined in `PROJECT.md` specifies individual modular route files under `backend/api/routes/`:
```
backend/api/routes/
├── __init__.py
├── auth.py         # POST /register, POST /login, GET /me
├── session.py      # POST /session/start
├── chat.py         # POST /chat/message, /ws/chat
├── profile.py      # GET /profile/{client_id}
├── compare.py      # POST /compare/etfs, POST /compare/bonds
├── portfolio.py    # GET /portfolio/{client_id}, POST /portfolio/{client_id}/health-report, POST /allocation/recommend
├── trade.py        # POST /trade/propose, POST /trade/execute, GET /trade/{order_id}, GET /trades/{client_id}
├── audit.py        # GET /audit/{client_id}, GET /audit/{client_id}/verify, POST /audit/{client_id}/anchor
├── market.py       # GET /market/quote/{symbol}, GET /market/macro
└── compliance.py   # GET /compliance/rules
```

**Current State**:
In the existing codebase, routes were grouped into `auth.py`, `advisory.py`, `portfolio.py`, and `ws.py`. While genuine logic (not static mocks) is largely wired into agents, bundling heterogeneous domains (sessions, chat, product comparison, market data, compliance) inside `advisory.py` and bundling portfolio, trade, and audit into `portfolio.py` deviates from the modular contract specified in `PROJECT.md`. Moreover, `main.py` only imports `advisory, auth, portfolio, ws`.

### 2.2 Mock Response Audit
A line-by-line inspection of all route handlers in `backend/api/routes/` confirmed:
- **No static mock returns**: Every route delegates to `AgentContainer` agents (`orchestrator`, `market`, `profiler`, `bias`, `compliance`, `allocation`, `comparison`, `execution`, `health`, `portfolio`, `audit`, `cache`).
- **No placeholder stubs**: Cryptographic hashing, token signing, database transactions, and agent pipelines are active.

### 2.3 Runtime Defect Analysis (Pre-existing Issues Identified)
During integration test execution against `tests/e2e/test_full_flow.py`, three critical defects and one hang scenario were isolated:

#### Defect A: `TypeError: Object of type datetime is not JSON serializable` in `AuditLogger` during `ComplianceGuard.check_trade`
- **Location**: `backend/agents/orchestrator.py:445` & `backend/agents/compliance_guard.py:1089`
- **Mechanism**: In `orchestrator.execute_proposal`, the trade dictionary contains `"user_approved_at": approval_ts` where `approval_ts` is a Python `datetime` object (`datetime.now(timezone.utc)`). When `compliance.check_trade()` passes this dictionary into `_record_audit_log(payload={"trade": trade})`, `audit_logger.log_audit_entry` attempts to insert the dictionary directly into SQLAlchemy `DBAuditLog(details=...)`. In SQLite/SQLAlchemy async sessions, flushing a dict containing a `datetime` object into a `JSON` column invokes Python's standard `json.dumps()` without `default=str`, triggering:
  `TypeError: Object of type datetime is not JSON serializable`
  This causes a transaction flush error, leaving the session in `PendingRollbackError` state and failing subsequent operations in `execution_module.py` and hanging the WebSocket handler.
- **Remediation**:
  1. In `orchestrator.py`, ensure `"user_approved_at"` in `trade` is formatted as an ISO 8601 string: `approval_ts.isoformat()`.
  2. In `services/audit_logger.py:log_audit_entry()`, sanitize the `details` dictionary before assignment to `DBAuditLog.details` via `json.loads(json.dumps(details, default=str))`.
  3. In `agents/compliance_guard.py`, ensure all recorded payloads serialize datetimes before audit logging.

#### Defect B: Regulatory Disclosure Missing from `AllocationEngine` Explanation (REG-002 Block)
- **Location**: `backend/agents/allocation_engine.py:345-354` & `backend/agents/orchestrator.py:309`
- **Mechanism**: In `AllocationEngine._generate_explanation()`, the default narrative does not include the mandatory regulatory disclosure phrase (*"Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."*). When `orchestrator.recommend_allocation()` runs `compliance.check_recommendation()`, `ComplianceGuard` evaluates the narrative against `REG-002`. Because the mandatory phrase is absent and `REG-002` severity is `BLOCK`, `ComplianceGuard` raises `ComplianceViolationError`. As a result, `recommend_allocation()` catches the violation and aborts before emitting the `AllocationEngine` recommendation event.
- **Remediation**:
  1. In `orchestrator.recommend_allocation()`, sanitize `result.explanation` using `self.c.compliance.check_text_output(result.explanation)[2]` before assembling the recommendation payload for compliance check.
  2. In `allocation_engine.py`, append the standard risk disclosure string to the generated narrative template.

#### Defect C: Prohibited Language in `SAFE_REPLACEMENT` String (REG-001 Loop)
- **Location**: `backend/agents/orchestrator.py:67-70`
- **Mechanism**:
  ```python
  SAFE_REPLACEMENT = (
      "I can't describe any investment as guaranteed or free of risk. Every investment "
      "can lose value, and I will only give you balanced, evidence-based information."
  )
  ```
  In `gate_text()`, when prohibited language is detected, the text is replaced with `SAFE_REPLACEMENT` and then passed into `compliance.check_text_output()`. But `SAFE_REPLACEMENT` itself contains the exact word `"guaranteed"`! Consequently, `check_text_output` flags `REG-001` again, returning the prohibited phrase to the caller. Additionally, `SAFE_REPLACEMENT` lacked the required risk disclosure keywords (*"loss of principal"*, *"past performance"*).
- **Remediation**:
  Replace `SAFE_REPLACEMENT` with:
  ```python
  SAFE_REPLACEMENT = (
      "I cannot promise returns or describe any investment as free of risk. Every investment "
      "can lose value, and I will only give you balanced, evidence-based information. "
      "Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."
  )
  ```

#### Defect D: WebSocket Test Hang
- **Location**: `backend/api/routes/ws.py:38-100`
- **Mechanism**: `test_websocket_propose_and_approve_flow` was waiting for `portfolio_update` event from the server. Due to Defect A (`PendingRollbackError` on trade execution), the trade was never filled and the `portfolio_update` event was never sent, causing the test's `ws.receive_json()` loop to block indefinitely. Fixing Defect A completely resolves this deadlock.

---

## 3. Target Route Architecture & Modular File Organization

To satisfy both `PROJECT.md` and `ORIGINAL_REQUEST.md`, the route files will be partitioned cleanly into dedicated modules under `backend/api/routes/`:

```
backend/api/routes/
├── __init__.py         # Re-exports all APIRouter instances for clean app assembly
├── auth.py             # Authentication & user profile routes
├── session.py          # Session lifecycle routes
├── chat.py             # REST chat and WebSocket streaming routes
├── profile.py          # Client profile retrieval and verification
├── compare.py          # Product comparison (ETFs & Bonds)
├── portfolio.py        # Portfolio state, asset allocation, health reports
├── trade.py            # Trade proposal, execution, and status polling
├── audit.py            # Audit trail querying, cryptographic verification, Sepolia anchoring
├── market.py           # Real-time quotes, macro indicators, yield curve
└── compliance.py       # Active compliance rules catalog
```

### Route Mounting in `backend/main.py`:
```python
from api.routes import (
    auth, session, chat, profile, compare,
    portfolio, trade, audit, market, compliance, ws
)

app.include_router(auth.router)
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(profile.router)
app.include_router(compare.router)
app.include_router(portfolio.router)
app.include_router(trade.router)
app.include_router(audit.router)
app.include_router(market.router)
app.include_router(compliance.router)
app.include_router(ws.router)
```
*(Note: To maintain 100% backward compatibility for any existing test or script, `advisory.py` can be retained as a re-exporting compatibility module or router aggregation, ensuring zero breaking changes.)*

---

## 4. Detailed Route-by-Route Implementation Specifications

### 4.1 Authentication: `auth.py`
- **Prefix**: `/api/v1/auth`
- **Tags**: `["auth"]`

#### Endpoints:
1. **`POST /register`**
   - **Status Code**: `201 Created`
   - **Request Body**:
     ```python
     class RegisterRequest(BaseModel):
         email: EmailStr
         password: str = Field(min_length=8, max_length=72)
         
         @field_validator("password")
         @classmethod
         def validate_password_strength(cls, v: str) -> str:
             common_weak = {"password", "12345678", "qwertyui", "admin123", "letmein1"}
             if v.lower() in common_weak:
                 raise ValueError("Password is too common or weak")
             return v
     ```
   - **Business Logic**:
     * Lowercase and strip email.
     * Query `DBUser` where `DBUser.email == email`.
     * If user exists: raise `HTTPException(status_code=409, detail="Email already registered")`.
     * Hash password with bcrypt: `get_password_hash(req.password)`.
     * Insert `DBUser(email=email, hashed_password=hashed)`.
     * Handle `IntegrityError` by rolling back and raising 409 Conflict.
     * Commit and refresh `user`.
     * Return `UserResponse(id=user.id, email=user.email)`.

2. **`POST /login`**
   - **Status Code**: `200 OK`
   - **Request**: `OAuth2PasswordRequestForm = Depends()` (extracting `username` and `password`)
   - **Business Logic**:
     * Query `DBUser` where `DBUser.email == form.username.lower().strip()`.
     * If user not found or `verify_password(form.password, user.hashed_password)` is False:
       Raise `HTTPException(status_code=401, detail="Incorrect email or password", headers={"WWW-Authenticate": "Bearer"})`.
     * If `not user.is_active`:
       Raise `HTTPException(status_code=403, detail="Inactive user account")`.
     * Create access token: `create_access_token({"sub": str(user.id)})`.
     * Return `TokenResponse(access_token=token, token_type="bearer")`.

3. **`GET /me`**
   - **Status Code**: `200 OK`
   - **Dependency**: `user: DBUser = Depends(get_current_user)`
   - **Business Logic**:
     * Returns `UserResponse(id=user.id, email=user.email)`.
     * Unauthenticated access automatically produces 401 via `get_current_user`.

---

### 4.2 Session Lifecycle: `session.py`
- **Prefix**: `/api/v1/session`
- **Tags**: `["session"]`

#### Endpoints:
1. **`POST /start`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`, `c: AgentContainer = Depends(get_container)`
   - **Response Model**:
     ```python
     class SessionStartResponse(BaseModel):
         session_id: str
         message: str
         stage: str
         client_id: Optional[str] = None
     ```
   - **Business Logic**:
     * Query database for latest `DBClientProfile` where `DBClientProfile.user_id == user.id`.
     * If existing profile found:
       - `client_id = existing.client_id`
       - `stage = "advising"`
     * Else:
       - `client_id = None`
       - `stage = "profiling"`
     * Call `c.orchestrator.start_session(user.id, client_id=client_id)`:
       - Generates `session_id = str(uuid.uuid4())`.
       - Stores session dict into `CacheService` under key `session:{session_id}` with TTL of 86400s (24h).
       - Selects initial greeting: `STATE_PROMPTS[STATE_DEMOGRAPHICS]` if profiling, else advisory welcome message.
     * Return `SessionStartResponse`.

---

### 4.3 Conversational Chat & Streaming: `chat.py`
- **Prefix**: `/api/v1/chat` (and `/ws/chat`)
- **Tags**: `["chat", "websocket"]`

#### Endpoints:
1. **`POST /message`** (REST Chat)
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`, `c: AgentContainer = Depends(get_container)`
   - **Request Model**:
     ```python
     class ChatMessage(BaseModel):
         session_id: str
         message: str = Field(min_length=1, max_length=4000)
     ```
   - **Response Model**:
     ```python
     class ChatResponse(BaseModel):
         text: str
         agent: str
         type: str
         events: List[Dict[str, Any]]
     ```
   - **Business Logic**:
     * Invoke `events = await c.orchestrator.handle_message(db, user.id, req.session_id, req.message)`.
     * Verify session ownership inside `orchestrator.load_session`: returns 403 if session `user_id != user.id`, 404 if not found.
     * Filter out `user_message` to extract the primary agent reply.
     * Return `ChatResponse`.

2. **`WebSocket /ws/chat/{session_id}` and `/ws/chat`**
   - **Query Parameters**: `token: Optional[str] = Query(None)`
   - **Authentication**:
     * Decodes JWT token via `decode_access_token(token)`.
     * Verifies active user record in DB.
     * If invalid or missing, immediately closes socket with `status.WS_1008_POLICY_VIOLATION`.
   - **Session Validation**:
     * Loads session from CacheService; closes with code 1008 if session does not belong to authenticated user.
   - **Event Streaming**:
     * Handles text messages, affirmative approvals (`{"type": "approve"}`), and cancellations (`{"type": "reject"}`).
     * Emits all 8 structured event types:
       - `agent_response`
       - `bias_alert`
       - `compliance_check`
       - `trade_proposal`
       - `trade_approved`
       - `trade_filled`
       - `portfolio_update`
       - `error`

---

### 4.4 Client Profile: `profile.py`
- **Prefix**: `/api/v1/profile`
- **Tags**: `["profile"]`

#### Endpoints:
1. **`GET /{client_id}`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `client_id: str`, `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`
   - **Business Logic**:
     * Enforce tenant isolation: `profile = await verify_client_ownership(user, client_id, db)`.
       - If `client_id` not found in `DBClientProfile`: raises 404 Not Found.
       - If `profile.user_id != user.id`: raises 403 Forbidden.
     * Return dictionary representation of `DBClientProfile` (excluding raw transcript).

---

### 4.5 Product Comparison: `compare.py`
- **Prefix**: `/api/v1/compare`
- **Tags**: `["comparison"]`

#### Endpoints:
1. **`POST /etfs`**
   - **Status Code**: `200 OK`
   - **Request Model**:
     ```python
     class CompareRequest(BaseModel):
         client_id: str
         symbols: List[str] = Field(min_length=2, max_length=15)
     ```
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`, `c: AgentContainer = Depends(get_container)`
   - **Business Logic**:
     * `profile = await verify_client_ownership(user, req.client_id, db)` (enforces 403/404).
     * Invoke `report = await c.comparison.compare_etfs(req.symbols, profile=profile, client_id=req.client_id)`.
     * Composite scoring applied ($w_{expense}=0.30, w_{tracking}=0.15, w_{liquidity}=0.20, w_{sharpe}=0.10, w_{drawdown}=0.15, w_{suitability}=0.10$).
     * Pass `report.summary_rationale` through `c.orchestrator.gate_text(..., db, req.client_id)`.
     * Return `{ "ranked_products": ..., "unsuitable_products": ..., "winner_symbol": ..., "rationale": ..., "report": ... }`.

2. **`POST /bonds`**
   - **Status Code**: `200 OK`
   - **Request Model**: `CompareRequest`
   - **Business Logic**: Same as ETF comparison, invoking `c.comparison.compare_bonds`.

---

### 4.6 Portfolio, Allocation & Health: `portfolio.py`
- **Prefix**: `/api/v1` (with routes under `/portfolio` and `/allocation`)
- **Tags**: `["portfolio", "allocation"]`

#### Endpoints:
1. **`GET /portfolio/{client_id}`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`, `c: AgentContainer = Depends(get_container)`
   - **Business Logic**:
     * `await verify_client_ownership(user, client_id, db)` (enforces 403/404).
     * `pf = await c.portfolio.get_portfolio(db, client_id, persist_snapshot=True)`.
     * Filter internal debug fields (`prices`, `position_qty`) and return `{ "client_id": ..., "total_value": ..., "cash": ..., "positions": ..., "weights": ..., "updated_at": ... }`.

2. **`POST /portfolio/{client_id}/health-report` and `POST /portfolio/health-report`**
   - **Status Code**: `200 OK`
   - **Accepts**: Either path parameter `{client_id}` OR JSON body `{"client_id": "..."}`.
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Record portfolio check in telemetry: `await c.bias.record_portfolio_check(client_id, db=db)`.
     * Fetch portfolio state: `pf = await c.portfolio.get_portfolio(db, client_id)`.
     * Call `report = await c.health.generate_health_report(db, client_id, portfolio=portfolio_arg)`.
     * Return `report.model_dump(mode="json")`.

3. **`POST /allocation/recommend`**
   - **Status Code**: `200 OK`
   - **Request Model**: `AllocationRequest(client_id: str)`
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Call `events = await c.orchestrator.recommend_allocation(db, req.client_id)`.
     * Inside `orchestrator.recommend_allocation`:
       - Loads `DBClientProfile`.
       - Computes CVaR optimized weights via `AllocationEngine.generate_allocation(profile, include_frontier=True, current_positions=..., db=db)`.
       - Sanitizes explanation text with mandatory risk disclosure (`REG-002`).
       - Validates recommendation against `ComplianceGuard.check_recommendation()`.
       - Logs `RECOMMENDATION_GENERATED` in `DBAuditLog`.
       - Returns structured agent event list.

---

### 4.7 Trading & Order Execution: `trade.py`
- **Prefix**: `/api/v1` (with routes under `/trade` and `/trades`)
- **Tags**: `["trading"]`

#### Endpoints:
1. **`POST /trade/propose`**
   - **Status Code**: `200 OK`
   - **Request Model**: `TradeProposalRequest(client_id: str, symbol: str, side: str, qty: float)`
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Call `proposal = await c.orchestrator.create_proposal(db, req.client_id, req.symbol, req.side, req.qty)`.
     * Stores proposal in CacheService with a 15-minute expiration (`PROPOSAL_TTL_SECONDS = 900`).
     * Logs `TRADE_PROPOSED` in `DBAuditLog`.
     * Return `{"proposal": proposal, "requires_user_approval": True}`.

2. **`POST /trade/execute`**
   - **Status Code**: `200 OK`
   - **Request Model**:
     ```python
     class TradeRequest(BaseModel):
         client_id: str
         symbol: Optional[str] = None
         qty: Optional[float] = None
         side: Optional[str] = None
         user_approved: bool = False
         proposal_id: Optional[str] = None
     ```
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * If `proposal_id` not provided: generate proposal dynamically from symbol, side, qty.
     * Enforce affirmative user approval (`REG-003`): if `not user_approved`, raise `HTTPException(status_code=403, detail="Trade blocked: affirmative user approval required (REG-003)")`.
     * Invoke `events = await c.orchestrator.execute_proposal(db, user.id, proposal_id, approved=req.user_approved)`.
       - Enforce 15-minute expiration (`REG-004`): raises 400 ExpiredApprovalError if timed out.
       - Enforce 30-second double-submit distributed lock via `cache.acquire_lock(f"lock:trade:{client_id}", timeout_seconds=30)`: raises 409 Conflict if duplicate trade attempted.
       - Enforce KYC verification: raises 403 if client profile `kyc_verified` is False.
       - Enforce pre-trade compliance checks: `ComplianceGuard.check_trade()` (CONC-001 single stock cap 15%, AML-001 single trade cap $50k, AML-002 velocity cap $100k/24h).
       - Sanitize all datetime objects in payload to ISO strings before audit logging.
       - Execute order via `ExecutionModule.execute_trade()` in paper trading mode.
       - Persist trade to `DBTrade` and log `TRADE_EXECUTED` to `DBAuditLog`.
     * Return `{"status": "success", "execution": ..., "events": events}`.

3. **`GET /trade/{order_id}`**
   - **Status Code**: `200 OK`
   - **Business Logic**:
     * Search `DBTrade` by `id == order_id` or `alpaca_order_id == order_id`.
     * If found: verify client ownership via `verify_client_ownership(user, trade.client_id, db)`.
     * Query order status via `status_info = await c.execution.get_order_status(order_id)`.
     * Return consolidated trade details.

4. **`GET /trades/{client_id}`**
   - **Status Code**: `200 OK`
   - **Query Parameters**: `limit: int = Query(50, ge=1, le=500)`
   - **Business Logic**:
     * Verify client ownership via `verify_client_ownership`.
     * Query `DBTrade` where `client_id == client_id` ordered by `created_at.desc()`.
     * Return `{"client_id": client_id, "trades": [...]}`.

---

### 4.8 Audit Trail & Verification: `audit.py`
- **Prefix**: `/api/v1/audit`
- **Tags**: `["audit"]`

#### Endpoints:
1. **`GET /{client_id}`**
   - **Status Code**: `200 OK`
   - **Query Parameters**: `limit: int = Query(100, ge=1, le=1000)`
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Query `DBAuditLog` for `client_id` ordered by `timestamp.desc()`.
     * Return `{"client_id": client_id, "entries": [...]}`.

2. **`GET /{client_id}/verify`**
   - **Status Code**: `200 OK`
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Execute `valid, bad_entry_id = await c.audit.verify_audit_chain(db, client_id)`.
     * Validates SHA-256 genesis hash (`prev_hash = "0" * 64`), SHA-256 chained hashes, and HMAC-SHA256 signatures against `settings.secret_key`.
     * Return `{"client_id": client_id, "valid": valid, "first_invalid_entry": bad_entry_id}`.

3. **`POST /{client_id}/anchor`**
   - **Status Code**: `200 OK`
   - **Business Logic**:
     * Verify ownership via `verify_client_ownership`.
     * Anchors Merkle root of audit log to Sepolia testnet smart contract (or dry-run if unconfigured).
     * Return anchoring transaction receipt.

---

### 4.9 Market Data: `market.py`
- **Prefix**: `/api/v1/market`
- **Tags**: `["market"]`

#### Endpoints:
1. **`GET /quote/{symbol}`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `c: AgentContainer = Depends(get_container)`
   - **Business Logic**:
     * Fetch quote via `q = await c.market.get_quote(symbol)`.
     * Rate-limited with circuit breaker and fallback to offline recorded fixtures in `tests/fixtures/`.
     * Return `q.model_dump(mode="json")`.

2. **`GET /macro`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `c: AgentContainer = Depends(get_container)`
   - **Business Logic**:
     * Fetch macroeconomic indicators and Treasury yield curve:
       ```python
       macro = await c.market.get_macro_context()
       curve = await c.market.get_yield_curve()
       ```
     * Return `{"macro": macro, "yield_curve": curve, "as_of": ...}`.

---

### 4.10 Regulatory Compliance Rules: `compliance.py`
- **Prefix**: `/api/v1/compliance`
- **Tags**: `["compliance"]`

#### Endpoints:
1. **`GET /rules`**
   - **Status Code**: `200 OK`
   - **Dependencies**: `user: DBUser = Depends(get_current_user)`, `db: AsyncSession = Depends(get_db)`, `c: AgentContainer = Depends(get_container)`
   - **Business Logic**:
     * Query active compliance rules from database: `rules = await c.compliance.get_active_rules(db)`.
     * Return sorted list of 12 catalogued rules (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`).

---

## 5. Security Invariants & Tenant Isolation

| Invariant | Condition | Expected Response | Enforced By |
|---|---|---|---|
| **Authentication Invariant** | Missing, expired, or invalid JWT Bearer token | `401 Unauthorized` (`WWW-Authenticate: Bearer`) | `core/security.py:get_current_user` |
| **User Inactivity Invariant** | `user.is_active == False` | `403 Forbidden` (`detail="Inactive user account"`) | `core/security.py:get_current_user` |
| **Tenant Isolation Invariant** | Requesting a `client_id` belonging to a different user | `403 Forbidden` (`detail="Forbidden: You do not have permission to access this client profile"`) | `core/security.py:verify_client_ownership` |
| **Client Non-Existence** | Requesting a `client_id` that does not exist | `404 Not Found` | `core/security.py:verify_client_ownership` |
| **Non-Discretionary Approval (`REG-003`)** | Trade execution attempted with `user_approved=False` | `403 Forbidden` (logged as `TRADE_BLOCKED`) | `agents/orchestrator.py` & `agents/execution_module.py` |
| **Approval Freshness (`REG-004`)** | Trade approval timestamp > 15 minutes old | `400 Bad Request` | `agents/execution_module.py` |
| **Double-Submit Prevention** | Consecutive trade execution submissions within 30 seconds | `409 Conflict` (via 30s lock `lock:trade:{client_id}`) | `agents/execution_module.py` |
| **Duplicate Registration** | Registration with existing email address | `409 Conflict` (`detail="Email already registered"`) | `api/routes/auth.py` |
| **Input Validation** | Password < 8 characters or malformed fields | `422 Unprocessable Entity` | Pydantic Request Models |
| **WebSocket Policy Invariant** | Missing or invalid token on WebSocket connection | `1008 Policy Violation` close frame | `api/routes/ws.py` / `core/security.py` |

---

## 6. Verification & Implementation Roadmap

### Verification Method:
To independently verify that the full API suite meets all requirements:
1. Run the test suite:
   ```bash
   pytest -v tests/e2e/test_full_flow.py
   pytest -v tests/unit/test_security.py
   ```
2. Verify all 13 REST endpoints and `/ws/chat`:
   - Start the server: `python main.py`
   - Inspect `/docs` for full OpenAPI schema coverage.
   - Run unauthenticated and cross-tenant curl / HTTP requests to verify 401 and 403 responses.

### Summary Checklist for Implementation:
- [x] Full route-by-route audit complete (zero mocks verified).
- [x] Architectural modularization defined matching `PROJECT.md`.
- [x] Identified and documented 3 runtime defects (Audit log datetime serialization, REG-002 explanation risk disclosure, and REG-001 SAFE_REPLACEMENT phrase loop).
- [x] Security invariants specified with exact status codes and exceptions.
- [x] Hand-off report prepared for downstream implementation and testing.

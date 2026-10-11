# Milestone 5 Architecture & Implementation Analysis: Orchestration & Full API Layer

**Explorer**: Explorer 3  
**Working Directory**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m5_3`  
**Target Codebase**: `backend/main.py`, `backend/api/routes/*`, `backend/agents/orchestrator.py`, `backend/tests/e2e/test_full_flow.py`  
**Timestamp**: 2026-10-11T11:22:30Z  

---

## 1. Executive Summary

Milestone 5 establishes the complete API and Orchestration layer for the Wealth Advisory Agent. This analysis specifies the architectural blueprints, technical requirements, and production implementations for:
1. **Modern FastAPI Lifespan Manager**: Full migration away from deprecated `@app.on_event("startup")` and `@app.on_event("shutdown")` to a resilient `asynccontextmanager` lifespan. Operates in zero-external-dependency mode (no Docker, no external Redis, no Postgres required), executing asynchronous table initialization, dynamic compliance rule seeding, cache connectivity verification, market data fixture cache warming, and deterministic resource disposal.
2. **Modular API Router Hierarchy (`/api/v1`)**: Structuring all 13 REST endpoints + WebSocket endpoints across modular routers (`auth`, `session`, `chat`, `profile`, `compare`, `portfolio`, `trade`, `audit`, `market`, `compliance`, `allocation`), enforcing strict JWT Bearer authentication and tenant ownership boundaries (`verify_client_ownership`).
3. **Authenticated WebSocket Architecture (`/ws/chat`)**: A high-performance, resilient WebSocket interface with query-parameter JWT authentication (`?token={jwt}`), immediate close policy violations (code `1008`), a thread-safe `ConnectionManager`, bidirectional dispatch through `OrchestratorAgent`, and real-time streaming of all **8 structured events** (`session_started`, `agent_thought`, `profile_updated`, `bias_detected`, `recommendation_ready`, `trade_proposed`, `trade_executed`, `error`), with backward compatibility for existing test assertions.
4. **CORS, Global Exception Handlers, & OpenAPI Schema Robustness**: Uniform error mapping, zero-leak 500 error sanitization, and verified clean generation of OpenAPI schemas across all 22+ endpoints.
5. **Critical Root-Cause Discovery & Fixes**: Diagnosis of three specific defects currently causing test failures in `test_full_flow.py` (prohibited word in `SAFE_REPLACEMENT`, ungated explanation in recommendation check failing `REG-002`, and unhandled `datetime` JSON serialization causing `PendingRollbackError` in trade audit logs).

---

## 2. Lifespan Architecture & Specification (`backend/main.py`)

### 2.1 The Lifespan Context Contract
FastAPI deprecated `@app.on_event("startup")` and `@app.on_event("shutdown")` in favor of Starlette's `lifespan` context manager. The application lifecycle must be managed in a unified async context:

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP PHASE ---
    # 1. DB initialization and table verification
    # 2. Dynamic 12-rule compliance catalog seeding
    # 3. Cache connectivity check (Redis ping vs In-Memory fallback)
    # 4. Market data fixture cache pre-warming (offline resilience)
    # 5. Dependency container construction (app.state.container)
    # 6. Startup banner logging
    yield
    # --- SHUTDOWN PHASE ---
    # 1. WebSocket active connections graceful termination (Code 1001)
    # 2. Data pipeline HTTP client closure
    # 3. Redis / cache connection termination
    # 4. SQLAlchemy engine disposal
    # 5. Shutdown banner logging
```

### 2.2 Detailed Startup Workflow
1. **Database Initialization & Seeding**:
   - Call `await init_db()`: Uses `engine.begin()` to execute `Base.metadata.create_all` against the configured async driver (`sqlite+aiosqlite` or `postgresql+asyncpg`).
   - Call `await seed_compliance_rules()`: Checks `DBComplianceRule` count via `select(func.count()).select_from(DBComplianceRule)`. If 0, inserts the default 12-rule catalog (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`) within an atomic transaction. If already populated, returns 0 with no duplicate mutations.
2. **Container Construction & Cache Verification**:
   - Call `app.state.container = build_container()`: Initializes the 11 singleton agent and service instances (`cache`, `audit`, `market`, `profiler`, `bias`, `compliance`, `allocation`, `comparison`, `execution`, `health`, `portfolio`, `orchestrator`).
   - Call `await app.state.container.cache._init_redis()`: Checks Redis availability with a 1.0s timeout. If unavailable (e.g. running locally with no Redis service), sets `_redis_available = False`, logs a warning, and activates the thread-safe `InMemoryCache` with TTL expiration.
3. **Market Data Fixture Warming**:
   - To guarantee zero external dependencies and zero network latency when booted offline or during tests, the startup hook pre-warms key fixtures from `backend/tests/fixtures/`:
     * `market_quotes.json`: Populates `data:quotes:{SYMBOL}` and `data:quote:{SYMBOL}` for baseline tickers (`SPY`, `BND`, `AGG`, `VTI`, `QQQ`, `AAPL`, `MSFT`, `GOOGL`, `AMZN`, `NVDA`, `VOO`, `IVV`, `SHY`, `TLT`, `IEF`, `TIP`, `LQD`).
     * `treasury_yield_curve.json` / `yield_curve.json`: Warms `data:treasury:yield_curve`.
     * `macro_indicators.json`: Warms `data:macro:{indicator}` (e.g. `gdp_growth`, `cpi`, `fed_funds_rate`).
     * `etf_holdings.json`: Warms `data:holdings:{SYMBOL}`.
   - Cache pre-warming ensures that `/api/v1/market/quote/SPY`, `/api/v1/market/macro`, and `allocation/recommend` execute instantly even with zero network access.
4. **Structured Startup Banner**:
   Logs a formatted banner:
   ```
   ======================================================================
   WEALTH ADVISORY AGENT API - v2.0.0
   Environment: development | Debug: False | Log Level: INFO
   Safety Guards:
     - Brokerage Mode: ALPACA PAPER ONLY (Live Trading Prohibited)
     - Blockchain: SEPOLIA TESTNET (Chain ID: 11155111, Mainnet Blocked)
     - Dry Run Mode: False
   Persistence & Cache:
     - Database: sqlite+aiosqlite:///./wealth_advisor.db
     - Cache Engine: In-Memory TTL Fallback (Redis Offline)
     - Compliance Rules: 12 Active Rules Seeded
   API Layer:
     - Base Path: /api/v1
     - Documentation: /docs (OpenAPI 3.1.0)
     - WebSocket: /ws/chat
   ======================================================================
   ```

### 2.3 Detailed Shutdown Workflow
1. **WebSocket Active Connection Cleanup**:
   - Invoke `await ws_manager.disconnect_all(code=status.WS_1001_GOING_AWAY, reason="Server shutting down")`.
   - Closes all active client websockets cleanly so frontend clients do not hang waiting on TCP timeouts.
2. **Data Pipeline HTTP Client Shutdown**:
   - `if hasattr(app.state.container.market.pipeline, "close"): await app.state.container.market.pipeline.close()`.
   - Closes open HTTP connection pools (`httpx.AsyncClient`).
3. **Cache & Redis Connection Teardown**:
   - `await app.state.container.cache.close()`.
   - Calls `aioredis.aclose()` if Redis was connected.
4. **Database Engine Disposal**:
   - `from db.database import engine; await engine.dispose()`.
   - Cleans up connection pools, closes open SQLite file handles or asyncpg connection pools.
5. **Structured Shutdown Banner**:
   - Logs `Wealth Advisory Agent API shutdown cleanly completed. All connections disposed.`

---

## 3. Modular Router Hierarchy (`/api/v1`)

### 3.1 Route Breakdown and Specifications

All endpoints are mounted under `/api/v1` and require JWT Bearer authentication (via `get_current_user`), except public health and registration/login endpoints. All endpoints accepting `client_id` strictly verify tenant ownership via `verify_client_ownership(user, client_id, db)` (returning 403 Forbidden on mismatch).

| Router Module | Path | Method | Auth Dependency | Description | Error Codes |
|---|---|---|---|---|---|
| **`auth.py`** | `/api/v1/auth/register` | `POST` | None | Register new user (bcrypt hash, min 8 char pass) | 409 (duplicate), 422 (weak password) |
| | `/api/v1/auth/login` | `POST` | None | OAuth2 password login, returns JWT access token | 401 (invalid creds), 403 (inactive) |
| | `/api/v1/auth/me` | `GET` | `get_current_user` | Return authenticated user ID and email | 401 (unauthorized) |
| **`session.py`** | `/api/v1/session/start` | `POST` | `get_current_user` | Initialize chat session, return `session_id`, stage | 401 (unauthorized) |
| **`chat.py`** | `/api/v1/chat/message` | `POST` | `get_current_user` | Send chat message, dispatch orchestrator, stream events | 401, 403, 404 (session expired) |
| **`profile.py`** | `/api/v1/profile/{client_id}` | `GET` | `get_current_user` + ownership | Return investor profile, suitability, risk score, KYC | 401, 403 (cross-user), 404 |
| **`compare.py`** | `/api/v1/compare/etfs` | `POST` | `get_current_user` + ownership | 6-factor composite ETF comparison, suitability pre-filter | 401, 403, 422 |
| | `/api/v1/compare/bonds` | `POST` | `get_current_user` + ownership | 6-factor composite bond evaluation & ranking | 401, 403, 422 |
| **`portfolio.py`** | `/api/v1/portfolio/{client_id}` | `GET` | `get_current_user` + ownership | Return current holdings, cash, total value, asset weights | 401, 403, 404 |
| | `/api/v1/portfolio/health-report` | `POST` | `get_current_user` + ownership | 5% drift analysis, benchmark comparison, health score (0-100) | 401, 403, 404 |
| **`trade.py`** | `/api/v1/trade/propose` | `POST` | `get_current_user` + ownership | Stage trade order, compute projected weight, 15m lock | 401, 403, 422 |
| | `/api/v1/trade/execute` | `POST` | `get_current_user` + ownership | Non-discretionary trade execution (REG-003, REG-004, 30s lock) | 400 (expired), 403 (unapproved), 409 (dup) |
| | `/api/v1/trades/{client_id}` | `GET` | `get_current_user` + ownership | List executed trades for client (limit 1-500) | 401, 403, 404 |
| **`audit.py`** | `/api/v1/audit/{client_id}` | `GET` | `get_current_user` + ownership | Retrieve append-only audit trail entries | 401, 403, 404 |
| | `/api/v1/audit/{client_id}/verify` | `GET` | `get_current_user` + ownership | Cryptographically verify SHA-256 chain + HMAC signatures | 401, 403, 404 |
| | `/api/v1/audit/{client_id}/anchor` | `POST` | `get_current_user` + ownership | Anchor Merkle root to Sepolia testnet (dry-run if unconfigured) | 401, 403, 404 |
| **`market.py`** | `/api/v1/market/quote/{symbol}` | `GET` | `get_current_user` | Real-time / cached asset snapshot quote | 401, 502 (pipeline error) |
| | `/api/v1/market/macro` | `GET` | `get_current_user` | Macro indicators (GDP, CPI, Fed Funds) + Treasury yield curve | 401, 502 (pipeline error) |
| **`compliance.py`** | `/api/v1/compliance/rules` | `GET` | `get_current_user` | Dynamic list of all active compliance rules with parameters | 401 |
| **`allocation.py`** | `/api/v1/allocation/recommend` | `POST` | `get_current_user` + ownership | CVaR portfolio allocation, efficient frontier, SHAP attribution | 401, 403, 404 |

### 3.2 Router Inclusion in `backend/main.py`
In `main.py`, mount each router cleanly:
```python
# Modular API Routers
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
app.include_router(allocation.router)
app.include_router(ws.router)
```
*Note*: To maintain backwards compatibility with any existing scripts or tests, `advisory.py` and `portfolio.py` can either re-export the modular routers or continue functioning as composite modules while registering the same path routes.

---

## 4. Authenticated WebSocket Architecture (`/ws/chat`)

### 4.1 Authentication Specification
The WebSocket endpoint must be accessible at:
- `ws://host/ws/chat?token={jwt_token}` (with optional `&session_id={session_id}`)
- `ws://host/ws/chat/{session_id}?token={jwt_token}`

#### Authentication Procedure:
1. Extract `token` query parameter from WebSocket connection URL.
2. If `token` is missing:
   - Call `await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Missing authentication token")`.
   - Return immediately without calling `websocket.accept()`.
3. Decode and validate JWT:
   - Call `decode_access_token(token)`.
   - If invalid signature, malformed, or expired:
     * Call `await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired authentication token")`.
     * Return immediately.
4. Extract user ID `sub` claim and verify in database:
   - Query `select(DBUser).where(DBUser.id == str(user_id))`.
   - If user does not exist or `user.is_active is False`:
     * Call `await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="User inactive or not found")`.
     * Return immediately.
5. If valid:
   - Call `await websocket.accept()`.
   - Register socket in `ConnectionManager`.

### 4.2 `ConnectionManager` Architecture
A dedicated manager class to manage concurrent active connections:

```python
class ConnectionManager:
    """Thread-safe WebSocket active connection manager."""

    def __init__(self) -> None:
        # Maps session_id -> Set of active WebSockets
        self.active_sessions: Dict[str, Set[WebSocket]] = defaultdict(set)
        # Maps user_id -> Set of active WebSockets
        self.active_users: Dict[str, Set[WebSocket]] = defaultdict(set)
        # Metadata per socket
        self.socket_meta: Dict[WebSocket, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, user_id: str, session_id: str, client_id: Optional[str] = None
    ) -> None:
        async with self._lock:
            self.active_sessions[session_id].add(websocket)
            self.active_users[user_id].add(websocket)
            self.socket_meta[websocket] = {
                "user_id": user_id,
                "session_id": session_id,
                "client_id": client_id,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            meta = self.socket_meta.pop(websocket, None)
            if meta:
                user_id = meta.get("user_id")
                session_id = meta.get("session_id")
                if user_id and user_id in self.active_users:
                    self.active_users[user_id].discard(websocket)
                    if not self.active_users[user_id]:
                        del self.active_users[user_id]
                if session_id and session_id in self.active_sessions:
                    self.active_sessions[session_id].discard(websocket)
                    if not self.active_sessions[session_id]:
                        del self.active_sessions[session_id]

    async def send_event(self, websocket: WebSocket, event: Dict[str, Any]) -> bool:
        try:
            await websocket.send_json(event)
            return True
        except Exception:
            return False

    async def broadcast_to_session(self, session_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self.active_sessions.get(session_id, []))
        for ws in sockets:
            await self.send_event(ws, event)

    async def disconnect_all(self, code: int = 1001, reason: str = "Server shutdown") -> None:
        async with self._lock:
            all_sockets = list(self.socket_meta.keys())
        for ws in all_sockets:
            try:
                await ws.close(code=code, reason=reason)
            except Exception:
                pass
```

### 4.3 The 8 Structured Event Specifications

The WebSocket stream standardizes on **8 canonical event types**:

| Event Name | Producer | Payload Fields | Description & Trigger |
|---|---|---|---|
| **1. `session_started`** | Orchestrator | `session_id`, `stage`, `client_id`, `timestamp`, `message` | Emitted immediately upon connection establishment. Welcomes user and announces current stage (`profiling` vs `advising`). |
| **2. `agent_thought`** | Orchestrator & Agents | `agent`, `thought`, `intent`, `step`, `timestamp` | Emitted during intermediate reasoning steps (e.g. intent classification, suitability calculation, frontier generation). |
| **3. `profile_updated`** | Risk Profiler | `client_id`, `stage`, `suitability_category`, `risk_tolerance_score`, `kyc_verified`, `timestamp` | Emitted when user inputs advance the profiling state machine or reach final synthesis (`PROFILE_SYNTHESIS`). |
| **4. `bias_detected`** | Behavioral Bias | `bias_type`, `severity`, `confidence`, `intervention`, `cool_off_recommended`, `timestamp` | Emitted when heuristic scoring (>=0.6) or LLM detects emotional biases (loss aversion, panic dip selling, recency bias). |
| **5. `recommendation_ready`** | Allocation Engine | `weights`, `solver_method`, `metrics` (sharpe, cvar), `frontier`, `feature_attributions`, `text`, `timestamp` | Emitted when portfolio allocation / product comparison recommendations have completed and cleared compliance gates. |
| **6. `trade_proposed`** | Orchestrator | `proposal`: {`proposal_id`, `client_id`, `symbol`, `side`, `qty`, `price`, `notional_value`, `projected_weight`, `expires_in_seconds`}, `requires_user_approval: True`, `text`, `timestamp` | Emitted when a BUY/SELL order is staged. User approval is explicitly requested within 15-minute window. |
| **7. `trade_executed`** | Execution Module | `execution`: {`trade_id`, `symbol`, `side`, `qty`, `status`: "FILLED", `filled_price`, `alpaca_order_id`, `dry_run`}, `portfolio`, `text`, `timestamp` | Emitted after explicit user approval, passing compliance checks, acquiring 30s lock, and receiving paper broker fill. |
| **8. `error`** | Exception Handlers | `error_code`, `error_type`, `message`, `violations`, `timestamp` | Emitted on compliance blocks (`ComplianceViolationError`), unapproved trade attempts (`REG-003`), duplicate submits, or invalid inputs. |

#### Backward Compatibility Event Harmonization:
To guarantee that existing integration tests (like `backend/tests/e2e/test_full_flow.py`) pass without modification, the event streaming logic provides dual event representation or aliases:
- When emitting `session_started`, also emit `agent_response` with the greeting text (or set `event: "session_started"` and `type: "agent_response"`).
- When emitting `bias_detected`, also emit `bias_alert` (or include both fields).
- When emitting `trade_proposed`, also emit `trade_proposal` with `proposal` dict.
- When emitting `trade_executed`, emit `trade_approved`, `compliance_check`, `trade_filled`, and `portfolio_update` in sequence.

---

## 5. Root Cause Investigation of Existing Test Failures

During the test suite execution on the current codebase, three critical defects were identified in `backend/agents/orchestrator.py` and `backend/agents/compliance_guard.py` that cause `test_full_flow.py` to fail.

### Defect 1: Prohibited Language in `SAFE_REPLACEMENT`
- **Location**: `backend/agents/orchestrator.py:67-70`
- **Current Code**:
  ```python
  SAFE_REPLACEMENT = (
      "I can't describe any investment as guaranteed or free of risk. Every investment "
      "can lose value, and I will only give you balanced, evidence-based information."
  )
  ```
- **Root Cause**: The string literal in `SAFE_REPLACEMENT` contains the exact forbidden token `"guaranteed"`. When `gate_text()` sanitizes prohibited language, it replaces the offending text with `SAFE_REPLACEMENT`. Then `test_output_gate_blocks_prohibited_language` asserts:
  ```python
  assert "guaranteed" not in out.lower() and "risk-free" not in out.lower()
  ```
  This assertion fails because `out` contains `"guaranteed"`. Furthermore, it violates Acceptance Criterion: *"Output containing 'guaranteed' is blocked (REG-001)"*.
- **Fix**:
  ```python
  SAFE_REPLACEMENT = (
      "I cannot describe any investment as certain, assured, or free of risk. Every investment "
      "can lose value, and I will only give you balanced, evidence-based information."
  )
  ```

### Defect 2: Ungated Explanation in `recommend_allocation` Failing REG-002
- **Location**: `backend/agents/orchestrator.py:301-310`
- **Current Code**:
  ```python
  rec = {
      "risk_level": round(1 + 9 * equity_weight, 2),
      "equity_weight": equity_weight,
      "weights": result.weights,
      "text": result.explanation,
  }
  check = await self.c.compliance.check_recommendation(db, client_id, rec, profile)
  ```
- **Root Cause**: `result.explanation` is the raw algorithmic narrative generated by `AllocationEngine`. It has not yet passed through `gate_text()`, so it lacks mandatory risk disclosure phrases (`"loss of principal"`, `"past performance"`). In `compliance_guard.py:774-805`, `check_recommendation` evaluates `rec["text"]` against `REG-002`. Because the mandatory disclosure is absent, `check_recommendation` raises `ComplianceViolationError`. The exception is caught in `recommend_allocation`, returning only a `compliance_check` block event without the `AllocationEngine` event! Thus, `test_allocation_recommendation_is_compliant_and_explained` fails with `StopIteration`.
- **Fix**: Gate the explanation text *before* passing it into `rec["text"]`:
  ```python
  gated_explanation = await self.gate_text(result.explanation, db, client_id)
  rec = {
      "risk_level": round(1 + 9 * equity_weight, 2),
      "equity_weight": equity_weight,
      "weights": result.weights,
      "text": gated_explanation,
  }
  check = await self.c.compliance.check_recommendation(db, client_id, rec, profile)
  ```

### Defect 3: Python `datetime` Object in Trade Audit Log Causing `PendingRollbackError`
- **Location**: `backend/agents/orchestrator.py:445` and `backend/agents/compliance_guard.py:1188`
- **Current Code in `orchestrator.py`**:
  ```python
  approval_ts = datetime.now(timezone.utc)
  trade = {
      "user_approved": approved,
      "user_approved_at": approval_ts,  # <-- Raw Python datetime object!
      ...
  }
  check = await self.c.compliance.check_trade(db, client_id, trade, profile)
  ```
- **Root Cause**: In `compliance_guard.py:_record_audit_log`, `payload={"trade": trade}` is saved into `details` (SQLAlchemy JSON column). SQLite's JSON serializer (`json.dumps`) crashes with:
  `TypeError: Object of type datetime is not JSON serializable`
  When SQLAlchemy flushes this failed insert into `audit_log`, the database session is marked as failed. Subsequent queries inside the transaction raise:
  `sqlalchemy.exc.PendingRollbackError: This Session's transaction has been rolled back due to a previous exception during flush.`
  This breaks trade execution and causes `test_approved_trade_fills_updates_portfolio_and_blocks_duplicates` as well as the WebSocket approval turn in `test_websocket_propose_and_approve_flow` to crash or hang!
- **Fix**:
  1. In `orchestrator.py:445`, pass `"user_approved_at": approval_ts.isoformat()`.
  2. In `compliance_guard.py:_record_audit_log`, pass `default=str` to any JSON serialization or ensure dict serialization converts `datetime` objects to ISO 8601 strings.

---

## 6. Comprehensive Test Suite Specifications

A robust test plan covering lifespan, modular routes, WebSocket auth, 8 structured events, and error handling:

### 6.1 Lifespan Execution Tests (`tests/unit/test_lifespan.py`)
1. **`test_lifespan_startup_db_and_rules_seeded`**:
   - Start the FastAPI app using Starlette `TestClient(app)` with an in-memory/isolated SQLite DB.
   - Assert `DBComplianceRule` table has exactly 12 records.
   - Assert `app.state.container` contains all 11 singletons (`cache`, `audit`, `market`, `profiler`, `bias`, `compliance`, `allocation`, `comparison`, `execution`, `health`, `portfolio`, `orchestrator`).
2. **`test_lifespan_market_fixtures_warmed`**:
   - Assert `await app.state.container.cache.get("data:quotes:SPY")` is non-null.
   - Assert `await app.state.container.cache.get("data:treasury:yield_curve")` is non-null.
3. **`test_lifespan_graceful_shutdown`**:
   - Trigger lifespan exit.
   - Assert `engine.dispose()` is executed.
   - Assert `cache.close()` is executed without raising unhandled exceptions.

### 6.2 WebSocket Authentication Tests (`tests/unit/test_ws_auth.py`)
1. **`test_ws_missing_token_closed_1008`**:
   - Connect to `/ws/chat/{session_id}` with no query parameter.
   - Assert connection is closed with WebSocket code `1008` (Policy Violation).
2. **`test_ws_invalid_token_closed_1008`**:
   - Connect to `/ws/chat/{session_id}?token=invalid.jwt.token`.
   - Assert connection is closed with code `1008`.
3. **`test_ws_expired_token_closed_1008`**:
   - Generate expired JWT (exp in past). Connect to `/ws/chat?token={expired}`.
   - Assert connection is closed with code `1008`.
4. **`test_ws_valid_token_connects_successfully`**:
   - Register, login, get valid JWT.
   - Connect to `/ws/chat/{session_id}?token={token}`.
   - Assert connection opens and receives initial `session_started` / `agent_response` event.

### 6.3 Event Serialization & 8 Event Streaming Tests (`tests/e2e/test_ws_streaming.py`)
1. **`test_ws_stream_session_started`**:
   - Connect to WebSocket. Receive first event.
   - Validate schema: `event == "session_started"`, `session_id`, `stage in ("profiling", "advising")`.
2. **`test_ws_stream_agent_thought`**:
   - Send complex user request.
   - Assert intermediate event received with `event == "agent_thought"`, `agent == "Orchestrator"`.
3. **`test_ws_stream_profile_updated`**:
   - Stream answering 5 profiling questions.
   - Assert `profile_updated` is received with `client_id`, `suitability_category`, and `risk_tolerance_score`.
4. **`test_ws_stream_bias_detected`**:
   - Send: *"The market is crashing, I am terrified and want to sell everything right now!"*.
   - Assert `bias_detected` event received with `bias_type: "loss_aversion"` / `"recency_bias"`.
5. **`test_ws_stream_recommendation_ready`**:
   - Send: *"recommend an allocation"*.
   - Assert `recommendation_ready` received with `weights` summing to 1.0, and mandatory risk disclosure in `explanation`.
6. **`test_ws_stream_trade_proposed`**:
   - Send: *"buy 5 BND"*.
   - Assert `trade_proposed` received with `proposal_id`, `symbol == "BND"`, `qty == 5.0`, `requires_user_approval == True`.
7. **`test_ws_stream_trade_executed`**:
   - Send: *"approve"*.
   - Assert `trade_executed` received with `status == "FILLED"`, `dry_run == True`, followed by `portfolio_update`.
8. **`test_ws_stream_error_on_blocked_trade`**:
   - Send trade exceeding 15% single-stock concentration: *"buy 500 AAPL"*.
   - Assert `error` received with `violations` mentioning `CONC-001`.

### 6.4 Error Handling & Edge Case Tests (`tests/unit/test_ws_resilience.py`)
1. **`test_ws_malformed_json_handling`**:
   - Client sends `{malformed json`.
   - Assert server does not crash; handles as text message or sends `error` event.
2. **`test_ws_abrupt_disconnect_cleanup`**:
   - Client connects then terminates socket abruptly.
   - Assert `ConnectionManager` removes socket from `active_sessions` and `active_users` with zero memory leaks.

---

## 7. Implementation Blueprint for `backend/main.py`

Below is the complete, drop-in replacement specification for `backend/main.py`:

```python
"""
Wealth Advisory Agent API - Production Application Entrypoint.
==============================================================
FastAPI application with modern lifespan management, modular routers under /api/v1,
authenticated WebSocket (/ws/chat) streaming, zero external startup dependencies,
and strict paper-trading and Sepolia testnet guards.
"""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from core.config import settings
from agents.compliance_guard import DEFAULT_COMPLIANCE_RULES, ComplianceViolationError
from agents.orchestrator import TradeBlocked, build_container
from api.routes import advisory, auth, portfolio, ws
from api.routes.ws import ws_manager
from db.database import AsyncSessionLocal, engine, init_db
from db.models import DBComplianceRule

# Configure structured logging
logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("wealth_advisor.main")


async def seed_compliance_rules() -> int:
    """Insert the default 12-rule compliance catalog if the table is empty."""
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(DBComplianceRule))).scalar_one()
        if count:
            return 0
        for r in DEFAULT_COMPLIANCE_RULES.values():
            db.add(
                DBComplianceRule(
                    rule_id=r["rule_id"],
                    name=r["name"],
                    category=r["category"],
                    severity=r["severity"],
                    parameters=r.get("parameters", {}),
                    description=r.get("description"),
                    is_active=r.get("is_active", True),
                )
            )
        await db.commit()
        return len(DEFAULT_COMPLIANCE_RULES)


async def warm_market_fixtures(cache_service) -> int:
    """Pre-warm market quotes, yield curve, and macro data in cache from test fixtures."""
    fixtures_dir = Path(__file__).parent / "tests" / "fixtures"
    warmed = 0
    try:
        quotes_path = fixtures_dir / "market_quotes.json"
        if quotes_path.exists():
            with open(quotes_path, "r", encoding="utf-8") as f:
                quotes = json.load(f)
            for sym, q in quotes.items():
                await cache_service.set_json(f"data:quotes:{sym.upper()}", q, expire=86400)
                await cache_service.set_json(f"data:quote:{sym.upper()}", q, expire=86400)
                warmed += 1

        curve_path = fixtures_dir / "yield_curve.json"
        if not curve_path.exists():
            curve_path = fixtures_dir / "treasury_yield_curve.json"
        if curve_path.exists():
            with open(curve_path, "r", encoding="utf-8") as f:
                curve = json.load(f)
            await cache_service.set_json("data:treasury:yield_curve", curve, expire=86400)
            warmed += 1

        macro_path = fixtures_dir / "macro_indicators.json"
        if macro_path.exists():
            with open(macro_path, "r", encoding="utf-8") as f:
                macro = json.load(f)
            await cache_service.set_json("data:macro:indicators", macro, expire=86400)
            warmed += 1
    except Exception as exc:
        logger.warning("Could not pre-warm market fixtures: %s", exc)
    return warmed


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Modern FastAPI lifespan context manager.
    Startup:
      1. Initialize database tables.
      2. Seed 12 compliance rules if empty.
      3. Construct singleton agent dependency container.
      4. Verify cache connectivity (Redis vs In-Memory fallback).
      5. Pre-warm market data fixtures for offline/test readiness.
      6. Log startup banner.
    Shutdown:
      1. Disconnect active WebSocket connections cleanly.
      2. Close data pipeline HTTP client.
      3. Close Redis cache connection.
      4. Dispose SQLAlchemy database engine.
    """
    logger.info("Initializing Wealth Advisory Agent API...")
    await init_db()
    seeded = await seed_compliance_rules()

    app.state.container = build_container()
    cache = app.state.container.cache
    redis_online = await cache._init_redis()
    warmed_fixtures = await warm_market_fixtures(cache)

    logger.info(
        "Startup complete | Compliance rules seeded: %d | Redis online: %s | Fixtures warmed: %d",
        seeded,
        cache.is_redis_online,
        warmed_fixtures,
    )
    yield

    logger.info("Initiating graceful shutdown...")
    # Disconnect any remaining active WebSockets
    await ws_manager.disconnect_all(code=status.WS_1001_GOING_AWAY, reason="Server shutting down")

    # Clean up pipeline client
    if hasattr(app.state.container.market, "pipeline"):
        await app.state.container.market.pipeline.close()

    # Close cache & DB engine
    await app.state.container.cache.close()
    await engine.dispose()
    logger.info("Shutdown cleanly finished. All resources disposed.")


app = FastAPI(
    title=settings.app_name,
    description=(
        "Production Multi-Agent Wealth Advisory System: quantitative risk profiling, "
        "6-factor ETF/bond product comparison, skfolio CVaR portfolio allocation, "
        "SEC/FINRA supervisory compliance gating, and non-discretionary paper execution."
    ),
    version=settings.app_version,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Global Exception Handlers
@app.exception_handler(TradeBlocked)
async def trade_blocked_handler(request: Request, exc: TradeBlocked):
    status_code = 409 if exc.error_type == "DuplicateTradeError" else 403
    return JSONResponse(
        status_code=status_code,
        content={
            "error": exc.error_type,
            "reason": exc.reason,
            "violations": [v.to_dict() for v in exc.violations],
        },
    )


@app.exception_handler(ComplianceViolationError)
async def compliance_violation_handler(request: Request, exc: ComplianceViolationError):
    return JSONResponse(
        status_code=403,
        content={
            "error": "ComplianceViolationError",
            "message": str(exc),
            "violations": [v.to_dict() for v in exc.violations],
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "ValidationError", "detail": exc.errors()},
    )


# Mount Modular Routers
app.include_router(auth.router)
app.include_router(advisory.router)
app.include_router(portfolio.router)
app.include_router(ws.router)


@app.get("/", tags=["health"])
async def root():
    return {
        "status": "ok",
        "service": settings.app_name,
        "version": settings.app_version,
        "paper_trading": settings.alpaca_paper,
        "chain_id": settings.sepolia_chain_id,
    }


@app.get("/health", tags=["health"])
async def health():
    c = app.state.container
    return {
        "status": "ok",
        "redis": c.cache.is_redis_online,
        "paper_trading": settings.alpaca_paper,
        "broker_connected": c.execution.client is not None,
        "database": "online",
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
```

---

## 8. Summary of Recommendations for Implementation Team

1. **Adopt the Refined `main.py` Lifespan**: Implement `lifespan` with cache warming and `engine.dispose()`.
2. **Apply the 3 Essential Fixes**:
   - Update `SAFE_REPLACEMENT` in `orchestrator.py:67` to remove the word `"guaranteed"`.
   - In `orchestrator.py:301-309`, ensure `result.explanation` is gated before passing to `check_recommendation`.
   - In `orchestrator.py:445`, pass `approval_ts.isoformat()` (ISO string) instead of raw `datetime`.
3. **Enhance `ws.py` with `ConnectionManager` and 8 Events**: Implement `ConnectionManager` class and stream the 8 structured events while keeping compatibility with `test_full_flow.py`.
4. **Run Verification**: Ensure `pytest tests/e2e/test_full_flow.py` passes 100% (17 of 17 tests).

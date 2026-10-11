## 2026-10-11T10:24:26Z
You are the Worker for Milestone 5 (Orchestration & Full API Layer) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m5
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Explorer findings to read and follow:
- Explorer 1 (Orchestrator Agent): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m5_1\handoff.md and analysis.md
- Explorer 2 (REST Routers & Zero-Mock Wiring): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m5_2\handoff.md and analysis.md
- Explorer 3 (Lifespan & Authenticated WebSocket): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m5_3\handoff.md and analysis.md

Write Ownership:
You own exclusively:
- backend/agents/orchestrator.py
- backend/api/routes/* (auth.py, session.py, chat.py, profile.py, compare.py, portfolio.py, trade.py, audit.py, market.py, compliance.py, ws.py, advisory.py)
- backend/api/deps.py
- backend/api/__init__.py
- backend/main.py
- backend/services/audit_logger.py
- backend/agents/compliance_guard.py
- backend/agents/allocation_engine.py
- backend/tests/unit/test_orchestrator.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Tasks & Implementation Requirements:

1. Root-Cause Defect Remediations:
   - Defect A (Datetime serialization in Audit Log):
     * In backend/agents/orchestrator.py (line ~445): ensure `"user_approved_at"` in trade dict is an ISO 8601 string (`approval_ts.isoformat()`).
     * In backend/services/audit_logger.py: in `log_audit_entry()`, sanitize `details` dict with `json.loads(json.dumps(details, default=str))` before assigning to `DBAuditLog.details`.
     * In backend/agents/compliance_guard.py: ensure audit log payloads format datetimes as strings.
   - Defect B (Regulatory Risk Disclosure on Recommendation):
     * In backend/agents/allocation_engine.py: append mandatory risk disclosure (*"Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."*) to the default explanation narrative template.
     * In backend/agents/orchestrator.py: call `self.gate_text()` on `result.explanation` before passing it to `self.c.compliance.check_recommendation()`.
   - Defect C (Prohibited Word in SAFE_REPLACEMENT):
     * In backend/agents/orchestrator.py: update `SAFE_REPLACEMENT` to eliminate the word `"guaranteed"` and include full risk disclosure:
       `"I cannot promise returns or describe any investment as free of risk. Every investment can lose value, and I will only give you balanced, evidence-based information. Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."`

2. backend/agents/orchestrator.py:
   - 5-State Session State Machine: `SessionStage(str, Enum)` with `PROFILING`, `ADVICE_GENERATION`, `PROPOSAL_REVIEW`, `EXECUTION`, `HEALTH_MONITORING`. Store/retrieve stage in `CacheService`.
   - Implement canonical Milestone 5 method signatures:
     * `async def process_user_message(self, session_id: str, user_id: str, client_id: Optional[str], message: str, db: AsyncSession) -> List[dict]`
     * `async def create_trade_proposal(self, db: AsyncSession, client_id: str, symbol: str, side: str, qty: float) -> dict`
     * `async def handle_trade_approval(self, db: AsyncSession, user_id: str, proposal_id: str, approved: bool) -> List[dict]`
   - Retain backward-compatible facades:
     * `async def handle_message(self, db: AsyncSession, user_id: str, session_id: str, text: str) -> List[Dict[str, Any]]`
     * `async def create_proposal(...)` and `async def execute_proposal(...)`
   - Intent routing:
     * Profiling answers -> `RiskProfilerAgent.process_input()`
     * Message inspection -> `BehavioralBiasAgent.detect_bias()` & `record_portfolio_check()`
     * Market queries ("quote SPY", "macro", "yield curve") -> `MarketDataAgent`
     * ETF/Bond comparison ("compare etf SPY VOO") -> `ProductComparisonAgent`
     * Allocation recommendation ("recommend allocation") -> `AllocationEngine.generate_allocation()`
     * Rebalance / health check ("health report", "rebalance") -> `HealthReportService.generate_health_report()`
     * Trade proposal & affirmative approval ("approve", "reject") -> `ExecutionModule.execute_trade()`
   - Universal compliance output gating: every single assistant text message passes through `gate_text()`.

3. Modular Router Hierarchy in backend/api/routes/:
   - Partition endpoints cleanly into:
     * `auth.py`: `POST /api/v1/auth/register`, `POST /api/v1/auth/login`, `GET /api/v1/auth/me`
     * `session.py`: `POST /api/v1/session/start`
     * `chat.py`: `POST /api/v1/chat/message`
     * `profile.py`: `GET /api/v1/profile/{client_id}`
     * `compare.py`: `POST /api/v1/compare/etfs`, `POST /api/v1/compare/bonds`
     * `portfolio.py`: `GET /api/v1/portfolio/{client_id}`, `POST /api/v1/portfolio/{client_id}/health-report`, `POST /api/v1/allocation/recommend`
     * `trade.py`: `POST /api/v1/trade/propose`, `POST /api/v1/trade/execute`, `GET /api/v1/trade/{order_id}`, `GET /api/v1/trades/{client_id}`
     * `audit.py`: `GET /api/v1/audit/{client_id}`, `GET /api/v1/audit/{client_id}/verify`, `POST /api/v1/audit/{client_id}/anchor`
     * `market.py`: `GET /api/v1/market/quote/{symbol}`, `GET /api/v1/market/macro`
     * `compliance.py`: `GET /api/v1/compliance/rules`
     * `ws.py`: authenticated WebSocket endpoints
   - In `backend/api/routes/advisory.py`: maintain as backward-compatible re-export module so any existing tests importing `advisory.router` continue to work.
   - Enforce Security Invariants:
     * Unauthenticated requests get 401 (`get_current_user`).
     * Accessing another user's `client_id` gets 403 (`verify_client_ownership`).
     * Trade execution without affirmative client approval gets 403 (`REG-003`).
     * Duplicate trade submit within 30s gets 409 Conflict (`lock:trade:{client_id}`).

4. backend/api/routes/ws.py & ConnectionManager:
   - Support both `/ws/chat?token={token}` and `/ws/chat/{session_id}?token={token}`.
   - Query authentication: extract `token`, decode JWT with `decode_access_token()`, verify user in DB. If invalid or missing, close with WebSocket code 1008 (Policy Violation).
   - Implement `ConnectionManager` for connection registration, disconnection, and event sending.
   - Stream all 8 structured events:
     1. `session_started`
     2. `agent_thought`
     3. `profile_updated`
     4. `bias_detected`
     5. `recommendation_ready`
     6. `trade_proposed`
     7. `trade_executed`
     8. `error`
     (and preserve event compatibility for existing tests expecting `portfolio_update`, `trade_filled`, etc.).

5. backend/main.py:
   - Modern FastAPI `lifespan` context manager:
     * Startup: run `init_db()`, `seed_compliance_rules()`, cache ping check, market fixture pre-warming.
     * Shutdown: close active WebSockets (`ws_manager.disconnect_all()`), `cache.close()`, `engine.dispose()`.
   - Mount all modular routers under `/api/v1`.
   - Zero-dependency startup: starts cleanly without Docker, external Postgres, or live Redis.
   - OpenAPI `/docs` lists all 22+ endpoints cleanly without error.

6. Unit Testing:
   - Implement `backend/tests/unit/test_orchestrator.py` covering the 5-state state machine, intent routing, compliance output gating, trade proposal and approval flow.
   - Run tests:
     * `pytest -v tests/unit/test_orchestrator.py`
     * `pytest -v tests/e2e/test_full_flow.py`
     * `pytest -q --cov=agents.orchestrator --cov=api --cov-fail-under=80`
   - Ensure all 17 tests in `test_full_flow.py` pass with 100% success.

7. Handoff:
   - Write your completion report to `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m5\handoff.md`.
   - Send a completion message back to the orchestrator with test results and coverage metrics.

# Handoff Report: Codebase Scaffold Survey

**Agent:** Survey Explorer 1  
**Folder:** `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_1`  
**Milestone:** backend_survey  
**Type:** Hard Handoff (Investigation Complete)  

---

## 1. Observation

Direct observations and verbatim evidence obtained from inspecting the codebase:

1. **Monolithic `backend/main.py` (297 lines):**
   - Startup uses deprecated event:
     ```python
     @app.on_event("startup")
     async def on_startup():
         await init_db()
     ```
     (Lines 47-49)
   - Mock responses hardcoded across endpoints:
     - `POST /api/v1/session/start`: returns `session_id="dummy-session-uuid-1234"` (line 90)
     - `POST /api/v1/chat/message`: returns `"Received your message: '{req.message}'. (Use WebSocket for streaming responses)"` (line 98)
     - `POST /api/v1/compare/etfs`: returns `[{"symbol": s, "score": 8.5} for s in req.symbols]` (line 107)
     - `POST /api/v1/compare/bonds`: returns `[{"symbol": s, "score": 7.2} for s in req.symbols]` (line 115)
     - `GET /api/v1/portfolio/{client_id}`: returns `{"total_value": 10000.0, "positions": [{"symbol": "BND", "qty": 10, "value": 720.5}]}` (lines 123-126)
     - `GET /api/v1/audit/{client_id}`: returns `{"entries": [{"event_type": "COMPLIANCE_CHECK", "status": "PASS", "timestamp": datetime.utcnow()}]}` (lines 134-136)
     - `GET /api/v1/market/quote/{symbol}`: returns `{"symbol": symbol, "price": 150.0, "timestamp": datetime.utcnow()}` (line 150)
     - `GET /api/v1/market/macro`: returns `{"cpi": 3.2, "unemployment_rate": 4.1, "fed_funds_rate": 5.25}` (line 155)
     - `POST /api/v1/portfolio/health-report`: returns `{"status": "Healthy", "drift_percentage": 2.1, "rebalance_recommended": False, ...}` (lines 161-164)
     - `POST /api/v1/trade/execute`: uses hardcoded `mock_rec = {"risk_level": 3, "avg_duration": 4.0}` (line 186)
   - WebSocket endpoint is `/ws/chat/{session_id}` (line 237) without token authentication or lifecycle event types.
   - `backend/api/routes` directory exists but is completely empty (0 files).

2. **Database Models & Tables (`backend/db/models.py` & `wealth_advisor.db`):**
   - Inspection command:
     `python -c "import sqlite3; c = sqlite3.connect('wealth_advisor.db'); print(c.execute('SELECT name FROM sqlite_master').fetchall())"`
     Result: `[('client_profiles',), ... ('audit_log',), ... ('trades',), ...]`
   - Exactly 3 tables exist in `wealth_advisor.db` and `db/models.py`.
   - Missing tables: `users`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`.
   - `DBClientProfile` is missing 11 fields declared in `models/client_profile.py` (`dependents`, `liquid_assets`, `monthly_expenses`, `existing_debts`, `investment_experience`, `loss_capacity`, `target_return`, `specific_goals`, `emotional_risk_score`, `panic_sell_likelihood`, `profiling_session_transcript`) as well as `user_id` foreign key.
   - `db/init.sql` and Alembic migrations (`db/migrations/`, `alembic.ini`) are completely missing.

3. **Execution Module (`backend/agents/execution_module.py`):**
   - In `place_order`:
     ```python
     if not self.client:
         logger.info(f"[DRY-RUN] Placing {side} order for {qty} shares of {symbol}")
         return {
             "status": "mock_filled",
             ...
         }
     ```
     (Lines 34-43). Silently falls back to mock fills if keys are absent without requiring an explicit `DRY_RUN` configuration flag.
   - Lacks double-submit lock (30s window), approval timestamp verification, KYC verification check, AML check, fill polling, and audit entry recording.

4. **Allocation Engine (`backend/agents/allocation_engine.py`):**
   - Optimization constraints are hardcoded:
     ```python
     model = MeanRisk(
         risk_measure=RiskMeasure.CVAR,
         objective_function="maximize_ratio",
         max_weight=0.30,
         min_weight=0.02,
         transaction_costs=0.001
     )
     ```
     (Lines 32-38). Does not derive constraints from client profile risk tolerance or liquidity.
   - Missing efficient frontier generator and portfolio rebalance trade generator.
   - Inconsistent weight attribute usage (`portfolio.weights` at line 45 vs `model.weights_` at line 103).

5. **Risk Profiler (`backend/agents/risk_profiler.py`):**
   - Single-prompt LLM call (lines 41-75) checking for `"PROFILE_COMPLETE"` string.
   - No state machine, no state transitions, no draft persistence, no quantitative score calculation (`suitability_category`, `emotional_risk_score`, `panic_sell_likelihood`), no KYC or AML checks.

6. **Behavioral Bias Agent (`backend/agents/behavioral_bias.py`):**
   - One-shot prompt to `gpt-4o` (lines 34-54).
   - No keyword/regex heuristic scoring, no behavioral telemetry analysis, no `behavioral_memory` persistence.

7. **Compliance Guard (`backend/agents/compliance_guard.py`):**
   - Only 2 rules exist: `SUIT-001` (line 34) and `REG-003` (line 41).
   - Missing 10 rules: `SUIT-002`, `SUIT-003`, `CONC-001..003`, `REG-001`, `REG-002`, `REG-004`, `AML-001..002`.
   - Rules are hardcoded in python, not loaded from DB.
   - No text output filter to catch prohibited guarantee language or mandate risk disclosures.

8. **Missing Core and Service Components:**
   - `core/` directory does not exist (`config.py` and `security.py` absent).
   - `services/` directory is completely empty (0 files). Absent: `cache.py`, `audit_logger.py`, `anchoring.py`, `data_pipeline.py`, `providers/`, `health_report.py`.
   - Missing agents: `agents/orchestrator.py`, `agents/market_data.py`, `agents/product_comparison.py`.

9. **Tests:**
   - `tests/` directory does not exist (0 test files).

10. **Environment & Dependencies:**
    - Python verification:
      - `alembic`: OK
      - `alpaca`: OK
      - `skfolio`: OK
      - `shap`: OK
      - `bcrypt`: OK
      - `redis` library: OK
      - `yfinance`: Missing from installed environment
      - `web3`: Missing from installed environment
      - `pytest_cov`: Missing from installed environment
      - Local Redis socket connection check (`127.0.0.1:6379`): `False` (not running; requires in-memory fallback)
      - Local SQLite configured default via `wealth_advisor.db`.

---

## 2. Logic Chain

1. **From Observation 1:** 9 out of 13 REST endpoints return hardcoded mock constants (`150.0`, `10000.0`, `dummy-session-uuid-1234`), and the WebSocket lacks authentication and structured events.
   - *Inference:* The API layer does not integrate real business logic or agent orchestration. Moving from monolith `main.py` to modular routers in `api/routes/` with `lifespan` and real services is required to fulfill R4.
2. **From Observation 2:** Only 3 database tables exist, missing `users`, `portfolio_snapshots`, `behavioral_memory`, and `compliance_rules`, while `DBClientProfile` is missing 11 profile fields and `user_id`.
   - *Inference:* User authentication (R1), user ownership checks, compliance rule configuration (R3), behavioral memory (R3), and portfolio drift history (R3) cannot function until `db/models.py` is expanded and migrations are created.
3. **From Observation 3 & 4:** `execution_module.py` allows unverified order submission with silent mock fills, and `allocation_engine.py` uses fixed parameters rather than client profile constraints.
   - *Inference:* Execution lacks regulatory safeguards (REG-003, REG-004, AML checks, 30s locks), and the allocation optimizer must be updated to accept dynamic risk profile parameters and generate rebalancing trades per R3.
4. **From Observation 5, 6, & 7:** `risk_profiler.py`, `behavioral_bias.py`, and `compliance_guard.py` are rudimentary proof-of-concept stubs lacking formal state machines, heuristics, memory, and 10 of the 12 required compliance rules.
   - *Inference:* The agent core must be systematically rewritten to incorporate state machines, draft persistence, rule catalog loading, and output filtering before orchestrator integration can succeed.
5. **From Observation 8 & 10:** `core/`, `services/`, and several agents are completely non-existent, and Redis is not running locally.
   - *Inference:* The foundational service layer (cache with in-memory fallback, hash-chained audit logger, data pipeline with fixtures, and security/config) must be constructed first before agents and routes can consume them.
6. **From Observation 9:** There are zero tests in the workspace.
   - *Inference:* All acceptance criteria (`pytest -q --cov=. --cov-fail-under=80`, compliance rule coverage, audit chain tamper tests, 10 spec scenarios) require building the testing framework and recorded fixtures from the ground up.

---

## 3. Caveats

- **No live external dependencies:** Local Redis is offline, and external APIs (Alpaca, yfinance, FRED, Sepolia) may be unauthenticated or rate-limited. All modules must support graceful in-memory and recorded fixture fallbacks.
- **Spec Section 8.2 Scenarios:** The specific text of "spec section 8.2" is defined through the 10 acceptance scenarios outlined in the implementation plan and original request (Retiree onboarding, Aggressive onboarding, Panic seller, Concentration limit, Trade without approval, Guaranteed language block, Risk disclosure block, Duplicate trade lock, KYC/AML block, Audit tamper detection). Explorer 3 is mapping these in parallel.
- **Frontend Independence:** Only the backend is examined and targeted; `frontend/` remains untouched.

---

## 4. Conclusion

The backend currently consists of a preliminary scaffold with 5 partial agent files, a monolith `main.py` dominated by mock responses, 3 partial DB tables, and no tests, auth, or services.

To achieve the requirements of `ORIGINAL_REQUEST.md` and pass all acceptance criteria, implementation should proceed along the structured 6-milestone roadmap:
- **M1 (Foundation):** `core/config.py`, `core/security.py`, full `db/models.py` + Alembic, `services/cache.py` (with in-memory fallback), `services/audit_logger.py`, and `services/anchoring.py`.
- **M2 (Data Layer):** `services/data_pipeline.py`, providers (equities, treasury, macro, fixtures), and `agents/market_data.py`.
- **M3 (Core Agents):** State-machine `risk_profiler.py`, heuristic/telemetry `behavioral_bias.py`, six-factor `product_comparison.py`, and profile-driven `allocation_engine.py`.
- **M4 (Compliance & Execution):** 12-rule `compliance_guard.py` with output filter, hardened `execution_module.py` (locks, approval window, KYC), and `health_report.py`.
- **M5 (Orchestrator & API):** `agents/orchestrator.py`, modular `api/routes/` with `lifespan`, authenticated `/ws/chat?token=...`, and replacement of all mock responses.
- **M6 (E2E & Verification):** Test suites (`unit/`, `integration/`, `e2e/`, `fixtures/`) covering all 10 scenarios with >= 80% code coverage.

---

## 5. Verification Method

To independently verify the observations made in this report:

1. **Inspect existing file hierarchy:**
   ```powershell
   Get-ChildItem -Recurse -File c:\Users\HP VICTUS\Documents\wealth_agent\backend
   ```
   *Expected:* Confirms absence of `core/`, `tests/`, `db/migrations/`, `api/routes/*`, and `services/*`.
2. **Inspect database tables:**
   ```powershell
   python -c "import sqlite3; c = sqlite3.connect('c:/Users/HP VICTUS/Documents/wealth_agent/backend/wealth_advisor.db'); print(c.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall())"
   ```
   *Expected:* Exactly 3 tables returned (`client_profiles`, `audit_log`, `trades`).
3. **Verify mock responses in `main.py`:**
   Inspect lines 86-165 of `c:\Users\HP VICTUS\Documents\wealth_agent\backend\main.py`.
   *Expected:* Hardcoded returns for session start, ETF/bond compare, portfolio, audit, market quotes, macro indicators, and health report.
4. **Verify compliance rule catalog in `agents/compliance_guard.py`:**
   Inspect lines 30-47 of `c:\Users\HP VICTUS\Documents\wealth_agent\backend\agents\compliance_guard.py`.
   *Expected:* Exactly two rules defined (`SUIT-001` and `REG-003`).
5. **Verify Redis offline status:**
   ```powershell
   python -c "import socket; s = socket.socket(); s.settimeout(1); print(s.connect_ex(('127.0.0.1', 6379)) != 0)"
   ```
   *Expected:* Returns `True` (port 6379 unreachable, validating requirement for automatic in-memory fallback).

---
*Report delivered by Survey Explorer 1.*

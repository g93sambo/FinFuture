# Handoff Report: Backend Environment & Dependency Survey

**Agent**: Survey Explorer 2  
**Handoff Type**: Hard (Investigation complete)  
**Target Path**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_2\handoff.md`  
**Reference Analysis**: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_2\analysis.md`

---

## 1. Observation

1. **Current `backend/requirements.txt`**:
   - Location: `c:\Users\HP VICTUS\Documents\wealth_agent\backend\requirements.txt:1-16`
   - Content contains 15 packages:
     ```txt
     fastapi>=0.104.1, uvicorn>=0.24.0, pydantic>=2.5.2, pydantic-settings>=2.1.0,
     SQLAlchemy>=2.0.23, asyncpg>=0.29.0, redis>=5.0.1, alpaca-py>=0.30.0,
     langchain>=0.0.344, shap>=0.44.0, scikit-learn>=1.3.2, skfolio>=0.1.0,
     openai>=1.13.3, python-dotenv>=1.0.0, aiosqlite>=0.19.0
     ```
   - Missing from `requirements.txt`: `passlib`, `bcrypt`, `python-jose`, `python-multipart`, `httpx`, `alembic`, `pytest`, `pytest-asyncio`, `pytest-cov`, `yfinance`, `web3`, `huggingface-hub`.

2. **Package Import Failures in Current Python Environment (Python 3.12.4)**:
   - Tool command: `python -c "pkgs = ['yfinance', 'web3', 'alembic', 'pytest_cov', 'bcrypt', 'alpaca', 'skfolio', 'shap', 'datasets', 'redis', 'sqlalchemy', 'fastapi', 'jose', 'passlib', 'aiosqlite', 'asyncpg']; ..."`
   - Output:
     - `yfinance MISSING: ModuleNotFoundError No module named 'yfinance'`
     - `web3 MISSING: ModuleNotFoundError No module named 'web3'`
     - `pytest_cov MISSING: ModuleNotFoundError No module named 'pytest_cov'`
     - `datasets MISSING: ModuleNotFoundError No module named 'pyarrow'`
     - `alembic INSTALLED 1.19.2`, `bcrypt INSTALLED 4.0.1`, `alpaca INSTALLED 0.44.0`, `skfolio INSTALLED 1.8.0`, `shap INSTALLED 0.53.0`, `redis INSTALLED 5.0.4`, `sqlalchemy INSTALLED 2.0.52`, `fastapi INSTALLED 0.141.1`, `jose INSTALLED 3.5.0`, `passlib INSTALLED 1.7.4`, `aiosqlite INSTALLED 0.22.1`, `asyncpg INSTALLED 0.32.0`.
   - Tool command: `pip check`
   - Output:
     - `datasets 3.6.0 requires dill, which is not installed.`
     - `datasets 3.6.0 requires pyarrow, which is not installed.`
     - `datasets 3.6.0 has requirement fsspec[http]<=2025.3.0,>=2023.1.0, but you have fsspec 2026.9.0.`
   - Tool command: `pip install --dry-run pytest-cov yfinance web3`
   - Output: Exited with code 0: `Would install ... pytest-cov-7.1.0 ... web3-8.0.0 ... yfinance-1.7.0`.

3. **Database Schema State**:
   - Location: `c:\Users\HP VICTUS\Documents\wealth_agent\backend\wealth_advisor.db`
   - Existing tables: `['client_profiles', 'audit_log', 'trades']` (each table has 0 rows).
   - Column schemas in `backend/db/models.py:10-66`:
     - `client_profiles`: missing `user_id` FK, `dependents`, `liquid_assets`, `monthly_expenses`, `existing_debts`, `investment_experience`, `loss_capacity`, `target_return`, `specific_goals`, `emotional_risk_score`, `panic_sell_likelihood`, `profiling_session_transcript`.
     - `audit_log`: missing append-only ORM event listener / database trigger.
     - Entirely missing tables: `users`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`.
   - Alembic status: `backend/alembic.ini` is `False`, `backend/db/migrations` is `False`.

4. **Service Infrastructure State**:
   - Redis connectivity: Tool test to `127.0.0.1:6379` returned `Redis port 6379 open: False`.
   - `backend/services/`: Directory is currently empty (`sizeBytes: 0`, 0 files).
   - `backend/api/routes/`: Directory is currently empty.
   - `backend/main.py:47-51`:
     ```python
     @app.on_event("startup")
     async def on_startup():
         await init_db()
         logger.info("Database initialized.")
     ```
   - `backend/main.py:86-166`: Monolithic routes returning hard-coded mock dictionaries (`dummy-session-uuid-1234`, `ranked_products: [{"symbol": s, "score": 8.5}]`, `total_value: 10000.0`, `price: 150.0`, etc.).
   - `backend/main.py:237`: `@app.websocket("/ws/chat/{session_id}")` lacks JWT token validation (`?token=...`).

5. **Test & Fixture State**:
   - `backend/tests` exists: `False`.
   - `backend/pytest.ini` exists: `False`.
   - Fixture recordings: No JSON/CSV fixtures exist anywhere for market quotes, treasury curve, macro data, Alpaca responses, or HuggingFace behavioral scenarios.

---

## 2. Logic Chain

1. **Test Execution & Coverage Gate**:
   - Per acceptance criteria: `pytest -q --cov=. --cov-fail-under=80 passes`.
   - Per observation 2, `pytest_cov` is not installed (`ModuleNotFoundError: No module named 'pytest_cov'`).
   - Therefore, any attempt to run `pytest --cov` will fail immediately until `pytest-cov` is installed via `pip install pytest-cov` and recorded in `requirements.txt`.
   - Furthermore, per observation 5, no tests or fixtures exist (`backend/tests` is False). A full test suite across unit, integration, and e2e covering the 10 spec scenarios is required to achieve 80% coverage.

2. **Provider Resilience & Data Pipeline**:
   - Per observation 2, `yfinance` and `web3` are not installed in the environment, and `datasets` cannot import due to missing `pyarrow`.
   - Per observation 4, local Redis is not running (`port 6379 open: False`).
   - Per user criteria: `python main.py starts with no Docker, Redis or Postgres`.
   - Therefore:
     - The cache and lock service (`services/cache.py`) must seamlessly fall back to an in-memory TTL dictionary store when Redis is unreachable.
     - The market data pipeline (`services/data_pipeline.py`) must implement circuit breakers, retry backoff, and pre-recorded offline fixtures (`tests/fixtures/`) so that tests and local runs succeed even without live network or external API tokens.
     - The anchoring service (`services/anchoring.py`) must gracefully run in dry-run mode when `web3` or keys are unconfigured, while enforcing chain ID 11155111 (Sepolia) and refusing chain ID 1 (Mainnet) if configured.
     - The behavioral bias agent (`agents/behavioral_bias.py`) must load calibrated behavioral scenario fixtures locally rather than failing on `datasets` import.

3. **Security, Auth, & Ownership Integrity**:
   - Per acceptance criteria: `Unauthenticated requests get 401; accessing another user's client_id gets 403`.
   - Per observation 3, `client_profiles` has no `user_id` foreign key, and `users` table does not exist.
   - Therefore, the database models must add `users` with bcrypt password hashing, add `user_id` to `client_profiles`, and enforce user ownership in `core/security.py` dependencies.

4. **Compliance & Trade Execution Guards**:
   - Per acceptance criteria: `Trade without approval is blocked (REG-003); duplicate submit within 30s is rejected; Output containing 'guaranteed' is blocked (REG-001); outputs lacking risk disclosure are blocked (REG-002)`.
   - Per observation 3 and code review, `ComplianceGuard` only has 2 hardcoded rules and lacks text output filtering.
   - Per observation 4, `ExecutionModule` has no duplicate locking mechanism.
   - Therefore, the full 12-rule catalog (`compliance_rules` table), text output inspection for guaranteed language and risk disclosures, and 30s distributed/in-memory lock on trade execution are required.

5. **Database Migration & Append-Only Guarantees**:
   - Per observation 3, Alembic is not configured.
   - Therefore, `alembic.ini` and `backend/db/migrations/` (with async `env.py`) must be created to manage migrations across SQLite and PostgreSQL cleanly.
   - The append-only invariant on `audit_log` must be enforced via ORM event listeners on SQLite and SQL triggers on PostgreSQL.

---

## 3. Caveats

1. **Frontend Directory**: `frontend/` was not inspected, as the user instructions explicitly state: "Do not touch frontend/, and do not add Docker files."
2. **External Network API Availability**: External API calls to Yahoo Finance, FRED, FiscalData, and Sepolia RPC depend on external network stability and rate limits; all verification and tests must use recorded fixtures and mock fallbacks to prevent test flakiness.
3. **OpenAI Model & Keys**: OpenAI API calls will fail or incur latency if run live during fast test execution; agent tests should mock LLM completions or use heuristic pattern evaluation.

---

## 4. Conclusion

The backend is fully architecturally viable for end-to-end completion. The prerequisite packages (`pytest-cov`, `yfinance`, `web3`) resolve cleanly with pip. The immediate path forward is:
1. Update `backend/requirements.txt` with missing packages and install `pytest-cov`, `yfinance`, `web3`.
2. Create `backend/core/config.py` (with paper-only guard and Sepolia chain guard) and `backend/core/security.py` (bcrypt + JWT + ownership checks).
3. Update `backend/db/models.py` with all 7 complete tables and ORM append-only listeners, then initialize Alembic (`alembic.ini`, `db/migrations/`).
4. Implement `services/cache.py` (Redis + in-memory fallback), `services/audit_logger.py` (HMAC + SHA-256 hash chaining), `services/anchoring.py` (Sepolia testnet dry-run), and `services/data_pipeline.py` (circuit-breaker + fixtures).
5. Implement `agents/orchestrator.py`, `agents/market_data.py`, `agents/product_comparison.py`, and refactor existing agents (`compliance_guard.py` full catalog, `risk_profiler.py` state machine, `execution_module.py` 30s lock, `behavioral_bias.py` heuristics + memory).
6. Refactor `main.py` using FastAPI `lifespan` and mount routers in `api/routes/`.
7. Build `backend/pytest.ini`, test fixtures, and comprehensive unit/integration/e2e tests to pass `pytest -q --cov=. --cov-fail-under=80`.

---

## 5. Verification Method

To independently verify these findings:

1. **Package Verification**:
   ```powershell
   python -c "import pytest_cov"
   # Output: ModuleNotFoundError: No module named 'pytest_cov'
   python -c "import yfinance"
   # Output: ModuleNotFoundError: No module named 'yfinance'
   python -c "import web3"
   # Output: ModuleNotFoundError: No module named 'web3'
   python -c "import datasets"
   # Output: ModuleNotFoundError: No module named 'pyarrow'
   ```

2. **Database Verification**:
   ```powershell
   python -c "import sqlite3; con=sqlite3.connect('wealth_advisor.db'); print([t[0] for t in con.execute('SELECT name FROM sqlite_master WHERE type=\'table\'').fetchall()])"
   # Output: ['client_profiles', 'audit_log', 'trades']
   ```

3. **Redis Verification**:
   ```powershell
   python -c "import socket; s=socket.socket(); s.settimeout(1); print(s.connect_ex(('127.0.0.1', 6379)) == 0)"
   # Output: False
   ```

4. **Future Implementation Verification Command**:
   ```powershell
   cd c:\Users\HP VICTUS\Documents\wealth_agent\backend
   pytest -q --cov=. --cov-fail-under=80
   ```
   **Invalidation Conditions**:
   - If `pytest_cov` is installed, command 1 will not error.
   - If migrations have run, `users`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`, and `alembic_version` will be present in SQLite.

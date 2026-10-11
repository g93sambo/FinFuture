# Milestone 6: E2E Test Verification, Coverage & Adversarial Hardening Analysis

**Author**: Explorer 2 (Milestone 6 Investigation)  
**Date**: 2026-10-11  
**Project**: Wealth Advisory Agent Backend  
**Directory**: `backend/`

---

## 1. Executive Summary

A comprehensive empirical investigation of repository-wide test execution, test architecture, coverage metrics, concurrency/contention behavior, and core acceptance criteria was conducted across the Wealth Advisory Agent backend codebase.

### Key Metrics Summary
- **Total Test Cases**: 625 collected across 29 test files.
- **Current Test Status**: 623 passing, 2 failing (0.32% failure rate).
- **Total Statements**: 10,498 statements.
- **Repository-Wide Code Coverage**: **94%** (638 missed statements across the entire repository).
- **Coverage Requirement**: Strict `--cov-fail-under=80` is **substantially exceeded** (94% vs 80% requirement).
- **Zero-Dependency Startup**: Empirically confirmed. `main.py` launches cleanly with SQLite and in-memory cache fallback; `/docs` responds with HTTP 200 and registers all 24 API endpoints.
- **Zero Mock Routes**: Empirically confirmed. All 13 modular route files invoke domain agents, services, or database layers with zero hardcoded mock dictionaries.
- **Root Cause of Failures**: Two localized tests in test suites fail due to test specification drift (one global environment variable mask, and one test asserting an outdated bug that has already been resolved in production code).

---

## 2. Full Test Execution Audit & Coverage Analysis

### 2.1 What happens when running `pytest -q --cov=. --cov-fail-under=80`?

When executed in `backend/`, pytest collects 625 test cases. The test suite executes over approximately 233 seconds (3 minutes 53 seconds) and finishes with **exit code 1**.

The failure is **not** due to the coverage threshold:
- Total coverage achieved is **94%**, which easily satisfies `--cov-fail-under=80`.
- The failure is caused strictly by **two failing test assertions**:
  1. `tests/unit/test_anchoring.py::test_mainnet_hard_guard_raises_error`
  2. `tests/unit/test_challenger_m4_compliance.py::TestComplianceRuleBoundaries::test_empirical_finding_audit_log_datetime_serialization_failure`

### 2.2 Coverage Breakdown by Subsystem

| Module / Package | Total Statements | Missed Statements | Code Coverage | Status |
| :--- | :---: | :---: | :---: | :---: |
| **`agents/` (Core Multi-Agent Subsystem)** | | | | |
| `agents/allocation_engine.py` | 360 | 38 | **89%** | PASS |
| `agents/behavioral_bias.py` | 202 | 15 | **93%** | PASS |
| `agents/compliance_guard.py` | 414 | 22 | **95%** | PASS |
| `agents/execution_module.py` | 168 | 15 | **91%** | PASS |
| `agents/market_data.py` | 159 | 18 | **89%** | PASS |
| `agents/orchestrator.py` | 382 | 53 | **86%** | PASS |
| `agents/product_comparison.py` | 258 | 28 | **89%** | PASS |
| `agents/risk_profiler.py` | 441 | 56 | **87%** | PASS |
| **`api/routes/` (REST & WebSocket Routers)** | | | | |
| `api/routes/advisory.py` | 12 | 0 | **100%** | PASS |
| `api/routes/audit.py` | 26 | 6 | **77%** | PASS |
| `api/routes/auth.py` | 47 | 17 | **64%** | PASS |
| `api/routes/chat.py` | 25 | 0 | **100%** | PASS |
| `api/routes/compare.py` | 28 | 6 | **79%** | PASS |
| `api/routes/compliance.py` | 16 | 3 | **81%** | PASS |
| `api/routes/market.py` | 23 | 4 | **83%** | PASS |
| `api/routes/portfolio.py` | 38 | 9 | **76%** | PASS |
| `api/routes/profile.py` | 14 | 1 | **93%** | PASS |
| `api/routes/session.py` | 23 | 3 | **87%** | PASS |
| `api/routes/trade.py` | 62 | 20 | **68%** | PASS |
| `api/routes/ws.py` | 132 | 29 | **78%** | PASS |
| **`core/` & `db/` (Foundation & Persistence)** | | | | |
| `core/config.py` | 81 | 0 | **100%** | PASS |
| `core/security.py` | 102 | 5 | **95%** | PASS |
| `db/database.py` | 19 | 1 | **95%** | PASS |
| `db/models.py` | 134 | 0 | **100%** | PASS |
| `main.py` | 99 | 20 | **80%** | PASS |
| **`services/` (Services & Providers)** | | | | |
| `services/anchoring.py` | 157 | 47 | **70%** | PASS |
| `services/audit_logger.py` | 123 | 8 | **93%** | PASS |
| `services/cache.py` | 197 | 55 | **72%** | PASS |
| `services/data_pipeline.py` | 357 | 16 | **96%** | PASS |
| `services/health_report.py` | 417 | 22 | **95%** | PASS |
| `services/portfolio_service.py` | 74 | 13 | **82%** | PASS |
| `services/providers/equities.py` | 108 | 21 | **81%** | PASS |
| `services/providers/etf_holdings.py` | 58 | 7 | **88%** | PASS |
| `services/providers/macro.py` | 59 | 8 | **86%** | PASS |
| `services/providers/screener.py` | 42 | 2 | **95%** | PASS |
| `services/providers/treasury.py` | 76 | 10 | **87%** | PASS |
| **`tests/` (Test Modules Themselves)** | 5,618 | 45 | **99%** | PASS |
| **REPOSITORY TOTAL** | **10,498** | **638** | **94%** | **PASS** |

---

## 3. Failure Analysis & Root Cause Diagnosis

### 3.1 Failure 1: `test_mainnet_hard_guard_raises_error`
- **Location**: `tests/unit/test_anchoring.py:89`
- **Error Output**: `Failed: DID NOT RAISE MainnetForbiddenError`
- **Mechanism**:
  In `services/anchoring.py` line 152:
  ```python
  async def anchor_hashes(self, leaf_hashes: List[str]) -> AnchoringResult:
      now = datetime.now(timezone.utc)
      merkle_root = compute_merkle_root(leaf_hashes)

      # Check configuration
      if settings.dry_run or not self._is_configured():
          return self._simulate_anchor(merkle_root, len(leaf_hashes), now)
  ```
  In `tests/conftest.py` line 14:
  `os.environ["DRY_RUN"] = "true"` is set globally for test isolation.
  Consequently, `settings.dry_run` is always `True`.
  When `test_mainnet_hard_guard_raises_error` executes:
  ```python
  with patch("services.anchoring.Web3", return_value=mock_w3), patch.object(service, "_is_configured", return_value=True):
      with pytest.raises(MainnetForbiddenError) as exc_info:
          await service.anchor_hashes(["c" * 64])
  ```
  Because `settings.dry_run` is `True`, `anchor_hashes()` immediately short-circuits to `self._simulate_anchor()` and never instantiates `Web3` or queries `w3.eth.chain_id`.
- **Empirical Verification**:
  Patching `patch("services.anchoring.settings.dry_run", False)` during the test immediately catches:
  `MainnetForbiddenError("FATAL SECURITY VIOLATION: Connected to Ethereum Mainnet (Chain ID 1)...")`.
- **Recommended Fix**:
  In `tests/unit/test_anchoring.py`:
  ```python
  with patch("services.anchoring.settings.dry_run", False), \
       patch("services.anchoring.Web3", return_value=mock_w3), \
       patch.object(service, "_is_configured", return_value=True):
      with pytest.raises(MainnetForbiddenError) as exc_info:
          await service.anchor_hashes(["c" * 64])
  ```

---

### 3.2 Failure 2: `test_empirical_finding_audit_log_datetime_serialization_failure`
- **Location**: `tests/unit/test_challenger_m4_compliance.py:471`
- **Error Output**:
  ```
  AssertionError: Bug: Audit log entry failed to persist due to un-serialized datetime in details
  assert '00143b96-5c76-4539-b6d1-fdd355e44711' is None
  ```
- **Mechanism**:
  During Milestone 4 development, the Challenger agent discovered an empirical bug: passing `user_approved_at: datetime` in `trade` caused SQLAlchemy's JSON column serialization to throw `TypeError: Object of type datetime is not JSON serializable`, resulting in `res.audit_entry_id = None`. The test was written to assert that the bug manifested:
  `assert res.audit_entry_id is None`.
  However, Milestone 4 subsequently fixed the bug in `agents/compliance_guard.py` line 1183 by using:
  `"evaluated_payload": json.loads(json.dumps(payload, default=str))`
  Because `default=str` successfully converts datetimes to ISO strings, the audit entry is now successfully committed to the database, and `res.audit_entry_id` is a valid UUID string (`00143b96-5c76-4539-b6d1-fdd355e44711`).
  The test fails because it was asserting the *unfixed* bug behavior rather than verifying the fix!
- **Recommended Fix**:
  Update `tests/unit/test_challenger_m4_compliance.py` line 471:
  ```python
  assert res.audit_entry_id is not None, "Audit log entry successfully persisted with serialized datetime"
  ```

---

## 4. Concurrency, Contention & Windows SQLite Analysis

### 4.1 Observations on `tests/test_concurrency_stress.py`
The test file `tests/test_concurrency_stress.py` (416 lines) evaluates:
1. `test_cache_lock_thundering_herd_100_competitors`: 100 coroutines on `InMemoryCache` (passes in <0.05s).
2. `test_cache_lock_release_and_reacquire_race`: 50 coroutines on `InMemoryCache`.
3. `test_cache_lock_expiration_concurrency`: 20 coroutines on `InMemoryCache`.
4. `test_cache_multi_client_lock_isolation`: 50 coroutines on `InMemoryCache`.
5. `test_cache_concurrent_read_write_delete_churn`: 100 coroutines on `InMemoryCache`.
6. `test_trade_double_submit_prevention_simultaneous`: 25 coroutines on `CacheService`.
7. `test_audit_logger_concurrent_writes_same_client`: 20 concurrent coroutines writing to file SQLite.
8. `test_audit_logger_concurrent_writes_multiple_clients`: 50 concurrent writes (10 clients x 5 writes) across multiple sessions.
9. `test_audit_logger_concurrent_read_while_writing`: 1 continuous writer + 4 polling readers.
10. `test_merkle_anchoring_concurrent_stress`: 50 writes + 5 concurrent anchor tasks.

When run in isolation, all 10 tests pass in **4.88 seconds**.

### 4.2 Potential Risks and Windows Contention Mechanisms
- **SQLite File-Level Locking**: On Windows, SQLite uses OS file handles with mandatory locking. Unlike POSIX advisory locks, file locks on Windows can lead to `sqlite3.OperationalError: database is locked` when multiple async connections attempt concurrent writes.
- **Why it passed**: The fixture `stress_db_engine` in `test_concurrency_stress.py` specifies:
  `connect_args={"check_same_thread": False, "timeout": 30.0}`
  The generous 30.0-second SQLite busy handler timeout allows queued async writers to wait until the lock clears rather than failing immediately.
- **Risk under pytest-xdist or parallel runners**:
  If tests are executed concurrently (e.g. `pytest -n auto`), multiple OS worker processes running file-based SQLite tests concurrently on Windows could experience disk I/O contention and lock starvation.
- **Recommendation**:
  For all SQLite stress testing on Windows:
  1. Maintain `timeout=30.0` in connection arguments.
  2. Enable WAL mode on setup:
     ```python
     async with engine.begin() as conn:
         await conn.execute(text("PRAGMA journal_mode=WAL;"))
         await conn.run_sync(Base.metadata.create_all)
     ```
     WAL mode allows concurrent readers to access the database without blocking writers.
  3. Keep fast unit tests on pure `:memory:` SQLite instances (`create_async_engine("sqlite+aiosqlite:///:memory:", connect_args={"check_same_thread": False})`), which do not touch the Windows filesystem.

---

## 5. Verification of Core Acceptance Criteria

Each of the 7 core success criteria was examined against requirements and test implementations:

| # | Acceptance Criterion | Test Location & Verification Evidence | Status |
|---|---|---|:---:|
| **1** | `pytest -q --cov=. --cov-fail-under=80` passes | Measured coverage is **94%** (10,498 statements, 638 missed). 623/625 tests pass. Requires the 2 minor test fixes detailed in §3 to achieve 100% green exit code. | **VERIFIED (Pending 2 Test Fixes)** |
| **2** | Audit chain of 100 entries verifies; tampered entry fails verification | Directly tested in `tests/unit/test_audit_logger.py::test_100_entries_verification_and_tamper_detection`, `tests/test_adversarial_m1.py::test_audit_log_100_concurrent_writes_same_client`, and `tests/unit/test_adversarial_crypto_challenger.py::test_audit_chains_arbitrary_lengths` (parametrized `[10, 100, 200]`). Tampering with entry #50 via raw SQL causes `verify_audit_chain()` to return `(False, tampered_id)`. | **VERIFIED (PASS)** |
| **3** | Trade without approval blocked (REG-003); duplicate submit within 30s rejected | Tested in `tests/unit/test_execution_module.py` (`test_execute_trade_without_approval_blocked_reg003`, `test_execute_trade_30s_double_submit_rejected`), `tests/unit/test_challenger_m4_execution.py::test_stress_concurrent_double_submit_single_winner`, `tests/test_concurrency_stress.py::test_trade_double_submit_prevention_simultaneous`, and `tests/e2e/test_full_flow.py::test_trade_execution_without_approval_fails_reg003`. Unapproved orders raise 403 / `TradeBlocked`, and duplicate orders within 30s raise 409 / `DuplicateTradeError`. | **VERIFIED (PASS)** |
| **4** | Unauthenticated requests get 401; accessing another user's client_id gets 403 | Tested across `tests/unit/test_challenger_m5_security.py` (Suite 1: 401 unauthorized across all routes; Suite 2: 403 tenant isolation across all routes), `tests/unit/test_security.py`, and `tests/e2e/test_full_flow.py` (`test_unauthenticated_requests_get_401`, `test_ownership_enforcement_prevents_cross_client_access`). All 20 protected routes reject missing/invalid tokens with 401, and cross-user `verify_client_ownership` rejects mismatched `client_id` with 403 Forbidden. | **VERIFIED (PASS)** |
| **5** | Output containing "guaranteed" blocked (REG-001); outputs lacking risk disclosure blocked (REG-002) | Tested in `tests/unit/test_compliance_guard.py` (`test_output_text_filter_prohibited_terms`, `test_output_text_filter_missing_disclosures`), `tests/unit/test_challenger_m4_compliance.py` (case-variation stress tests: `gUaRaNtEeD`, `GUARANTEED`, etc.), `tests/unit/test_challenger_m5_orchestrator.py` (adversarial prompt injections), and `tests/e2e/test_full_flow.py` (`test_compliance_blocks_guaranteed_return_output`). Promissory words are stripped/blocked, and mandatory risk disclosure is appended. | **VERIFIED (PASS)** |
| **6** | `python main.py` starts with zero external dependencies, and /docs lists all endpoints | Empirically verified via `TestClient(app)` startup with mock Redis/broker absent. Database initializes SQLite tables, compliance rules are seeded, fixtures are pre-warmed from JSON, `/docs` returns HTTP 200, and `/openapi.json` enumerates all **24 API endpoints** (13 core REST, 8 WebSocket/events, plus auxiliary health/compliance routes). | **VERIFIED (PASS)** |
| **7** | Zero hardcoded mock responses remaining in routes | Inspected all 13 route files in `backend/api/routes/` (`auth.py`, `session.py`, `chat.py`, `profile.py`, `compare.py`, `portfolio.py`, `trade.py`, `audit.py`, `market.py`, `compliance.py`, `ws.py`, `advisory.py`). Zero mock dictionaries or dummy payloads found. All routes dispatch to `AgentContainer` agents, `AsyncSession` database queries, or `PortfolioService`/`AuditLogger`. | **VERIFIED (PASS)** |

---

## 6. Performance Profiling & Test Optimization Opportunities

### 6.1 Slowest 10 Tests Identification
From our profile run of the full test suite (`--durations=10`):

| Duration | Test Case | Reason for Latency |
| :---: | :--- | :--- |
| **37.27s** | `tests/unit/test_adversarial_data_layer_challenger.py::test_pipeline_e2e_trip_circuit_and_fixture_fallback_without_calling_provider` | Executes 5 consecutive failures through `DataPipeline`. Each failure triggers 3 retries with 1s exponential backoff ($1\text{s} + 2\text{s} + 4\text{s} = 7\text{s}$ sleep per failure). $5 \times 7\text{s} = 35\text{s}$ of real wall-clock `asyncio.sleep()`. |
| **7.53s** | `tests/unit/test_data_pipeline.py::test_pipeline_degrades_to_fixture_on_live_error` | Also runs 3 live provider retries with real exponential backoff sleeping 1s, 2s, 4s before degrading to fixture. |
| **5.39s** | `tests/e2e/test_full_flow.py::test_allocation_recommendation_is_compliant_and_explained` | Skfolio mathematical portfolio optimization and CVaR calculations with real asset returns matrix. |
| **4.87s** | `tests/unit/test_challenger_m5_orchestrator.py::test_websocket_rapid_message_burst` | Async broadcast of 50 rapid WebSocket chat messages through memory manager. |
| **2.52s** | `tests/unit/test_product_comparison.py::test_bond_comparison_pipeline_duration_check` | Treasury yield curve fetch and bond duration math. |
| **2.50s** | `tests/unit/test_market_data_agent.py::test_get_etf_holdings_caches_result` | ETF holdings aggregation and cache serialization. |
| **2.44s** | `tests/e2e/test_full_flow.py::test_oversized_single_position_blocked_by_concentration_rule` | Multi-agent flow with compliance check and portfolio snapshot persistence. |
| **2.13s** | `tests/unit/test_cache.py::test_lock_timeout_expiration` | Intentional sleep of 2.1 seconds to test 2.0s lock TTL expiration. |
| **2.12s** | `tests/unit/test_cache.py::test_cache_ttl_expiration` | Intentional sleep of 2.1 seconds to test 2.0s cache key TTL expiration. |
| **2.11s** | `tests/e2e/test_full_flow.py::test_profiling_completes_and_persists` | Full 6-state risk profiler transition test with database persistence. |

### 6.2 Optimization Proposals
1. **Mock or Reduce Retry Sleep in Data Pipeline Tests**:
   - In `test_adversarial_data_layer_challenger.py` and `test_data_pipeline.py`, monkeypatch `asyncio.sleep` or instantiate `DataPipeline` with `initial_backoff=0.001`.
   - **Impact**: Shaves **~45 seconds** off the suite execution time immediately.
2. **Shorten TTL in Cache Tests**:
   - In `test_cache.py`, use a TTL of `0.05s` and sleep `0.06s` instead of a 2.0s TTL with `2.1s` sleep.
   - **Impact**: Shaves **~4 seconds** off `test_cache.py`.
3. **Total Suite Speedup**:
   - Applying these non-intrusive test timing optimizations will reduce total test suite duration from **233s (~4 mins)** to **under 180s (~3 mins)** without altering any test assertions or test coverage.

---

## 7. Recommended Milestone 6 Execution Plan

To complete Milestone 6 verification smoothly and achieve 100% test pass rate with coverage >= 80%:

### Phase 1: Apply the 2 Necessary Test Fixes
1. Edit `backend/tests/unit/test_anchoring.py`:
   - Patch `services.anchoring.settings.dry_run = False` in `test_mainnet_hard_guard_raises_error`.
2. Edit `backend/tests/unit/test_challenger_m4_compliance.py`:
   - Update line 471 in `test_empirical_finding_audit_log_datetime_serialization_failure` from `assert res.audit_entry_id is None` to `assert res.audit_entry_id is not None`.

### Phase 2: Apply Optional Test Speed Optimizations
- Reduce retry sleep in `test_adversarial_data_layer_challenger.py` and `test_data_pipeline.py`.
- Reduce sleep intervals in `test_cache.py`.

### Phase 3: Final Verification Execution
Run the full official command:
```bash
cd backend
python -m pytest -q --cov=. --cov-fail-under=80
```
**Expected Outcome**:
- 625 passed, 0 failed in ~180-230s.
- Total coverage: 94% (well exceeding 80%).
- Exit code: 0.

### Phase 4: Zero-Dependency & OpenAPI Verification
Run standalone verification script:
```bash
python -c "from main import app; from fastapi.testclient import TestClient; c = TestClient(app); assert c.get('/docs').status_code == 200; print('Docs verified 200 OK')"
```

---

## 8. Summary & Conclusion
The Wealth Advisory Agent backend is in an exceptionally robust state. The test architecture thoroughly covers all unit, boundary, integration, and E2E application scenarios. The 94% repository coverage easily satisfies the 80% requirement. Once the two minor test drift issues are addressed by the implementer, Milestone 6 will achieve flawless 100% green verification.

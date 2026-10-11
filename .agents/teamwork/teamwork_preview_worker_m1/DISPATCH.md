# Dispatch: Milestone 1 Worker (Foundation Implementation)
Files owned:
- `backend/requirements.txt`
- `backend/core/config.py`
- `backend/core/security.py`
- `backend/db/models.py`
- `backend/db/database.py`
- `backend/db/init.sql`
- `backend/alembic.ini`
- `backend/db/migrations/`
- `backend/services/cache.py`
- `backend/services/audit_logger.py`
- `backend/services/anchoring.py`
- Unit tests for M1 foundation components in `backend/tests/unit/`

Requirements: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md`
Project Plan: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md`
Explorer handoffs:
- M1_1: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_1\handoff.md`
- M1_2: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_2\handoff.md`
- M1_3: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_3\handoff.md`
## 2026-10-10T12:47:38Z
You are the Worker for Milestone 1 (Foundation) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m1
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Explorer findings:
- Explorer 1: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_1\handoff.md
- Explorer 2: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_2\handoff.md (Note: Explorer 2 generated verified implementations in c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_2\proposed_models.py, proposed_init.sql, proposed_alembic.ini, proposed_env.py, proposed_0001_initial_schema.py)
- Explorer 3: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_3\handoff.md

Write Ownership:
You own exclusively:
- backend/requirements.txt
- backend/core/__init__.py, backend/core/config.py, backend/core/security.py
- backend/db/__init__.py, backend/db/database.py, backend/db/models.py, backend/db/init.sql
- backend/alembic.ini, backend/db/migrations/ (env.py, script.py.mako, versions/0001_initial_schema.py)
- backend/services/__init__.py, backend/services/cache.py, backend/services/audit_logger.py, backend/services/anchoring.py
- backend/tests/unit/ (test_config.py, test_security.py, test_models.py, test_cache.py, test_audit_logger.py, test_anchoring.py)

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Implementation Requirements:
1. Update backend/requirements.txt with all required dependencies and install missing packages (pytest-cov, yfinance, web3, etc.).
2. Implement backend/core/config.py with Pydantic settings, startup validation (strict paper-only Alpaca guard, Sepolia testnet chain ID 11155111 guard, rejecting mainnet chain ID 1).
3. Implement backend/core/security.py with bcrypt password hashing, RFC 7519 JWT create/verify, get_current_user dependency, WebSocket ?token= query auth, and verify_client_ownership tenant isolation (403 Forbidden).
4. Implement backend/db/models.py with all 7 models (DBUser, DBClientProfile with all 11 missing fields and user_id FK, DBPortfolioSnapshot, DBTrade, DBAuditLog, DBBehavioralMemory, DBComplianceRule) and append-only listeners blocking UPDATE/DELETE on DBAuditLog.
5. Create backend/db/init.sql and Alembic migrations (alembic.ini, backend/db/migrations/env.py, versions/) supporting SQLite and Postgres. Run alembic upgrade head to initialize the database with all 12 compliance rules.
6. Implement backend/services/cache.py with transparent Redis and in-memory TTL dictionary store fallback, 30s trade locks, and standardized key formats.
7. Implement backend/services/audit_logger.py with SHA-256 hash chaining, HMAC-SHA256 signature, asyncio serialization lock, log_audit_entry(), and verify_audit_chain().
8. Implement backend/services/anchoring.py with Merkle root computation over audit entry hashes, Sepolia testnet transaction submission, and dry-run mode when unconfigured (refusing mainnet).
9. Implement unit tests in backend/tests/unit/ covering config, security, models, cache, audit logger (verifying 100 entries and detecting tampered row), and anchoring.
10. Execute the test suite using pytest to verify that all M1 unit tests pass.
11. Write your completion report to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m1\handoff.md and notify the orchestrator.

## 2026-10-11T11:10:50Z
You are the Worker for Milestone 6 (E2E Verification & Adversarial Hardening) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m6
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md
E2E Test Architecture: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\TEST_INFRA.md

Explorer findings to read and follow:
- Explorer 1: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m6_1\handoff.md and analysis.md
- Explorer 2: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m6_2\handoff.md and analysis.md

Write Ownership:
You own exclusively:
- backend/tests/unit/test_anchoring.py
- backend/tests/unit/test_challenger_m4_compliance.py
- backend/tests/e2e/test_spec_scenarios.py
- backend/.coveragerc

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Tasks:
1. Fix the 2 test assertions:
   - In `backend/tests/unit/test_anchoring.py`: in `test_mainnet_hard_guard_raises_error` (around line 85-90), patch `services.anchoring.settings.dry_run = False` (or use `patch.object(settings, "dry_run", False)`) so that `anchor_hashes` reaches the `MAINNET_CHAIN_ID` guard and raises `MainnetForbiddenError`.
   - In `backend/tests/unit/test_challenger_m4_compliance.py`: in `test_empirical_finding_audit_log_datetime_serialization_failure` (line ~471), update the assertion to verify that audit logging now succeeds without serialization error:
     `assert res.audit_entry_id is not None` (and optionally verify that the entry exists in `DBAuditLog`).
2. Create `backend/.coveragerc`:
   ```ini
   [run]
   omit =
       tests/*
       alembic/*
   ```
3. Implement `backend/tests/e2e/test_spec_scenarios.py`:
   Implement comprehensive end-to-end test functions covering all 10 Real-World Application Scenarios (S01 to S10 from §8.2 of the plan and `TEST_INFRA.md`):
   - `test_s01_conservative_retiree_onboarding`: Onboards conservative retiree, verifies risk score <= 3.0, category Conservative, profile persisted in DB.
   - `test_s02_product_comparison_for_moderate`: Compares ETFs/Bonds for moderate client, verifies 6-factor composite scoring and volatility alignment.
   - `test_s03_compliance_blocking_suit_001`: Submits high-risk equity recommendation for conservative client, verifies `SUIT-001` triggers BLOCK with violation explanation.
   - `test_s04_concentration_check_conc_001_and_002`: Tests position allocation > 15% (`CONC-001`) and sector allocation > 30% (`CONC-002`), verifying both trigger BLOCK.
   - `test_s05_paper_trade_execution`: Generates trade proposal, verifies paper order submission, fill tracking, trade recorded in `trades` table, and audit entry signed.
   - `test_s06_behavioral_bias_intervention`: Submits emotional/loss-averse messages, verifies `BehavioralBiasAgent` detects loss aversion (>0.6), emits debiasing intervention, updates behavioral memory.
   - `test_s07_audit_chain_100_entries_and_tamper_check`: Generates 100 sequential audit log entries, verifies HMAC-SHA256 chain passes; alters entry #50 in DB, verifies chain verification detects tampering and returns `(False, tampered_id)`.
   - `test_s08_regulatory_guaranteed_language_filter`: Evaluates text with prohibited words ("guaranteed", "risk-free"), verifies `REG-001` replacement; evaluates recommendation lacking risk disclosure, verifies `REG-002` appending.
   - `test_s09_non_discretionary_approval_gate`: Submits trade without client approval (`user_approved=False`), verifies `REG-003` block (403); submits duplicate trade within 30 seconds, verifies 409 Conflict.
   - `test_s10_portfolio_drift_and_rebalance_report`: Creates portfolio with >5% drift, verifies `HealthReportService` generates alerts, calculates health score, compares to 60/40 benchmark, and generates SELL-before-BUY rebalance orders.
4. Run full test verification:
   - `pytest -v tests/e2e/test_spec_scenarios.py`
   - `pytest -v tests/unit/test_anchoring.py tests/unit/test_challenger_m4_compliance.py`
   - `pytest -q --cov=. --cov-fail-under=80`
   Verify that all 635+ tests pass with 100% success rate and total coverage >= 80%.
5. Handoff:
   - Write your completion report to `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m6\handoff.md`.
   - Send completion message back to orchestrator with all test results and coverage metrics.

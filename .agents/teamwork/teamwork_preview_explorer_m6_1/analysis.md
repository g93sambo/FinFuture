# Milestone 6 Exploration Report: E2E Verification & Adversarial Hardening

**Author**: Explorer 1 (`teamwork_preview_explorer_m6_1`)  
**Target Milestone**: Milestone 6 (E2E Verification & Adversarial Hardening)  
**Project Root**: `c:\Users\HP VICTUS\Documents\wealth_agent`  
**Backend Root**: `c:\Users\HP VICTUS\Documents\wealth_agent\backend`  
**Authoritative Specs**: `ORIGINAL_REQUEST.md`, `PROJECT.md`, `TEST_INFRA.md` (Section 3.2 S01-S10)  

---

## 1. Executive Summary

A comprehensive investigation into the test infrastructure and codebase of the Wealth Advisory Agent backend was performed to assess readiness for Milestone 6.
Key results from executing the complete backend test suite:
- **Total Test Count**: 625 test cases across unit, integration, and E2E suites.
- **Pass Rate**: 623 passed, 2 failed in 203.31 seconds.
- **Backend Code Coverage**: **94% total coverage** across all modules (`agents`: 86–95%, `services`: 70–96%, `api`: 64–100%, `core`: 95–100%, `db`: 95–100%).
- **Compliance Rule Coverage**: All 12 regulatory rules (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`) have comprehensive unit and mathematical boundary coverage with both **PASS** and **FAIL** test cases.
- **Primary Gaps Identified**:
  1. **Spec Scenarios S01–S10 E2E Gap**: While existing unit and challenger suites cover the underlying agent mechanics, the current end-to-end suite (`backend/tests/e2e/test_full_flow.py`) only exercises a single generic "35yo Growth Software Engineer" profile and does NOT systematically implement the 10 real-world application scenarios (S01–S10) defined in `TEST_INFRA.md` §3.2 / Spec §8.2.
  2. **Two Isolated Test Failures**:
     - `tests/unit/test_anchoring.py::test_mainnet_hard_guard_raises_error`: Failed because `settings.dry_run=True` returns early before evaluating `w3.eth.chain_id == MAINNET_CHAIN_ID`. Patching `settings.dry_run=False` resolves the test.
     - `tests/unit/test_challenger_m4_compliance.py::TestComplianceRuleBoundaries::test_empirical_finding_audit_log_datetime_serialization_failure`: Originally written as a challenger bug demonstration that `res.audit_entry_id is None`. The bug in `ComplianceGuard` was subsequently fixed in production code, causing the test's stale negative assertion to fail.

---

## 2. Mapping of the 10 Spec Scenarios (S01–S10) Against Existing Test Coverage

| # | Spec Scenario | Requirement & Expected Outcome | Existing Test Coverage | Status & Identified Gaps |
|---|---------------|--------------------------------|------------------------|--------------------------|
| **S01** | **Conservative Retiree Onboarding** | Auth, 6-state Profiler, DB, Audit.<br>User (age 65+, retired, capital preservation, low risk) achieves risk score $\le 3.0$, suitability category `"Conservative"`, intermediate draft cached in Redis/in-memory, final profile persisted in DB, audit log signed. | - Unit: `test_risk_profiler.py::test_scoring_suitability_mapping` (verifies `score=2.0` $\to$ `"Conservative"`).<br>- E2E: `test_full_flow.py::test_profiling_completes_and_persists` (tests only 35yo software engineer, risk 7.0 $\to$ Growth profile). | **PARTIAL / GAP**: No E2E test runs the complete dialogue onboarding for a retiree client via `/api/v1/chat/message` or `/ws/chat`, verifying risk score $\le 3.0$, `"Conservative"` classification, draft caching, and audit logging. |
| **S02** | **Product Comparison for Moderate** | Data Pipeline, Product Compare, Allocation.<br>Moderate investor profile (risk 5.0–6.0). Evaluates ETFs/Bonds with 6-factor composite scoring ($w=0.30, 0.15, 0.20, 0.10, 0.15, 0.10$), filters unsuitable high-volatility products, outputs ranked list with winner and rationale. | - Unit: `test_product_comparison.py::test_factor_weights_sum_to_one`, `test_etf_comparison_pipeline_ranking`, `test_suitability_prefilter_allows_compliant`.<br>- E2E: `test_full_flow.py::test_compare_etfs_ranks_products` (uses Growth profile with SPY/VTI/QQQ). | **PARTIAL / GAP**: E2E route `/api/v1/compare/etfs` is tested with a Growth profile rather than a Moderate profile; volatility alignment and suitability pre-filtering against a moderate risk budget are not verified end-to-end. |
| **S03** | **Compliance Blocking (SUIT-001)** | Compliance Guard, DB Rules, Cryptographic Audit.<br>High-risk equity (or aggressive allocation exceeding risk tolerance + 1.0) proposed to a conservative profile is strictly BLOCKED (`403 Forbidden` / `BLOCK` status) with explanatory violation detail and audit record. | - Unit: `test_compliance_guard.py::test_suit_001_fail` (rec risk 7.5 > profile 5.0+1.0 $\to$ `ComplianceViolationError`).<br>- Unit: `test_challenger_m4_compliance.py::test_suit_001_boundary` (6.000 pass, 6.001 fail).<br>- E2E: `test_full_flow.py` has **zero** tests for SUIT-001. | **UNIT COVERED / E2E GAP**: SUIT-001 has strict unit boundary tests, but is completely absent from the E2E API suite. Need an E2E test submitting a high-risk trade proposal for a conservative client and asserting `403` with `SUIT-001`. |
| **S04** | **Concentration Check (CONC-001 / CONC-002)** | Compliance Guard, Allocation.<br>Position allocation $> 15\%$ (single stock) or sector $> 30\%$ is BLOCKED with structured violation explanation and audit trail. | - Unit: `test_compliance_guard.py::test_conc_001_single_stock_fail`, `test_conc_002_sector_limit_fail`.<br>- Unit: `test_challenger_m4_compliance.py` (15.00% vs 15.01%, 30.00% vs 30.01%).<br>- E2E: `test_full_flow.py::test_oversized_single_position_blocked_by_concentration_rule` (buys 500 AAPL $\to$ 403). | **PARTIAL**: Single-stock concentration is tested via API in `test_full_flow.py`, but does not assert violation detail ("CONC-001"), nor verifies `CONC-002` sector concentration ($> 30\%$) at the E2E layer. |
| **S05** | **Paper Trade Execution** | Execution Module, Alpaca Client / DRY_RUN, 30s Lock, Audit.<br>Pre-trade gates pass, paper order placed, fill tracked, trade persisted in DB `trades` table, and audit entry signed with SHA-256 + HMAC. | - Unit: `test_execution_module.py::test_execute_trade_dry_run_success`.<br>- Unit: `test_challenger_m4_execution.py::test_dry_run_execution_persists_trade_and_audit`.<br>- E2E: `test_full_flow.py::test_approved_trade_fills_updates_portfolio_and_blocks_duplicates`. | **COVERED**: Thoroughly exercised in unit, challenger, and E2E suites. |
| **S06** | **Behavioral Bias Intervention** | Chat WebSocket / REST, Behavioral Bias Agent, Heuristics, Memory.<br>Loss aversion trigger $> 0.60$ detected from panicky user dialogue ("sell everything right now!"), debiasing message returned, `bias_alert` emitted, and event stored in `behavioral_memory` table. | - Unit: `test_behavioral_bias.py` (all 5 biases, 0.60 threshold, DB persistence).<br>- E2E: `test_full_flow.py::test_bias_alert_surfaces_in_chat` (POST `/api/v1/chat/message`). | **PARTIAL**: Tested via REST in `test_full_flow.py`, but WebSocket `/ws/chat` streaming event `bias_alert` is not tested, and DB `behavioral_memory` / profile emotional risk score update is not asserted in E2E. |
| **S07** | **100-Entry Audit Chain & Tamper Check** | Audit Logger, SHA-256 Hash Chaining, HMAC Signatures.<br>100 sequential audit entries verify cleanly (`valid=True`). Tampering a row in the database causes verification to fail (`valid=False`) and identifies the exact corrupted entry ID. | - Unit: `test_audit_logger.py::test_100_entries_verification_and_tamper_detection` (generates 100 entries, tampers entry #50 $\to$ detected).<br>- E2E: `test_full_flow.py::test_audit_chain_verifies_then_detects_tampering` (tests only 3 entries via API). | **UNIT COVERED / E2E GAP**: The 100-entry audit chain is only tested in unit isolation. No E2E test verifies 100 entries via `/api/v1/audit/{client_id}` and `/api/v1/audit/{client_id}/verify` with raw database tampering. |
| **S08** | **Regulatory Guaranteed Language Filter** | Compliance Guard, Output Text Filter (`REG-001` / `REG-002`).<br>Output containing prohibited promissory language ("guaranteed", "risk-free") is blocked/replaced (`REG-001`). Outputs lacking mandatory risk disclosure have disclosures appended (`REG-002`). | - Unit: `test_compliance_guard.py::test_reg_001_and_reg_002_text_output_filter`.<br>- Unit: `test_challenger_m4_compliance.py::TestAdversarialTextFilter` (15 evasive phrases).<br>- E2E: `test_full_flow.py::test_output_gate_blocks_prohibited_language` (calls internal `gate_text`). | **UNIT COVERED / E2E GAP**: E2E test calls `orchestrator.gate_text` directly in Python rather than calling API routes (`/api/v1/chat/message`, `/api/v1/allocation/recommend`, `/api/v1/portfolio/health-report`) and checking response text and audit log. |
| **S09** | **Non-Discretionary Approval Gate** | Execution Module, `REG-003`, `REG-004`, 30s Trade Lock.<br>Trade without explicit approval is blocked (`REG-003`). Trade submitted $> 15$ minutes after approval is blocked (`REG-004`). Second trade within 30s is rejected (`409 Conflict`). | - Unit: `test_compliance_guard.py` & `test_execution_module.py` (REG-003, REG-004, 30s lock).<br>- E2E: `test_full_flow.py::test_trade_without_approval_is_blocked_reg003`, `test_approved_trade_fills_updates_portfolio_and_blocks_duplicates`. | **PARTIAL**: REG-003 and 30s lock are covered in E2E. REG-004 (15-minute stale approval window) is only tested in unit tests, not via `/api/v1/trade/execute`. |
| **S10** | **Portfolio Drift & Rebalance Report** | Health Report, Market Data Agent, Allocation Engine.<br>5%–10% allocation drift detected against target. Benchmark compared. Rebalance trade orders generated (strictly SELL before BUY, dust threshold $\ge \$10.00$). | - Unit: `test_health_report.py` (drift, alerts, health score).<br>- Unit: `test_challenger_m4_compliance.py` (4.9% vs 5.0% vs 5.1% drift, SELL-before-BUY, $10 dust).<br>- E2E: `test_full_flow.py::test_health_report` (only checks 0–100 score and narrative). | **UNIT COVERED / E2E GAP**: `test_full_flow.py` does not test drift detection (e.g., 10% drift), benchmark comparison details, or the generation of rebalance orders via the portfolio health report API endpoint. |

---

## 3. Compliance Rules Coverage Audit (All 12 Rules: PASS & FAIL)

Every one of the 12 compliance rules was audited across the test suite for both PASS and FAIL coverage:

| Rule ID | Rule Name & Threshold | PASS Test Location & Condition | FAIL Test Location & Condition | Status |
|---------|-----------------------|--------------------------------|--------------------------------|:------:|
| **SUIT-001** | Risk Profile Alignment<br>($\text{Risk} \le \text{Tolerance} + 1.0$) | `test_compliance_guard.py:45` (rec 6.0 $\le$ prof 5.0+1.0)<br>`test_challenger_m4_compliance.py:159` (6.000) | `test_compliance_guard.py:56` (rec 7.5 > prof 5.0+1.0)<br>`test_challenger_m4_compliance.py:168` (6.001) | **100% COVERED** |
| **SUIT-002** | Time Horizon Constraint<br>($< 3\text{y} \implies \text{Eq} \le 40\%, \text{Dur} \le 7\text{y}$, no illiquid) | `test_compliance_guard.py:71` (Eq 35%, Dur 4.5y)<br>`test_challenger_m4_compliance.py:180` (Eq 40.0%, Dur 7.0y) | `test_compliance_guard.py:87` (Eq 65%)<br>`test_challenger_m4_compliance.py:186` (Eq 40.01%, Dur 7.001y) | **100% COVERED** |
| **SUIT-003** | Loss Capacity Ceiling<br>($\text{Low} \implies \text{Risk} \le 5.0, \text{Eq} \le 50\%$, no Aggr Growth) | `test_compliance_guard.py:125` (Risk 4.0, Eq 40%)<br>`test_challenger_m4_compliance.py:226` (Risk 5.00, Eq 50.0%) | `test_compliance_guard.py:140` (Risk 6.5, Eq 70%)<br>`test_challenger_m4_compliance.py:231` (Risk 5.01, Eq 50.01%) | **100% COVERED** |
| **CONC-001** | Single Stock Limit<br>($\text{Max Single Position} \le 15.0\%$) | `test_compliance_guard.py:160` (Single stock 12%)<br>`test_challenger_m4_compliance.py:261` (15.00%) | `test_compliance_guard.py:173` (Single stock 22%)<br>`test_challenger_m4_compliance.py:267` (15.01%) | **100% COVERED** |
| **CONC-002** | Sector Concentration Limit<br>($\text{Max Single Sector} \le 30.0\%$) | `test_compliance_guard.py:191` (Tech 25% $\le$ 30%)<br>`test_challenger_m4_compliance.py:305` (30.00%) | `test_compliance_guard.py:204` (Tech 42% > 30%)<br>`test_challenger_m4_compliance.py:311` (30.01%) | **100% COVERED** |
| **CONC-003** | Minimum Asset Class Diversification<br>($\ge 2 \text{ classes with } \ge 5.0\%$; WARN) | `test_compliance_guard.py:222` (Eq 60%, FI 40%)<br>`test_challenger_m4_compliance.py:323` (Eq 80%, FI 20%) | `test_compliance_guard.py:236` (Eq 100% $\to$ WARN)<br>`test_challenger_m4_compliance.py:330` (Eq 98%, FI 2% $\to$ WARN) | **100% COVERED** |
| **REG-001** | Prohibited Promissory Language<br>(Block "guaranteed", "risk-free", etc.) | `test_compliance_guard.py:271` (Clean text)<br>`test_challenger_m4_compliance.py:128` (Disclosed text) | `test_compliance_guard.py:257` ("guaranteed 15%")<br>`test_challenger_m4_compliance.py:91` (15 evasion phrases) | **100% COVERED** |
| **REG-002** | Mandatory Risk Disclosure<br>(Must contain investment risk disclaimer) | `test_compliance_guard.py:271` (Contains disclosure)<br>`test_challenger_m4_compliance.py:128` (3 valid phrases) | `test_compliance_guard.py:264` (Missing disclosure $\to$ appends sanitized disclosure)<br>`test_challenger_m4_compliance.py:114` | **100% COVERED** |
| **REG-003** | Non-Discretionary Confirmation<br>(Explicit `user_approved == True` required) | `test_compliance_guard.py:286` (`user_approved=True`)<br>`test_full_flow.py:157` (Execute trade) | `test_compliance_guard.py:301` (`user_approved=False`)<br>`test_full_flow.py:146` (Blocked 403) | **100% COVERED** |
| **REG-004** | Approval Window Freshness<br>(Trade must execute within 900s / 15m) | `test_compliance_guard.py:320` (5 mins ago)<br>`test_challenger_m4_compliance.py:359` (899s ago) | `test_compliance_guard.py:337` (20 mins ago)<br>`test_challenger_m4_compliance.py:364` (901s ago, None) | **100% COVERED** |
| **AML-001** | Single Transaction Notional Ceiling<br>($> \$100,000$ requires enhanced KYC) | `test_compliance_guard.py:358` (\$18.5k)<br>`test_compliance_guard.py:390` (\$185k + enhanced KYC)<br>`test_challenger_m4_compliance.py:382` (\$100,000.00) | `test_compliance_guard.py:373` (\$185k without enhanced KYC)<br>`test_challenger_m4_compliance.py:390` (\$100,001.00) | **100% COVERED** |
| **AML-002** | Order Velocity Limit<br>(Max 5 orders in rolling 10-minute window) | `test_compliance_guard.py:410` (Recent count 2)<br>`test_challenger_m4_compliance.py:413` (4 orders, 5th passes) | `test_compliance_guard.py:426` (Recent count 5)<br>`test_challenger_m4_compliance.py:422` (5 orders, 6th fails) | **100% COVERED** |

---

## 4. Root Cause Analysis of the 2 Failing Tests

### 4.1 `tests/unit/test_anchoring.py::test_mainnet_hard_guard_raises_error`
- **Error Output**: `Failed: DID NOT RAISE MainnetForbiddenError`
- **Location**: `tests/unit/test_anchoring.py:89`
- **Root Cause**:
  In `services/anchoring.py` lines 152–153:
  ```python
  if settings.dry_run or not self._is_configured():
      return self._simulate_anchor(merkle_root, len(leaf_hashes), now)
  ```
  `settings.dry_run` is `True` by default in `core/config.py`. The unit test patched `service._is_configured` to return `True`, but did not override `settings.dry_run`. As a result, the method took the dry-run branch before ever calling `w3 = Web3(...)` or validating `w3.eth.chain_id == MAINNET_CHAIN_ID`.
- **Remediation**:
  In `tests/unit/test_anchoring.py`, patch `settings.dry_run`:
  ```python
  with patch("services.anchoring.settings.dry_run", False), \
       patch("services.anchoring.Web3", return_value=mock_w3), \
       patch.object(service, "_is_configured", return_value=True):
      with pytest.raises(MainnetForbiddenError) as exc_info:
          await service.anchor_hashes(["c" * 64])
  ```

### 4.2 `tests/unit/test_challenger_m4_compliance.py::TestComplianceRuleBoundaries::test_empirical_finding_audit_log_datetime_serialization_failure`
- **Error Output**: `AssertionError: Bug: Audit log entry failed to persist due to un-serialized datetime in details. assert '64d50c57-bc92-4b05-8556-f7bdf1373177' is None`
- **Location**: `tests/unit/test_challenger_m4_compliance.py:471`
- **Root Cause**:
  This test was originally created as an empirical bug discovery by Challenger 1 to document that passing a `datetime` object in `trade['user_approved_at']` caused SQLAlchemy JSON serialization to crash and fail to write an audit entry (`res.audit_entry_id is None`).
  The bug was **subsequently fixed** in `agents/compliance_guard.py` by ensuring all `datetime` values are converted to ISO strings before recording audit logs.
  Because the bug is now fixed, `res.audit_entry_id` successfully returns the generated UUID (`'64d50c57-bc92-4b05-8556-f7bdf1373177'`), which causes the test's stale negative assertion (`assert res.audit_entry_id is None`) to fail.
- **Remediation**:
  Update the assertion to verify that the bug is resolved and the audit log entry is successfully created:
  ```python
  assert res.audit_entry_id is not None, "Audit log entry must successfully persist with serialized datetime"
  ```

---

## 5. Specification for Dedicated E2E Test Suite (`backend/tests/e2e/test_spec_scenarios.py`)

To achieve complete, unambiguous compliance with Section 3.2 of `TEST_INFRA.md` and Section 8.2 of the technical specification, a dedicated test file `backend/tests/e2e/test_spec_scenarios.py` must be added. Each test must be completely isolated, authentic (zero mocks in domain routes), and exercise the specific scenario requirements:

```python
# Architecture Outline for backend/tests/e2e/test_spec_scenarios.py

import pytest
from starlette.testclient import TestClient
from main import app

# S01: Conservative Retiree Onboarding
def test_scenario_s01_conservative_retiree_onboarding(client):
    """
    Onboards a 68-year-old retired client with capital preservation goal and low risk tolerance (2/10).
    Verifies:
    1. Intermediate profile drafts persist in cache.
    2. Final profile has risk_tolerance_score <= 3.0 and suitability_category == 'Conservative'.
    3. Profile is saved in DB and KYC is verified.
    4. Cryptographic audit log entry is signed and chained.
    """

# S02: Product Comparison for Moderate
def test_scenario_s02_product_comparison_for_moderate(client):
    """
    Onboards a 42-year-old moderate client (score 5.5).
    Calls POST /api/v1/compare/etfs with ['SPY', 'VTI', 'BND', 'QQQ'].
    Verifies:
    1. Six-factor composite scores computed for each product.
    2. Products ranked with winner identified and rationale generated.
    3. Unsuitable high-volatility products filtered per suitability criteria.
    """

# S03: Compliance Blocking (SUIT-001)
def test_scenario_s03_compliance_blocking_suit001(client):
    """
    Attempts to propose/execute a high-risk trade (QQQ / 3x leveraged ETF) for a Conservative profile.
    Verifies:
    1. Returns HTTP 403 Forbidden.
    2. Response detail contains 'SUIT-001' violation code.
    3. AUDIT_LOG records compliance check failure.
    """

# S04: Concentration Check (CONC-001 & CONC-002)
def test_scenario_s04_concentration_check_conc001_and_conc002(client):
    """
    Attempts to allocate > 15% to a single equity (AAPL) or > 30% to a single sector (Tech).
    Verifies:
    1. Trade is BLOCKED with HTTP 403.
    2. Response detail specifies 'CONC-001' (single stock) or 'CONC-002' (sector).
    3. Audit log reflects blocked transaction.
    """

# S05: Paper Trade Execution
def test_scenario_s05_paper_trade_execution(client):
    """
    Proposes trade for compliant BND, approves via user_approved=True.
    Verifies:
    1. Trade status is 'FILLED'.
    2. DBTrade record is persisted in database.
    3. Portfolio position is updated.
    4. Audit log entry is signed and SHA-256 chained.
    """

# S06: Behavioral Bias Intervention
def test_scenario_s06_behavioral_bias_intervention(client):
    """
    Sends panicky message ('The market crashed, I am terrified, sell everything!') via REST and WebSocket.
    Verifies:
    1. Loss aversion detected with confidence > 0.60.
    2. bias_alert event emitted in response stream.
    3. Calming, debiasing intervention returned in dialogue.
    4. Event stored in behavioral_memory table.
    """

# S07: 100-Entry Audit Chain & Tamper Check
def test_scenario_s07_100_entry_audit_chain_and_tamper_check(client):
    """
    Generates 100 sequential audit events for a client.
    Verifies:
    1. GET /api/v1/audit/{client_id}/verify returns valid=True, first_invalid_entry=None.
    2. Modifies row #50 directly via raw sqlite3 query.
    3. GET /api/v1/audit/{client_id}/verify returns valid=False and first_invalid_entry == row #50 ID.
    """

# S08: Regulatory Guaranteed Language Filter
def test_scenario_s08_regulatory_language_filter_reg001_and_reg002(client):
    """
    Triggers advice generation and checks output text filtering.
    Verifies:
    1. Promissory words ('guaranteed', 'risk-free') are NEVER present in output (REG-001).
    2. Mandatory risk disclosure is ALWAYS present in recommendations (REG-002).
    3. OUTPUT_FILTERED audit log is recorded when filtering occurs.
    """

# S09: Non-Discretionary Approval Gate
def test_scenario_s09_nondiscretionary_approval_gate_reg003_and_reg004(client):
    """
    Verifies:
    1. Unapproved trade (user_approved=False) blocked with REG-003 (HTTP 403).
    2. Duplicate submission within 30s rejected with HTTP 409 Conflict.
    3. Stale proposal (> 15 minutes) rejected with REG-004.
    """

# S10: Portfolio Drift & Rebalance Report
def test_scenario_s10_portfolio_drift_and_rebalance_report(client):
    """
    Sets up a portfolio snapshot with > 10% drift from 60/40 target.
    Calls POST /api/v1/portfolio/health-report.
    Verifies:
    1. 10% drift detected and reported.
    2. Benchmark comparison computed.
    3. Rebalance orders generated strictly with SELL orders preceding BUY orders.
    4. Small orders under $10 dust threshold are suppressed.
    """
```

---

## 6. Coverage Gate Strategy (`--cov-fail-under=80`)

- Baseline full-suite coverage when excluding `tests/` from measured scope: **94%**.
- Current module coverage breakdown:
  - `core/`: 95–100%
  - `db/`: 95–100%
  - `agents/`: 86–95%
  - `services/`: 70–96% (anchoring at 70%, cache at 72%, health_report at 95%, data_pipeline at 96%, audit_logger at 93%)
  - `api/routes/`: 64–100% (auth at 64%, trade at 68%, compare at 79%, portfolio at 76%, ws at 78%)
- By implementing `backend/tests/e2e/test_spec_scenarios.py`, coverage of `api/routes/trade.py`, `api/routes/auth.py`, `api/routes/compare.py`, and `api/routes/portfolio.py` will increase further, cementing overall coverage well above the required 80% threshold.
- In `pytest.ini` or command invocation, use:
  ```bash
  pytest -q --cov=agents --cov=services --cov=api --cov=core --cov=db --cov-fail-under=80
  ```
  or configure `omit = tests/*` in `.coveragerc` so that test files are not counted as un-executed application code.

---

## 7. Actionable Recommendations for Milestone 6 Implementer

1. **Fix the 2 Unit Test Defects**:
   - `tests/unit/test_anchoring.py`: Patch `settings.dry_run = False` in `test_mainnet_hard_guard_raises_error`.
   - `tests/unit/test_challenger_m4_compliance.py`: Update line 471 assertion to `assert res.audit_entry_id is not None` to reflect the fixed datetime serialization.
2. **Add `.coveragerc`**:
   - Create `backend/.coveragerc` with:
     ```ini
     [run]
     omit =
         tests/*
         */tests/*
     ```
   - This ensures `pytest -q --cov=. --cov-fail-under=80` measures only genuine application code and immediately exceeds 90% coverage.
3. **Implement `backend/tests/e2e/test_spec_scenarios.py`**:
   - Implement the 10 scenario tests (S01 to S10) adhering to the structure outlined in Section 5.
   - Run `pytest -v tests/e2e/test_spec_scenarios.py` to confirm 100% pass rate.
4. **Final Gate Verification**:
   - Run `pytest -q --cov=. --cov-fail-under=80` and verify all 635+ tests pass with zero failures.

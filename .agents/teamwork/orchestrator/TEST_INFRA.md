# E2E Test Infra: Wealth Advisory Agent Backend

## Test Philosophy
- **Opaque-box & Requirement-driven**: Derived directly from `ORIGINAL_REQUEST.md` and the v2.0 specification (`generate_tech_doc.py` section 8.2), independent of internal implementation tricks.
- **Progressive Testability**: Tier 1 tests verify fundamental units and contracts; Tier 2 tests boundary conditions; Tier 3 tests cross-feature combinations; Tier 4 validates realistic real-world multi-step workflows.
- **Coverage Standard**: Strict requirement `pytest -q --cov=. --cov-fail-under=80`. Every compliance rule must have dedicated pass and fail test cases.

## Feature Inventory Coverage Matrix
| # | Feature | Requirement Source | Tier 1 (Unit) | Tier 2 (Boundary) | Tier 3 (Cross) | Tier 4 (Scenario) |
|---|---------|-------------------|:-------------:|:-----------------:|:--------------:|:-----------------:|
| 1 | Config & Paper Guard | R1, Acceptance Criteria | 5 | 5 | ✓ | S05 |
| 2 | Auth & Ownership | R1, Acceptance Criteria | 5 | 5 | ✓ | S01, S09 |
| 3 | DB Models & Append-Only | R1, Acceptance Criteria | 5 | 5 | ✓ | S07 |
| 4 | DB Migrations & Seeds | R1 | 5 | 5 | ✓ | S01 |
| 5 | Cache & 30s Lock | R1, Acceptance Criteria | 5 | 5 | ✓ | S05, S09 |
| 6 | Hash-Chain Audit & Verify | R1, Acceptance Criteria | 5 | 5 | ✓ | S07 |
| 7 | Sepolia Anchoring | R1 | 5 | 5 | ✓ | S07 |
| 8 | Resilient Data Pipeline | R2 | 5 | 5 | ✓ | S02, S10 |
| 9 | Providers & Fixtures | R2 | 5 | 5 | ✓ | S02 |
| 10 | Market Data Agent | R2 | 5 | 5 | ✓ | S02, S10 |
| 11 | Risk Profiler Machine | R3, Scenario 1 | 5 | 5 | ✓ | S01 |
| 12 | Behavioral Bias & Memory | R3, Scenario 6 | 5 | 5 | ✓ | S06 |
| 13 | 6-Factor Product Scoring | R3, Scenario 2 | 5 | 5 | ✓ | S02 |
| 14 | Allocation & Frontier | R3, Scenario 2, 10 | 5 | 5 | ✓ | S02, S10 |
| 15 | 12 Compliance Rules | R3, Scenario 3, 4 | 24 (pass+fail) | 12 | ✓ | S03, S04 |
| 16 | Output Filter (Guaranteed/Risk) | R3, Scenario 8, Acceptance | 5 | 5 | ✓ | S08 |
| 17 | Execution Module (Lock/KYC/Approval)| R3, Scenario 5, 9, Acceptance | 5 | 5 | ✓ | S05, S09 |
| 18 | Health & Drift Report | R3, Scenario 10 | 5 | 5 | ✓ | S10 |
| 19 | Orchestrator Agent & Workflow | R3 | 5 | 5 | ✓ | S01-S10 |
| 20 | 13 REST API Routers | R4, Acceptance Criteria | 13 | 13 | ✓ | S01-S10 |
| 21 | WebSocket Chat Events | R4 | 8 | 8 | ✓ | S01, S06 |
| 22 | Lifespan & Zero Mock | R4, Acceptance Criteria | 5 | 5 | ✓ | S01 |

## Real-World Application Scenarios (Tier 4 / Spec Section 8.2)
| # | Scenario | Features Exercised | Expected Outcome |
|---|----------|-------------------|------------------|
| S01 | Conservative Retiree Onboarding | Auth, Profiler, DB, Audit | Risk score <= 3.0, conservative category, draft persisted |
| S02 | Product Comparison for Moderate | Data Pipeline, Product Compare, Allocation | ETFs aligned with profile volatility, 6-factor ranked scores |
| S03 | Compliance Blocking (SUIT-001) | Compliance Guard, DB Rules, Audit | High-risk equity proposed to conservative profile is BLOCKED |
| S04 | Concentration Check (CONC-001) | Compliance Guard, Allocation | Position allocation > 30% is BLOCKED with violation explanation |
| S05 | Paper Trade Execution | Execution Module, Alpaca Client, 30s Lock, Audit | Paper order placed, fill tracked, trade stored, audit signed |
| S06 | Behavioral Bias Intervention | Chat WS, Bias Agent, Heuristics, Memory | Loss aversion trigger detected (>0.6), debiasing message sent |
| S07 | 100-Entry Audit Chain & Tamper Check | Audit Logger, SHA-256 Chain, HMAC | 100 entries verify OK; tampered database row fails verification |
| S08 | Regulatory Guaranteed Language Filter | Compliance Guard, Text Filter (REG-001/002) | Output with 'guaranteed' is blocked; lack of risk disclosure blocked |
| S09 | Non-Discretionary Approval Gate | Execution Module, REG-003, REG-004 | Trade without approval blocked; 30s duplicate submit rejected |
| S10 | Portfolio Drift & Rebalance Report | Health Report, Market Data, Allocation | 10% drift detected, benchmark compared, rebalance trades generated |

## Test Architecture
- Test Runner: `pytest -q --cov=. --cov-fail-under=80`
- Test Root: `backend/tests/`
  - `conftest.py`: Async client fixtures, SQLite in-memory DB fixture, mock provider fixtures, test JWT tokens
  - `fixtures/`: Offline JSON fixtures for market quotes, yield curve, macro indicators, Alpaca responses
  - `unit/`: Isolated component tests
  - `integration/`: Multi-service database and pipeline tests
  - `e2e/`: Full API and WebSocket scenarios covering S01-S10

## Coverage Thresholds
- Unit Tests: >= 115 test cases
- Boundary / Corner Cases: >= 115 test cases
- Cross-Feature Pairwise Tests: >= 23 test cases
- Application / E2E Scenarios: 10 spec scenarios (S01 to S10)
- Total test count: >= 260 test cases
- Code coverage: >= 80% with `--cov-fail-under=80`

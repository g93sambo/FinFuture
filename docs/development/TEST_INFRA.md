# TEST_INFRA.md: Dual-Track E2E Testing Infrastructure (R1–R6)

## 1. Executive Summary & Dual-Track Philosophy

This document specifies the testing infrastructure, methodology, and execution framework for the **Wealth Advisory Agent System Evolution (R1 through R6)**.

The testing architecture follows a **Dual-Track Engineering** model:
- **Track 1 (Implementation Track)**: Progresses sequentially across Milestones M0 through M6 (Baseline Stabilization, Centralized Tool Registry, Web Intel & Filings, Quantitative Engine, Research DAG & Specialists, Streaming Telemetry, and Acceptance).
- **Track 2 (Test Engineering Track)**: Establishes an independent, requirement-driven **opaque-box** test suite organized into 4 hierarchical tiers located under `tests/e2e_research/`.

Every test in this suite is derived strictly from authoritative specifications:
1. `ORIGINAL_REQUEST.md` (Requirements R1 through R6 and Acceptance Criteria)
2. `PROJECT.md` (Architecture, 42-Feature Inventory, and Interface Contracts)

```
+-----------------------------------------------------------------------------------+
|                           Dual-Track Testing Architecture                         |
+-----------------------------------------------------------------------------------+
| Track 1 (Implementation):  [M0] -> [M1] -> [M2] -> [M3] -> [M4] -> [M5] -> [M6]   |
|                               ^      ^      ^      ^      ^      ^        |       |
|                               |      |      |      |      |      |        v       |
| Track 2 (Test Suite):      +-------------------------------------------+  All     |
|                            | 4-Tier Opaque-Box Suite (tests/e2e_research)|  42     |
|                            |  Tier 1: Smoke / Contracts & Interfaces   |  Features|
|                            |  Tier 2: Functional Core & Determinism    |  Verified|
|                            |  Tier 3: DAG Workflows, Roles & Memory    |  100%    |
|                            |  Tier 4: E2E Scenarios, Streams & Reports |  Green   |
|                            +-------------------------------------------+          |
+-----------------------------------------------------------------------------------+
```

---

## 2. Four-Tier Test Suite Hierarchy

The test suite is structured into four distinct, progressive tiers:

### Tier 1: Smoke, Contracts & Interface Boundaries (`test_tier1_contracts.py`)
- **Objective**: Validate all structural interfaces, Pydantic schemas, role-based access control (RBAC) boundaries, and typing contracts across all modules before functional execution.
- **Scope**:
  - `BaseTool` abstract base class contract and Pydantic v2 `args_schema` validation.
  - `ToolRegistry` registration, role authorization filters, and unknown tool rejection.
  - `ResearchTask`, `TaskGraphState`, and `SubtaskResult` typed inter-node schemas.
  - `EvidenceItem` schema and verification status enums (`VERIFIED`, `CONTRADICTED`, `UNCONFIRMED`).
  - Quantitative engine function signatures, parameter contracts, and return structures.
  - Telemetry event payload schemas (`research_milestone`, event types, timestamps).
- **Failure Impact**: Blocks higher tiers if schemas or interface contracts break.

### Tier 2: Functional Core & Mathematical Determinism (`test_tier2_functional_core.py`)
- **Objective**: Guarantee 100% mathematical determinism and algorithmic correctness for all analytical engines, filings parsers, and data services. Zero arithmetic is ever delegated to non-deterministic LLM generations.
- **Scope**:
  - **Hurdle Rate Bisection Solver**: Solves required pre-tax return ($R_{\text{req}} = 34.44\%$) for $\$10\text{M} \to \$100\text{M}$ with $\$500\text{k}/\text{yr}$ inflation-adjusted withdrawals.
  - **10-Year Cash Flow Recursion**: Full annual audited accounting reconciliation of deposits, gross returns, advisory fees (1%), tax drag (15%), and net flows.
  - **Student-t Fat-Tail Monte Carlo**: 10,000-path simulation with $\nu=5$ degrees of freedom, Cholesky correlation matrix, annual rebalancing, and reproducible seed (`seed=42`).
  - **Multi-Factor Stress Testing**: Deterministic crash modeling (2008 GFC $-42\%$, 2022 Stagflation $-18\%$, Sequence-of-Returns 2-year consecutive drawdown $-48\%$, and exact recovery CAGR math).
  - **Deterministic DCF Valuation**: Unlevered Free Cash Flow (FCF) projections, WACC discounting, Gordon Growth terminal value, and per-share equity valuation.
  - **Risk Metrics**: Parametric and Historical Value at Risk (VaR 95%/99%), Conditional VaR (CVaR / Expected Shortfall), and annualized Sharpe ratio.
  - **5-Pillar Hurdle Scoring**: Quantitative score (0-100) with binary YES/NO decision gating.
  - **SEC EDGAR Facts Provider & 10-K Narrative Parser**: Parsing XBRL company facts and HTML 10-K narrative items (Item 1A Risk Factors, Item 7 MD&A, Item 8 Financial Statements).
  - **Tri-Layer Prompt Injection Sanitizer**: HTML tag stripping, XML `<untrusted_external_content>` isolation, and regex heuristic screening.
  - **Content Deduplication & Timestamp Stratification**: SHA-256 fingerprinting and temporal ordering.
  - **Evidence Ledger Service & Clickable Citations**: Adding claims, recording contradictions, calculating confidence scores, and formatting clickable markdown source citations.

### Tier 3: Workflow, Integration & DAG Task Graph (`test_tier3_dag_workflows.py`)
- **Objective**: Verify multi-agent task graph decomposition, dynamic dependency scheduling, persona execution, tenant memory isolation, self-verification, and compliance gating.
- **Scope**:
  - **Task Graph DAG Engine**: Topological sorting, dependency resolution, parallel branch execution, and cycle detection.
  - **8 Specialist Analyst Roles**: Execution behavior and output schema conformance for:
    1. Financial Analyst (fundamentals, ratios, capital structure)
    2. Macro & Market Analyst (rates, yield curves, macro regimes)
    3. Investment Research Analyst (business moat, catalysts, industry)
    4. Quantitative Analyst (Monte Carlo, factor models, hurdle math)
    5. Intelligence / Web Analyst (SEC filings, live news, filings facts)
    6. Risk & Devil's Advocate (bear cases, downside catalysts, adversarial review)
    7. Personalized Advisory (client risk profile alignment, tax gating)
    8. Compliance Guard Node (regulatory oversight, disclosure gating)
  - **Execution & Tool-Call Budgets**: Per-task and graph-level timeout enforcement and maximum tool-call limits.
  - **Tenant-Isolated Memory**: Multi-tenant database and cache isolation ensuring Client A cannot access Client B's session or profile memory.
  - **Memory Freshness TTL Invalidation**: Stratified TTL hierarchy invalidating stale market (15 min), macro (24 hr), and research data.
  - **Bounded Self-Verification Loop**: Max 2-iteration self-correction loop detecting mathematical discrepancies or missing citations before finalizing output.
  - **Compliance Guard Engine**: Full 12-rule dynamic catalog (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`), guaranteed return blocking (`REG-001`), and risk disclosure enforcement (`REG-002`).
  - **Non-Discretionary Paper Trading Guard**: Mandatory user confirmation, 30s double-submit idempotency lock, and strict paper-only execution (`paper=True`).

### Tier 4: End-to-End User Scenarios & Telemetry Stream (`test_tier4_e2e_scenarios.py`)
- **Objective**: Validate complete real-world user research journeys, live telemetry streaming over WebSockets/SSE, institutional markdown report rendering, client UI event contracts, cryptographic audit trails, and Sepolia Merkle anchoring.
- **Scope**:
  - **Full E2E Research Workflows**:
    - Scenario A: Institutional $\$10\text{M} \to \$100\text{M}$ Moonshot vs. Endowment Analysis (complete decomposition, research, modeling, devil's advocate challenge, and final fiduciary rejection of moonshot in favor of all-weather endowment).
    - Scenario B: Mega-Cap Tech Deep Dive (SEC EDGAR extraction, DCF valuation, stress testing, and evidence synthesis).
  - **Streaming Telemetry Events**: Async event emission over WebSocket `/ws/chat` and SSE `/api/v1/research/stream`:
    - `research_started`
    - `task_graph_generated`
    - `analyst_dispatched`
    - `tool_call_started`
    - `evidence_logged`
    - `model_computed`
    - `devils_advocate_review`
    - `self_verification_status`
    - `report_chunk`
  - **Institutional Markdown Report Builder**: Unabridged tables (cash flow schedules, portfolio comparisons, stress tests), structured Evidence Ledger section, and clickable citation footer with zero truncated placeholders.
  - **Client UI Telemetry Contract**: Event schema validation matching `backend/chat_client.html` rendering requirements.
  - **Tool Execution Adapters**: Bounded retries with exponential backoff and jitter, circuit breaker state machine (`CLOSED` -> `OPEN` -> `HALF_OPEN`), and execution provenance logging.
  - **Cryptographic Audit Trail & Sepolia Merkle Anchoring**: SHA-256 hash-chained append-only log verification, tamper detection, and dry-run Merkle root anchoring.
  - **Baseline Stabilization & Regression**: Verification that baseline multi-agent capabilities remain intact.

---

## 3. Comprehensive 42-Feature Coverage Matrix

Every single feature defined in `PROJECT.md` is mapped to an authoritative test tier, test class, and verification method:

| # | Feature Name | Milestone | Test Tier | Test Class & Method | Authoritative Requirement |
|---|--------------|-----------|-----------|---------------------|---------------------------|
| 1 | Baseline Test Stabilization | M0 | Tier 4 | `TestE2EScenarios.test_baseline_orchestrator_stabilization` | M0 clean 644/644 baseline |
| 2 | Tool Base & Pydantic Schemas | M1 | Tier 1 | `TestContractInterfaces.test_base_tool_pydantic_contract` | R3 Pydantic v2 argument schemas |
| 3 | Centralized Tool Registry | M1 | Tier 1 | `TestContractInterfaces.test_tool_registry_contract` | R3 Centralized tool registry singleton |
| 4 | Tool Execution Adapters | M1 | Tier 4 | `TestE2EScenarios.test_tool_execution_adapter_circuit_breaker` | R3 Retries, circuit breakers, provenance |
| 5 | Core Tools Migration | M1 | Tier 4 | `TestE2EScenarios.test_core_tools_migration_and_execution` | R3 Core market, macro, treasury tools |
| 6 | SEC EDGAR Facts Provider | M2 | Tier 2 | `TestFunctionalCore.test_sec_edgar_facts_provider` | R2 Primary filing XBRL fact extraction |
| 7 | SEC Narrative Filing Extractor | M2 | Tier 2 | `TestFunctionalCore.test_sec_narrative_filing_extractor` | R2 10-K/10-Q/8-K narrative parsing (Items 1A, 7) |
| 8 | Multi-Source Web Search Adapter | M2 | Tier 2 | `TestFunctionalCore.test_web_search_adapter_formulation` | R2 Multi-source search & query formulation |
| 9 | Untrusted Content Sanitizer | M2 | Tier 2 | `TestFunctionalCore.test_untrusted_content_sanitizer_trilayer` | R2 Tri-layer prompt injection defense |
| 10 | Content Deduplication & Hash | M2 | Tier 1 | `TestContractInterfaces.test_content_hash_deduplication_contract` | R2 SHA-256 deduplication & timestamps |
| 11 | Evidence Ledger Service | M2 | Tier 2 | `TestFunctionalCore.test_evidence_ledger_lifecycle` | R2/R4 Hypotheses, supporting/contradicting claims |
| 12 | Clickable Citation Generator | M2 | Tier 2 | `TestFunctionalCore.test_clickable_citation_generator` | R2 Clickable source URLs with publisher metadata |
| 13 | Student-t Monte Carlo Simulation | M3 | Tier 2 | `TestFunctionalCore.test_student_t_monte_carlo_reproducibility` | R4 10k-path Student-t ($\nu=5$) simulation |
| 14 | Hurdle Rate Bisection Solver | M3 | Tier 2 | `TestFunctionalCore.test_hurdle_rate_bisection_solver` | R4 $R_{\text{req}}=34.44\%$ numerical bisection |
| 15 | 10-Year Cash Flow Schedules | M3 | Tier 2 | `TestFunctionalCore.test_10year_cash_flow_accounting_schedule` | R4 10-year recursion with withdrawals & fees |
| 16 | Multi-Factor Stress Testing | M3 | Tier 2 | `TestFunctionalCore.test_multi_factor_stress_testing_math` | R4 2008 GFC, 2022 Stagflation, Sequence-of-returns |
| 17 | Deterministic DCF Valuation | M3 | Tier 2 | `TestFunctionalCore.test_deterministic_dcf_valuation` | R4 Unlevered FCF DCF, WACC discounting |
| 18 | VaR, CVaR & Sharpe Metrics | M3 | Tier 2 | `TestFunctionalCore.test_var_cvar_sharpe_metrics` | R4 Parametric/Historical VaR, CVaR, Sharpe |
| 19 | 5-Pillar Hurdle Scoring | M3 | Tier 2 | `TestFunctionalCore.test_5pillar_hurdle_scoring_rule` | R4 0-100 hurdle score with binary decision |
| 20 | DAG Task Graph Engine | M4 | Tier 3 | `TestDAGWorkflows.test_dag_task_graph_resolution_and_cycles` | R1 Declarative DAG with dynamic resolution |
| 21 | Financial Analyst Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_financial_analyst` | R1 Financial statements, ratios, capital structure |
| 22 | Macro & Market Analyst Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_macro_analyst` | R1 Interest rates, yield curves, macro regimes |
| 23 | Investment Research Analyst Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_investment_research` | R1 Business model, competitive moat, catalysts |
| 24 | Quantitative Analyst Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_quantitative_analyst` | R1 Quantitative models & factor stress tests |
| 25 | Intelligence / Web Analyst Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_intelligence_analyst` | R1 Live news, filings facts, prospectuses |
| 26 | Risk & Devil's Advocate Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_devils_advocate` | R1 Adversarial review & downside catalysts |
| 27 | Personalized Advisory Role | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_personalized_advisory` | R1 Tailoring findings to profile & constraints |
| 28 | Compliance Guard Node | M4 | Tier 3 | `TestDAGWorkflows.test_analyst_role_compliance_guard_node` | R1/R5 Inviolable regulatory oversight node |
| 29 | Typed Inter-Node Contracts | M4 | Tier 1 | `TestContractInterfaces.test_typed_internode_task_contracts` | R1 Pydantic schemas for tasks, inputs, outputs |
| 30 | Execution & Tool-Call Budgets | M4 | Tier 3 | `TestDAGWorkflows.test_execution_and_tool_call_budgets` | R1 Configurable timeouts & tool-call limits |
| 31 | Tenant-Isolated Memory | M4 | Tier 3 | `TestDAGWorkflows.test_tenant_isolated_memory` | R5 User-scoped memory isolation |
| 32 | Memory Freshness TTL Invalidation | M4 | Tier 3 | `TestDAGWorkflows.test_memory_freshness_ttl_invalidation` | R5 Stratified TTL cache invalidation |
| 33 | Bounded Self-Verification Loop | M4 | Tier 3 | `TestDAGWorkflows.test_bounded_self_verification_loop` | R5 Max 2 iterations verifying calculations |
| 34 | Non-Discretionary Paper Trading Guard | M4 | Tier 3 | `TestDAGWorkflows.test_non_discretionary_paper_trading_guard` | R5 Mandatory confirmation, 30s lock, paper-only |
| 35 | Streaming WebSocket Telemetry | M5 | Tier 4 | `TestE2EScenarios.test_streaming_websocket_telemetry_flow` | R6 Real-time research milestones to /ws/chat |
| 36 | SSE Research Streaming Route | M5 | Tier 4 | `TestE2EScenarios.test_sse_research_streaming_route` | R6 Server-Sent Events endpoint /api/v1/research/stream |
| 37 | Institutional Markdown Report Builder | M5 | Tier 4 | `TestE2EScenarios.test_institutional_markdown_report_builder` | R6 Unabridged tables, evidence ledgers, citations |
| 38 | Client UI Telemetry Rendering | M5 | Tier 4 | `TestE2EScenarios.test_client_ui_telemetry_event_contract` | R6 chat_client.html rendering contract |
| 39 | Audit Logging & Merkle Anchoring | M5 | Tier 4 | `TestE2EScenarios.test_audit_logging_and_merkle_anchoring` | R6 SHA-256 hash chaining & Sepolia anchoring |
| 40 | Opaque-Box E2E Test Suite (Tiers 1-4) | M6 | All | `tests/e2e_research/` full suite execution | Survey (Dual Track) 4-tier requirement suite |
| 41 | Adversarial Coverage Hardening (Tier 5) | M6 | Tier 2/3 | `tests/adversarial/` stress & injection attacks | Survey (Dual Track) Adversarial hardening |
| 42 | Full System Verification & Acceptance | M6 | Tier 4 | `TestE2EScenarios.test_full_system_acceptance_criteria` | Survey Complete acceptance criteria pass |

---

## 4. Test Infrastructure & Fixture Strategy

### Hermetic Test Environment Setup
Tests run isolated from real network and external broker APIs:
- **Database**: In-memory SQLite with SQLAlchemy AsyncSession (`sqlite+aiosqlite:///:memory:`).
- **Cache & Locks**: In-memory fallback simulated via unreachable Redis port (`redis://127.0.0.1:1/0`), verifying the resilience of `CacheService`.
- **Anchoring**: `DRY_RUN=true` to guarantee no on-chain Sepolia transactions are submitted.
- **LLM & Search APIs**: Hermetic mocking with recorded deterministic fixtures matching exact real-world response schemas.
- **Deterministic Seeding**: `np.random.seed(42)` and `random.seed(42)` across all stochastic financial simulations to ensure 100% bitwise reproducibility.

### Directory Layout
```
tests/e2e_research/
├── __init__.py
├── conftest.py                      # Global fixtures, test DB, mock data, and environment setup
├── test_tier1_contracts.py          # Tier 1: Schemas, interfaces, and typing contracts
├── test_tier2_functional_core.py    # Tier 2: Mathematical determinism & core services
├── test_tier3_dag_workflows.py      # Tier 3: TaskGraph, 8 analyst roles, memory & compliance
└── test_tier4_e2e_scenarios.py      # Tier 4: E2E inquiry journeys, streaming & reports
```

### Progressive Testability Architecture
To support continuous testing during incremental milestone development:
1. Every test file is fully valid Python and discovers cleanly under pytest without collection errors.
2. Implemented modules (e.g. `financial_engineering.py`, `compliance_guard.py`, `audit_logger.py`, `anchoring.py`) run directly and verify real behavior immediately.
3. Modules scheduled for upcoming milestones (e.g., `tools/`, `research/`) are tested against strict specification contracts; where dynamic imports are resolved, fallback contract harnesses or milestone skip markers provide clear traceability without halting the test runner.
4. When an implementation agent completes an assigned milestone, the corresponding tests transition immediately from skipped to passing.

---

## 5. Execution Commands

### Run Full 4-Tier E2E Suite
```powershell
pytest tests/e2e_research/ -v
```

### Run Specific Tiers
```powershell
# Tier 1: Smoke / Contracts & Interfaces
pytest tests/e2e_research/test_tier1_contracts.py -v

# Tier 2: Functional Core & Math Determinism
pytest tests/e2e_research/test_tier2_functional_core.py -v

# Tier 3: Workflow, Integration & DAG Task Graph
pytest tests/e2e_research/test_tier3_dag_workflows.py -v

# Tier 4: End-to-End Scenarios, Streaming & Reports
pytest tests/e2e_research/test_tier4_e2e_scenarios.py -v
```

### Run with Coverage Verification
```powershell
pytest tests/e2e_research/ -q --tb=short
```

---

## 6. Verification & Escalation Protocol

- **Test Integrity Standard**: Tests assert against mathematical ground truth and explicit specification invariants. Facade tests that trivially assert `True` are strictly prohibited.
- **Defect Escalation**: When a test detects an implementation defect in existing code, the QA/Test Writer documents the exact failure trace in `handoff.md` and escalates to the implementing agent. Test code must never be mutated to accommodate buggy implementations.

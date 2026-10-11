# Milestone 5 Explorer 1 Handoff Report: OrchestratorAgent Architecture & Specifications

## 1. Observation

Direct observations from codebase inspection:
1. **Existing Orchestrator Scaffold (`backend/agents/orchestrator.py`)**:
   - Lines 130-132: Session stages are currently modeled as a binary string:
     `stage = "advising" if client_id else "profiling"`
     instead of the 5 required states (`PROFILING`, `ADVICE_GENERATION`, `PROPOSAL_REVIEW`, `EXECUTION`, `HEALTH_MONITORING`).
   - Line 182: Method signature is `async def handle_message(self, db: AsyncSession, user_id: str, session_id: str, text: str) -> List[Dict[str, Any]]` instead of the required canonical signature `async process_user_message(session_id: str, user_id: str, client_id: Optional[str], message: str, db: AsyncSession) -> List[dict]`.
   - Line 386: Proposal creation is named `async def create_proposal(self, db: AsyncSession, client_id: str, symbol: str, side: str, qty: float) -> Dict[str, Any]`.
   - Line 426: Proposal execution is named `async def execute_proposal(self, db: AsyncSession, user_id: str, proposal_id: str, approved: bool) -> List[Dict[str, Any]]`.
   - Lines 155-172: Output text gate `gate_text(text, db, client_id)` already validates through `self.c.compliance.check_text_output(text)`, replaces prohibited language (`REG-001`) with `SAFE_REPLACEMENT`, appends risk disclosures (`REG-002`), and logs `OUTPUT_FILTERED` warning to `audit_log`.
   - Lines 257-280: Advising turn uses regex matching for `APPROVE_RE`, `REJECT_RE`, `TRADE_RE`, `COMPARE_RE`, and keywords for health/allocation, but lacks dedicated routing for real-time market quotes (`MarketDataAgent.get_quote`), macroeconomic context (`get_macro_context`, `get_yield_curve`), and rebalancing trade generation (`RebalancePlan`).

2. **Downstream Core Agent Interfaces**:
   - `RiskProfilerAgent` (`backend/agents/risk_profiler.py`, line 654): `async def process_input(self, session_id: str, user_message: str, db: Optional[AsyncSession] = None) -> Dict[str, Any]` returns `{"status": "in_progress" | "complete", "response": ..., "client_id": ..., "extracted_data": ..., "profile": ...}`.
   - `BehavioralBiasAgent` (`backend/agents/behavioral_bias.py`, line 215, 352): `async def detect_bias(client_id: str, user_message: str, db: Optional[AsyncSession] = None) -> List[BiasDetectionResult]` and `async def record_portfolio_check(client_id: str, db: Optional[AsyncSession] = None) -> Optional[TelemetrySignal]`.
   - `ProductComparisonAgent` (`backend/agents/product_comparison.py`, line 400-500): `async def compare_etfs(...)` and `compare_bonds(...)` return `ComparisonReport`.
   - `AllocationEngine` (`backend/agents/allocation_engine.py`, line 81, 91): `async def generate_allocation(profile, include_frontier=True, current_positions=..., db=...) -> AllocationResult`.
   - `ComplianceGuard` (`backend/agents/compliance_guard.py`, line 411, 840, 1117): `async def check_recommendation(db, client_id, rec, profile)` and `async def check_trade(db, client_id, trade, profile)` and `def check_text_output(text) -> Tuple[bool, List[str], str]`.
   - `ExecutionModule` (`backend/agents/execution_module.py`, line 70, 100): `async def execute_trade(...) -> TradeExecutionResult` enforcing `REG-003`, `REG-004`, 30s lock `lock:trade:{client_id}`, and KYC verification.
   - `HealthReportService` (`backend/services/health_report.py`, line 70-100): `async def generate_health_report(db, client_id, portfolio=...) -> HealthReportResult`.

3. **Current Test Suite State**:
   - `backend/tests/e2e/test_full_flow.py` contains 17 high-level test functions testing full application flow.
   - `backend/tests/unit/` lacks a dedicated `test_orchestrator.py` unit test file isolating multi-agent dispatching, state transitions, intent parsing, and compliance output gating.

---

## 2. Logic Chain

1. **State Machine Expansion**:
   - Observation: Currently, sessions only record `"profiling"` or `"advising"` in cache (`backend/agents/orchestrator.py:131`).
   - Reasoning: Real-world advisory dialogues require managing multi-step asynchronous user actions, specifically reviewing trade orders before execution, and inspecting drift/alerts.
   - Deduction: Introducing `SessionStage(str, Enum)` with 5 states (`PROFILING`, `ADVICE_GENERATION`, `PROPOSAL_REVIEW`, `EXECUTION`, `HEALTH_MONITORING`) cleanly isolates the state transitions, enables deterministic routing, and ensures trade proposals remain unexecuted until affirmative approval.

2. **Signature Unification & Backward Compatibility**:
   - Observation: Milestone 5 requirement specifies `process_user_message(session_id, user_id, client_id, message, db) -> List[dict]`, while existing code has `handle_message(db, user_id, session_id, text) -> List[dict]`.
   - Reasoning: Existing API routes in `backend/api/routes/advisory.py` and `backend/api/routes/ws.py` currently call `handle_message`.
   - Deduction: Making `process_user_message` the primary implementation and wrapping it with `handle_message` as a facade ensures 100% contract compliance with Milestone 5 requirements while preserving 100% backward compatibility with existing tests and API routes.

3. **Intent Recognition & Specialized Dispatching**:
   - Observation: User requests can include market queries ("quote SPY", "what are treasury rates?"), portfolio rebalancing ("rebalance my portfolio"), and comparisons ("compare bonds BND AGG").
   - Reasoning: If not recognized by specialized regexes, these either fall back to general LLM answers or generic prompts, bypassing specialized agents (`MarketDataAgent`, `AllocationEngine`).
   - Deduction: Adding explicit priority-ordered regex matching for market quotes, macro context, and rebalancing allows the orchestrator to route directly to `MarketDataAgent` and `AllocationEngine.generate_rebalance_plan()`.

4. **Universal Compliance Gating**:
   - Observation: All outgoing user text must be strictly compliant with SEC/FINRA rules (`REG-001` prohibiting promissory language and `REG-002` mandating risk disclosure).
   - Reasoning: Any uncaught response could expose the advisory platform to severe regulatory penalties.
   - Deduction: Every turn response from every sub-agent (Risk Profiler, Allocation Engine, Product Comparison, Health Report, Execution Module, and general LLM) must funnel through `gate_text()`, ensuring `ComplianceGuard.check_text_output()` sanitizes every single outgoing message.

---

## 3. Caveats

1. **OpenAI API Key Dependency**: If `OPENAI_API_KEY` is not present or unconfigured, `_general_reply` falls back to deterministic guidance text, and `BehavioralBiasAgent` Layer 2 falls back to Layer 1 calibrated heuristic regex matching. The system is designed to operate 100% offline without live network dependencies.
2. **Alpaca Broker Dependency**: When Alpaca credentials are not supplied, `ExecutionModule` runs in `DRY_RUN` paper trading mode, using realistic simulated prices from `SIMULATED_PRICES`.
3. **Database Transactions**: `AsyncSession` is passed into all agent dispatch routines. All mutations to `DBClientProfile`, `DBTrade`, `DBAuditLog`, and `DBBehavioralMemory` occur within transactional boundaries.

---

## 4. Conclusion

The architectural design and specification for `backend/agents/orchestrator.py` is fully documented in `backend/.agents/teamwork/teamwork_preview_explorer_m5_1/analysis.md`. The design:
- Defines the 5-state session state machine (`PROFILING` $\to$ `ADVICE_GENERATION` $\longleftrightarrow$ `PROPOSAL_REVIEW` $\to$ `EXECUTION` / `HEALTH_MONITORING`).
- Specifies the canonical Milestone 5 method signatures (`process_user_message`, `create_trade_proposal`, `handle_trade_approval`) alongside backward-compatible aliases.
- Details the multi-agent dispatch matrix for all 8 downstream agents/services.
- Guarantees universal compliance gating (`REG-001` replacement + `REG-002` risk disclosure).
- Specifies 6 comprehensive test groups comprising 18 detailed test scenarios for `backend/tests/unit/test_orchestrator.py`.

---

## 5. Verification Method

1. **Inspect Specifications**:
   - View `backend/.agents/teamwork/teamwork_preview_explorer_m5_1/analysis.md` to review the architectural design, class interfaces, event models, and test scenarios.
2. **Verify Code References**:
   - Check `backend/agents/orchestrator.py` against the specifications in `analysis.md` to confirm compatibility with existing imports and models.
   - Check `backend/api/routes/advisory.py`, `portfolio.py`, and `ws.py` to confirm that `handle_message`, `create_proposal`, and `execute_proposal` backward-compatible facades preserve existing routing.
3. **Execution Command**:
   - Run `pytest backend/tests/e2e/test_full_flow.py -v` to verify existing full flow integration tests pass.

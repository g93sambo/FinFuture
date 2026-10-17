# Project: Wealth Advisory Agent System Evolution (R1–R6)

## Architecture
The system evolves the existing multi-agent FastAPI wealth advisory platform into a non-discretionary, human-in-the-loop, tool-using financial research and institutional decision-support system.

### Key Architectural Layers:
1. **Research Orchestration Engine (`backend/research/task_graph.py`)**:
   - Declarative Directed Acyclic Graph (DAG) with dynamic dependency resolution and parallel task dispatch.
   - 8 Specialist Analyst Personas: Financial Analyst, Macro & Market Analyst, Investment Research Analyst, Quantitative Analyst, Intelligence/Web Analyst, Risk & Devil's Advocate, Personalized Advisory, Compliance Guard.
   - Typed inter-node Pydantic contracts (`TaskGraphState`, `ResearchTask`, `SubtaskResult`).
   - Configurable execution and tool-call budgets.
2. **Centralized Tool Registry (`backend/tools/`)**:
   - Decoupled `ToolRegistry` with validated Pydantic v2 argument/output schemas.
   - Role-based authorization matrix controlling which analyst role can execute which tool.
   - Bounded retries with exponential backoff and jitter, circuit breaker state machine (`CLOSED`, `OPEN`, `HALF_OPEN`), and execution provenance logging.
3. **Live Web Intelligence & Document Retrieval (`backend/services/web_intelligence.py`, `backend/services/providers/sec_edgar.py`)**:
   - Multi-source search (`ddgs`), primary filing extraction (SEC EDGAR XBRL facts and 10-K/10-Q/8-K narrative parsing), prospectus extraction.
   - Tri-layer prompt injection defense in `backend/services/sanitizer.py` (HTML/Unicode sanitization, `<untrusted_external_content>` XML delimiter isolation, regex heuristic screening).
   - Auditable `EvidenceLedger` tracking supporting/contradicting claims, timestamps, and clickable citations.
4. **Deterministic Quantitative Engine (`backend/services/financial_engineering.py`)**:
   - 10,000-path multivariate Student-t ($\nu=5$) fat-tail Monte Carlo simulation with Cholesky correlation.
   - Numerical hurdle rate bisection solver ($R_{\text{req}}$ = 34.44% for $10M \to $100M with $500k/yr withdrawals).
   - 10-year cash flow recursion schedules, multi-factor stress tests & market crash recovery math.
   - Deterministic DCF/WACC valuation, Parametric/Historical VaR, CVaR, Sharpe ratio calculations.
   - 5-pillar Hurdle Score with binary YES/NO decision rule. Zero arithmetic delegated to LLM generation.
5. **Memory, Self-Verification & Non-Discretionary Compliance (`backend/research/memory.py`, `backend/research/verification.py`, `backend/agents/compliance_guard.py`)**:
   - Tenant-isolated database and cache memory with TTL freshness invalidation.
   - Bounded self-verification loop (max 2 iterations) validating citations and table calculations.
   - Full 12-rule compliance catalog (`SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`), regulatory guarantee/risk disclosure text filters, 30s idempotency locks, 15-minute proposal validity, and paper-trading enforcement (`paper=True`).
6. **Streaming Frontend Telemetry & Observability (`backend/api/routes/ws.py`, `backend/api/routes/research.py`, `backend/chat_client.html`)**:
   - Real-time WebSocket and SSE event streaming (`research_started`, `task_graph_generated`, `analyst_dispatched`, `tool_call_started`, `evidence_logged`, `model_computed`, `devils_advocate_review`, `self_verification_status`, `report_chunk`).
   - Institutional markdown report renderer with unabridged tables.
   - Append-only hash-chained audit logging and Sepolia Merkle anchoring.

---

## Feature Inventory
Every feature from the Survey phase is mapped to an assigned milestone:

| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | Baseline Test Stabilization | Fix 6 isolated regressions in orchestrator & behavioral bias to restore 644/644 clean baseline | M0 | Survey (DONE) |
| 2 | Tool Base & Pydantic Schemas | Define `BaseTool` with Pydantic v2 argument/output validation | M1 | Survey (R3 - DONE) |
| 3 | Centralized Tool Registry | Registry singleton with registration, lookup, schema export, and role filtering | M1 | Survey (R3 - DONE) |
| 4 | Tool Execution Adapters | Bounded retries, exponential backoff, jitter, circuit breakers, provenance logging | M1 | Survey (R3 - DONE) |
| 5 | Core Tools Migration | Migrate existing market, macro, treasury, screener, and portfolio tools into registry | M1 | Survey (R3 - DONE) |
| 6 | SEC EDGAR Facts Provider | Async provider querying SEC EDGAR companyfacts XBRL JSON API for GAAP metrics | M2 | Survey (R2) |
| 7 | SEC Narrative Filing Extractor | Parse 10-K, 10-Q, 8-K narrative sections (Items 1A, 7, 8) with BeautifulSoup | M2 | Survey (R2) |
| 8 | Multi-Source Web Search Adapter | Resilient search query formulation with DuckDuckGo fallback and caching | M2 | Survey (R2) |
| 9 | Untrusted Content Sanitizer | Tri-layer prompt injection defense (HTML stripping, XML isolation, regex heuristics) | M2 | Survey (R2) |
| 10 | Content Deduplication & Hash | SHA-256 deduplication and publication/event timestamp stratification | M2 | Survey (R2) |
| 11 | Evidence Ledger Service | Structured ledger recording hypotheses, supporting/contradicting data, and status | M2 | Survey (R2, R4) |
| 12 | Clickable Citation Generator | Format and link verified source URLs with publisher metadata for every factual claim | M2 | Survey (R2) |
| 13 | Student-t Monte Carlo Simulation | 10,000-path Student-t ($\nu=5$) fat-tail simulation with Cholesky decomposition | M3 | Survey (R4) |
| 14 | Hurdle Rate Bisection Solver | Numerical root-finding bisection solver for required return with cash withdrawals | M3 | Survey (R4) |
| 15 | 10-Year Cash Flow Schedules | Deterministic recursion modeling deposits, returns, and inflation-adjusted withdrawals | M3 | Survey (R4) |
| 16 | Multi-Factor Stress Testing | Macro shock models (Stagflation, 2008 GFC, Rate Shock) with recovery trajectories | M3 | Survey (R4) |
| 17 | Deterministic DCF Valuation | Unlevered Free Cash Flow DCF, WACC discounting, and terminal value computation | M3 | Survey (R4) |
| 18 | VaR, CVaR & Sharpe Metrics | Parametric and historical VaR, CVaR (Expected Shortfall), and annualized Sharpe ratios | M3 | Survey (R4) |
| 19 | 5-Pillar Hurdle Scoring | Deterministic 0-100 hurdle score with binary YES/NO decision rule | M3 | Survey (R4) |
| 20 | DAG Task Graph Engine | Declarative task graph with dynamic dependency resolution and parallel execution | M4 | Survey (R1) |
| 21 | Financial Analyst Role | Specialist analyzing financial statements, ratios, earnings, and capital structure | M4 | Survey (R1) |
| 22 | Macro & Market Analyst Role | Specialist analyzing interest rates, yield curves, inflation, and macro regime | M4 | Survey (R1) |
| 23 | Investment Research Analyst Role | Specialist analyzing business model, competitive moat, catalysts, and industry | M4 | Survey (R1) |
| 24 | Quantitative Analyst Role | Specialist driving quantitative models, Monte Carlo, and factor stress testing | M4 | Survey (R1) |
| 25 | Intelligence / Web Analyst Role | Specialist gathering live news, SEC filings, prospectuses, and verifiable facts | M4 | Survey (R1) |
| 26 | Risk & Devil's Advocate Role | Adversarial specialist testing downside catalysts, bear cases, and counter-hypotheses | M4 | Survey (R1) |
| 27 | Personalized Advisory Role | Specialist tailoring research findings to user profile, risk tolerance, and constraints | M4 | Survey (R1) |
| 28 | Compliance Guard Node | Inviolable rule verification ensuring regulatory adherence and risk disclosures | M4 | Survey (R1, R5) |
| 29 | Typed Inter-Node Contracts | Pydantic schemas for tasks, node inputs, node outputs, and graph state | M4 | Survey (R1) |
| 30 | Execution & Tool-Call Budgets | Configurable per-task and per-graph execution timeouts and tool-call limits | M4 | Survey (R1) |
| 31 | Tenant-Isolated Memory | User-scoped profile, research session, and decision memory isolation | M4 | Survey (R5) |
| 32 | Memory Freshness TTL Invalidation | Stratified TTL hierarchy invalidating stale market, macro, and research cache | M4 | Survey (R5) |
| 33 | Bounded Self-Verification Loop | Dual-pass verification loop verifying numbers against tools before finalizing | M4 | Survey (R5) |
| 34 | Non-Discretionary Paper Trading Guard | Mandatory user confirmation, 30s double-submit lock, paper-only execution | M4 | Survey (R5) |
| 35 | Streaming WebSocket Telemetry | Async event callback streaming real-time research milestones to `/ws/chat` | M5 | Survey (R6) |
| 36 | SSE Research Streaming Route | Server-Sent Events endpoint `/api/v1/research/stream` for research execution | M5 | Survey (R6) |
| 37 | Institutional Markdown Report Builder | Renderer generating unabridged tables, evidence ledgers, and citation footers | M5 | Survey (R6) |
| 38 | Client UI Telemetry Rendering | Enhance `backend/chat_client.html` to display streaming research cards and steps | M5 | Survey (R6) |
| 39 | Audit Logging & Merkle Anchoring | Append-only SHA-256 hash chaining and Sepolia testnet Merkle anchoring | M5 | Survey (R6) |
| 40 | Opaque-Box E2E Test Suite (Tiers 1-4) | Comprehensive 4-tier test suite derived from requirements | M6 | Survey (TEST_READY.md) |
| 41 | Adversarial Coverage Hardening (Tier 5) | White-box adversarial testing, stress harness, and edge case coverage | M6 | Survey (Dual Track) |
| 42 | Full System Verification & Acceptance | Comprehensive end-to-end verification against all user acceptance criteria | M6 | Survey |

---

## Milestones

| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| M0 | Baseline Stabilization | Restore 644/644 clean test baseline by fixing 6 known regressions | none | DONE |
| M1 | Centralized Tool Registry | Pydantic tool schemas, authorization, circuit breakers, tool migration | M0 | DONE |
| M2 | Web Intel, Filings & Evidence Ledger | SEC EDGAR, search, prompt injection defense, evidence ledger & citations | M1 | DONE |
| M3 | Deterministic Quantitative Engine | Student-t Monte Carlo, DCF, hurdle rate, cash flows, VaR/CVaR, Sharpe | M0 | DONE |
| M4 | Research DAG & Specialist Personas | TaskGraph, 8 analyst roles, user memory, self-verification, paper guards | M1, M2, M3 | DONE |
| M5 | Streaming Telemetry & Observability | WebSocket/SSE milestones, institutional report builder, UI rendering | M4 | DONE |
| M6 | E2E Test Verification & Hardening | 100% pass of E2E suite (Tiers 1-4) and Tier 5 adversarial hardening | M5, TEST_READY.md | DONE |

---

## Interface Contracts

### 1. `backend/tools/` ↔ Analyst Agents
```python
class BaseTool(ABC):
    name: str
    description: str
    args_schema: Type[BaseModel]
    required_roles: List[str]  # Role-based access control
    async def execute(self, **kwargs) -> ToolResult: ...

class ToolRegistry:
    def register(self, tool: BaseTool) -> None: ...
    def get_tool(self, name: str) -> Optional[BaseTool]: ...
    def get_tools_for_role(self, role: str) -> List[BaseTool]: ...
    async def execute_tool(self, name: str, role: str, args: Dict[str, Any], context: ExecutionContext) -> ToolResult: ...
```

### 2. `backend/services/evidence_ledger.py` ↔ Research Orchestrator
```python
class EvidenceItem(BaseModel):
    id: str
    claim: str
    supporting_facts: List[str]
    contradicting_facts: List[str]
    source_urls: List[str]
    publisher: str
    retrieval_timestamp: datetime
    confidence_score: float
    verification_status: Literal["VERIFIED", "CONTRADICTED", "UNCONFIRMED"]

class EvidenceLedger:
    def add_claim(self, claim: str, source: Dict[str, Any]) -> str: ...
    def add_contradiction(self, claim_id: str, contradiction: str, source: Dict[str, Any]) -> None: ...
    def get_citations(self) -> List[Dict[str, str]]: ...
    def export_markdown_table(self) -> str: ...
```

### 3. `backend/research/task_graph.py` ↔ Analyst Nodes
```python
class ResearchTask(BaseModel):
    task_id: str
    role: str  # One of the 8 specialist analyst roles
    description: str
    dependencies: List[str]
    input_data: Dict[str, Any]
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"]
    result: Optional[Dict[str, Any]] = None

class TaskGraphState(BaseModel):
    inquiry: str
    user_id: str
    tasks: Dict[str, ResearchTask]
    evidence_ledger: EvidenceLedger
    final_report: Optional[str] = None
```

### 4. `backend/services/financial_engineering.py` (Quantitative Engine)
```python
def run_student_t_monte_carlo(
    initial_wealth: float,
    cash_flows: List[float],
    asset_weights: Dict[str, float],
    annual_returns: Dict[str, float],
    annual_vols: Dict[str, float],
    corr_matrix: np.ndarray,
    df_t: int = 5,
    num_paths: int = 10000,
    num_years: int = 10,
    seed: int = 42
) -> Dict[str, Any]: ...

def calculate_dcf_valuation(
    fcf_projections: List[float],
    terminal_growth_rate: float,
    wacc: float,
    shares_outstanding: float,
    net_debt: float
) -> Dict[str, Any]: ...
```

### 5. `backend/api/routes/ws.py` (Streaming Telemetry Contract)
```python
# Event schema emitted via async event_callback:
{
    "type": "research_milestone",
    "milestone": "planning" | "evidence_gathering" | "modeling" | "devils_advocate" | "verification" | "report_generation",
    "step_id": str,
    "role": str,
    "data": dict,
    "timestamp": str (ISO 8601)
}
```

---

## Code Layout
- `backend/tools/`: Centralized Tool Registry, BaseTool, adapters, and schemas.
- `backend/research/`: Task graph DAG, 8 specialist analyst classes, user memory, self-verification.
- `backend/services/`:
  - `web_intelligence.py`: Multi-source search & document retrieval.
  - `sanitizer.py`: Tri-layer prompt injection defense.
  - `evidence_ledger.py`: Auditable evidence ledger and citation manager.
  - `financial_engineering.py`: Deterministic quantitative modeling engine.
  - `report_builder.py`: Institutional markdown report renderer.
  - `providers/sec_edgar.py`: SEC EDGAR XBRL facts and 10-K section parser.
- `backend/api/routes/`:
  - `ws.py`: Real-time streaming WebSocket endpoint.
  - `research.py`: REST and SSE research endpoints.
- `backend/chat_client.html`: Browser test client with live telemetry display.
- `tests/e2e/`: End-to-end integration test suites.
- `tests/e2e_research/`: 4-tier requirement-driven E2E research test suite.
- `tests/unit/`: Unit test suites for tools, math, evidence, and analysts.
- `tests/adversarial/`: Adversarial stress tests, injection attacks, and edge cases.

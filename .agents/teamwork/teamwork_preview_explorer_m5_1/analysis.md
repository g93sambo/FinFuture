# Milestone 5 Architecture & Implementation Specification: OrchestratorAgent

**Author**: Explorer 1 (Milestone 5 - Orchestration & Full API Layer)  
**Target Path**: `backend/agents/orchestrator.py`  
**Dependencies**: `risk_profiler.py`, `behavioral_bias.py`, `market_data.py`, `product_comparison.py`, `allocation_engine.py`, `compliance_guard.py`, `execution_module.py`, `health_report.py`, `portfolio_service.py`

---

## 1. Executive Summary

The `OrchestratorAgent` is the central operational nervous system of the Wealth Advisory Agent backend. It unifies conversational interactions across REST (`POST /api/v1/chat/message`) and WebSocket (`/ws/chat/{session_id}?token=...`) channels into a single, deterministic, state-machine-driven event pipeline.

Key responsibilities:
1. **Multi-Agent Coordination**: Directs inbound user dialogue to specialized downstream domain agents (`RiskProfilerAgent`, `BehavioralBiasAgent`, `MarketDataAgent`, `ProductComparisonAgent`, `AllocationEngine`, `HealthReportService`, and `ExecutionModule`).
2. **Explicit Session State Machine**: Formally manages conversation progression through 5 distinct operational stages:
   $$\text{PROFILING} \longrightarrow \text{ADVICE\_GENERATION} \longleftrightarrow \begin{cases} \text{PROPOSAL\_REVIEW} \longrightarrow \text{EXECUTION} \\ \text{HEALTH\_MONITORING} \end{cases}$$
3. **Universal Compliance Gating**: Implements mandatory, non-bypassable pre-transmission output filtering on **every single outbound message and recommendation** via `ComplianceGuard.check_text_output()` (REG-001 prohibited promissory language replacement, REG-002 mandatory risk disclosure) and `ComplianceGuard.check_recommendation()` (SUIT-001..003, CONC-001..003).
4. **Non-Discretionary Trade Execution Gate**: Generates structured, time-bounded (15-minute window per REG-004) trade proposals requiring explicit client affirmative authorization (`user_approved == True` per REG-003) before engaging the `ExecutionModule` (guarded by 30-second double-submit distributed locks and KYC verification).
5. **Cryptographic Audit Logging**: Dispatches audit events to the append-only, HMAC-signed, SHA-256 hash-chained `DBAuditLog` for every state change, proposal creation, user rejection, compliance warning/block, and executed transaction.

---

## 2. Review of Existing Implementation & Gap Analysis

Inspection of the existing `backend/agents/orchestrator.py` reveals a functional initial scaffold, but highlights critical architectural gaps that must be closed for full Milestone 5 compliance:

| Feature / Requirement | Current Implementation in `orchestrator.py` | Required Milestone 5 Specification | Gap & Necessary Action |
| :--- | :--- | :--- | :--- |
| **Session States** | Binary string flag (`"profiling"` vs `"advising"`). | 5 formal states: `PROFILING`, `ADVICE_GENERATION`, `PROPOSAL_REVIEW`, `EXECUTION`, `HEALTH_MONITORING`. | Implement `SessionStage(str, Enum)`. Maintain stage transitions in cache session dict. |
| **Public Message Signature** | `handle_message(db, user_id, session_id, text) -> List[dict]` | `process_user_message(session_id, user_id, client_id, message, db) -> List[dict]` | Implement `process_user_message` as canonical method; provide `handle_message` as backward-compatible facade. |
| **Trade Proposal Signature** | `create_proposal(db, client_id, symbol, side, qty) -> dict` | `create_trade_proposal(db, client_id, symbol, side, qty, session_id) -> dict` | Implement `create_trade_proposal` with `session_id` integration; alias `create_proposal`. |
| **Trade Approval Signature** | `execute_proposal(db, user_id, proposal_id, approved) -> List[dict]` | `handle_trade_approval(db, user_id, proposal_id, approved, session_id) -> dict/List[dict]` | Implement `handle_trade_approval` returning structured event output; alias `execute_proposal`. |
| **Intent Recognition** | Basic regex substring checks for trade, compare, health. | Robust intent routing engine covering profiling, quotes, macro/yield curve, comparison, allocation, rebalancing, proposals, approvals. | Add dedicated intent parsers with priority ordering and regex catalogs. |
| **Rebalancing Intent** | Subsumed under general "health" / "allocat" check. | Explicit detection of rebalance request $\to$ invokes `AllocationEngine.generate_allocation()` with positions $\to$ produces `RebalancePlan` $\to$ automatically proposes SELL-first rebalance order. | Add rebalance routing and automated proposal transition. |
| **Market Data Inquiries** | General OpenAI fallback or generic canned response. | Direct routing of ticker quotes and macro/rates inquiries to `MarketDataAgent` (`get_quote`, `get_yield_curve`, `get_macro_context`). | Add quote and macro intent parsing and agent invocation. |
| **Unit Test Coverage** | Zero dedicated unit tests in `backend/tests/unit/test_orchestrator.py` (only e2e in `test_full_flow.py`). | Comprehensive unit test suite with 100% coverage of all states, routing intents, compliance gating, and trade flows. | Detail complete test suite scenarios for `test_orchestrator.py`. |

---

## 3. Architecture Specification for `OrchestratorAgent`

### 3.1 Session State Machine

The session state machine governs the conversation context stored in Redis (with in-memory dictionary fallback) under key `session:{session_id}` with `TTL = 86400` (24 hours).

```
                      ┌────────────────────────────────────────┐
                      │             [SESSION START]            │
                      └───────────────────┬────────────────────┘
                                          │
                        Client ID exists? │
                        ┌─────────────────┴─────────────────┐
                        │ No                                │ Yes
                        ▼                                   ▼
             ┌─────────────────────┐             ┌─────────────────────┐
             │      PROFILING      │             │  ADVICE_GENERATION  │◄────────────┐
             └──────────┬──────────┘             └──────────┬──────────┘             │
                        │                                   │                        │
       Profile synthesis│                   Trade order or  │ Ask for portfolio      │
               complete │                  rebalance intent │ health / drift         │
                        ▼                                   ▼                        │
             ┌─────────────────────┐             ┌─────────────────────┐             │
             │  ADVICE_GENERATION  │             │   HEALTH_MONITORING │             │
             └──────────┬──────────┘             └──────────┬──────────┘             │
                        │                                   │                        │
      User submits order│                   Rebalance order │ Report generated       │
     intent (e.g., buy) │                   recommended     │ or inquiry returns     │
                        ▼                                   │                        │
             ┌─────────────────────┐                        │                        │
             │   PROPOSAL_REVIEW   │◄───────────────────────┘                        │
             └──────────┬──────────┘                                                 │
                        │                                                            │
         User response? ├──────────────────────────┐                                 │
                        │ Reject / Cancel          │ Approve (`user_approved=True`)  │
                        ▼                          ▼                                 │
             ┌─────────────────────┐    ┌─────────────────────┐                      │
             │ (Cancel proposal &  │    │      EXECUTION      │                      │
             │ return to advisory) │    │  (Compliance check, │                      │
             └──────────┬──────────┘    │  broker order fill) │                      │
                        │               └──────────┬──────────┘                      │
                        │                          │ Order filled/blocked            │
                        └──────────────────────────┴─────────────────────────────────┘
```

#### State Definitions
1. **`SessionStage.PROFILING ("PROFILING")`**:
   - Active when client onboarding questionnaire is ongoing.
   - Evaluates inbound message for behavioral biases (`client_id = f"pending-{session_id}"`).
   - Dispatches message to `RiskProfilerAgent.process_input()`.
   - When profiler emits `status == "complete"`:
     - Associates `user_id` with profile and persists `DBClientProfile` in database.
     - Logs audit entry `PROFILE_COMPLETED`.
     - Transitions state to `ADVICE_GENERATION`.
     - Emits `profile_complete=True` event.

2. **`SessionStage.ADVICE_GENERATION ("ADVICE_GENERATION")`**:
   - Default operating state for onboarded clients.
   - Checks every message with `BehavioralBiasAgent.detect_bias()`.
   - Parses intent: quotes, macro, ETF/bond comparison, asset allocation, rebalancing, portfolio health, trade proposal.
   - If user requests a trade or rebalance order is generated, transitions to `PROPOSAL_REVIEW`.
   - If user requests health diagnosis, transitions to `HEALTH_MONITORING`.

3. **`SessionStage.PROPOSAL_REVIEW ("PROPOSAL_REVIEW")`**:
   - Active when a trade proposal is pending user authorization (`session["pending_proposal_id"]` is set).
   - TTL for proposal is 15 minutes (`PROPOSAL_TTL_SECONDS = 900`).
   - If user inputs approval keywords (`APPROVE_RE`): transitions to `EXECUTION`.
   - If user inputs rejection keywords (`REJECT_RE`): deletes cached proposal, logs `TRADE_REJECTED_BY_USER`, clears pending proposal, and returns to `ADVICE_GENERATION`.
   - If user asks clarifying questions: answers question while keeping `pending_proposal_id` active.

4. **`SessionStage.EXECUTION ("EXECUTION")`**:
   - Triggered when client affirmatively approves a proposal (`user_approved == True`).
   - Validates proposal age ($\le 900\text{s}$ per REG-004) and user ownership.
   - Runs `ComplianceGuard.check_trade()` across REG-003, REG-004, CONC-001, AML-001, AML-002.
   - If compliance blocks: logs violation, raises `TradeBlocked`, emits `compliance_check` failure, and returns to `ADVICE_GENERATION`.
   - If compliance passes: calls `ExecutionModule.execute_trade()` (30s lock, KYC validation, paper execution, DB recording, audit log `TRADE_EXECUTED`).
   - Emits `trade_approved`, `compliance_check`, `trade_filled`, and `portfolio_update` events.
   - Transitions state back to `ADVICE_GENERATION`.

5. **`SessionStage.HEALTH_MONITORING ("HEALTH_MONITORING")`**:
   - Active during portfolio health inspection and drift analysis.
   - Tracks portfolio check timestamp via `BehavioralBiasAgent.record_portfolio_check()` (alerts if $\ge 3$ checks in 10 minutes).
   - Generates health report via `HealthReportService.generate_health_report()`.
   - Emits `portfolio_update` event with drift analysis, concentration metrics, benchmark comparison, health grade, and narrative.
   - If rebalancing is recommended and user consents, transitions to `PROPOSAL_REVIEW`; otherwise transitions back to `ADVICE_GENERATION`.

---

### 3.2 Dialogue Routing & Intent Parsing

The dialogue router evaluates incoming text in strict priority order to prevent ambiguity:

```
Inbound User Message
  │
  ├─► Layer 0: Behavioral Bias Inspection (BehavioralBiasAgent)
  │            ↳ Emits bias_alert event if heuristic score >= 0.6 or LLM confirmed
  │
  ├─► Layer 1: Active Stage Check
  │    ├─ If stage == PROFILING:
  │    │   ↳ Route to RiskProfilerAgent.process_input()
  │    │
  │    └─ If stage == PROPOSAL_REVIEW (pending_proposal_id active):
  │        ├─ If APPROVE_RE match ──► Route to handle_trade_approval(approved=True)
  │        ├─ If REJECT_RE match  ──► Cancel proposal & revert to ADVICE_GENERATION
  │        └─ Else                ──► Answer inquiry, retain pending_proposal_id
  │
  └─► Layer 2: Intent Classification in ADVICE_GENERATION
       ├─ [Priority 1: Direct Trade Intent] TRADE_RE match ("buy 10 SPY", "sell 5 BND")
       │   ↳ Route to create_trade_proposal() ──► Transition to PROPOSAL_REVIEW
       │
       ├─ [Priority 2: Rebalancing Intent] REBALANCE_RE match ("rebalance", "fix drift")
       │   ↳ Route to AllocationEngine.generate_allocation() with positions ──► Propose trade
       │
       ├─ [Priority 3: Comparison Intent] COMPARE_RE match ("compare SPY VTI", "compare bonds")
       │   ↳ Route to ProductComparisonAgent (ETFs or Bonds based on keyword)
       │
       ├─ [Priority 4: Health / Drift Intent] HEALTH_RE match ("health", "drift", "how is my portfolio")
       │   ↳ Transition to HEALTH_MONITORING ──► HealthReportService.generate_health_report()
       │
       ├─ [Priority 5: Allocation Intent] ALLOCATION_RE match ("recommend allocation", "portfolio")
       │   ↳ Route to AllocationEngine.generate_allocation() ──► Compliance check ──► Say
       │
       ├─ [Priority 6: Market Quotes & Macro Intent] MARKET_RE match ("quote SPY", "yield curve", "macro")
       │   ↳ Route to MarketDataAgent (get_quote, get_yield_curve, get_macro_context)
       │
       └─ [Priority 7: General Wealth Advisory Query]
           ↳ Route to cautious, non-discretionary LLM / fallback reply
```

#### Calibrated Regex Patterns
```python
TRADE_RE = re.compile(
    r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+(?:shares?\s+of\s+|units?\s+of\s+)?([A-Za-z]{1,5})\b",
    re.IGNORECASE,
)
APPROVE_RE = re.compile(
    r"^\s*(approve|approved|confirm|yes|execute|go ahead|proceed)\b",
    re.IGNORECASE,
)
REJECT_RE = re.compile(
    r"^\s*(reject|cancel|no|decline|stop|abort|don't|dont)\b",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(
    r"\b(compare|versus|vs|better than|difference between)\b",
    re.IGNORECASE,
)
REBALANCE_RE = re.compile(
    r"\b(rebalance|rebalancing|realign|fix drift|adjust allocation)\b",
    re.IGNORECASE,
)
HEALTH_RE = re.compile(
    r"\b(health|drift|how is my portfolio|portfolio review|performance|portfolio status)\b",
    re.IGNORECASE,
)
ALLOCATION_RE = re.compile(
    r"\b(allocat|recommend|what should i invest|build (?:me )?a portfolio|suggest a portfolio)\b",
    re.IGNORECASE,
)
QUOTE_RE = re.compile(
    r"\b(?:quote|price of|how much is)\s+([A-Za-z]{1,5})\b",
    re.IGNORECASE,
)
MACRO_RE = re.compile(
    r"\b(macro|yield curve|treasury rates|interest rates|inflation|gdp|unemployment)\b",
    re.IGNORECASE,
)
TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
STOPWORDS_TICKER = {"ETF", "ETFS", "AND", "VS", "THE", "BOND", "BONDS", "FOR", "BUY", "SELL"}
```

---

### 3.3 Multi-Agent Dispatch Matrix

| Inbound User Intent | Target Agent / Service | Method Invocation | Pre-Conditions / Dependencies | Primary Output | Audit Event Type |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Onboarding Dialogue** | `RiskProfilerAgent` | `process_input(session_id, text, db)` | Stage == `PROFILING` | Next interview prompt or synthesized profile | `PROFILE_COMPLETED` (on completion) |
| **Linguistic / Emotional Bias** | `BehavioralBiasAgent` | `detect_bias(client_id, user_message=text, db=db)` | Evaluated on *every* turn | List of `BiasDetectionResult` (emits `bias_alert` events) | `BEHAVIORAL_BIAS_DETECTED` (in DB `behavioral_memory`) |
| **Frequent Portfolio Checks** | `BehavioralBiasAgent` | `record_portfolio_check(client_id, db=db)` | Triggered on `/portfolio/{id}` and health reports | `TelemetrySignal` (anxiety warning if $\ge 3$ in 10m) | `TELEMETRY_SIGNAL` |
| **Real-time Price Snapshot** | `MarketDataAgent` | `get_quote(symbol)` | Valid ticker symbol | `MarketDataPoint` (price, bid, ask, volume) | None (Cached) |
| **Macro & Yield Curve** | `MarketDataAgent` | `get_macro_context()`, `get_yield_curve()` | Macro query | `MacroData`, `YieldCurveData` | None (Cached) |
| **Product Comparison (ETFs)** | `ProductComparisonAgent` | `compare_etfs(symbols, profile, client_id)` | $\ge 2$ symbols | `ComparisonReport` (6-factor scores, rank, winner) | None |
| **Product Comparison (Bonds)** | `ProductComparisonAgent` | `compare_bonds(symbols, profile, client_id)` | $\ge 2$ symbols | `ComparisonReport` (duration, yield, credit score) | None |
| **Portfolio Allocation (CVaR)** | `AllocationEngine` | `generate_allocation(profile, include_frontier=True, current_positions=pos)` | Completed client profile | `AllocationResult` (weights, solver, frontier, SHAP) | `RECOMMENDATION_GENERATED` |
| **Portfolio Drift & Health** | `HealthReportService` | `generate_health_report(db, client_id, portfolio)` | Client portfolio exists | `HealthReportResult` (drift, HHI, score, narrative) | None |
| **Compliance Check (Rec)** | `ComplianceGuard` | `check_recommendation(db, client_id, rec, profile)` | Generated allocation | `ComplianceCheckResult` (passes or blocks) | `COMPLIANCE_RECOMMENDATION_CHECK` |
| **Compliance Check (Text)** | `ComplianceGuard` | `check_text_output(text)` | *All outgoing text* | `(passed, violations, sanitized_text)` | `OUTPUT_FILTERED` (if REG-001/002 triggered) |
| **Compliance Check (Trade)** | `ComplianceGuard` | `check_trade(db, client_id, trade, profile)` | User approved trade | `ComplianceCheckResult` (REG-003, 004, CONC-001, AML) | `COMPLIANCE_TRADE_CHECK` |
| **Order Execution** | `ExecutionModule` | `execute_trade(db, client_id, proposal_id, ...)` | `user_approved == True`, KYC, 30s lock | `TradeExecutionResult` (FILLED, trade_id) | `TRADE_EXECUTED` |
| **Portfolio State Ledger** | `PortfolioService` | `get_portfolio(db, client_id, persist_snapshot=True)` | Post-trade fill or health query | Current positions, cash, total value, weights | Snapshot in `portfolio_snapshots` |

---

### 3.4 Universal Compliance Gating Workflow

To satisfy the strict regulatory requirements of Milestone 5, **no text or advice leaves `OrchestratorAgent` without passing through the Compliance Guard**.

```python
async def gate_text(self, text: str, db: Optional[AsyncSession], client_id: Optional[str]) -> str:
    """
    Mandatory compliance filter for all outbound conversational text.
    1. Checks REG-001 (prohibited promissory terms). If found, replaces entire text
       with SAFE_REPLACEMENT and audits as WARNING.
    2. Checks REG-002 (mandatory risk disclosures). If missing, appends standard disclosure.
    """
    passed, violations, sanitized = self.c.compliance.check_text_output(text)
    if violations:
        if any(v.startswith("REG-001") for v in violations):
            # Strip promissory text entirely
            _, _, sanitized = self.c.compliance.check_text_output(SAFE_REPLACEMENT)
        if db is not None and client_id:
            try:
                await self.c.audit.log_audit_entry(
                    db=db,
                    client_id=client_id,
                    event_type="OUTPUT_FILTERED",
                    actor="AGENT:orchestrator",
                    details={"violations": violations, "original_text_sample": text[:200]},
                    status="WARN",
                )
            except Exception as exc:
                logger.error("Failed to audit filtered output: %s", exc)
    return sanitized
```

When generating asset allocations, the orchestrator also gates through `check_recommendation()`:
```python
check = await self.c.compliance.check_recommendation(db, client_id, rec, profile)
if not check.passed:
    # Emit compliance violation event and refuse recommendation delivery
    events.append(_event(
        "compliance_check", "ComplianceGuard",
        "Recommendation blocked by compliance rules.",
        passed=False, violations=[v.to_dict() for v in check.violations]
    ))
    return events
```

---

### 3.5 Trade Proposal & Non-Discretionary Execution Flow

The trade execution workflow implements a strict human-in-the-loop guarantee. The agent is entirely non-discretionary: **it cannot execute any order without affirmative client consent**.

```
User says "buy 10 SPY"
  │
  ▼
create_trade_proposal(client_id, "SPY", "BUY", 10.0)
  │ 1. Resolve current market price (~$510.50)
  │ 2. Compute notional value ($5,105.00)
  │ 3. Project new holding weight (e.g. 5.1%)
  │ 4. Generate proposal_id UUID
  │ 5. Cache proposal with 15-minute TTL (key: proposal:{id})
  │ 6. Log audit entry: TRADE_PROPOSED
  │ 7. Set session["pending_proposal_id"] = proposal_id
  │ 8. Transition stage to PROPOSAL_REVIEW
  │
  ▼
Emit event: trade_proposal
"Proposed order: BUY 10 SPY at about $510.50 (~$5,105.00). Reply 'approve' to execute within 15 minutes, or 'cancel'."
  │
  ├───────────────────────────────────────────────────────┐
  │ User replies "approve"                                │ User replies "reject"
  ▼                                                       ▼
handle_trade_approval(proposal_id, approved=True)      handle_trade_approval(proposal_id, approved=False)
  │ 1. Check proposal expiration (elapsed <= 15m)        │ 1. Evict proposal from cache
  │ 2. Verify client ownership (profile.user_id==user_id)│ 2. Log audit: TRADE_REJECTED_BY_USER
  │ 3. Run ComplianceGuard.check_trade():                 │ 3. Clear session["pending_proposal_id"]
  │    - REG-003: user_approved == True                  │ 4. Revert stage to ADVICE_GENERATION
  │    - REG-004: approval_timestamp <= 15m              │ 5. Emit cancellation confirmation
  │    - CONC-001: projected_weight <= 15%               └────────────────────────────────────────
  │    - AML-001: notional <= $100k
  │    - AML-002: <= 5 orders in 10m
  │ 4. Acquire 30s trade lock: lock:trade:{client_id}
  │ 5. Verify client.kyc_verified == True
  │ 6. Submit to Alpaca paper / simulated fill
  │ 7. Record in DB trades table (status = FILLED)
  │ 8. Log audit: TRADE_EXECUTED
  │ 9. Delete proposal from cache
  │ 10. Update portfolio snapshot in DB
  │ 11. Revert stage to ADVICE_GENERATION
  │
  ▼
Emit events:
  - trade_approved
  - compliance_check (passed=True)
  - trade_filled (order details)
  - portfolio_update (new balance & weights)
```

---

## 4. Class & Public Method Signatures for `OrchestratorAgent`

### 4.1 Data Models & Enums

```python
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

class SessionStage(str, Enum):
    PROFILING = "PROFILING"
    ADVICE_GENERATION = "ADVICE_GENERATION"
    PROPOSAL_REVIEW = "PROPOSAL_REVIEW"
    EXECUTION = "EXECUTION"
    HEALTH_MONITORING = "HEALTH_MONITORING"


class TradeProposal(BaseModel):
    proposal_id: str
    client_id: str
    symbol: str
    side: str  # "BUY" | "SELL"
    qty: float
    price: float
    notional_value: float
    projected_weight: float
    created_at: str
    expires_in_seconds: int = 900
```

### 4.2 OrchestratorAgent Class Interface

```python
class OrchestratorAgent:
    def __init__(self, container: AgentContainer) -> None:
        self.c = container

    # --- Session Management ---
    async def start_session(
        self,
        user_id: str,
        client_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Initializes a new conversation session with appropriate stage."""
        ...

    async def load_session(
        self,
        session_id: str,
        user_id: str,
    ) -> Dict[str, Any]:
        """Loads and verifies ownership of an active session from cache."""
        ...

    async def save_session(
        self,
        session: Dict[str, Any],
    ) -> None:
        """Persists session state and stage to cache with standard TTL."""
        ...

    # --- Compliance Text Filter ---
    async def gate_text(
        self,
        text: str,
        db: Optional[AsyncSession],
        client_id: Optional[str],
    ) -> str:
        """Synchronously filters text through REG-001/002 and logs audit warnings."""
        ...

    # --- Core Public Message Handler (Canonical Milestone 5 Signature) ---
    async def process_user_message(
        self,
        session_id: str,
        user_id: str,
        client_id: Optional[str],
        message: str,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        """
        Coordinates full multi-agent dialogue turn across conversational states:
        - Layer 0: Behavioral bias detection on user message
        - Layer 1: PROFILING turn vs ADVICE_GENERATION / PROPOSAL_REVIEW turns
        - Layer 2: Intent classification & specialized agent dispatch
        - Layer 3: Output compliance gating on all replies
        Returns list of structured JSON events.
        """
        ...

    # Backwards-compatible alias for existing route callers
    async def handle_message(
        self,
        db: AsyncSession,
        user_id: str,
        session_id: str,
        text: str,
    ) -> List[Dict[str, Any]]:
        session = await self.load_session(session_id, user_id)
        return await self.process_user_message(
            session_id=session_id,
            user_id=user_id,
            client_id=session.get("client_id"),
            message=text,
            db=db,
        )

    # --- Trade Proposal Management ---
    async def create_trade_proposal(
        self,
        db: AsyncSession,
        client_id: str,
        symbol: str,
        side: str,
        qty: float,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Creates time-limited trade proposal with price projection,
        records audit entry, sets cache with 15m TTL, and returns proposal dictionary.
        """
        ...

    create_proposal = create_trade_proposal  # Alias for existing callers

    # --- Trade Approval & Execution ---
    async def handle_trade_approval(
        self,
        db: AsyncSession,
        user_id: str,
        proposal_id: str,
        approved: bool,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Handles client authorization decision for a pending trade proposal:
        - If approved: enforces 15m window, KYC, compliance check (REG-003, 004, CONC-001, AML),
          30s duplicate submit lock, Alpaca/simulated fill, DB persistence, and audit logging.
        - If rejected: evicts proposal, logs audit, and notifies user.
        Returns list of generated events.
        """
        ...

    execute_proposal = handle_trade_approval  # Alias for existing callers

    # --- Specialized Flow Dispatchers ---
    async def recommend_allocation(
        self,
        db: AsyncSession,
        client_id: str,
    ) -> List[Dict[str, Any]]:
        ...

    async def compare_products(
        self,
        db: AsyncSession,
        client_id: str,
        symbols: List[str],
        bonds: bool = False,
    ) -> List[Dict[str, Any]]:
        ...

    async def generate_health_report(
        self,
        db: AsyncSession,
        client_id: str,
    ) -> List[Dict[str, Any]]:
        ...
```

---

### 4.3 Structured Event Specifications (8 Standard Event Types)

All public methods return lists of plain dictionaries matching this exact schema specification:

1. **`user_message`**:
   ```json
   {
     "event": "user_message",
     "agent": "User",
     "text": "buy 10 SPY",
     "timestamp": "2026-10-11T12:00:00Z"
   }
   ```
2. **`agent_response`**:
   ```json
   {
     "event": "agent_response",
     "agent": "Orchestrator",
     "text": "Sanitized advice text with mandatory risk disclosures...",
     "timestamp": "2026-10-11T12:00:01Z",
     "weights": {"SPY": 0.6, "BND": 0.4}
   }
   ```
3. **`bias_alert`**:
   ```json
   {
     "event": "bias_alert",
     "agent": "BehavioralBias",
     "text": "Market pullbacks are normal volatility. Cashing out crystallizes paper losses...",
     "bias_type": "loss_aversion",
     "severity": "high",
     "confidence": 0.85,
     "cool_off_recommended": true,
     "timestamp": "2026-10-11T12:00:01Z"
   }
   ```
4. **`compliance_check`**:
   ```json
   {
     "event": "compliance_check",
     "agent": "ComplianceGuard",
     "passed": true,
     "details": {"checks": [...]},
     "violations": [],
     "warnings": [],
     "timestamp": "2026-10-11T12:00:02Z"
   }
   ```
5. **`trade_proposal`**:
   ```json
   {
     "event": "trade_proposal",
     "agent": "Orchestrator",
     "text": "Proposed order: BUY 10 SPY at about $510.50 (~$5,105.00)...",
     "proposal": {
       "proposal_id": "7b6b1...f9",
       "client_id": "c-1234",
       "symbol": "SPY",
       "side": "BUY",
       "qty": 10.0,
       "price": 510.50,
       "notional_value": 5105.00,
       "projected_weight": 0.051,
       "created_at": "2026-10-11T12:00:01Z",
       "expires_in_seconds": 900
     },
     "timestamp": "2026-10-11T12:00:01Z"
   }
   ```
6. **`trade_approved`**:
   ```json
   {
     "event": "trade_approved",
     "agent": "User",
     "text": "Approved BUY 10 SPY",
     "proposal": {...},
     "timestamp": "2026-10-11T12:00:02Z"
   }
   ```
7. **`trade_filled`**:
   ```json
   {
     "event": "trade_filled",
     "agent": "ExecutionModule",
     "text": "Order FILLED: BUY 10 SPY at $510.50 (simulated paper fill).",
     "execution": {
       "success": true,
       "order_id": "alpaca_sim_9a8b",
       "trade_id": "trade_c7e1",
       "client_id": "c-1234",
       "proposal_id": "7b6b1...f9",
       "symbol": "SPY",
       "side": "BUY",
       "qty": 10.0,
       "filled_price": 510.50,
       "status": "FILLED",
       "dry_run": true
     },
     "timestamp": "2026-10-11T12:00:03Z"
   }
   ```
8. **`portfolio_update`**:
   ```json
   {
     "event": "portfolio_update",
     "agent": "PortfolioService",
     "portfolio": {
       "source": "ledger",
       "cash": 94895.00,
       "total_value": 100000.00,
       "positions": [{"symbol": "SPY", "qty": 10.0, "market_value": 5105.00, "weight": 0.05105}],
       "weights": {"SPY": 0.05105}
     },
     "timestamp": "2026-10-11T12:00:03Z"
   }
   ```
9. **`error`**:
   ```json
   {
     "event": "error",
     "agent": "ExecutionModule",
     "error": "ComplianceViolationError",
     "text": "Trade blocked: Projected weight exceeds single-stock ceiling (CONC-001)",
     "violations": [{"rule_id": "CONC-001", "severity": "BLOCK"}],
     "timestamp": "2026-10-11T12:00:02Z"
   }
   ```

---

## 5. Comprehensive Test Scenarios for `test_orchestrator.py`

To ensure full test suite coverage and rigorous verification of Milestone 5, the following test scenarios must be implemented in `backend/tests/unit/test_orchestrator.py`:

### Group 1: Session State Machine & Lifecycle Transitions
- **`test_session_start_profiling_vs_advising`**:
  * Case A: Start session without `client_id` $\to$ stage is `PROFILING`, greeting prompts demographics.
  * Case B: Start session with existing `client_id` $\to$ stage is `ADVICE_GENERATION`, greeting offers advisory options.
- **`test_profiling_state_progression_to_advising`**:
  * Execute sequential profiling turns (demographics, income, horizon, risk tolerance, PEP status).
  * Verify `RiskProfiler` responses are returned and gated.
  * On final synthesis turn, verify state transitions to `ADVICE_GENERATION`, `client_id` is assigned to session, and `PROFILE_COMPLETED` audit log is written.
- **`test_proposal_review_state_entry_and_exit`**:
  * In `ADVICE_GENERATION`, send "buy 5 BND".
  * Verify transition to `PROPOSAL_REVIEW` with `pending_proposal_id` stored in session.
  * User sends "reject" $\to$ proposal deleted from cache, `TRADE_REJECTED_BY_USER` audited, session reverts to `ADVICE_GENERATION`.

### Group 2: Intent Routing & Multi-Agent Dispatching
- **`test_market_quote_routing`**:
  * User message: "quote SPY" or "price of AAPL".
  * Verify `MarketDataAgent.get_quote` is called and price snapshot event is returned.
- **`test_macro_indicators_routing`**:
  * User message: "how is the economy and what are treasury rates?"
  * Verify `MarketDataAgent.get_macro_context` and `get_yield_curve` are called.
- **`test_compare_etfs_routing`**:
  * User message: "compare SPY VTI QQQ".
  * Verify `ProductComparisonAgent.compare_etfs` is invoked with parsed tickers.
  * Verify ranked list, composite scores, and winning symbol are returned in response.
- **`test_compare_bonds_routing`**:
  * User message: "compare bonds BND AGG".
  * Verify `ProductComparisonAgent.compare_bonds` is invoked with `bonds=True`.
- **`test_allocation_recommendation_routing`**:
  * User message: "recommend a portfolio for me".
  * Verify `AllocationEngine.generate_allocation` is invoked.
  * Verify `ComplianceGuard.check_recommendation` evaluates suitability.
  * Verify `RECOMMENDATION_GENERATED` audit log is written.
- **`test_health_monitoring_and_rebalancing_routing`**:
  * User message: "how is my portfolio health and check drift".
  * Verify transition to `HEALTH_MONITORING`.
  * Verify `HealthReportService.generate_health_report` is called.
  * Verify portfolio check timestamp is recorded.

### Group 3: Universal Compliance Output Gating
- **`test_gate_text_blocks_prohibited_guarantee_language_reg001`**:
  * Input text: `"Our algorithm guarantees 15% risk-free returns with zero chance of loss."`
  * Verify text is completely stripped of prohibited phrases and replaced with `SAFE_REPLACEMENT`.
  * Verify `OUTPUT_FILTERED` audit log is written with status `WARN`.
- **`test_gate_text_injects_mandatory_risk_disclosure_reg002`**:
  * Input text: `"We recommend buying VTI for long-term index growth."`
  * Verify output text has standard disclosure appended: `"Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."`
- **`test_allocation_blocked_by_compliance_guard`**:
  * Mock `ComplianceGuard.check_recommendation` to return `passed=False` with `SUIT-001` violation.
  * Verify allocation is NOT emitted to user; instead, `compliance_check` block event is emitted.

### Group 4: Non-Discretionary Trade Proposal & Execution Gate
- **`test_trade_without_user_approval_is_blocked_reg003`**:
  * Call `handle_trade_approval(..., approved=False)`.
  * Verify trade is blocked, `ExecutionModule` is never called, and `TradeBlocked` exception or error event is raised.
- **`test_expired_trade_approval_is_blocked_reg004`**:
  * Create proposal, manually advance proposal creation time or TTL past 15 minutes.
  * Call `handle_trade_approval(..., approved=True)`.
  * Verify 404 / 400 Expired error is raised.
- **`test_concentration_violation_blocks_trade_conc001`**:
  * Submit trade proposal that would take a single equity to 25% of portfolio value.
  * Approve trade.
  * Verify `ComplianceGuard.check_trade` raises `CONC-001` violation.
  * Verify trade is not sent to broker.
- **`test_duplicate_trade_submission_lock_rejection`**:
  * Execute an approved trade for client A.
  * Immediately submit a second trade for client A within 30 seconds.
  * Verify 409 Conflict / `DuplicateTradeError` lock rejection.
- **`test_successful_end_to_end_trade_flow`**:
  * Propose: "buy 10 BND".
  * Approve: "approve".
  * Verify sequence of events: `trade_approved` $\to$ `compliance_check` (passed) $\to$ `trade_filled` $\to$ `portfolio_update`.
  * Verify proposal is evicted from cache and `trades` table contains filled record.

### Group 5: Behavioral Bias Interventions & Telemetry
- **`test_dialogue_loss_aversion_detection`**:
  * User message: `"The market is crashing, I want to sell all my positions and move to cash!"`
  * Verify `bias_alert` event is emitted with `bias_type: loss_aversion`, `severity: high`, and calming intervention text recommending cool-off.
- **`test_dialogue_overconfidence_detection`**:
  * User message: `"I'm 100% sure this stock is going to 10x, diversification is for losers."`
  * Verify `bias_alert` event is emitted with `bias_type: overconfidence`.
- **`test_rapid_portfolio_check_telemetry_signal`**:
  * Call health report endpoint 3 times in rapid succession for same client ID.
  * Verify `BehavioralBiasAgent.record_portfolio_check` returns `rapid_checks` telemetry signal.
  * Verify anxiety/cool-off guidance is surfaced to client.

### Group 6: Session Security & Multi-Tenant Isolation
- **`test_cross_user_session_access_denied`**:
  * User B attempts to access `session_id` belonging to User A.
  * Verify 403 Forbidden is raised.
- **`test_cross_user_proposal_execution_denied`**:
  * User B attempts to approve `proposal_id` belonging to User A's client profile.
  * Verify 403 Forbidden is raised.

---

## 6. Implementation Plan & Source File Changes

When moving from design to implementation (Task Execution):
1. **Refactor `backend/agents/orchestrator.py`**:
   - Add `SessionStage(str, Enum)` with all 5 states.
   - Implement `process_user_message(session_id, user_id, client_id, message, db)` conforming to the canonical Milestone 5 signature.
   - Retain `handle_message` as backward-compatible facade.
   - Implement `create_trade_proposal` and `handle_trade_approval`, aliasing `create_proposal` and `execute_proposal`.
   - Implement intent routing for market quotes, macro context, and rebalancing requests.
   - Ensure `gate_text` is invoked on all response pathways.
2. **Implement Unit Test Suite `backend/tests/unit/test_orchestrator.py`**:
   - Write comprehensive tests covering all 6 test groups detailed in Section 5.
3. **Verify API Routes & Lifespan**:
   - Ensure `backend/api/routes/advisory.py`, `portfolio.py`, and `ws.py` seamlessly invoke both canonical and legacy orchestrator methods.
   - Verify `pytest` passes with 100% compliance rule coverage and $\ge 80\%$ line coverage.

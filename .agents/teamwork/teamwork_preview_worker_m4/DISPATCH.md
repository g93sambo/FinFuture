## 2026-10-10T17:51:23Z
You are the Worker for Milestone 4 (Compliance, Execution & Health Report) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m4
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Explorer findings to read and follow:
- Explorer 1 (Compliance Guard): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_1\handoff.md and analysis.md
- Explorer 2 (Execution Module): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_2\handoff.md and analysis.md
- Explorer 3 (Health Report Service): c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_3\handoff.md and analysis.md

Write Ownership:
You own exclusively:
- backend/agents/compliance_guard.py
- backend/agents/execution_module.py
- backend/services/health_report.py
- backend/tests/unit/test_compliance_guard.py
- backend/tests/unit/test_execution_module.py
- backend/tests/unit/test_health_report.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Implementation Requirements:

1. backend/agents/compliance_guard.py:
   - Dynamic rule loading: query `compliance_rules` table via SQLAlchemy AsyncSession with full 12-rule static in-memory fallback if DB is unseeded or empty.
   - Comprehensive implementation of all 12 rules:
     * SUIT-001: Risk Profile Alignment (recommendation risk level <= client risk tolerance score + 1; block if violated)
     * SUIT-002: Time Horizon Constraint (horizon < 3 years requires max equity 40%, no high-duration > 7y bonds or illiquid assets; block if violated)
     * SUIT-003: Loss Capacity Ceiling (low loss capacity caps equity risk at Moderate; block if violated)
     * CONC-001: Single Stock Limit (single equity allocation <= 15% of total portfolio; block if violated)
     * CONC-002: Sector Concentration Limit (single sector allocation <= 30% of total portfolio; block if violated)
     * CONC-003: Minimum Asset Class Diversification (portfolio must contain at least 2 distinct asset classes; warn/block if violated)
     * REG-001: Prohibited Language Filter (blocks text containing 'guaranteed', 'risk-free', 'can\'t lose', 'no risk', 'sure thing', 'promise high returns')
     * REG-002: Mandatory Risk Disclosure (verifies that any recommendation text includes standard investment risk disclosures e.g. 'Past performance is no guarantee of future results' or 'Investing involves risk, including possible loss of principal'; appends or blocks if missing)
     * REG-003: Non-Discretionary Confirmation (trade execution requires explicit client approval flag user_approved == True; blocks execution if False)
     * REG-004: Stale Approval Window (trade approval timestamp must be within the last 15 minutes / 900s; blocks if expired)
     * AML-001: Single Transaction Limit (single order notional value <= $100,000 without enhanced KYC / AML review; blocks if exceeded)
     * AML-002: Rapid Velocity Limit (blocks more than 5 trade orders within 10 minutes for a client)
   - Cryptographic audit logging: every check logs an entry into `DBAuditLog` via `AuditLogger.log_audit_entry` recording check results, passed status, violations, and details.
   - Public signatures:
     * `async check_recommendation(db: AsyncSession, client_id: str, recommendation: dict, profile: Any, portfolio: Optional[dict] = None) -> ComplianceCheckResult`
     * `async check_trade(db: AsyncSession, client_id: str, trade: dict, profile: Any) -> ComplianceCheckResult`
     * `check_text_output(text: str) -> Tuple[bool, List[str], str]`
     * `async get_active_rules(db: AsyncSession) -> List[Any]`
     * Retain backward-compatible methods/dataclasses so existing callers don't break.

2. backend/agents/execution_module.py:
   - Paper trading enforcement: `paper=True` hard-enforced; refuse any live trading environment.
   - Alpaca `TradingClient` integration with graceful dual-engine `DRY_RUN` fallback when credentials or library are absent.
   - Pre-trade validation gates:
     * Non-discretionary user approval verified (`approved == True`, enforcing REG-003).
     * 15-minute approval freshness window verified (`approval_timestamp >= now - 15 minutes`, enforcing REG-004).
     * KYC verification check: verify client profile has `kyc_verified == True`.
     * 30-second double-submit lock: acquire distributed lock `lock:trade:{client_id}` via `CacheService.acquire_lock` with 30s TTL. If lock is held, reject trade immediately (`ValueError("Duplicate submit rejected: trade in progress within 30 seconds")` or HTTP 429).
   - Order execution flow:
     * In live/paper mode: submit market order to Alpaca via `TradingClient`.
     * In dry-run mode: generate authentic simulated fill with order ID, timestamp, and price.
     * Fill polling / order status retrieval helper.
   - Database persistence:
     * Insert record into `trades` table (`DBTrade`) with order_id, client_id, proposal_id, symbol, side, qty, filled_price, status, and executed_at.
   - Audit logging:
     * Log audit entry via `AuditLogger.log_audit_entry` (`TRADE_EXECUTED` or `TRADE_BLOCKED`) with order details, signature, and client ID.
   - Public signatures:
     * `async execute_trade(db: AsyncSession, client_id: str, proposal_id: str, symbol: str, side: str, qty: float, approved: bool, approval_timestamp: datetime, dry_run: Optional[bool] = None) -> TradeExecutionResult`
     * `async get_order_status(order_id: str) -> dict`
     * Backward-compatible `place_order(symbol: str, qty: float, side: str, user_approved: bool) -> dict`.

3. backend/services/health_report.py:
   - Clean Pydantic data schemas: `DriftItem`, `DriftAnalysisResult`, `TurnoverMetrics`, `ConcentrationMetrics`, `BenchmarkComparisonResult`, `HealthScoreBreakdown`, `AlertItem`, `RebalanceOrder`, `NarrativeSection`, `HealthReportResponse`.
   - Portfolio drift analysis:
     * Compare current asset allocations against target allocation weights.
     * Calculate absolute drift ($|w_{current} - w_{target}|$) and percentage drift for each asset class.
     * 5% drift threshold trigger: flag asset classes exceeding 0.05 absolute drift as requiring rebalancing.
   - Benchmark comparison:
     * Compare current portfolio asset mix, annualized return estimate, and risk against standard 60/40 benchmark (`SPY` 60%, `BND` 40%) and cash/treasury risk-free benchmark.
   - Portfolio health score composite:
     * Strictly bounded $[0.0, 100.0]$ score: base potential (80), diversification reward ($+0$ to $+20$ based on $N_{eff} = 1/\text{HHI}$), drift penalty ($0$ to $-40$), concentration penalty ($0$ to $-20$ for single positions $>20\%$), and suitability misalignment penalty ($0$ to $-20$).
   - Alert rules engine:
     * Generate structured alerts: `DRIFT_ALERT` (if any asset drift > 5%), `CONCENTRATION_ALERT` (if single position > 20%), `VOLATILITY_ALERT`, `REBALANCE_RECOMMENDED`.
   - Rebalancing trade generator:
     * Strictly ordered SELL-before-BUY orders to preserve liquidity, respecting $\pm 1\%$ target tolerance band and $\$10.00$ minimum trade dusting threshold.
   - Dual-mode narrative generator:
     * LLM generation via OpenAI with full deterministic markdown templated fallback for offline/CI execution. Strict adherence to `REG-001` (zero guarantee language) and `REG-002` (mandatory regulatory risk disclosures).
   - Public signatures:
     * `HealthReportService` class
     * `async generate_health_report(db: AsyncSession, client_id: str, portfolio: Optional[dict] = None, target_weights: Optional[dict] = None) -> HealthReportResponse`
     * `calculate_drift(current_weights: dict, target_weights: dict, threshold: float = 0.05) -> DriftAnalysisResult`
     * `compute_health_score(drift_result: DriftAnalysisResult, concentration_metrics: dict) -> float`

4. Unit Testing:
   - Implement tests in backend/tests/unit/:
     * `test_compliance_guard.py`: all 12 rules tested with both PASS and FAIL cases; text output filter blocking 'guaranteed' and enforcing risk disclosures; DB dynamic loading; audit logging verification.
     * `test_execution_module.py`: successful paper trade execution, 30s double-submit lock rejection, unapproved trade rejection (`REG-003`), expired approval rejection (`REG-004`), KYC unverified rejection, dry-run mode, and audit logging.
     * `test_health_report.py`: 5% drift threshold trigger, health score bounds [0, 100], alert rules, SELL-before-BUY rebalancing order generation, and offline narrative execution.
   - Run pytest to ensure all new unit tests pass and all 334 existing repo tests pass without regression.
   - Verify coverage meets the >=80% gate: `pytest -q --cov=agents.compliance_guard --cov=agents.execution_module --cov=services.health_report`

5. Handoff:
   - Write completion report to `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m4\handoff.md`.
   - Send completion message to orchestrator with test results and coverage metrics.

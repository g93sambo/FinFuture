# Dispatch: Milestone 4 Explorer 1 (Compliance Guard)
- Working Directory: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_1
- Role: M4 Compliance Guard Explorer
- Objective: Design architecture and implementation specifications for backend/agents/compliance_guard.py.

## 2026-10-10T17:44:59Z
You are Explorer 1 for Milestone 4 (Compliance Guard) of the Wealth Advisory Agent backend.
Working directory: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_1
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Scope & Tasks:
1. Read ORIGINAL_REQUEST.md and PROJECT.md.
2. Inspect backend/agents/compliance_guard.py, backend/db/models.py (specifically DBComplianceRule and DBAuditLog), and backend/services/audit_logger.py.
3. Design the architecture and implementation specifications for backend/agents/compliance_guard.py:
   - Dynamic loading of rules: query `compliance_rules` table via SQLAlchemy async session, with static in-memory fallback for all 12 rules if DB table is unseeded or empty.
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
   - Audit logging: EVERY compliance check execution MUST log an audit entry via `AuditLogger.log_audit_entry` recording check results, passed status, violations, and details.
   - Public class and method signatures:
     * ComplianceGuard class
     * async check_recommendation(db: AsyncSession, client_id: str, recommendation: dict, profile: DBClientProfile, portfolio: Optional[dict] = None) -> ComplianceCheckResult
     * async check_trade(db: AsyncSession, client_id: str, trade: dict, profile: DBClientProfile) -> ComplianceCheckResult
     * check_text_output(text: str) -> Tuple[bool, List[str], str] (validates REG-001 and REG-002, returns (passed, violations, sanitized_text))
     * async get_active_rules(db: AsyncSession) -> List[DBComplianceRule]
4. Detail comprehensive test scenarios covering both passing and failing cases for all 12 rules.
5. Write your complete analysis to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m4_1\analysis.md and structured handoff.md.
6. Send a message to the orchestrator upon completion.

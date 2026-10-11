# Milestone 4 Explorer 1 Analysis: Compliance Guard Architecture & Implementation Specifications

**Agent**: Explorer 1 (`teamwork_preview_explorer_m4_1`)  
**Domain**: Milestone 4 — Regulatory, Suitability, Concentration, AML Compliance & Output Filtering  
**Target File**: `backend/agents/compliance_guard.py`  
**Date**: 2026-10-10  

---

## 1. Executive Summary & Mission Overview

In an institutional-grade, multi-agent automated wealth advisory architecture, the **Compliance Guard** (`agents/compliance_guard.py`) serves as the non-bypassable supervisory control and regulatory enforcement layer. Operating in accordance with SEC Regulation Best Interest (Reg BI), FINRA Rule 2111 (Suitability), the Investment Advisers Act of 1940 (Anti-Fraud and Marketing Rule § 206(4)-1), and Bank Secrecy Act / Anti-Money Laundering (BSA/AML) standards, the Compliance Guard intercepts:
1. **Investment Recommendations & Portfolio Allocations** (`check_recommendation`): Validates suitability against client risk profile, investment horizon, loss capacity, single-stock concentration, sector concentration, and minimum asset class diversification.
2. **Order Executions** (`check_trade`): Enforces non-discretionary client approval confirmation (`REG-003`), approval freshness windows (`REG-004`), single transaction notional limits (`AML-001`), and rapid order velocity limits (`AML-002`).
3. **Client-Facing Communications & AI Outputs** (`check_text_output`): Sanitizes and validates conversational responses against prohibited promissory / guaranteed return phrasing (`REG-001`) and enforces mandatory regulatory risk disclosures (`REG-002`).
4. **Append-Only Cryptographic Audit Logging**: Every compliance check execution writes a hash-chained, HMAC-signed audit log entry into `DBAuditLog` via `AuditLogger.log_audit_entry`, establishing a non-repudiable supervisory record.

---

## 2. Current Baseline & Gap Analysis

### 2.1 Inspection of `backend/agents/compliance_guard.py`
The existing implementation is a preliminary 72-line stub:
- **Missing Rules**: Only implements rudimentary definitions for `SUIT-001` and `REG-003`. 10 of the 12 required compliance rules (`SUIT-002`, `SUIT-003`, `CONC-001`, `CONC-002`, `CONC-003`, `REG-001`, `REG-002`, `REG-004`, `AML-001`, `AML-002`) are completely absent.
- **No Dynamic Database Loading**: Rules are hardcoded as static lambda objects in `__init__`. Does not query the `compliance_rules` table via SQLAlchemy `AsyncSession`.
- **No In-Memory Fallback Mechanism**: If DB is empty or during standalone offline unit tests, there is no standardized dictionary fallback for all 12 rules.
- **No Audit Logger Integration**: Does not call `AuditLogger.log_audit_entry`, violating the fundamental requirement that all compliance evaluations must produce verifiable audit log entries.
- **Missing Required Interface Methods**:
  - Missing `async check_trade(db, client_id, trade, profile)`
  - Missing `check_text_output(text)`
  - Missing `async get_active_rules(db)`
- **Incompatible Signature for Recommendations**: Currently defines `async def check_recommendation(self, recommendation: dict, profile: Any, portfolio: Any = None) -> dict`, lacking `db: AsyncSession` and `client_id: str`.

### 2.2 Inspection of Database Models (`backend/db/models.py`)
- `DBComplianceRule` (`models.py:209-222`):
  - Primary key: `rule_id` (e.g. `SUIT-001`, `CONC-001`).
  - Columns: `name`, `category` (`SUITABILITY`, `CONCENTRATION`, `REGULATORY`, `AML`), `severity` (`BLOCK`, `WARN`), `parameters` (`JSON`), `description` (`Text`), `is_active` (`Boolean`), `created_at`, `updated_at`.
- `DBAuditLog` (`models.py:163-192`):
  - Cryptographically chained audit trail with ORM append-only invariant listeners (`prevent_audit_log_instance_update`, `prevent_audit_log_instance_delete`, `prevent_audit_log_bulk_mutation`).
- `DBTrade` (`models.py:134-162`):
  - Captures `client_id`, `symbol`, `qty`, `side`, `order_type`, `status`, `compliance_report` (JSON), `user_approved_at`, `created_at`.
- `DBClientProfile` (`models.py:55-117`):
  - Contains `risk_tolerance_score`, `investment_horizon_years`, `liquidity_needs`, `loss_capacity`, `suitability_category`, `kyc_verified`, `aml_flag`.

### 2.3 Inspection of Audit Logger (`backend/services/audit_logger.py`)
- `AuditLogger.log_audit_entry(db, client_id, event_type, actor, details, status, session_id, hmac_key)`:
  - Appends SHA-256 hash-chained and HMAC-signed records into `DBAuditLog`.
  - Serialized per `client_id` with `asyncio.Lock` to guarantee chain linearizability without forks.
  - Can be called via singleton `get_audit_logger().log_audit_entry(...)` or module function `log_audit_entry(...)`.

---

## 3. Core Architectural Design

```
                     +---------------------------------------+
                     |         Caller / Orchestrator         |
                     +---------------------------------------+
                        |                 |                |
    check_recommendation|      check_trade|check_text_output|
                        v                 v                v
+-------------------------------------------------------------------------+
|                         ComplianceGuard Agent                           |
|                                                                         |
|  +-------------------------------------------------------------------+  |
|  |                     Dynamic Rule Catalog Engine                   |  |
|  |  1. Query DB `compliance_rules` table via SQLAlchemy AsyncSession |  |
|  |  2. In-Memory Static Fallback (All 12 rules loaded if DB empty)   |  |
|  |  3. Active status (`is_active`) & parameter override filter       |  |
|  +-------------------------------------------------------------------+  |
|                                                                         |
|  +-----------------------+ +-----------------------+                    |
|  |   Suitability Rules   | |  Concentration Rules  |                    |
|  |  * SUIT-001 (Risk)    | |  * CONC-001 (Stock)   |                    |
|  |  * SUIT-002 (Horizon) | |  * CONC-002 (Sector)  |                    |
|  |  * SUIT-003 (Loss Cap)| |  * CONC-003 (Classes) |                    |
|  +-----------------------+ +-----------------------+                    |
|  +-----------------------+ +-----------------------+                    |
|  |   Regulatory Rules    | |       AML Rules       |                    |
|  |  * REG-001 (Language) | |  * AML-001 (Notional) |                    |
|  |  * REG-002 (Disclosure| |  * AML-002 (Velocity) |                    |
|  |  * REG-003 (Approval) | +-----------------------+                    |
|  |  * REG-004 (Freshness)|                                              |
|  +-----------------------+                                              |
+-------------------------------------------------------------------------+
       |                                              |
       | Severity Evaluation:                         | Cryptographic
       | - Any BLOCK violated -> passed = False       | Audit Trail
       | - Only WARN violated  -> passed = True       |
       v                                              v
+-----------------------------+         +-------------------------------+
|    ComplianceCheckResult    |         |          AuditLogger          |
| - passed: bool              |         | log_audit_entry(...)          |
| - violations: List          |         | - event_type: COMPLIANCE_...  |
| - warnings: List            |         | - SHA-256 chain + HMAC        |
| - rule_results: List        |         | - Target: DBAuditLog          |
+-----------------------------+         +-------------------------------+
```

### 3.1 Dual-Mode Rule Loading (DB + In-Memory Fallback)
1. **Database-Driven Configuration**: At evaluation time, `ComplianceGuard.get_active_rules(db)` executes:
   ```python
   stmt = select(DBComplianceRule).where(DBComplianceRule.is_active == True)
   result = await db.execute(stmt)
   db_rules = result.scalars().all()
   ```
2. **Deterministic Fallback**: If `db_rules` is empty (e.g., test fixtures without seed scripts, unmigrated schemas, or disconnected DB), the guard seamlessly instantiates rule models from `DEFAULT_COMPLIANCE_RULES`.
3. **Parameter Merging**: If a rule exists in the database, its database parameters (`rule.parameters`) and severity (`rule.severity`) take precedence, allowing compliance officers to tune thresholds dynamically without code redeployments.

### 3.2 Evaluation Pipeline & Severity Semantics
- **`BLOCK` Severity**: A violation of any active `BLOCK` rule causes the entire check to fail (`passed = False`), populating the `violations` list. If requested or configured, a `ComplianceViolationError` is raised.
- **`WARN` Severity**: A violation of a `WARN` rule (such as `CONC-003`) is appended to `warnings`. It does not prevent execution or advice generation (`passed = True`), but is logged in the cryptographic audit trail for compliance review.

### 3.3 Cryptographic Audit Trail Coupling
Every call to `check_recommendation` and `check_trade` MUST invoke:
```python
await log_audit_entry(
    db=db,
    client_id=client_id,
    event_type=event_type,  # e.g., "COMPLIANCE_RECOMMENDATION_CHECK" or "COMPLIANCE_TRADE_CHECK"
    actor="AGENT:compliance_guard",
    details={
        "target_type": "RECOMMENDATION" | "TRADE",
        "passed": result.passed,
        "violations": [v.to_dict() for v in result.violations],
        "warnings": result.warnings,
        "active_rules_evaluated": [r.rule_id for r in active_rules],
        "evaluated_payload": payload_summary,
    },
    status="PASS" if result.passed else "FAIL"
)
```
This guarantees complete supervisory traceability for audits by FINRA or the SEC.

---

## 4. Comprehensive Specification of All 12 Compliance Rules

### 4.1 SUIT-001: Risk Profile Alignment
- **Category**: `SUITABILITY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: FINRA Rule 2111 (Reasonable-Basis & Customer-Specific Suitability), SEC Reg BI.
- **Parameters**: `{"max_risk_delta": 1.0}`
- **Logic**:
  - Extract client risk tolerance: `client_risk = profile.risk_tolerance_score` (scale 1.0 to 10.0, default 5.0).
  - Extract recommendation risk: `rec_risk = recommendation.get("risk_level")` or weighted average product risk.
  - Allowed threshold: `max_allowed = client_risk + max_risk_delta`.
  - Condition: If `rec_risk > max_allowed`, rule fails with `BLOCK`.
- **Pass Case**: Client risk score = 5.0, recommendation risk level = 6.0 (diff 1.0 <= 1.0).
- **Fail Case**: Client risk score = 4.0, recommendation risk level = 7.0 (diff 3.0 > 1.0).

### 4.2 SUIT-002: Time Horizon Constraint
- **Category**: `SUITABILITY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: FINRA Rule 2111 Investment Profile Component (Time Horizon), SEC Form CRS.
- **Parameters**:
  ```json
  {
    "short_horizon_threshold_years": 3,
    "max_equity_weight": 0.40,
    "max_bond_duration": 7.0,
    "allow_illiquid": false
  }
  ```
- **Logic**:
  - Extract `horizon = profile.investment_horizon_years`.
  - If `horizon < 3`:
    1. **Equity Ceiling**: Proposed equity allocation must be `<= 40%` (0.40).
    2. **Duration Ceiling**: No bond/fixed income holding may have duration `> 7.0` years (or weighted average duration `> 7.0`).
    3. **Liquidity Restriction**: Illiquid assets (`is_liquid == False` or `liquidity == "low"`) are strictly prohibited.
  - If any condition is breached when `horizon < 3`, rule fails with `BLOCK`.
- **Pass Case**: Horizon = 2 years, Equity allocation = 35%, Bond duration = 3.5 years, 100% liquid assets.
- **Fail Case**: Horizon = 2 years, Equity allocation = 65% (violates 40% ceiling) OR Bond duration = 15.0 years (violates 7y duration).

### 4.3 SUIT-003: Loss Capacity Ceiling
- **Category**: `SUITABILITY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Reg BI Care Obligation (evaluating client financial ability to absorb losses).
- **Parameters**:
  ```json
  {
    "low_capacity_max_risk": 5.0,
    "low_capacity_max_equity": 0.50,
    "disallowed_categories": ["Growth", "Aggressive Growth", "Aggressive"]
  }
  ```
- **Logic**:
  - Extract `loss_capacity = str(profile.loss_capacity).lower()`.
  - If `loss_capacity == "low"`:
    1. Maximum allowable recommendation risk level is capped at Moderate (`<= 5.0`).
    2. Maximum equity allocation is capped at `<= 50%` (0.50).
    3. Recommendations categorized as "Growth" or "Aggressive Growth" are blocked.
  - If breached, rule fails with `BLOCK`.
- **Pass Case**: Client loss capacity = "low", Recommendation risk level = 4.5, Equity = 40%, Category = "Moderate Conservative".
- **Fail Case**: Client loss capacity = "low", Recommendation risk level = 7.5 (exceeds 5.0) OR Equity = 70% (exceeds 50%).

### 4.4 CONC-001: Single Stock Limit
- **Category**: `CONCENTRATION` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Investment Company Act of 1940 Diversification Standards & Modern Portfolio Theory.
- **Parameters**: `{"max_single_stock_weight": 0.15}` (15%)
- **Logic**:
  - In recommendations: Inspect asset weights. Any individual single-stock holding (non-broad index ETF) with `weight > 0.15` triggers a violation.
  - In trade execution: Compute projected holding weight: `(current_holding_value + order_notional) / total_portfolio_value`. If `> 0.15`, trade is blocked.
- **Pass Case**: Single equity holding (e.g., AAPL) weight = 12% of total portfolio.
- **Fail Case**: Single equity holding weight = 22% of total portfolio (exceeds 15% limit).

### 4.5 CONC-002: Sector Concentration Limit
- **Category**: `CONCENTRATION` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Prudent Investor Rule & Institutional Concentration Risk Management.
- **Parameters**: `{"max_sector_weight": 0.30}` (30%)
- **Logic**:
  - Evaluate sector breakdown from recommendation or portfolio metadata (e.g. Technology, Healthcare, Financials, Energy).
  - If any single sector has aggregate allocation `weight > 0.30`, rule fails with `BLOCK`.
- **Pass Case**: Technology = 25%, Healthcare = 20%, Financials = 15%, Industrials = 15%, Fixed Income = 25%.
- **Fail Case**: Technology = 42% of total portfolio (exceeds 30% sector limit).

### 4.6 CONC-003: Minimum Asset Class Diversification
- **Category**: `CONCENTRATION` | **Severity**: `WARN` (or `BLOCK` per DB configuration)
- **Parameters**: `{"min_asset_classes": 2, "min_weight_threshold": 0.05}`
- **Logic**:
  - Count distinct asset classes (e.g., Equity, Fixed Income, Cash/Treasury, Commodities, Real Estate) having `weight >= 0.05`.
  - If distinct count `< 2`, rule triggers violation. Default severity is `WARN` (annotates compliance report and audit trail without stopping user execution unless overridden in DB to `BLOCK`).
- **Pass Case**: Portfolio contains 70% Equities and 30% Fixed Income (2 asset classes >= 5%).
- **Fail Case**: Portfolio contains 100% Equities (only 1 asset class, triggers CONC-003 warning).

### 4.7 REG-001: Prohibited Language Filter
- **Category**: `REGULATORY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: SEC Marketing Rule 206(4)-1 (prohibiting untrue, unsubstantiated, or misleading promissory statements), FINRA Rule 2210.
- **Parameters**:
  ```json
  {
    "prohibited_phrases": [
      "guaranteed",
      "risk-free",
      "can't lose",
      "cant lose",
      "no risk",
      "sure thing",
      "promise high returns",
      "100% safe",
      "certain return"
    ]
  }
  ```
- **Logic**:
  - Case-insensitive regex word boundary scanning over text.
  - If any prohibited phrase is detected, `check_text_output` returns `passed = False`, `violations = [f"Prohibited language detected: '{phrase}'"]`.
- **Pass Case**: `"This diversified ETF portfolio targets an annualized expected return of 6.5% with moderate volatility."`
- **Fail Case**: `"This investment offers guaranteed profits with a risk-free strategy."`

### 4.8 REG-002: Mandatory Risk Disclosure
- **Category**: `REGULATORY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: SEC Rule 206(4)-1 & FINRA Rule 2210 Mandatory Investment Disclosures.
- **Parameters**:
  ```json
  {
    "required_phrases": [
      "past performance is no guarantee of future results",
      "investing involves risk, including possible loss of principal"
    ],
    "standard_disclosure": "Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results."
  }
  ```
- **Logic**:
  - Evaluates whether text includes standard regulatory disclosures.
  - If missing:
    - Sets `passed = False` (or flagged in violation list).
    - Automatically generates `sanitized_text` by appending `standard_disclosure`.
- **Pass Case**: Text containing `"Please note that past performance is no guarantee of future results and investing involves risk."`
- **Fail Case**: Text lacking any disclaimer. Function returns `passed = False`, and provides `sanitized_text` containing the original text plus the standard disclosure block.

### 4.9 REG-003: Non-Discretionary Confirmation
- **Category**: `REGULATORY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Advisers Act Fiduciary Duty & Non-Discretionary Advisory Authorization.
- **Parameters**: `{"require_explicit_approval": true}`
- **Logic**:
  - Evaluates trade payload in `check_trade`.
  - Requires `trade.get("user_approved") is True` or `trade.get("approved") is True`.
  - If `False` or omitted, trade is blocked immediately.
- **Pass Case**: `trade = {"symbol": "VTI", "qty": 10, "user_approved": True, ...}` -> Passes.
- **Fail Case**: `trade = {"symbol": "VTI", "qty": 10, "user_approved": False, ...}` -> Blocked with REG-003 violation.

### 4.10 REG-004: Stale Approval Window
- **Category**: `REGULATORY` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Best Execution & Stale Market Order Protection.
- **Parameters**: `{"max_approval_window_seconds": 900}` (15 minutes)
- **Logic**:
  - Extracts `approval_timestamp = trade.get("user_approved_at") or trade.get("approval_timestamp")`.
  - Validates `0 <= (now_utc - approval_timestamp).total_seconds() <= 900`.
  - If older than 900 seconds (15 minutes), or if timestamp is missing or in the future beyond clock skew, trade is blocked.
- **Pass Case**: Approval timestamp recorded 4 minutes ago (240s <= 900s) -> Passes.
- **Fail Case**: Approval timestamp recorded 22 minutes ago (1320s > 900s) -> Blocked with REG-004 violation.

### 4.11 AML-001: Single Transaction Limit
- **Category**: `AML` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Bank Secrecy Act (BSA) Currency Transaction Reporting & Large Order Surveillance.
- **Parameters**: `{"max_single_order_notional": 100000.0, "require_enhanced_kyc": true}`
- **Logic**:
  - Computes order notional: `notional = qty * price` (or `trade.get("notional_value")`).
  - If `notional > 100,000.0`:
    - Checks whether client has verified enhanced KYC (`profile.kyc_verified is True and not profile.aml_flag and trade.get("enhanced_kyc_approved") is True`).
    - If enhanced verification is not present or if `profile.aml_flag is True`, order is blocked.
- **Pass Case**: Trade notional = $45,000 (<= $100,000) -> Passes.
- **Fail Case**: Trade notional = $150,000 without enhanced AML review -> Blocked with AML-001 violation.

### 4.12 AML-002: Rapid Velocity Limit
- **Category**: `AML` | **Severity**: `BLOCK`
- **Regulatory Foundation**: Anti-Churning, Market Manipulation Surveillance & Account Takeover Defense.
- **Parameters**: `{"max_orders_in_window": 5, "window_seconds": 600}` (5 orders in 10 minutes)
- **Logic**:
  - In database mode: Queries `trades` table for orders created by `client_id` in the last 10 minutes:
    ```python
    stmt = select(func.count(DBTrade.id)).where(
        DBTrade.client_id == client_id,
        DBTrade.created_at >= ten_minutes_ago
    )
    recent_order_count = (await db.execute(stmt)).scalar() or 0
    ```
  - In unit test / offline mode: Can accept `recent_orders_count` in `trade` payload.
  - If `recent_order_count >= 5`, the incoming trade exceeds the limit and is blocked.
- **Pass Case**: Client has submitted 2 orders in the last 10 minutes -> Passes.
- **Fail Case**: Client has already submitted 5 orders in the last 10 minutes; 6th order is blocked.

---

## 5. Output Text Filter Architecture (`check_text_output`)

To gate all conversational text generated by LLMs or prompt templates before delivery to clients or WebSockets:
```python
def check_text_output(self, text: str) -> Tuple[bool, List[str], str]:
    """
    Validates conversational output against REG-001 (prohibited language)
    and REG-002 (mandatory risk disclosures).
    
    Returns:
        (passed: bool, violations: List[str], sanitized_text: str)
    """
```
### Pipeline Steps:
1. **REG-001 Scanning**: Compile word-boundary regex patterns for:
   `["guaranteed", "risk-free", "risk free", "can't lose", "cant lose", "no risk", "sure thing", "promise high returns", "100% safe", "certain return"]`.
   If any match is found, add violation.
2. **REG-002 Disclosure Verification**: Check if text contains required phrases:
   `["past performance", "risk of loss", "investing involves risk"]`.
   If absent and text constitutes investment guidance or advice, flag violation and prepare `sanitized_text = text.rstrip() + "\n\n" + STANDARD_DISCLOSURE`.
3. **Outcome**:
   - If REG-001 is violated: `passed = False`, `sanitized_text` remains unsent/flagged.
   - If only REG-002 was missing: `passed = False` (or conditionally sanitizable), `sanitized_text` contains disclosure.

---

## 6. Public Class, Data Models & Method Signatures

### 6.1 Data Models & Results Structures
```python
@dataclass
class ComplianceViolation:
    rule_id: str
    rule_name: str
    category: str
    severity: str  # "BLOCK" | "WARN"
    description: str
    actual_value: Any = None
    threshold: Any = None

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class RuleCheckDetail:
    rule_id: str
    rule_name: str
    category: str
    passed: bool
    severity: str
    details: str

    def to_dict(self) -> dict:
        return asdict(self)

@dataclass
class ComplianceCheckResult:
    passed: bool
    violations: List[ComplianceViolation]
    warnings: List[str]
    rule_results: List[RuleCheckDetail]
    timestamp: datetime
    audit_entry_id: Optional[str] = None
    sanitized_text: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "rule_results": [r.to_dict() for r in self.rule_results],
            "timestamp": self.timestamp.isoformat(),
            "audit_entry_id": self.audit_entry_id,
            "sanitized_text": self.sanitized_text,
        }

class ComplianceViolationError(Exception):
    def __init__(self, violations: List[ComplianceViolation]):
        self.violations = violations
        super().__init__(f"Compliance checks failed: {[v.rule_id for v in violations]}")
```

### 6.2 Core Class Interface (`ComplianceGuard`)
```python
class ComplianceGuard:
    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger or get_audit_logger()
        self._static_fallback_rules = DEFAULT_COMPLIANCE_RULES

    @property
    def rules(self) -> List[Any]:
        """Backwards compatibility property for existing main.py route."""
        return [
            type("RuleObj", (), {
                "id": r["rule_id"],
                "name": r["name"],
                "description": r["description"],
                "severity": r["severity"]
            })()
            for r in self._static_fallback_rules.values()
        ]

    async def get_active_rules(self, db: Optional[AsyncSession] = None) -> List[DBComplianceRule]:
        """
        Dynamically loads active rules from `compliance_rules` table.
        Falls back to in-memory static catalog if table is empty or db is None.
        """
        ...

    async def check_recommendation(
        self,
        db: Optional[AsyncSession],
        client_id: str,
        recommendation: dict,
        profile: DBClientProfile,
        portfolio: Optional[dict] = None
    ) -> ComplianceCheckResult:
        """
        Evaluates recommendation against SUIT-001..003, CONC-001..003, and REG-001..002.
        Logs verifiable audit entry in DBAuditLog.
        """
        ...

    async def check_trade(
        self,
        db: Optional[AsyncSession],
        client_id: str,
        trade: dict,
        profile: DBClientProfile
    ) -> ComplianceCheckResult:
        """
        Evaluates proposed trade against REG-003, REG-004, AML-001, AML-002, and CONC-001.
        Logs verifiable audit entry in DBAuditLog.
        """
        ...

    def check_text_output(self, text: str) -> Tuple[bool, List[str], str]:
        """
        Synchronously validates text against REG-001 and REG-002.
        Returns (passed, violations, sanitized_text).
        """
        ...
```

---

## 7. Comprehensive Test Scenarios (Pass & Fail Matrix for All 12 Rules)

| Rule ID | Category | Severity | Pass Scenario | Fail Scenario |
|---|---|---|---|---|
| **SUIT-001** | SUITABILITY | BLOCK | `profile.risk_tolerance_score = 5.0`, `rec.risk_level = 6.0` (delta = 1.0 <= 1.0) -> PASS | `profile.risk_tolerance_score = 4.0`, `rec.risk_level = 7.0` (delta = 3.0 > 1.0) -> BLOCKED |
| **SUIT-002** | SUITABILITY | BLOCK | `horizon = 2y`, `equity = 0.35`, `duration = 4.0y`, `is_liquid = True` -> PASS | `horizon = 2y`, `equity = 0.60` (exceeds 40%) OR `duration = 9.0y` (exceeds 7y) -> BLOCKED |
| **SUIT-003** | SUITABILITY | BLOCK | `loss_capacity = "low"`, `rec.risk_level = 4.0`, `equity = 0.40` -> PASS | `loss_capacity = "low"`, `rec.risk_level = 7.0` OR `category = "Growth"` -> BLOCKED |
| **CONC-001** | CONCENTRATION | BLOCK | Single equity position `AAPL weight = 0.12` (<= 15%) -> PASS | Single equity position `AAPL weight = 0.22` (> 15%) -> BLOCKED |
| **CONC-002** | CONCENTRATION | BLOCK | Sector weights: `Tech = 0.25, Health = 0.20, Fin = 0.20` (all <= 30%) -> PASS | Sector weights: `Tech = 0.38` (> 30%) -> BLOCKED |
| **CONC-003** | CONCENTRATION | WARN | Portfolio contains `Equity = 0.60, Fixed Income = 0.40` (2 classes >= 5%) -> PASS | Portfolio contains `Equity = 1.00` (1 class only) -> WARN generated, passed=True |
| **REG-001** | REGULATORY | BLOCK | Text: `"This portfolio aims for balanced growth with diversified exposure."` -> PASS | Text: `"Invest now for guaranteed 15% profits risk-free."` -> BLOCKED |
| **REG-002** | REGULATORY | BLOCK | Text contains `"Investing involves risk, including possible loss of principal."` -> PASS | Text without disclosure -> `passed = False`, `sanitized_text` appended with disclosure |
| **REG-003** | REGULATORY | BLOCK | Trade payload: `{"user_approved": True}` -> PASS | Trade payload: `{"user_approved": False}` -> BLOCKED |
| **REG-004** | REGULATORY | BLOCK | Approval timestamp is 5 minutes ago (`300s <= 900s`) -> PASS | Approval timestamp is 20 minutes ago (`1200s > 900s`) -> BLOCKED |
| **AML-001** | AML | BLOCK | Trade order notional = `$45,000` (<= $100,000) -> PASS | Trade order notional = `$180,000` without enhanced KYC -> BLOCKED |
| **AML-002** | AML | BLOCK | Client has 2 orders in last 10 minutes (<= 5) -> PASS | Client has 5 existing orders in last 10m; 6th order is submitted -> BLOCKED |

### Additional Edge Case Scenarios
- **SCENARIO-E1: Empty Database Fallback**: Query DB returns 0 rows. Guard loads fallback catalog; checks proceed without raising exceptions.
- **SCENARIO-E2: Dynamic DB Severity Override**: Compliance officer sets `CONC-003` severity to `BLOCK` in `compliance_rules` table. Portfolio with 1 asset class is now blocked instead of warned.
- **SCENARIO-E3: Inactive Rule Bypass**: A rule is updated in DB with `is_active = False`. Guard ignores the rule during evaluation.
- **SCENARIO-E4: Cryptographic Audit Trail Verification**: After 10 compliance checks, `verify_audit_chain` verifies the entire sequence with 100% hash and HMAC integrity.
- **SCENARIO-E5: Legacy Parameter Adapter**: Calling `check_recommendation(recommendation, profile)` without `db` or `client_id` executes safely via backward-compatible signature.

---

## 8. Concrete Implementation Blueprint

The full proposed implementation structure for `backend/agents/compliance_guard.py` includes:
1. `DEFAULT_COMPLIANCE_RULES` static dictionary covering all 12 rules with standard parameters.
2. Result dataclasses: `ComplianceViolation`, `RuleCheckDetail`, `ComplianceCheckResult`, and `ComplianceViolationError`.
3. Regex compilation for `REG-001` prohibited terms and `REG-002` disclosure matching.
4. Dynamic loading helper `get_active_rules(db)`.
5. `_check_suit_rules`, `_check_conc_rules`, `_check_reg_rules`, `_check_aml_rules` dedicated helper evaluators.
6. Centralized `_record_audit_log` invoking `AuditLogger.log_audit_entry`.
7. `check_text_output` public method returning `(passed, violations, sanitized_text)`.
8. Flexible parameter signatures on `check_recommendation` and `check_trade` handling both modern async DB sessions and legacy caller signatures.

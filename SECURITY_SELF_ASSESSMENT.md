# Security & Compliance Self-Assessment Report (Deliverable #05)

**Competition Track:** 2026 8th FinTechathon — International Track · Topic B: Wealth Advisory Agent ("AI as a Financial Participant")  
**System Name:** FinFuture — Non-Discretionary Multi-Agent Wealth Advisory System (`wealth_agent`)  
**Operating Mandate:** Strictly **Non-Discretionary, Human-in-the-Loop** Advisory & Execution (Autonomous Execution Hard-Disabled in Code)  
**Security Architecture Standard:** Code-Enforced 5-Tier Permission Model + Deterministic 12-Rule Compliance Firewall + Anonymized LLM Context + RFC 6962 On-Chain Audit Trail

---

## 1. Executive Summary

Financial AI agents must never operate as unchecked autonomous traders over client capital. Relying on LLM system prompts alone for fiduciary compliance, arithmetic, or execution gating is fragile due to prompt injection, hallucinated figures, and non-deterministic reasoning.

FinFuture enforces a **strictly non-discretionary, human-in-the-loop architecture** where **the model writes the words, deterministic code supplies the numbers, and no trade can ever execute without explicit human approval under code-enforced limits**:

1. **Strictly Non-Discretionary Mandate (Autonomous Execution Hard-Disabled):** The agent cannot execute trades autonomously. Every order requires an explicit client approval click (`user_approved=True`), and autonomous execution (`TIER_5_AUTONOMOUS_DISABLED`) is hard-disabled in both startup configuration (`core/config.py:guard_autonomous_execution_disabled`) and runtime compliance gates (`PERM-TIER-5`).
2. **Code-Enforced 5-Tier Permission Model:** Rather than a binary allow/deny toggle, FinFuture enforces five distinct operational tiers in code (`TIER_1_READ_ONLY`, `TIER_2_ADVISE`, `TIER_3_PROPOSE_TRADE`, `TIER_4_EXECUTE_WITH_APPROVAL`, and `TIER_5_AUTONOMOUS_DISABLED`), with hard per-trade caps (`$100,000`), rolling 24-hour daily caps (`$250,000`), an 86-symbol vetted instrument whitelist, and Step-Up MFA verification above `$1,000` or `5%` NAV.
3. **Transparent External API & LLM Data Privacy Architecture:** Market, macro, and filing providers (`Yahoo Finance`, `FRED`, `SEC EDGAR`) receive **only ticker symbols or series IDs**. By contrast, the external LLM inference API (`OpenAI` / `Gemini`) necessarily receives the advisory and profiling dialogue (including financial parameters such as age, income/net worth, risk score, and horizon). To protect client privacy, FinFuture strips direct PII (names, emails, phone numbers, SSN/BVN/NIN, account numbers) via `ComplianceGuard.redact_sensitive_data()` before every LLM request and replaces `client_id` / `full_name` with a one-way SHA-256 pseudonym (`ANON-XXXXXXXX`).
4. **12-Rule Pre-Execution Compliance Firewall & Anomaly Circuit Breaker:** Every recommendation and trade ticket is validated by `ComplianceGuard` (`backend/agents/compliance_guard.py`). An automated Anomaly Circuit Breaker trips to `OPEN_LOCKED` for 15 minutes if $\ge 3$ security or compliance violations occur within 60 seconds.
5. **Cryptographic Auditability & On-Chain Anchoring:** Every state transition is recorded in an append-only SHA-256 hash chain signed with HMAC-SHA256, compiled into an **RFC 6962 Binary Merkle Tree**, and anchored to the **Ethereum Sepolia Testnet (`chain_id=11155111`)** with individual Merkle inclusion proofs verifiable in the UI.

---

## 2. Five-Tier Permission Implementation (Enforced in Code)

Implemented in `backend/agents/compliance_guard.py` (`get_permission_tier_catalog()`, `classify_trade_permission_tier()`, `check_trade()`), `backend/agents/orchestrator.py` (`create_trade_proposal()`, `handle_trade_approval()`), and `backend/api/routes/trade.py`, and exposed via `GET /api/v1/compliance/permission-tiers`:

| Tier ID | Badge | Permission Scope | Code-Enforced Limits & Thresholds | Permitted Operations | Enforcement Module & Gate |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`TIER_1_READ_ONLY`** | `GREEN` | **Read-Only Market & Portfolio Data** | `max_notional_usd = $0`; `can_mutate_state = False`; `can_stage_proposal = False` | Fetch quotes & history (`MarketDataService`), FRED macro & yield curves, SEC EDGAR XBRL/10-K filings, read portfolio & verify Merkle proofs | `ToolRegistry` read-only role permissions + `sanitizer.py` XML isolation on external text |
| **`TIER_2_ADVISE`** | `GREEN` | **Advise, Profile & Simulate** | `max_notional_usd = $0`; `can_stage_proposal = False`; `can_execute_trade = False` | Risk profiling (`RiskProfiler`), 6-factor ETF/Bond comparison (`ProductComparator`), Black-Litterman/CVaR & Student-$t$ Monte Carlo (`AllocationEngine`), 3-reviewer verification loop | Deterministic Python quant engines + `RULE-11` guarantee filter + `RULE-12` mandatory risk disclosure |
| **`TIER_3_PROPOSE_TRADE`** | `YELLOW` | **Propose Trade (Draft Unsigned Ticket)** | `proposal_ttl = 900s (15m)`; `symbol_whitelist_enforced = True`; `can_execute_trade = False` | Draft unsigned `TradeProposal` (`create_trade_proposal`), pre-compute post-trade portfolio weight & notional, classify execution verification requirements | `Orchestrator.create_trade_proposal()` enforces `PERM-CIRCUIT-BREAKER` (HTTP 423) and `PERM-WHITELIST` (HTTP 403) before staging; zero broker API calls |
| **`TIER_4_EXECUTE_WITH_APPROVAL`** | `RED` | **Execute with Human Approval Under Hard Limits** | • **Per-Trade Cap:** `$100,000.00` (`AML-001`)<br>• **Daily 24h Cap:** `$250,000.00` (`PERM-CAP-DAILY`)<br>• **Step-Up MFA Threshold:** `> $1,000` or `> 5%` NAV (`PERM-STEP-UP-MFA`)<br>• **Whitelist:** 86 vetted symbols (`PERM-WHITELIST`)<br>• **Idempotency:** 30s lock | Submit approved paper order to Alpaca Paper (`paper-api.alpaca.markets`) or Bamboo Sandbox after human approval and 12-rule compliance pass | `ComplianceGuard.check_trade()` + `ExecutionModule.execute_trade()` enforce `REG-003` (`user_approved=True`), 15-min TTL, 30s lock, `$100k` single cap, `$250k` 24h cap, 86-symbol whitelist, and 6-digit MFA OTP + attestation |
| **`TIER_5_AUTONOMOUS_DISABLED`** | `DISABLED` | **Autonomous / Discretionary Execution (Hard-Disabled)** | `allow_autonomous_execution = False` (immutable startup + runtime invariant) | **None.** Unattended, background, scheduled, or agent-initiated order execution without live per-trade human sign-off is forbidden | 1. `core/config.py`: `guard_autonomous_execution_disabled` refuses startup if enabled<br>2. `api/routes/trade.py`: HTTP 403 on `autonomous=True`<br>3. `ComplianceGuard.check_trade()`: `PERM-TIER-5` hard block |

---

## 3. External API & LLM Data Privacy Architecture

A rigorous security assessment must distinguish between **market data APIs** and **external LLM inference APIs**:

| External Service Class | Providers Used | What Data Leaves the Backend | Privacy & Security Mitigation Enforced in Code |
| :--- | :--- | :--- | :--- |
| **Market, Macro & Filing APIs** | Yahoo Finance, FRED, SEC EDGAR, Finnhub | **Only public ticker symbols (`SPY`, `BND`), CIK numbers, or macro series IDs.** Zero client profile, balance, or conversation data is ever transmitted. | Enforced by typed tool schemas (`GetStockQuoteArgs`, `GetMacroIndicatorsArgs`) in `backend/tools/`. |
| **External LLM Inference API** | OpenAI / Gemini (`AsyncOpenAI` client in `orchestrator.py` and `risk_profiler.py`) | Receives **redacted user messages** (up to the last 8 turns) and an **anonymized suitability context snippet** containing numerical financial parameters (`age`, `risk_score`, `investment_horizon_years`, `liquid_net_worth`, `liquidity_buffer_months`, and portfolio ticker weights) required for advisory synthesis and onboarding extraction. | **1. Pre-LLM Direct PII Redaction (`ComplianceGuard.redact_sensitive_data()`):** Strips self-reported names, email addresses, phone numbers, SSN/BVN/NIN national IDs, credit/debit card numbers, IBANs, and API/bearer tokens from user text and chat history in `orchestrator.py` before calling `client.chat.completions.create()`.<br>**2. Cryptographic Pseudonymization (`context_builder.py`):** `ClientFinancialContext.to_system_prompt_snippet()` replaces `client_id` and `name` with a one-way SHA-256 pseudonym (`ANON-XXXXXXXX`) under `[ANONYMIZED CLIENT SUITABILITY CONTEXT — DIRECT PII REDACTED]`.<br>**3. Local Deterministic Scoring:** Risk scoring and portfolio math run locally in Python, never in the LLM. |
| **Broker Execution Sandbox** | Alpaca Paper Trading (`paper-api.alpaca.markets`), Bamboo Sandbox | Receives only `(symbol, side, qty, type="market", time_in_force="day")` for approved paper orders. | Paper-only endpoint guard (`ExecutionModule`) + zero transmission of client identity or financial profile to the broker API. |

---

## 4. Five Mandatory Competition Security Pillars

| Pillar ID | Competition Requirement | Architectural Implementation | Verification Endpoint / Module |
| :--- | :--- | :--- | :--- |
| **PILLAR-1** | **Prompt Injection Defense** | Two-stage pre-LLM input firewall (`RULE-09`) scanning for jailbreaks, system-prompt overrides, role-play hijacks, and compliance-bypass instructions, plus `<untrusted_external_content>` XML sandboxing (`sanitizer.py`) on all web/filing text. | `ComplianceGuard.check_input_safety()` · `POST /api/v1/compliance/check-input` |
| **PILLAR-2** | **Sensitive Data Redaction & LLM Anonymization** | Regex + token-boundary redaction (`RULE-10`) stripping names, emails, SSN/BVN/NIN, card numbers, IBANs, phone numbers, and secrets before persistence or external LLM calls, paired with `ANON-XXXXXXXX` SHA-256 pseudonymization. | `ComplianceGuard.redact_sensitive_data()` · `ClientFinancialContext.to_system_prompt_snippet()` |
| **PILLAR-3** | **5-Tier Least-Privilege Permission Model** | Explicit 5-tier permission enforcement (`TIER_1_READ_ONLY` to `TIER_5_AUTONOMOUS_DISABLED`) with code-enforced `$100k` per-trade cap, `$250k` daily cap, 86-symbol whitelist, and autonomous execution hard-disabled. | `GET /api/v1/compliance/permission-tiers` · `ComplianceGuard.check_trade()` |
| **PILLAR-4** | **Human-in-the-Loop Confirmation & Circuit Breaker** | Every trade requires a 15-minute cryptographic `proposal_id`, explicit human approval, Step-Up 6-digit MFA OTP + attestation for Red-tier trades (`> $1,000` or `> 5%` NAV), and an **Anomaly Circuit Breaker** that locks execution after $\ge 3$ blocked attempts in 60s. | `TradeTicket.tsx` · `POST /api/v1/compliance/circuit-breaker/simulate` |
| **PILLAR-5** | **Dual-Ledger Auditability (Ethereum Sepolia + WeBank FISCO BCOS v3.6)** | Append-only SHA-256 hash chain + HMAC-SHA256 signatures + RFC 6962 binary Merkle tree root anchored simultaneously to **Ethereum Sepolia (`chain_id=11155111`)** and **WeBank FISCO BCOS v3.6 (`group0` PBFT + WeEvent topic `com.webank.finfuture.audit.anchor`)** via non-blocking worker threads (`asyncio.to_thread`) with per-entry inclusion proofs. | `POST /api/v1/audit/{client_id}/anchor/fisco-bcos` · `GET /api/v1/audit/{client_id}/merkle-proof/{entry_id}` |

---

## 5. Deterministic Compliance Firewall & Permission Gate Catalog

All rules execute deterministically in `backend/agents/compliance_guard.py`:

### A. 12 Core Regulatory Rules (`DEFAULT_COMPLIANCE_RULES`)
1. **`SUIT-001` Risk Score Alignment:** Blocks any asset whose volatility exceeds the client's calibrated risk tolerance ceiling (incorporating behavioral reveal calibration).
2. **`SUIT-002` Investment Horizon Gate:** Blocks illiquid or long-duration instruments when the client's investment horizon is short ($\le 3$ years).
3. **`SUIT-003` Liquidity Buffer Preservation:** Requires preserving at least 3 months of emergency cash buffer (`5%–10%` NAV) post-trade.
4. **`CONC-001` Single-Stock Concentration Limit:** Caps any single equity position at `15%` of total portfolio NAV.
5. **`CONC-002` Single-ETF Concentration Limit:** Caps any single ETF position at `40%` of total portfolio NAV.
6. **`CONC-003` Sector Concentration Limit:** Caps any single GICS sector at `35%` of total portfolio NAV.
7. **`REG-001` No Guarantee Language:** Scans outbound advisory text and blocks any phrase implying guaranteed returns or risk-free equity gains.
8. **`REG-002` Risk Disclosure Required:** Appends mandatory MiFID II / SEC Reg BI / CSRC risk disclosures to advisory outputs.
9. **`REG-003` Non-Discretionary Approval Required:** Blocks any trade execution lacking explicit human approval (`user_approved=True`) and valid approval timestamp.
10. **`REG-004` KYC Verification Gate:** Blocks trade execution for any profile where `kyc_verified` is `False`.
11. **`AML-001` Per-Trade Notional Cap:** Blocks any single order exceeding **`$100,000.00`** (`MAX_SINGLE_TRADE_NOTIONAL_USD`) without enhanced KYC approval.
12. **`AML-002` Rapid Round-Trip Churn Detection:** Blocks >3 round-trip orders on the same symbol within a rolling 24-hour window.

### B. 5 Additional Code-Enforced Permission Gates (`check_trade()`)
- **`PERM-TIER-5` (Autonomous Execution Disabled):** Hard-blocks any trade where `autonomous=True` or `execution_mode="autonomous"`.
- **`PERM-CIRCUIT-BREAKER` (Anomaly Lock Gate):** Hard-blocks proposal staging and execution when the client's Anomaly Circuit Breaker is in `OPEN_LOCKED`.
- **`PERM-WHITELIST` (Approved Symbol Whitelist):** Hard-blocks any ticker not in the 86-symbol vetted universe (`ALLOWED_TRADING_SYMBOLS`).
- **`PERM-CAP-DAILY` (Rolling 24-Hour Daily Notional Cap):** Queries `DBTrade` over the prior 24 hours and blocks execution if `prior_24h_notional + current_notional > $250,000.00` (`MAX_DAILY_TRADE_NOTIONAL_USD`).
- **`PERM-STEP-UP-MFA` (Red-Tier Step-Up MFA & Attestation Gate):** Verifies the 6-digit MFA OTP and fiduciary attestation checkbox on Red-tier orders (`notional > $1,000` or `projected_weight > 5%`).

---

## 6. Known-Risk Register & Mitigation Matrix

Exposed live via `GET /api/v1/compliance/permission-tiers` (`get_known_risk_register()` in `backend/agents/compliance_guard.py`):

| Risk ID | Category | Known Risk Description | Residual Severity | Engineering Mitigation Implemented |
| :--- | :--- | :--- | :--- | :--- |
| **`RISK-01`** | **LLM Hallucination & Unverified Financial Claims** | Generative models may fabricate market prices, yields, Sharpe ratios, or statutory tax citations if allowed to answer from weights. | `LOW` | All numerical figures are computed by deterministic Python engines (`AllocationEngine`, `ProductComparator`, `PortfolioService`), statutory clauses are retrieved from `legal_knowledge.py`, and outbound text is screened by `NumericConsistencyReviewer` and `ComplianceGuard`. |
| **`RISK-02`** | **Prompt Injection & Indirect Web Poisoning** | Malicious user prompts or poisoned SEC/web text could attempt to hijack agent instructions or bypass compliance rules. | `LOW` | Untrusted external content is stripped of scripts/HTML and isolated inside `<untrusted_external_content>` XML tags (`sanitizer.py`), user prompts pass `check_input_safety()` (`RULE-09`), and `ComplianceGuard` runs outside the LLM in pure Python. |
| **`RISK-03`** | **Unauthorized or Excessive Order Execution** | An agent or compromised session might attempt autonomous execution, out-of-universe meme-stock trades, or excessive daily volume. | `LOW` | Enforced 5-Tier Permission Model: Tier 5 autonomous mode is hard-disabled in config and code (`PERM-TIER-5`); Tier 4 enforces `$100k` per-trade cap (`AML-001`), `$250k` 24h daily cap (`PERM-CAP-DAILY`), 86-symbol whitelist (`PERM-WHITELIST`), 30s idempotency lock, and Step-Up MFA (`PERM-STEP-UP-MFA`). |
| **`RISK-04`** | **External LLM Inference Privacy Exposure** | While market/macro APIs receive only ticker symbols, external LLM inference APIs receive the profiling and advisory conversation (including income, net worth, age, and risk preferences). | `LOW` | `ComplianceGuard.redact_sensitive_data()` strips names, emails, phone numbers, SSN/BVN/NIN, card numbers, and IBANs before every LLM call (`orchestrator.py`), and `ClientFinancialContext.to_system_prompt_snippet()` replaces `client_id` and `name` with a one-way SHA-256 pseudonym (`ANON-XXXXXXXX`). |
| **`RISK-05`** | **Market Data Latency & Stale Quotes** | External Yahoo Finance / FRED feeds may experience rate-limiting or delayed ticks during volatile market opens. | `LOW` | Multi-provider fallback pipeline with explicit provenance tags (`live` vs `cached` vs `fallback`); static test fixtures are isolated under `data:fixture_quotes:*` in production so live market quotes are never shadowed. |
| **`RISK-06`** | **Audit Log Tampering & Repudiation** | Post-hoc modification of database rows to conceal compliance failures or trade approvals. | `LOW` | Append-only SHA-256 hash chain (`entry_hash = SHA256(prev_hash || payload)`) + HMAC-SHA256 signatures + RFC 6962 binary Merkle tree root anchored to Ethereum Sepolia (`chain_id=11155111`). |

---

## 7. Verification & Reproducibility Instructions for Judges

1. **Automated Security & Compliance Test Suite:**
   ```bash
   $env:PYTHONPATH="backend;."; python -m pytest backend/tests/unit/test_compliance_guard.py backend/tests/unit/test_challenger_m4_compliance.py backend/tests/unit/test_challenger_m5_security.py -v
   ```
2. **Interactive Security & 5-Tier Permission Console (`/app/compliance`):**
   - Inspect all **5 Permission Tiers (`TIER_1_READ_ONLY` to `TIER_5_AUTONOMOUS_DISABLED`)** and their code-enforced limits (`$100k` single cap, `$250k` daily cap, 86-symbol whitelist).
   - Trigger a live **Anomaly Circuit Breaker Stress Test** (`POST /api/v1/compliance/circuit-breaker/simulate`) and verify that trade staging and execution lock immediately (`OPEN_LOCKED`).
   - Test the **Prompt Injection & PII Redaction Endpoint** (`POST /api/v1/compliance/check-input`).
3. **Red-Tier Step-Up MFA Execution Gate (`/app/trade` or `/app/advisor`):**
   - Draft any trade with notional $> \$1,000$ or portfolio weight $> 5\%$ to trigger the **`RED TIER · Strong Verification`** gate requiring the 6-digit MFA OTP and non-discretionary attestation checkbox, verified both in UI and in `ComplianceGuard.check_trade()` (`PERM-STEP-UP-MFA`).
4. **On-Chain Merkle Inclusion Proof Verification (`/app/audit`):**
   - Expand any signed audit entry and click **"Verify RFC 6962 Merkle Inclusion Proof"** to inspect its leaf hash, sibling audit path, and Sepolia anchor transaction.

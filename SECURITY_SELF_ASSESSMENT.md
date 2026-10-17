# Security & Compliance Self-Assessment Report (Deliverable #05)

**Competition Track:** 2026 8th FinTechathon — International Track · Topic B: Wealth Advisory Agent ("AI as a Financial Participant")  
**System Name:** Fiduciary Wealth Advisory Multi-Agent System (`wealth_agent`)  
**Security Architecture Standard:** Deterministic Compliance Firewall + Tiered Permission Matrix + RFC 6962 On-Chain Audit Trail

---

## 1. Executive Summary

Financial AI agents face a fundamental tension between **autonomy** and **fiduciary safety**. Relying on LLM system prompts for financial compliance is inherently fragile due to prompt injection, hallucinated arithmetic, and non-deterministic reasoning.

Our architecture enforces a strict separation of powers:
1. **Zero LLM Arithmetic or Execution Authority:** All portfolio optimization (CVaR/Markowitz, Student-$t$ fat-tail Monte Carlo, tax-loss harvesting) and compliance checks are executed in deterministic, pure-Python engines (`backend/agents/allocation_engine.py`, `backend/agents/compliance_guard.py`).
2. **Tiered Permission Matrix (`GREEN` / `YELLOW` / `RED`):** Every agent tool call and user action is classified into one of three permission tiers with corresponding authorization gates.
3. **12-Rule Pre-Execution Compliance Firewall:** No recommendation or trade ticket can reach the client or the execution sandbox without passing `ComplianceGuard`.
4. **Anomaly Circuit Breaker:** Automatically trips to `OPEN_LOCKED` if $\ge 3$ security or compliance violations occur within a 60-second sliding window.
5. **Cryptographic Auditability & On-Chain Anchoring:** Every event is recorded in an append-only SHA-256 hash chain signed with HMAC-SHA256, compiled into an **RFC 6962 Merkle Tree**, and anchored to the **Ethereum Sepolia Testnet (`chain_id=11155111`)** with individual Merkle inclusion proofs verifiable in the UI.

---

## 2. Three-Tier Permission Matrix (`GREEN` / `YELLOW` / `RED`)

Implemented in `backend/agents/compliance_guard.py` (`get_permission_tier_catalog()`, `classify_trade_permission_tier()`) and exposed via `GET /api/v1/compliance/permission-tiers`:

| Permission Tier | Policy Mode | Thresholds & Scope | Representative Agent Operations | Verification Gate |
| :--- | :--- | :--- | :--- | :--- |
| **`GREEN`** | **Auto-Execute (Read-Only & Computation)** | Zero capital movement; zero external state mutation | Market quote & yield curve fetch (`MarketDataService`), 6-factor ETF/Bond screening (`ProductComparator`), CVaR/Markowitz & Student-$t$ Monte Carlo (`AllocationEngine`), Drift & Health diagnostics (`HealthMonitor`), Tax strategy analysis (`TaxStrategist`) | Deterministic schema validation + `AuditTrail` logging |
| **`YELLOW`** | **User Confirmation Required (Standard Advisory & Rebalance)** | Trade notional $\le \$1,000$ AND projected position weight $\le 5\%$ of portfolio NAV | Risk profile updates (`RiskProfiler`), standard fractional rebalance orders, tax-loss harvest swap proposals within suitability bounds | Pre-trade `ComplianceGuard` 12-rule pass + Explicit Human-in-the-Loop `Approve` click |
| **`RED`** | **Strong Multi-Factor Verification (High-Impact Execution)** | Trade notional $> \$1,000$ OR projected single-position weight $> 5\%$ of NAV, OR cross-border remittance / on-chain settlement | Large-notional order execution (`ExecutionAgent`), concentration-sensitive allocations, circuit-breaker administrative reset | Pre-trade `ComplianceGuard` pass + **Step-Up 6-Digit MFA OTP** (`482910` in sandbox) + **Non-Discretionary Client Attestation Checkbox** |

---

## 3. Five Mandatory Competition Security Pillars

| Pillar ID | Competition Requirement | Architectural Implementation | Verification Endpoint / Module |
| :--- | :--- | :--- | :--- |
| **PILLAR-1** | **Prompt Injection Defense** | Two-stage pre-LLM input sanitization (`RULE-09`) scanning for jailbreaks, system-prompt overrides, role-play hijacks, and compliance-bypass instructions before any agent invocation. | `ComplianceGuard.check_input_safety()` · `POST /api/v1/compliance/check-input` |
| **PILLAR-2** | **Sensitive Data Redaction** | Automatic regex + token-boundary redaction (`RULE-10`) stripping SSNs, credit/debit card numbers, IBANs, raw API keys, and bearer tokens from both user inputs and LLM outputs before persistence. | `ComplianceGuard.redact_sensitive_data()` · `AuditTrail` |
| **PILLAR-3** | **Least-Privilege Tool Scoping** | Sub-agents (`RiskProfiler`, `ProductComparator`, `AllocationEngine`, `HealthMonitor`) hold read-only service handles and cannot invoke `ExecutionAgent` or mutate balances directly. | `backend/agents/orchestrator.py` |
| **PILLAR-4** | **Execution Confirmation & Circuit Breaker** | Every trade requires a cryptographic proposal ID, `YELLOW`/`RED` human confirmation, and an active **Anomaly Circuit Breaker** that locks `RED`/`YELLOW` execution after $\ge 3$ blocked attempts in 60s. | `TradeTicket.tsx` · `POST /api/v1/compliance/circuit-breaker/simulate` |
| **PILLAR-5** | **Tamper-Evident Auditability & On-Chain Anchoring** | Append-only SHA-256 hash chain + HMAC-SHA256 signatures + RFC 6962 binary Merkle tree root anchored to Ethereum Sepolia (`chain_id=11155111`) with per-entry inclusion proofs. | `GET /api/v1/audit/{client_id}/merkle-proof/{entry_id}` |

---

## 4. Deterministic 12-Rule Compliance Firewall Catalog

All 12 rules execute deterministically in `backend/agents/compliance_guard.py`:

1. **`RULE-01` Suitability Gate:** Blocks any instrument whose `risk_level` (1–5) exceeds the client's calibrated `risk_tier` (incorporating behavioral reveal calibration).
2. **`RULE-02` Single-Position Concentration Limit:** Caps any single ETF/bond holding at tier-specific maximums (`20%` Tier 1 up to `35%` Tier 5).
3. **`RULE-03` Asset-Class Ceiling:** Enforces maximum equity weight per risk tier (`25%` Conservative up to `90%` Aggressive).
4. **`RULE-04` Minimum Cash Reserve Buffer:** Requires at least `2%–5%` liquid cash reserve post-trade to prevent margin or settlement overdraft.
5. **`RULE-05` Fixed-Income Duration vs. Horizon Check:** Warns or blocks long-duration bond funds (e.g., `TLT`) when the client's investment horizon is short ($\le 3$ years).
6. **`RULE-06` Order Notional & Buying Power Gate:** Rejects buy orders exceeding available settled cash or sell orders exceeding held shares (zero short-selling or leverage).
7. **`RULE-07` Excessive Turnover & Churn Guard:** Flags rebalancing plans whose one-way portfolio turnover exceeds `40%` in a single cycle.
8. **`RULE-08` Restricted & Complex Instrument Filter:** Blocks leveraged, inverse, or unapproved speculative tickers outside the vetted fiduciary universe.
9. **`RULE-09` Adversarial Prompt & Jailbreak Firewall:** Blocks prompt injection patterns attempting to override fiduciary rules or extract system prompts.
10. **`RULE-10` PII & Credential Leakage Prevention:** Masks sensitive identifiers before logging or LLM context injection.
11. **`RULE-11` Guarantee & Promissory Language Filter:** Scans outbound advisory text and blocks or rewrites any phrase implying guaranteed returns or risk-free equity gains.
12. **`RULE-12` Mandatory Regulatory Disclosure Injection:** Appends MiFID II / SEC Reg BI / CSRC suitability and risk disclosures to every advisory output.

---

## 5. Known-Risk Register & Mitigation Matrix

 competition judges evaluate whether the team honestly identifies residual risks and documents concrete engineering controls (`get_known_risk_register()` in `backend/agents/compliance_guard.py`):

| Risk ID | Category | Failure Mode | Residual Severity | Mitigation Control Implemented |
| :--- | :--- | :--- | :--- | :--- |
| **`RISK-01`** | **Market Data Latency & Stale Quotes** | External Yahoo Finance / FRED feeds may experience rate-limiting or delayed ticks during volatile market opens. | `LOW` | 3-tier fallback pipeline (Live API $\to$ SQLite TTL cache $\to$ deterministic synthetic history) with explicit data-source provenance tags (`live` vs `cached` vs `fallback`) on every quote. |
| **`RISK-02`** | **Historical Covariance Breakdown in Tail Regimes** | Standard Markowitz mean-variance underestimates fat-tail correlation spikes during liquidity crises (e.g., 2008 GFC or 2022 rate shock). | `MEDIUM` | Primary optimizer uses **95% CVaR (Expected Shortfall)** rather than variance alone, paired with **Student-$t$ ($\nu=5$) Monte Carlo** simulation and interactive macro stress testing (`POST /api/v1/portfolio/simulate-shock`). |
| **`RISK-03`** | **Stated vs. Revealed Risk Tolerance Mismatch** | Retail investors frequently overstate their risk appetite in calm markets and panic-sell during drawdowns. | `LOW` | **Behavioral Stress Calibration** in `profile/page.tsx` probes crisis reactions (`-20%` crash, FOMO rally, liquidity shock) and caps effective suitability tier at $\min(\text{Stated}, \text{Revealed})$. |
| **`RISK-04`** | **Adversarial Multi-Turn Jailbreak Attempts** | Attackers may attempt to split a compliance-bypass instruction across multiple chat turns or trigger rapid automated order spam. | `LOW` | Stateless per-turn `ComplianceGuard` evaluation (never trusting prior chat context for authorization) + **Anomaly Circuit Breaker** that locks execution after 3 blocked attempts in 60s. |
| **`RISK-05`** | **Public Testnet RPC Congestion (Sepolia)** | Ethereum Sepolia RPC endpoints may experience block delays or missing gas credentials in offline judging environments. | `LOW` | Deterministic `dry_run` anchoring fallback that computes the exact RFC 6962 Merkle root and verifiable leaf-to-root inclusion path (`GET /api/v1/audit/{client_id}/merkle-proof/{entry_id}`) without failing the audit workflow. |

---

## 6. Verification & Reproducibility Instructions for Judges

1. **Automated Test Suite:**
   ```bash
   python -m pytest backend/tests/ -q
   ```
2. **Interactive Security & Compliance Console:**
   - Open `/app/compliance` in the web application to inspect the **3-Tier Permission Matrix**, trigger a live **Anomaly Circuit Breaker Stress Test**, test the **Prompt Injection & Output Sanitizer**, and review the **Known-Risk Register**.
3. **Step-Up MFA Execution Gate:**
   - Draft any trade with notional $> \$1,000$ or weight $> 5\%$ on `/app/trade` or `/app/advisor` to trigger the **`RED TIER · Strong Verification`** modal requiring the 6-digit MFA code (`482910`) and fiduciary attestation.
4. **On-Chain Merkle Inclusion Proof Verification:**
   - Open `/app/audit`, expand any signed audit entry, and click **"Verify RFC 6962 Merkle Inclusion Proof"** to inspect its leaf hash, sibling audit path, and Sepolia anchor transaction.

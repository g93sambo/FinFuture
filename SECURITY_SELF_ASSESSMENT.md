# FinFuture — Security Self-Assessment Report (Deliverable 05)

**Competition:** 2026 8th FinTechathon — International Track · **Topic B: Wealth Advisory Agent**
**System:** FinFuture — a non-discretionary, human-in-the-loop multi-agent wealth advisory platform
**Scope of this report:** permission-tier implementation and known-risk list, as required by the submission checklist
**Code reviewed:** `main` at commit `3bb9824` (2026-10-18), plus the remediation changes described in §5.1 (2026-10-19) · Companion document: [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)

> **Operating mandate.** FinFuture advises and proposes; it never trades on its own. Every order needs a person to approve it, it is checked by deterministic code outside the language model, and it can only reach a **paper-trading** broker endpoint. Live-money endpoints and autonomous execution are refused at application start-up.

---

## 1. Executive summary

| Control | Status | Where |
| :--- | :--- | :--- |
| Autonomous execution (Tier 5) hard-disabled | Enforced at start-up, API and compliance layer | `core/config.py`, `api/routes/trade.py`, `ComplianceGuard.check_trade` |
| Paper trading only | Start-up refuses live Alpaca URLs and `ALPACA_PAPER=false` | `core/config.py` |
| Testnet only | Start-up refuses any chain ID other than Sepolia (11155111) | `core/config.py` |
| 12 compliance rules + 5 permission gates | Pure Python, runs outside the LLM | `agents/compliance_guard.py` |
| Per-trade cap \$100k, rolling 24 h cap \$250k, 129-symbol whitelist | Enforced on every execution | `ComplianceGuard.check_trade` |
| Step-up confirmation for orders > \$1,000 or > 5 % NAV | Enforced on every approval path (REST, WebSocket, chat) | `Orchestrator.handle_trade_approval`, `PERM-STEP-UP-MFA` |
| Production secret guard | Start-up refuses default or short `SECRET_KEY` / `AUDIT_SECRET_KEY` | `core/config.py` |
| Login throttling | 5 failed attempts per account per 15 min → HTTP 429 | `api/routes/auth.py` |
| Tenant isolation | Ownership check on every client-scoped route and WebSocket | `core/security.verify_client_ownership`, `api/routes/ws.py` |
| Prompt-injection defence | Input pattern scan + isolation of external content | `check_input_safety`, `services/sanitizer.py` |
| PII minimisation towards the LLM | Regex redaction + `ANON-XXXXXXXX` pseudonym | `redact_sensitive_data`, `services/context_builder.py` |
| Tamper-evident audit trail | SHA-256 hash chain + HMAC + RFC 6962 Merkle proofs | `services/audit_logger.py`, `services/anchoring.py` |

**Our overall assessment:** the design is safe for its intended scope, a **sandbox with paper money**. The hard boundaries (no autonomous trading, no live broker, no mainnet) are enforced at start-up and cannot be switched off at runtime. Our review found several weaknesses. We fixed the bypass of the step-up gate (`RISK-14`) and the static demo code (part of `RISK-07`). Production now refuses default signing secrets (`RISK-08`), and FISCO BCOS receipts are labelled as simulated (`RISK-16`). Real circuit-breaker locks can no longer be cleared by the user (`RISK-17`). We also added login throttling (`RISK-11`), narrowed CORS (`RISK-19`), and repaired the restart-recovery path (`RISK-20`). That path had never run because of a variable-shadowing bug. Two controls remain **demonstration-grade** and need replacing before real client money: the step-up code is derived from the proposal ID rather than being a true second factor (`RISK-07`), and approval is still a flag set by the authenticated client (`RISK-15`). §5 lists every item with its current status.

---

## 2. Permission-tier implementation

The tiers are declared in `ComplianceGuard.get_permission_tier_catalog()` and served live at `GET /api/v1/compliance/permission-tiers`. Tiers are not just labels: each is backed by a specific code path that the tier below cannot reach.

| Tier | Badge | What it may do | What stops it doing more |
| :--- | :--- | :--- | :--- |
| **`TIER_1_READ_ONLY`** | GREEN | Quotes, history, FRED macro, Treasury curve, SEC EDGAR filings, own portfolio and audit reads | Read-only tools in `ToolRegistry`. Provider calls carry tickers, CIKs or series IDs only. |
| **`TIER_2_ADVISE`** | GREEN | Risk profiling, 6-factor product comparison, Black–Litterman / CVaR allocation, Monte Carlo, tax analysis, research reports | These modules return data only and have no broker client. Outbound text passes `REG-001` (no guarantee language) and `REG-002` (risk disclosure). |
| **`TIER_3_PROPOSE_TRADE`** | YELLOW | Stage an unsigned `TradeProposal` with a 15-minute TTL (`PROPOSAL_TTL_SECONDS = 900`) | `Orchestrator.create_trade_proposal()` makes no broker call. It refuses a locked circuit breaker (HTTP 423) and non-whitelisted symbols (HTTP 403) before staging. |
| **`TIER_4_EXECUTE_WITH_APPROVAL`** | RED | Submit an approved order to Alpaca **Paper** or the Bamboo sandbox | Runs only through `handle_trade_approval()`, then `check_trade()`, then `ExecutionModule.execute_trade()`. The gates are listed below. |
| **`TIER_5_AUTONOMOUS_DISABLED`** | DISABLED | Nothing | 1. `ALLOW_AUTONOMOUS_EXECUTION=true` raises at start-up (`guard_autonomous_execution_disabled`). 2. `autonomous=true` on `/trade/execute` returns HTTP 403 and records a security incident. 3. `PERM-TIER-5` blocks in `check_trade`. |

### 2.1 Tier 4 execution gates (in order)

1. **Ownership:** `verify_client_ownership` on the request, and the proposal's `client_id` must belong to the caller (HTTP 403 otherwise).
2. **Proposal freshness:** the proposal must exist and be at most 15 minutes old. If the cache was lost (for example after a restart), it is recovered from `TRADE_PROPOSED` audit entries inside the TTL window.
3. **Replay protection:** a proposal already executed is rejected with `DuplicateTradeError` (HTTP 409). This is checked in the cache, then in `TRADE_EXECUTED` audit entries from the same window.
4. **Step-up pre-check:** for a Red-tier order (> \$1,000 or > 5 % NAV), an approval without a step-up code is turned back with `StepUpRequiredError` (HTTP 403). This covers a chat "yes", a WebSocket approve and a bare REST call. The proposal stays pending, and the rejection does not count towards the circuit breaker.
5. **`REG-003` explicit approval:** `user_approved=True` with an approval timestamp.
6. **`REG-004` KYC flag:** the profile must have `kyc_verified=True`.
7. **`AML-001` per-trade cap:** notional must not exceed **\$100,000** (`MAX_SINGLE_TRADE_NOTIONAL_USD`).
8. **`PERM-CAP-DAILY`:** the prior 24 h of `trades` plus this order must not exceed **\$250,000** (`MAX_DAILY_TRADE_NOTIONAL_USD`).
9. **`PERM-WHITELIST`:** the symbol must be in `ALLOWED_TRADING_SYMBOLS`, a frozen set of **129** symbols (US ETFs and large caps, bond and commodity ETFs, NGX equities, WeBank shelf products).
10. **`PERM-CIRCUIT-BREAKER`:** three or more blocked attempts within 60 s lock the client for 15 minutes (`OPEN_LOCKED`). A user can clear a lock only if it was caused entirely by simulated drills.
11. **`PERM-STEP-UP-MFA`:** orders over \$1,000 or over 5 % of NAV need the 6-digit code for that proposal (constant-time comparison) and a fiduciary attestation. The gate is always on for proposal approvals. The code itself is still demonstration-grade; see `RISK-07`.
12. **`SUIT-*` / `CONC-*` / `AML-002`:** suitability, concentration and churn rules.
13. **30-second double-submit lock:** a cache lock, plus a durable check in the `trades` table that rejects an identical client, symbol and side committed in the last 30 s.
14. **Paper-only broker:** the base URL was already validated at start-up.

Every pass, block and execution is written to the hash-chained audit log.

### 2.2 Compliance rule catalogue (`DEFAULT_COMPLIANCE_RULES`)

| ID | Rule | ID | Rule |
| :--- | :--- | :--- | :--- |
| `SUIT-001` | Asset risk within client's calibrated tolerance | `REG-001` | No guaranteed-return language |
| `SUIT-002` | Horizon gate for illiquid/long-duration assets | `REG-002` | Mandatory risk disclosure |
| `SUIT-003` | Liquidity buffer preserved post-trade | `REG-003` | Explicit human approval |
| `CONC-001` | Single stock ≤ 15 % NAV | `REG-004` | KYC verified |
| `CONC-002` | Single ETF ≤ 40 % NAV | `AML-001` | Per-trade notional ≤ \$100k |
| `CONC-003` | Single sector ≤ 35 % NAV | `AML-002` | > 3 round trips per symbol / 24 h blocked |

Permission gates: `PERM-TIER-5`, `PERM-CIRCUIT-BREAKER`, `PERM-WHITELIST`, `PERM-CAP-DAILY`, `PERM-STEP-UP-MFA`.

---

## 3. Data that leaves the backend

| Destination | What is sent | Control |
| :--- | :--- | :--- |
| Yahoo Finance, FRED, SEC EDGAR, Finnhub | Ticker symbols, CIKs, series IDs | Typed tool argument schemas; no client fields exist on these calls |
| LLM API (OpenAI-compatible) | Up to the last 8 dialogue turns plus a suitability snippet (age, horizon, risk score, liquid net worth, buffer months, holdings weights) | `redact_sensitive_data()` strips e-mails, phone numbers, SSN/BVN/NIN/TIN, card/account numbers, IBANs, API keys and bearer tokens, and "my name is …" names. `client_id` and name are replaced by `ANON-` plus a truncated SHA-256. |
| Alpaca Paper / Bamboo sandbox | `(symbol, side, qty, type, time_in_force)` | Paper-only URL guard; no identity or profile data |
| Sepolia / FISCO BCOS (optional) | Merkle root only | No entry content leaves the system |

**Residual exposure (honest view):** the LLM provider still receives financial attributes and free-text dialogue. Regex redaction does not catch every form of PII. For example, a name given without "my name is", a street address, or an employer name would be sent. See `RISK-04`.

---

## 4. Prompt-injection and output controls

- **User input (`RULE-09`):** `check_input_safety()` matches system-prompt overrides, compliance-bypass requests, "execute without approval" instructions, jailbreak/DAN phrasing and HTML/script payloads. Matches are blocked and count towards the circuit breaker.
- **External content:** `services/sanitizer.py` strips HTML and scripts, normalises Unicode and neutralises delimiter collisions. It wraps web and filing text in `<untrusted_external_content>` before the model sees it.
- **Structural defence:** even a fully successful injection can at most produce text or a *proposal*. The LLM has no tool that executes a trade. Execution requires the separate approval call and the deterministic gates in §2.1.
- **Output:** `check_text_output()` applies `REG-001`/`REG-002`. The three-reviewer stage (suitability, devil's advocate, numeric consistency) re-checks advice before delivery.

---

## 5. Known-risk register

Severity describes the **current sandbox deployment** (paper money, test chain). "Production" severity is what the risk would become with real client funds.

| ID | Risk | Status | Sandbox | Production | Mitigation in place | Still needed before real money |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **RISK-01** | LLM fabricates prices, yields or statistics | Mitigated | Low | Medium | All figures come from deterministic Python. Statutes come from `legal_knowledge.py`. A numeric-consistency reviewer checks output. | Per-figure provenance check on final text |
| **RISK-02** | Direct or indirect prompt injection | Mitigated | Low | Medium | `RULE-09` pattern scan and `<untrusted_external_content>` isolation. The LLM has no tool that executes trades. | Classifier-based detection; pattern lists are bypassable by paraphrase |
| **RISK-03** | Excessive or unauthorised order execution | Mitigated | Low | Medium | Tier 5 disabled; caps; whitelist; 30 s lock; circuit breaker; step-up always enforced on Red tier | See RISK-07, RISK-15 |
| **RISK-04** | Financial attributes and unredacted PII sent to LLM provider | Partly mitigated | Medium | High | Regex redaction and SHA-256 pseudonym | Self-hosted or zero-retention model endpoint; NER-based redaction |
| **RISK-05** | Stale or unavailable market data | Mitigated | Low | Medium | Provider fallback chain with `live` / `cached` / `fallback` provenance tags. Fixtures are isolated under a fallback key in production. | Staleness threshold that blocks proposals |
| **RISK-06** | Audit log tampering | Mitigated (detection) | Low | Medium | Hash chain, HMAC, Merkle proofs; ORM hooks reject UPDATE/DELETE; production refuses the default HMAC key | See RISK-09, RISK-16, RISK-18 |
| **RISK-07** | Step-up "MFA" is not a second factor | **Open (reduced)** | Low | **High** | **Fixed:** the static code `482910` is no longer accepted by the backend or the UI, and the code is compared in constant time. **Still true:** the code is derived from the `proposal_id` digits, and the UI shows it, so it is attestation friction, not authentication. | Server-issued one-time challenge bound to TOTP/WebAuthn |
| **RISK-08** | Default `SECRET_KEY` / `AUDIT_SECRET_KEY` | **Fixed** | Low | Low | With `ENVIRONMENT=production`, start-up refuses either key if it is the development default, shorter than 32 characters, or identical to the other (`guard_production_secrets`). | Rotate keys through a secrets manager |
| **RISK-09** | Sepolia anchoring may be `dry_run` | Open (by design) | Medium | Medium | Receipts carry `status`; mainnet is rejected; `dry_run` is labelled | Record real Sepolia transaction hashes as execution evidence |
| **RISK-10** | JWT in `localStorage`, no revocation | Open | Medium | High | React output escaping, server-side sanitisation, 60-minute expiry | `HttpOnly` / `SameSite` cookie, CSP header, revocation list |
| **RISK-11** | No inbound rate limiting or login lockout | **Partly fixed** | Low | Medium | **Fixed:** 5 failed logins per account in 15 minutes return HTTP 429 with `Retry-After`, and a successful login clears the count. **Limits:** the counter is in-process (per instance, reset on restart). An attacker can deliberately lock a known account for 15 minutes. Registration and chat are not throttled. | Gateway-level per-IP limits; throttle `/auth/register` and chat |
| **RISK-12** | KYC/AML is self-declared | Open | Medium | **High** | Unverified profiles are blocked by `REG-004` | Identity-verification provider |
| **RISK-13** | Shared state in process memory (Redis optional; live `/health` shows `redis: false`) | Partly mitigated | Medium | Medium | Durable 30 s duplicate check in PostgreSQL, and proposal recovery and replay rejection from the audit log. **Circuit-breaker and login-throttle state are still in memory.** They reset on restart and are not shared across instances. | Redis or a PostgreSQL-backed circuit breaker and throttle |
| **RISK-14** | Step-up gate was opt-in on the API | **Fixed** | — | — | `handle_trade_approval` always sets `enforce_step_up_mfa`. `check_trade` defaults it on for any trade carrying a `proposal_id`. Approvals without a code are turned back before compliance. Regression tests cover omitted fields and the old static code. | — |
| **RISK-15** | "Human approval" is a client-asserted flag; `/trade/execute` can propose and execute in one call | **Open** | Low | **High** | Requires an authenticated owner. Every Red-tier order now needs the step-up code. The approval timestamp is audited and every gate in §2.1 runs. | Approval bound to a fresh second-factor challenge; remove the one-call propose+execute path |
| **RISK-16** | FISCO BCOS receipt said `confirmed` without a transaction | **Fixed (labelling)** | Low | Medium | A receipt built after only reading the node's block height now has `status="simulated"` and `onchain=false`. The audit page shows a "Simulated" tag and states that no transaction was submitted. | Submit a real transaction to `AuditAnchorConsortium.sol` before presenting FISCO anchoring as evidence |
| **RISK-17** | Circuit breaker was self-resettable | **Fixed** | — | Low | The demo "simulate" button records `SIMULATED_DRILL` incidents. `POST /compliance/circuit-breaker/reset` returns HTTP 423 when any real blocked attempt is behind the current lock or the 60 s watch window, so such locks must expire. | Admin role for manual unlocks |
| **RISK-18** | Append-only is enforced in the ORM, not the database | Open | Low | Medium | The hash chain and HMAC detect edits (`/audit/{id}/verify`). Anyone with the HMAC key and DB access could rewrite the chain consistently. | DB role without UPDATE/DELETE on `audit_log`; real external anchoring |
| **RISK-19** | CORS allowed any `https://*.vercel.app` origin | **Fixed (narrowed)** | Low | Low | The origin regex is now configurable (`CORS_ORIGIN_REGEX`). The default allows only `fin-future` / `finfuture` Vercel domains and localhost. Auth uses bearer tokens, not cookies. | Pin the exact production origin; Vercel project names are not reserved, so a third party could create `fin-future-x.vercel.app` |
| **RISK-20** | Restart fallbacks scanned only the latest 50 / 100 audit entries, and never ran | **Fixed** | — | — | A local variable named `desc` shadowed `sqlalchemy.desc`, so both fallbacks always raised and fell through silently. That is fixed. The queries now cover every `TRADE_PROPOSED` / `TRADE_EXECUTED` entry inside the proposal TTL window instead of a fixed row count. A regression test covers recovery and replay rejection after cache loss. | Index or column for `proposal_id` at higher volume |

`GET /api/v1/compliance/permission-tiers` currently serves `RISK-01` to `RISK-06` from `get_known_risk_register()`. `RISK-07` to `RISK-20` are documented here only.

### 5.1 Remediation log (2026-10-19)

| Item | Change | Files |
| :--- | :--- | :--- |
| RISK-14 | Step-up always enforced; `StepUpRequiredError` for approvals without a code | `agents/orchestrator.py`, `agents/compliance_guard.py` |
| RISK-07 | Static code removed; constant-time comparison | `agents/compliance_guard.py`, `frontend/.../TradeTicket.tsx` |
| RISK-08 | Production start-up guard for signing secrets | `core/config.py` |
| RISK-16 | `simulated` / `onchain=false` FISCO receipts; UI label | `services/anchoring.py`, `frontend/.../audit/page.tsx` |
| RISK-17 | Drill-only reset; HTTP 423 otherwise | `agents/compliance_guard.py`, `api/routes/compliance.py`, `frontend/.../compliance/page.tsx` |
| RISK-11 | Per-account failed-login throttle | `api/routes/auth.py` |
| RISK-19 | Configurable, narrowed CORS origin regex | `core/config.py`, `main.py` |
| RISK-20 | `desc` shadowing fixed; time-window queries | `agents/orchestrator.py` |
| Related | REST `/chat/message` returns blocked approvals as error events instead of HTTP 500 | `api/routes/chat.py` |

**Deployment note:** the backend will not start with `ENVIRONMENT=production` until `SECRET_KEY` and `AUDIT_SECRET_KEY` are set on Render to two different random values of at least 32 characters. For example, `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

**Remaining before real money:** RISK-07 / RISK-15 (true second factor bound to approval), RISK-10 (cookie-based session and CSP), RISK-12 (real KYC), RISK-13 (shared state store) and RISK-18 (database-level append-only).

---

## 6. Verification evidence

| Check | Result |
| :--- | :--- |
| Security and compliance unit suites (`test_compliance_guard`, `test_challenger_m4_compliance`, `test_challenger_m5_security`, `test_security`, `test_permission_tiers_and_privacy`, `test_audit_logger`, `test_config`) | **all passed** (local run, 2026-10-19), including new regression tests for RISK-07, -08, -11, -14 and -17 |
| Full Python suite (`backend/tests`, `tests`) | **913 / 913 passed** (local run, 2026-10-19). Frontend `tsc --noEmit` and ESLint are clean on the changed pages |
| Live production run against Render and Vercel (2026-10-18) | 57 / 57 operations passed; `evidence/LIVE_VERIFICATION_REPORT.md` |

Reproduce:

```bash
PYTHONPATH=backend:. python -m pytest \
  backend/tests/unit/test_compliance_guard.py backend/tests/unit/test_challenger_m4_compliance.py \
  backend/tests/unit/test_challenger_m5_security.py backend/tests/unit/test_security.py \
  backend/tests/unit/test_permission_tiers_and_privacy.py backend/tests/unit/test_audit_logger.py \
  backend/tests/unit/test_config.py -q
```

**Interactive checks for judges:**

- `/app/compliance`: view the tier catalogue and trigger the circuit breaker (`POST /api/v1/compliance/circuit-breaker/simulate`). Test injection and redaction with `POST /api/v1/compliance/check-input`.
- `/app/trade`: an order over \$1,000 shows the RED step-up dialog, and approving it without the code is refused. A non-whitelisted symbol is refused at proposal time (HTTP 403).
- `/app/audit`: verify the chain and open a Merkle inclusion proof. The Sepolia receipt shows `dry_run` unless an RPC is configured. The FISCO BCOS receipt is tagged "Simulated".

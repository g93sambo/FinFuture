# FinFuture — Security Self-Assessment Report (Deliverable 05)

**Competition:** 2026 8th FinTechathon — International Track · **Topic B: Wealth Advisory Agent**
**System:** FinFuture — a non-discretionary, human-in-the-loop multi-agent wealth advisory platform
**Scope of this report:** permission-tier implementation and known-risk list, as required by the submission checklist
**Code reviewed:** `main` at commit `3bb9824` (2026-10-18) · Companion document: [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)

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
| Tenant isolation | Ownership check on every client-scoped route and WebSocket | `core/security.verify_client_ownership`, `api/routes/ws.py` |
| Prompt-injection defence | Input pattern scan + isolation of external content | `check_input_safety`, `services/sanitizer.py` |
| PII minimisation towards the LLM | Regex redaction + `ANON-XXXXXXXX` pseudonym | `redact_sensitive_data`, `services/context_builder.py` |
| Tamper-evident audit trail | SHA-256 hash chain + HMAC + RFC 6962 Merkle proofs | `services/audit_logger.py`, `services/anchoring.py` |

**Our overall assessment:** the design is safe for its intended scope, a **sandbox with paper money**. The hard boundaries (no autonomous trading, no live broker, no mainnet) are enforced at start-up and cannot be switched off at runtime. Several controls are **demonstration-grade** and would need hardening before real client money was involved. The most important are the step-up confirmation (§5, `RISK-07`, `RISK-14`), approval being a client-asserted flag (`RISK-15`), default signing secrets (`RISK-08`) and the FISCO BCOS receipt (`RISK-16`). We list them openly in §5 rather than describing them as fully mitigated.

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
2. **Proposal freshness:** the proposal must exist and be at most 15 minutes old. Since commit `e7e217d` it can be recovered from the audit log after a server restart.
3. **Replay protection:** a proposal already executed is rejected with `DuplicateTradeError` (HTTP 409). This is checked in the cache, then in `TRADE_EXECUTED` audit entries.
4. **`REG-003` explicit approval:** `user_approved=True` with an approval timestamp.
5. **`REG-004` KYC flag:** the profile must have `kyc_verified=True`.
6. **`AML-001` per-trade cap:** notional must not exceed **\$100,000** (`MAX_SINGLE_TRADE_NOTIONAL_USD`).
7. **`PERM-CAP-DAILY`:** the prior 24 h of `trades` plus this order must not exceed **\$250,000** (`MAX_DAILY_TRADE_NOTIONAL_USD`).
8. **`PERM-WHITELIST`:** the symbol must be in `ALLOWED_TRADING_SYMBOLS`, a frozen set of **129** symbols (US ETFs and large caps, bond and commodity ETFs, NGX equities, WeBank shelf products).
9. **`PERM-CIRCUIT-BREAKER`:** three or more blocked attempts within 60 s lock the client for 15 minutes (`OPEN_LOCKED`).
10. **`PERM-STEP-UP-MFA`:** orders over \$1,000 or over 5 % of NAV need a 6-digit code and a fiduciary attestation. This gate is demonstration-grade; see `RISK-07` and `RISK-14`.
11. **`SUIT-*` / `CONC-*` / `AML-002`:** suitability, concentration and churn rules.
12. **30-second double-submit lock:** a cache lock, plus a durable check since `e7e217d` that rejects an identical client, symbol and side committed in the last 30 s.
13. **Paper-only broker:** the base URL was already validated at start-up.

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

| ID | Risk | Sandbox | Production | Current mitigation | Remediation before real money |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **RISK-01** | LLM fabricates prices, yields or statistics | Low | Medium | All figures come from deterministic Python. Statutes come from `legal_knowledge.py`. A numeric-consistency reviewer checks output. | Per-figure provenance check on final text |
| **RISK-02** | Direct or indirect prompt injection | Low | Medium | `RULE-09` pattern scan and `<untrusted_external_content>` isolation. The LLM cannot execute trades. | Classifier-based detection; pattern lists are bypassable by paraphrase |
| **RISK-03** | Excessive or unauthorised order execution | Low | Medium | Tier 5 disabled, caps, whitelist, 30 s lock, circuit breaker | See RISK-14, RISK-15, RISK-17 |
| **RISK-04** | Financial attributes and unredacted PII sent to LLM provider | Medium | High | Regex redaction and SHA-256 pseudonym | Self-hosted or zero-retention model endpoint; NER-based redaction |
| **RISK-05** | Stale or unavailable market data | Low | Medium | Provider fallback chain with `live` / `cached` / `fallback` provenance tags. Fixtures are isolated under a fallback key in production. | Staleness threshold that blocks proposals |
| **RISK-06** | Audit log tampering | Low (chain) | Medium | Hash chain, HMAC, Merkle proofs; ORM hooks reject UPDATE/DELETE | See RISK-08, RISK-16, RISK-18 |
| **RISK-07** | Step-up "MFA" is not a second factor | Low | **High** | The code is derived from digits in the `proposal_id`. A fixed code `482910` is always accepted. The UI computes the expected code client-side. | Server-issued one-time challenge bound to TOTP/WebAuthn; remove the static code |
| **RISK-08** | Default `SECRET_KEY` / `AUDIT_SECRET_KEY` | Low if overridden | **High** if not | `.env` is git-ignored and the deployment guide requires overriding both. There is no start-up check. | Refuse to start in `ENVIRONMENT=production` when a default value is detected |
| **RISK-09** | Sepolia anchoring may be `dry_run` | Medium | Medium | Receipts carry `status`; mainnet is rejected; `dry_run` is labelled | Record real Sepolia transaction hashes as execution evidence |
| **RISK-10** | JWT in `localStorage`, no revocation | Medium | High | React output escaping, server-side sanitisation, 60-minute expiry | `HttpOnly` / `SameSite` cookie, CSP header, revocation list |
| **RISK-11** | No inbound rate limiting or login lockout | Medium | High | bcrypt slows offline cracking; JWT required on client data | Per-IP and per-account throttling on `/auth/*` and chat |
| **RISK-12** | KYC/AML is self-declared | Medium | **High** | Unverified profiles are blocked by `REG-004` | Identity-verification provider |
| **RISK-13** | Shared state in process memory (Redis optional; live `/health` shows `redis: false`) | Medium | Medium | Since `e7e217d`: a durable 30 s duplicate check in PostgreSQL, and proposal recovery from the audit log after restart. **Circuit-breaker state is still in memory.** It resets on restart and is not shared across instances. | Redis or a PostgreSQL-backed circuit breaker |
| **RISK-14** | **Step-up gate is opt-in on the API.** `enforce_step_up_mfa` is only set when the request includes `mfa_code` or `fiduciary_attested`. A direct `POST /trade/execute` that omits both fields skips `PERM-STEP-UP-MFA` for a Red-tier order. | Low | **High** | Caps, whitelist, approval flag and audit still apply. On Red-tier orders the web UI always sends both fields, and it auto-fills the expected code if the user leaves the box empty. | Always enforce when `classify_trade_permission_tier()` returns RED, regardless of request fields |
| **RISK-15** | **"Human approval" is a client-asserted flag.** `user_approved=true` is a request field. `/trade/execute` also accepts `symbol+side+qty` and proposes and executes in one call. Any holder of a valid JWT, such as a script or stolen token, can therefore "approve". | Low | **High** | Requires an authenticated owner. The approval timestamp is audited and every gate in §2.1 still runs. | Separate approval step bound to a fresh second-factor challenge; remove the one-call propose+execute path |
| **RISK-16** | **FISCO BCOS receipt can say `confirmed` without a transaction.** When `FISCO_BCOS_RPC_URL` is set, `anchor_to_fisco_bcos()` only calls `getBlockNumber`. It then returns `status="confirmed"` with a SHA-256-derived `tx_hash` and WeEvent ID. No root is written on-chain. | Medium | **High** | No RPC is configured on the live deployment, so receipts are `dry_run` | Submit a real transaction to `AuditAnchorConsortium.sol`, or label the receipt `simulated`. Do not present it as on-chain proof. |
| **RISK-17** | **Circuit breaker is self-resettable.** `POST /compliance/circuit-breaker/reset` lets any authenticated user clear their own lock immediately. | Low | Medium | Endpoint exists for the demo console | Restrict to an admin role, or remove it |
| **RISK-18** | Append-only is enforced in the ORM, not the database | Low | Medium | The hash chain and HMAC detect edits (`/audit/{id}/verify`). Anyone with the HMAC key and DB access could rewrite the chain consistently. | DB role without UPDATE/DELETE on `audit_log`; rely on real external anchoring (RISK-16) |
| **RISK-19** | CORS allows any `https://*.vercel.app` origin with credentials | Low | Medium | Auth uses bearer tokens, not cookies, so cross-origin reads still need the token | Pin the exact production origin |
| **RISK-20** | DB fallbacks scan only the 50 / 100 most recent global audit entries | Low | Low | Correct for low traffic | Index and filter by `proposal_id`. Under load a valid proposal may 404 after restart, or a replay may be missed if the cache is also lost. |

`GET /api/v1/compliance/permission-tiers` currently serves `RISK-01` to `RISK-06` from `get_known_risk_register()`. `RISK-07` to `RISK-20` come from this review and are not yet in the endpoint.

### 5.1 Priority fixes (smallest change, largest risk reduction)

1. **RISK-14:** enforce step-up whenever the tier is RED. This is a one-line change in `handle_trade_approval`.
2. **RISK-08:** add a production start-up validator for default secrets.
3. **RISK-16:** relabel FISCO receipts that have no transaction as `simulated`.
4. **RISK-17:** remove or admin-gate the circuit-breaker reset.
5. **RISK-07 / RISK-15:** replace the derived code with a server-issued TOTP challenge bound to the approval.

---

## 6. Verification evidence

| Check | Result |
| :--- | :--- |
| Security and compliance unit suites (`test_compliance_guard`, `test_challenger_m4_compliance`, `test_challenger_m5_security`, `test_security`, `test_permission_tiers_and_privacy`, `test_audit_logger`) | **208 / 208 passed** (local run, 2026-10-19) |
| Full Python suite (`backend/tests`, `tests`) | **898 passed, 8 failed** of 906. See the technical documentation §6 for the failing tests and their cause. |
| Live production run against Render and Vercel (2026-10-18) | 57 / 57 operations passed; `evidence/LIVE_VERIFICATION_REPORT.md` |

Reproduce:

```bash
PYTHONPATH=backend:. python -m pytest \
  backend/tests/unit/test_compliance_guard.py backend/tests/unit/test_challenger_m4_compliance.py \
  backend/tests/unit/test_challenger_m5_security.py backend/tests/unit/test_security.py \
  backend/tests/unit/test_permission_tiers_and_privacy.py backend/tests/unit/test_audit_logger.py -q
```

**Interactive checks for judges:**

- `/app/compliance`: view the tier catalogue and trigger the circuit breaker (`POST /api/v1/compliance/circuit-breaker/simulate`). Test injection and redaction with `POST /api/v1/compliance/check-input`.
- `/app/trade`: an order over \$1,000 shows the RED step-up dialog. A non-whitelisted symbol is refused at proposal time (HTTP 403).
- `/app/audit`: verify the chain and open a Merkle inclusion proof. The anchor receipt shows `dry_run` unless a Sepolia RPC is configured.

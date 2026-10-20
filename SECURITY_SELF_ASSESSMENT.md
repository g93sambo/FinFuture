# FinFuture — Security Self-Assessment Report (Deliverable 05)

**Competition:** 2026 8th FinTechathon — International Track · **Topic B: Wealth Advisory Agent**
**System:** FinFuture — a non-discretionary, human-in-the-loop multi-agent wealth advisory platform
**Scope of this report:** permission-tier implementation and known-risk list, as required by the submission checklist
**Code reviewed:** `main` at commit `3b61d21` (2026-10-20). Remediation since the first review (2026-10-18) is logged in §5.1 (2026-10-19) and §5.2 (2026-10-20) · Companion document: [`docs/TECHNICAL_DOCUMENTATION.md`](docs/TECHNICAL_DOCUMENTATION.md)

> **Operating mandate.** FinFuture advises and proposes; it never trades on its own. Every order needs a person to approve it, it is checked by deterministic code outside the language model, and it can only reach a **paper-trading** broker endpoint. Live-money endpoints and autonomous execution are refused at application start-up.

---

## 1. Executive summary

| Control | Status | Where |
| :--- | :--- | :--- |
| Autonomous execution (Tier 5) hard-disabled | Enforced at start-up, API and compliance layer | `core/config.py`, `api/routes/trade.py`, `ComplianceGuard.check_trade` |
| Paper trading only | Start-up refuses live Alpaca URLs and `ALPACA_PAPER=false` | `core/config.py` |
| Testnet only | Start-up refuses any chain ID other than Sepolia (11155111) | `core/config.py` |
| 12 compliance rules + 5 permission gates | Pure Python, runs outside the LLM | `agents/compliance_guard.py` |
| Per-trade cap \$100k, rolling 24 h cap \$250k, 101-symbol whitelist | Enforced on every execution | `ComplianceGuard.check_trade` |
| Step-up one-time code for orders > \$1,000 or > 5 % NAV | Random single-use code emailed out-of-band, bound to user + proposal, 5 min TTL, 5 attempts; enforced on every approval path | `services/otp_service.py`, `Orchestrator.handle_trade_approval`, `PERM-STEP-UP-MFA` |
| Production secret guard | Start-up refuses default or short `SECRET_KEY` / `AUDIT_SECRET_KEY` | `core/config.py` |
| Login throttling and password policy | 5 failed attempts per account per 15 min → HTTP 429; per-IP limits on sign-up and failed logins; passwords of at least 10 characters with a letter and a digit, not a common password, not containing the email name | `api/routes/auth.py` |
| Per-client funds isolation | All clients route orders through one Alpaca paper account, but each client's cash and holdings come from their own trades, and an order cannot spend more cash or sell more shares than that client holds | `services/portfolio_service.py`, `ExecutionModule.execute_trade` (`CLIENT_BALANCE`) |
| Tenant isolation | Ownership check on every client-scoped route and WebSocket | `core/security.verify_client_ownership`, `api/routes/ws.py` |
| Prompt-injection defence | Input pattern scan + isolation of external content | `check_input_safety`, `services/sanitizer.py` |
| PII minimisation towards the LLM | Regex redaction + `ANON-XXXXXXXX` pseudonym | `redact_sensitive_data`, `services/context_builder.py` |
| Tamper-evident audit trail | SHA-256 hash chain + HMAC + Merkle inclusion proofs; optional Sepolia anchoring | `services/audit_logger.py`, `services/anchoring.py` |

**Our overall assessment:** the design is safe for its intended scope, a **sandbox with paper money**. The hard boundaries (no autonomous trading, no live broker, no mainnet) are enforced at start-up and cannot be switched off at runtime. Our review found several weaknesses. We fixed the bypass of the step-up gate (`RISK-14`) and the static demo code (part of `RISK-07`). Production now refuses default signing secrets (`RISK-08`), and integrations that could only be simulated in a sandbox were removed (`RISK-16`, `RISK-21`). Real circuit-breaker locks can no longer be cleared by the user (`RISK-17`). We also added login throttling (`RISK-11`), narrowed CORS (`RISK-19`), and repaired the restart-recovery path (`RISK-20`). A second review on 2026-10-20 found that every client saw, and could spend, the one shared broker account's cash and positions (`RISK-25`); portfolios are now per client and a balance gate blocks over-spending. The step-up code is now a real out-of-band one-time passcode: a random code emailed to the account address, stored only as an HMAC digest, single-use and bound to one user and one proposal (`RISK-07`). Red-tier approvals are therefore bound to a fresh second-factor challenge; small (Yellow-tier) approvals remain a flag set by the authenticated client (`RISK-15`). §5 lists every item with its current status.

---

## 2. Permission-tier implementation

The tiers are declared in `ComplianceGuard.get_permission_tier_catalog()` and served live at `GET /api/v1/compliance/permission-tiers`. Tiers are not just labels: each is backed by a specific code path that the tier below cannot reach.

| Tier | Badge | What it may do | What stops it doing more |
| :--- | :--- | :--- | :--- |
| **`TIER_1_READ_ONLY`** | GREEN | Quotes, history, FRED macro, Treasury curve, SEC EDGAR filings, own portfolio and audit reads | Read-only tools in `ToolRegistry`. Provider calls carry tickers, CIKs or series IDs only. |
| **`TIER_2_ADVISE`** | GREEN | Risk profiling, 6-factor product comparison, Black–Litterman / CVaR allocation, Monte Carlo, tax analysis, research reports | These modules return data only and have no broker client. Outbound text passes `REG-001` (no guarantee language) and `REG-002` (risk disclosure). |
| **`TIER_3_PROPOSE_TRADE`** | YELLOW | Stage an unsigned `TradeProposal` with a 15-minute TTL (`PROPOSAL_TTL_SECONDS = 900`) | `Orchestrator.create_trade_proposal()` makes no broker call. It refuses a locked circuit breaker (HTTP 423) and non-whitelisted symbols (HTTP 403) before staging. |
| **`TIER_4_EXECUTE_WITH_APPROVAL`** | RED | Submit an approved order to Alpaca **Paper** | Runs only through `handle_trade_approval()`, then `check_trade()`, then `ExecutionModule.execute_trade()`. The gates are listed below. |
| **`TIER_5_AUTONOMOUS_DISABLED`** | DISABLED | Nothing | 1. `ALLOW_AUTONOMOUS_EXECUTION=true` raises at start-up (`guard_autonomous_execution_disabled`). 2. `autonomous=true` on `/trade/execute` returns HTTP 403 and records a security incident. 3. `PERM-TIER-5` blocks in `check_trade`. |

### 2.1 Tier 4 execution gates (in order)

1. **Ownership:** `verify_client_ownership` on the request, and the proposal's `client_id` must belong to the caller (HTTP 403 otherwise).
2. **Proposal freshness:** the proposal must exist and be at most 15 minutes old. If the cache was lost (for example after a restart), it is recovered from `TRADE_PROPOSED` audit entries inside the TTL window.
3. **Replay protection:** a proposal already executed is rejected with `DuplicateTradeError` (HTTP 409). This is checked in the cache, then in `TRADE_EXECUTED` audit entries from the same window.
4. **Step-up one-time code:** for a Red-tier order (> \$1,000 or > 5 % NAV), an approval without a code is turned back with `StepUpRequiredError` (HTTP 403); this covers a chat "yes", a WebSocket approve and a bare REST call, and the proposal stays pending. The client requests a code with `POST /api/v1/trade/{proposal_id}/step-up`. `StepUpOTPService` generates 6 random digits (`secrets`), stores only `HMAC-SHA256(SECRET_KEY, proposal_id:user_id:code)`, and emails the code to the account address (Brevo, Resend or SMTP). Codes expire after 5 minutes and allow 5 guesses, after which they are burned and a security incident is recorded. They are consumed on first success, and resends are limited to one per 30 s and 5 per proposal. Attestation is checked before the code, so a missing checkbox does not burn it (`AttestationRequiredError`, HTTP 400). A wrong code returns `InvalidStepUpCodeError` with the attempts left. Issue, success and failure are written to the audit chain (`STEP_UP_OTP_ISSUED` / `_VERIFIED` / `_FAILED`). In production, a server without an email provider refuses to issue codes (HTTP 503) rather than falling back.
5. **`REG-003` explicit approval:** `user_approved=True` with an approval timestamp.
6. **KYC flag:** the profile must have `kyc_verified=True`; otherwise `ExecutionModule` raises `KYCUnverifiedError` with the reason and the fix in plain words (for example, a source of funds that cannot be verified). **`REG-004`** separately rejects an approval older than 15 minutes.
7. **`CLIENT_BALANCE` (per-client funds):** a buy must cost no more than the client's own available cash (cash minus open buy orders, at the live quote), and a sell must not exceed the client's own shares minus open sell orders. This is needed because every client shares one Alpaca paper account, whose buying power would otherwise let one client spend another's money. Blocks are written to the audit chain.
8. **`AML-001` per-trade cap:** notional must not exceed **\$100,000** (`MAX_SINGLE_TRADE_NOTIONAL_USD`).
9. **`PERM-CAP-DAILY`:** the prior 24 h of `trades` plus this order must not exceed **\$250,000** (`MAX_DAILY_TRADE_NOTIONAL_USD`).
10. **`PERM-WHITELIST`:** the symbol must be in `ALLOWED_TRADING_SYMBOLS`, a frozen set of **101** symbols that Alpaca can trade (US equity, bond, commodity and spot-crypto ETFs, and US large caps).
11. **`PERM-CIRCUIT-BREAKER`:** three or more blocked attempts within 60 s lock the client for 15 minutes (`OPEN_LOCKED`). A user can clear a lock only if it was caused entirely by simulated drills.
12. **`PERM-STEP-UP-MFA`:** orders over \$1,000 or over 5 % of NAV pass only if the orchestrator has verified the emailed code server-side (`step_up_verified`) and the client attested. The guard never compares a code supplied in the request body.
13. **`SUIT-*` / `CONC-*` / `AML-002`:** suitability, concentration and order-velocity rules.
14. **30-second double-submit lock:** a cache lock, plus a durable check in the `trades` table that rejects an identical client, symbol and side committed in the last 30 s.
15. **Paper-only broker:** the base URL was already validated at start-up.

Every pass, block and execution is written to the hash-chained audit log.

### 2.2 Compliance rule catalogue (`DEFAULT_COMPLIANCE_RULES`)

| ID | Rule | ID | Rule |
| :--- | :--- | :--- | :--- |
| `SUIT-001` | Asset risk within the client's tolerance (max delta 1.0) | `REG-001` | Prohibited language ("guaranteed", "risk-free", "100% safe", …) |
| `SUIT-002` | Horizon < 3 years: equity ≤ 40 %, bond duration ≤ 7 y, no illiquid assets | `REG-002` | Mandatory risk disclosure |
| `SUIT-003` | Low loss capacity: risk ≤ 5, equity ≤ 50 %, no growth/aggressive categories | `REG-003` | Explicit human approval |
| `CONC-001` | Single stock ≤ 15 % NAV (client-directed override with attestation and step-up). Broad index and bond funds (SPY, VTI, BND, AGG, …) are exempt; single stocks and single-asset funds (GLD, IBIT) are not | `REG-004` | Approval no older than 15 minutes |
| `CONC-002` | Single sector ≤ 30 % NAV | `AML-001` | Per-trade notional ≤ \$100k (above needs enhanced KYC) |
| `CONC-003` | At least 2 asset classes above 5 % each | `AML-002` | At most 5 orders per 10 minutes |

Permission gates: `PERM-TIER-5`, `PERM-CIRCUIT-BREAKER`, `PERM-WHITELIST`, `PERM-CAP-DAILY`, `PERM-STEP-UP-MFA`.

---

## 3. Data that leaves the backend

| Destination | What is sent | Control |
| :--- | :--- | :--- |
| Yahoo Finance, FRED, SEC EDGAR, Finnhub | Ticker symbols, CIKs, series IDs | Typed tool argument schemas; no client fields exist on these calls |
| LLM API (OpenAI-compatible) | Up to the last 8 dialogue turns plus a suitability snippet (age, horizon, risk score, liquid net worth, buffer months, holdings weights) | `redact_sensitive_data()` strips e-mails, phone numbers, SSN/BVN/NIN/TIN, card/account numbers, IBANs, API keys and bearer tokens, and "my name is …" names. `client_id` and name are replaced by `ANON-` plus a truncated SHA-256. |
| Alpaca Paper | `(symbol, side, qty, type, time_in_force)` | Paper-only URL guard; no identity or profile data |
| Ethereum Sepolia (optional) | Merkle root only | No entry content leaves the system |
| Email provider (Brevo / Resend / SMTP) | Account email, step-up code, order summary | Sent only to the account owner |

**Residual exposure (honest view):** the LLM provider still receives financial attributes and free-text dialogue. Regex redaction does not catch every form of PII. For example, a name given without "my name is", a street address, or an employer name would be sent. See `RISK-04`.

---

## 4. Prompt-injection and output controls

- **User input (`RULE-09`):** `check_input_safety()` matches system-prompt overrides, compliance-bypass requests, "execute without approval" instructions, jailbreak/DAN phrasing and HTML/script payloads. Matches are blocked and count towards the circuit breaker.
- **External content:** `services/sanitizer.py` strips HTML and scripts, normalises Unicode and neutralises delimiter collisions. It wraps web and filing text in `<untrusted_external_content>` before the model sees it.
- **Structural defence:** even a fully successful injection can at most produce text or a *proposal*. The LLM has no tool that executes a trade. Execution requires the separate approval call and the deterministic gates in §2.1.
- **Output:** `check_text_output()` applies `REG-001`/`REG-002`. Negated phrases ("not guaranteed") and the term "risk-free rate" are not treated as promises, so a disclaimer no longer causes a whole answer to be replaced. The three-reviewer stage (suitability, devil's advocate, numeric consistency) re-checks advice before delivery.
- **Scope:** the advisor's instructions limit it to money topics; off-topic requests are declined with a pointer to the financial angle.

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
| **RISK-07** | Step-up "MFA" was not a second factor (code derived from `proposal_id`, shown in the UI) | **Fixed** | Low | Medium | Random single-use code delivered out-of-band by email, stored as an HMAC digest, bound to user and proposal, 5 min TTL, 5 attempts, resend throttling, audited. The derivation function and the UI auto-fill were deleted. `OTP_DEV_ECHO` (local demo aid) is refused in production. **Residual:** email is a weaker factor than an authenticator; whoever controls the mailbox can approve. | TOTP or WebAuthn as the step-up factor |
| **RISK-08** | Default `SECRET_KEY` / `AUDIT_SECRET_KEY` | **Fixed** | Low | Low | With `ENVIRONMENT=production`, start-up refuses either key if it is the development default, shorter than 32 characters, or identical to the other (`guard_production_secrets`). | Rotate keys through a secrets manager |
| **RISK-09** | Sepolia anchoring is off unless a wallet is configured | **Fixed (honest reporting)** | Low | Medium | Without a wallet no transaction hash is produced (`tx_hash=null`, status `not_configured`); the former hash-shaped placeholder was removed. Real anchors return an Etherscan link and are recorded as `AUDIT_ANCHORED` audit entries. `verify_anchor` checks the chain instead of the hash format. Mainnet is rejected. | Configure a funded testnet wallet to produce anchors |
| **RISK-10** | JWT in `localStorage`, no revocation | Open | Medium | High | React output escaping, server-side sanitisation, 60-minute expiry. Sign-out and expired sessions also clear the client's name, open chat and saved results from the browser. | `HttpOnly` / `SameSite` cookie, CSP header, revocation list |
| **RISK-11** | No inbound rate limiting or login lockout | **Partly fixed** | Low | Medium | **Fixed:** 5 failed logins per account in 15 minutes return HTTP 429 with `Retry-After`, and a successful login clears the count. **Limits:** the counter is in-process (per instance, reset on restart). An attacker can deliberately lock a known account for 15 minutes. Registration and chat are not throttled. | Gateway-level per-IP limits; throttle `/auth/register` and chat |
| **RISK-12** | KYC/AML is self-declared | Open | Medium | **High** | Unverified profiles are blocked at execution (`KYCUnverifiedError`) | Identity-verification provider |
| **RISK-13** | Shared state in process memory (Redis optional; live `/health` shows `redis: false`) | Partly mitigated | Medium | Medium | Durable 30 s duplicate check in PostgreSQL, and proposal recovery and replay rejection from the audit log. **Circuit-breaker and login-throttle state are still in memory.** They reset on restart and are not shared across instances. | Redis or a PostgreSQL-backed circuit breaker and throttle |
| **RISK-14** | Step-up gate was opt-in on the API | **Fixed** | — | — | `handle_trade_approval` always sets `enforce_step_up_mfa`. `check_trade` defaults it on for any trade carrying a `proposal_id`. Approvals without a code are turned back before compliance. Regression tests cover omitted fields and the old static code. | — |
| **RISK-15** | "Human approval" is a client-asserted flag; `/trade/execute` can propose and execute in one call | **Partly fixed** | Low | Medium | Every Red-tier approval is now bound to a fresh emailed one-time code for that proposal, so the one-call path cannot execute a Red-tier order. Yellow-tier orders (≤ \$1,000 and ≤ 5 % NAV) still rely on the authenticated approval flag. | Remove the one-call propose+execute path |
| **RISK-16** | Blockchain receipts other than Sepolia could not be verified on a public chain | **Fixed (removed)** | — | — | Only verifiable Sepolia anchoring remains; the other receipt integrations were removed. | — |
| **RISK-21** | Sandbox features that could not be backed by live data | **Fixed (removed)** | — | — | Integrations that could only be simulated (external broker and custodian connections, a second broker, static FX data) were removed. Every figure the app shows comes from live data or the client's own paper-trading ledger, Merkle proofs are verified, and paper fills are labelled. | — |
| **RISK-17** | Circuit breaker was self-resettable | **Fixed** | — | Low | The demo "simulate" button records `SIMULATED_DRILL` incidents, and the drill buttons are hidden from customers unless `NEXT_PUBLIC_SHOW_DEMO_CONTROLS=true`. `POST /compliance/circuit-breaker/reset` returns HTTP 423 when any real blocked attempt is behind the current lock or the 60 s watch window, so such locks must expire. | Admin role for manual unlocks |
| **RISK-18** | Append-only is enforced in the ORM, not the database | Open | Low | Medium | The hash chain and HMAC detect edits (`/audit/{id}/verify`). Anyone with the HMAC key and DB access could rewrite the chain consistently. | DB role without UPDATE/DELETE on `audit_log`; real external anchoring |
| **RISK-19** | CORS allowed any `https://*.vercel.app` origin | **Fixed (narrowed)** | Low | Low | The origin regex is now configurable (`CORS_ORIGIN_REGEX`). The default allows only `fin-future` / `finfuture` Vercel domains and localhost. Auth uses bearer tokens, not cookies. | Pin the exact production origin; Vercel project names are not reserved, so a third party could create `fin-future-x.vercel.app` |
| **RISK-22** | `POST /compliance/check-input` accepted any `client_id`, so a user could send blocked prompts in another client's name and trip that client's circuit breaker | **Fixed** | — | — | A supplied `client_id` must belong to the caller (`verify_client_ownership`, HTTP 403 otherwise). Regression test in `test_production_hardening.py`. | — |
| **RISK-23** | Configuration errors printed every setting, API keys included, into the logs | **Fixed** | — | — | `hide_input_in_errors=True` on the settings model; the Redis connection log no longer includes credentials. | Secrets manager with scheduled rotation |
| **RISK-24** | Sign-up and credential spraying were limited only per account; chat attachments had no type or size limit and were stored whole | **Fixed** | — | — | Per-IP limits on registrations (10/hour) and failed logins (30/15 min). Attachments: images only (PNG, JPEG, WebP, GIF), at most 4 per message and 4 MB each, enforced on REST and WebSocket. The unused `/api/v1/research/*` router (unauthenticated stream, unbounded in-memory state, hard-coded citations) was removed. | Shared limiter in Redis when running several instances |
| **RISK-25** | One shared Alpaca paper account served every client: each saw the same cash, other clients' holdings and trades, and could spend cash or sell shares belonging to others | **Fixed** | — | — | Each client's portfolio is a ledger of their own trades on a $100k simulated start, valued at live prices. Open broker orders are synced to their real fills and reserve cash or shares. The `CLIENT_BALANCE` gate (§2.1, step 7) blocks orders beyond the client's own balance. Valuation history recorded from the shared account is excluded. Tests in `test_per_client_portfolio.py`. | Separate broker sub-accounts per client |
| **RISK-26** | Any signed-in client could trigger Sepolia anchoring, which spends the server wallet's test ETH, with no rate limit | **Fixed** | — | Low | Ownership check; testnet only. One anchor per client per 10 minutes (`ANCHOR_COOLDOWN_SECONDS`, held in the shared cache) and at most 20 per hour server-wide (`ANCHOR_MAX_PER_HOUR`), both returning HTTP 429 with `Retry-After`. A send that fails does not use up the cooldown. Tests in `test_anchor_rate_limit.py`. | Server-wide cap in Redis when running several instances |
| **RISK-20** | Restart fallbacks scanned only the latest 50 / 100 audit entries | **Fixed** | — | — | The queries now cover every `TRADE_PROPOSED` / `TRADE_EXECUTED` entry inside the proposal TTL window instead of a fixed row count. A regression test covers recovery and replay rejection after cache loss. | Index or column for `proposal_id` at higher volume |

`GET /api/v1/compliance/permission-tiers` currently serves `RISK-01` to `RISK-06` from `get_known_risk_register()`. `RISK-07` to `RISK-26` are documented here only.

### 5.1 Remediation log (2026-10-19)

| Item | Change | Files |
| :--- | :--- | :--- |
| RISK-14 | Step-up always enforced; `StepUpRequiredError` for approvals without a code | `agents/orchestrator.py`, `agents/compliance_guard.py` |
| RISK-07 | Static code removed, then replaced with an emailed single-use OTP (`StepUpOTPService`, `POST /trade/{id}/step-up`) | `services/otp_service.py`, `agents/orchestrator.py`, `agents/compliance_guard.py`, `api/routes/trade.py`, `frontend/.../TradeTicket.tsx` |
| RISK-08 | Production start-up guard for signing secrets | `core/config.py` |
| RISK-16, RISK-21, RISK-09 | Removed sandbox-only integrations; verifiable Sepolia anchoring with Etherscan links; real Merkle-proof verification | `services/anchoring.py`, `api/routes/audit.py`, `agents/execution_module.py`, `frontend/src/app/app/*` |
| RISK-17 | Drill-only reset; HTTP 423 otherwise | `agents/compliance_guard.py`, `api/routes/compliance.py`, `frontend/.../compliance/page.tsx` |
| RISK-11 | Per-account failed-login throttle | `api/routes/auth.py` |
| RISK-19 | Configurable, narrowed CORS origin regex | `core/config.py`, `main.py` |
| RISK-20 | Restart-recovery queries cover the whole proposal time window | `agents/orchestrator.py` |
| Related | REST `/chat/message` returns blocked approvals as error events instead of HTTP 500 | `api/routes/chat.py` |
| Hardening | API errors no longer echo internal exception text. Security headers added (`nosniff`, `DENY` framing, referrer policy, HSTS in production). Production refuses `DEBUG=true` and `OTP_DEV_ECHO=true` | `main.py`, `api/routes/*.py`, `core/config.py` |
| RISK-22, RISK-23, RISK-24 | Tenant check on `check-input`; secrets hidden from config errors and logs; per-IP auth limits; image-only bounded attachments; unused research router removed; frontend security headers and `poweredByHeader: false`; CI with a dev-artifact check | `api/routes/compliance.py`, `core/config.py`, `services/cache.py`, `api/routes/auth.py`, `services/attachments.py`, `api/routes/chat.py`, `api/routes/ws.py`, `frontend/next.config.mjs`, `.github/workflows/ci.yml` |

### 5.2 Remediation log (2026-10-20)

| Item | Change | Files |
| :--- | :--- | :--- |
| RISK-25 | Per-client portfolio ledger, open-order sync to real fills, `CLIENT_BALANCE` pre-trade gate, history excludes shared-account snapshots | `services/portfolio_service.py`, `agents/execution_module.py`, `agents/orchestrator.py`, `api/routes/portfolio.py` |
| CONC-001 | Broad index and bond funds exempt from the single-stock limit; the trade ticket relies on the server's decision | `agents/compliance_guard.py`, `agents/orchestrator.py`, `frontend/.../TradeTicket.tsx` |
| RISK-10 (partial) | Sign-out clears account data from browser storage | `frontend/src/lib/auth.tsx` |
| RISK-17 | Drill buttons hidden unless `NEXT_PUBLIC_SHOW_DEMO_CONTROLS=true` | `frontend/.../compliance/page.tsx` |
| Accuracy | Health review counts cash, so a small holding is no longer reported as 100 % concentration; rebalance plans priced at live quotes; net worth is savings minus debts | `services/health_report.py`, `api/routes/profile.py` |
| Exposure | Full internal IDs replaced by short references in the UI; user IDs in the audit trail shown as "You" | `frontend/src/lib/format.ts`, `frontend/.../audit/page.tsx`, `frontend/.../profile/page.tsx` |
| Output | `REG-001` ignores negated phrases and "risk-free rate"; advisor limited to money topics | `agents/compliance_guard.py`, `agents/orchestrator.py` |
| Auth | Password policy on sign-up (length, letter and digit, common-password list, no email name) | `api/routes/auth.py`, `frontend/.../register/page.tsx` |
| RISK-26 | Per-client cooldown and server-wide hourly cap on Sepolia anchoring | `api/routes/audit.py`, `core/config.py` |

**Deployment note:** the backend will not start with `ENVIRONMENT=production` until `SECRET_KEY` and `AUDIT_SECRET_KEY` are set on Render to two different random values of at least 32 characters. For example, `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Red-tier trades also need an email provider: set `BREVO_API_KEY` and `EMAIL_FROM`. Render's free tier blocks outbound SMTP, so prefer an HTTPS provider there.

**Remaining before real money:** RISK-07 residual (authenticator-app or WebAuthn factor instead of email), RISK-15 (remove one-call propose+execute), RISK-10 (cookie-based session and CSP), RISK-12 (real KYC), RISK-13 (shared state store), RISK-18 (database-level append-only) and RISK-25 residual (per-client broker sub-accounts).

---

## 6. Verification evidence

| Check | Result |
| :--- | :--- |
| Security and compliance unit suites (`test_compliance_guard`, `test_challenger_m4_compliance`, `test_challenger_m5_security`, `test_security`, `test_permission_tiers_and_privacy`, `test_audit_logger`, `test_config`) | **all passed** (local run, 2026-10-19), including new regression tests for RISK-07, -08, -11, -14 and -17, and `test_step_up_otp.py` for the emailed one-time code |
| Full Python suite as run in CI (`backend/tests`, `tests/e2e_research`, `tests/unit`) | **930 passed, 0 failed** (829 + 101; local run, 2026-10-20). Frontend type-check, ESLint, dev-artifact check and production build are clean |
| Per-client funds and balance gate (`test_per_client_portfolio.py`) | Clients do not see each other's trades; open orders sync to real fills and reserve cash; buying beyond one's own cash and selling unheld shares are blocked; CONC-001 exempts SPY and BND but not AAPL or GLD |
| Live HTTP run of the OTP flow (local server, 2026-10-19) | No code → 403 `StepUpRequiredError`; the old derived code → rejected; resend within 30 s → 429; wrong code → 403 with attempts left; missing attestation → 400 without consuming the code; correct code → filled; replay → 409. Each step appears in the audit chain. |
| Live production run against Render and Vercel (2026-10-18) | 57 / 57 operations passed; raw results with the hash-chained audit entries and their verification in `evidence/live_e2e_results.json` |

Reproduce:

```bash
PYTHONPATH=backend:. python -m pytest \
  backend/tests/unit/test_compliance_guard.py backend/tests/unit/test_challenger_m4_compliance.py \
  backend/tests/unit/test_challenger_m5_security.py backend/tests/unit/test_security.py \
  backend/tests/unit/test_permission_tiers_and_privacy.py backend/tests/unit/test_audit_logger.py \
  backend/tests/unit/test_config.py -q
```

**Interactive checks for judges:**

- `/app/compliance`: view the tier catalogue and the circuit-breaker state. On a demo deployment with `NEXT_PUBLIC_SHOW_DEMO_CONTROLS=true`, trip it with the drill button (`POST /api/v1/compliance/circuit-breaker/simulate`). Test injection and redaction with `POST /api/v1/compliance/check-input`.
- `/app/trade`: an order over \$1,000 shows the RED step-up dialog and emails a 6-digit code to the account address. Approving without it, with a wrong code (attempts left are shown) or with a reused code is refused. A non-whitelisted symbol is refused at proposal time (HTTP 403).
- `/app/trade` with two accounts: orders placed by one never appear in the other's portfolio, and a buy larger than the account's own cash is refused with the amount available.
- `/app/audit`: verify the chain and open a Merkle inclusion proof. When a Sepolia wallet is configured, anchor the trail and open the transaction on Etherscan; its input data equals the Merkle root.

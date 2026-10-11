# Handoff Report: Requirements & Module Interface Contracts

**Agent ID:** Survey Explorer 3 (`teamwork_preview_explorer_survey_3`)  
**Target:** Orchestrator (`498f461a-015a-42ad-98d2-3a9070fe1d9a`)  
**Timestamp:** 2026-10-10T12:35:00Z  
**Deliverable File:** `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_3\analysis.md`

---

## 1. Observation
1. **Authoritative Request File** (`c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md`):
   * Line 10–21 specifies requirements: R1 Foundation (paper-only guard, auth, models, migrations, cache, audit hash chain, Sepolia anchoring), R2 Data Layer (pluggable providers, circuit breaker, TTLs), R3 Agents (Orchestrator, Risk Profiler, Market Data, Product Comparison, Allocation Engine, Behavioral Bias, Compliance Guard, Execution Module, Health Report), R4 API (all 13 REST endpoints + `/ws/chat`, JWT, lifespan), R5 Tests (10 scenarios in spec section 8.2).
   * Line 22–31 specifies Acceptance Criteria: `pytest -q --cov=. --cov-fail-under=80`, pass/fail cases for every compliance rule, 100-entry audit chain + tamper detection, REG-003 trade approval gate + 30s double-submit lock, 401 unauthenticated and 403 cross-client ownership guards, REG-001 "guaranteed" block, REG-002 risk disclosure requirement, zero-container startup via `python main.py`, and zero hard-coded mock route returns.
2. **Approved Plan File** (`C:\Users\HP VICTUS\.gemini\antigravity\brain\9f1c4f1d-ef21-4c12-aa8c-d125e3bed282\implementation_plan.md`):
   * Confirms technical choices: bcrypt+JWT auth, pluggable data providers (yfinance, FiscalData REST, FRED/CalcFi CSV with sample fallback), SQLite default / Postgres via `DATABASE_URL`, Redis with automatic in-memory TTL fallback, Sepolia testnet-only anchoring with Chain ID 1 refusal, `gpt-4o` LLM, and removal of mock route returns.
3. **v2.0 Technical Specification Source** (`C:\Users\HP VICTUS\.gemini\antigravity\scratch\wealth-advisory-agent\generate_tech_doc.py`):
   * Lines 1741–1753 define **Section 8.2 Key Test Scenarios** (the exact 10 scenarios referenced in `ORIGINAL_REQUEST.md` and the approved plan):
     1. Risk Profiling (conservative user receives score $\le 3.0$ and conservative category)
     2. Product Comparison (moderate profile yields ETFs with aligned volatility)
     3. Compliance Blocking (high-risk asset to conservative profile blocked by `SUIT-001`)
     4. Concentration Check (attempted allocation $> 30\%$ blocked by `CONC-001`)
     5. Trade Execution (Alpaca paper trade placement, fill, and audit entry)
     6. Bias Detection (loss aversion triggers detected with debiasing intervention)
     7. Audit Chain (100 sequential entries verified; tampered row detected)
     8. Guaranteed Returns (text with "guaranteed" blocked by `REG-001`)
     9. Non-Discretionary (unapproved trade blocked by `REG-003`)
     10. Portfolio Drift (10% drift triggers rebalancing recommendation)
   * Lines 1847–1865 define **Appendix A: Compliance Rule Catalog** with 12 rules:
     `SUIT-001..003`, `CONC-001..003`, `REG-001..004`, `AML-001..002`.
   * Lines 1804–1839 define the REST API endpoints and WebSocket event schemas (`user_message`, `agent_response`, `trade_proposal`, `trade_approved`, `trade_filled`, `portfolio_update`, `bias_alert`, `compliance_check`).
4. **Backend Roadmap & SQL Seeding** (`C:\Users\HP VICTUS\.gemini\antigravity\brain\5ffb5bec-9397-423f-876e-9572678af55f\backend_roadmap.md`):
   * Lines 274–286 provide exact seed parameters and DDL for all 12 compliance rules.
   * Lines 397–429 define TTL constants and Redis lock keys (`lock:trade:{client_id}`, `profile:draft:{session_id}`).
   * Lines 747–807 define the 6-factor composite product scoring weights ($0.30, 0.15, 0.20, 0.10, 0.15, 0.10$).
5. **Existing Codebase Scaffold** (`c:\Users\HP VICTUS\Documents\wealth_agent\backend/`):
   * `main.py`: Contains 12 placeholder REST routes + 1 WebSocket route, with mock return objects and deprecated `@app.on_event("startup")`.
   * `db/models.py`: Defines only `DBClientProfile`, `DBAuditLog`, `DBTrade`. Missing `users`, `portfolio_snapshots`, `behavioral_memory`, `compliance_rules`.
   * `agents/compliance_guard.py`: Implements only `SUIT-001` and `REG-003`.
   * `agents/execution_module.py`: Lacks Redis trade locks, KYC gate, and production error guards.

---

## 2. Logic Chain
1. *Observation 1 & 3* link `ORIGINAL_REQUEST.md` requirement R5 ("covering the 10 scenarios in spec section 8.2") directly to the Section 8.2 test catalog in `generate_tech_doc.py` lines 1741–1753.
2. *Observation 1, 3 & 4* establish the exact 12-rule Compliance Catalog: 3 Suitability rules (`SUIT-001..003`), 3 Concentration rules (`CONC-001..003`), 4 Regulatory rules (`REG-001..004`), and 2 AML rules (`AML-001..002`), along with their check functions, severities (`BLOCK` vs `WARN`), and parameters.
3. *Observation 1, 2 & 3* establish the API surface: 13 REST endpoints (Auth register/login/me, session start, chat message, profile get, compare ETFs/bonds, portfolio get/health-report, trade execute, audit get/verify) plus the `/ws/chat` event loop with 8 structured event payloads.
4. *Observation 1 & 5* reveal the gaps between the current scaffold and the target requirements: the existing backend is a scaffold requiring structural decomposition into clean router modules, full model definitions, full agent state machines, pluggable data pipelines, and a test suite with 80%+ coverage.
5. Therefore, a complete specification breakdown with explicit data models, method signatures, schemas, and verification commands is required to enable implementation agents to build each milestone without ambiguity.

---

## 3. Caveats
- `FRED_API_KEY`: In development environments without a free FRED key, the macro provider will fall back to US Treasury data and recorded CalcFi sample fixtures, as agreed in the approved plan.
- Sepolia Ethereum testnet anchoring requires testnet credentials (`SEPOLIA_RPC_URL`, `SEPOLIA_PRIVATE_KEY`, `AUDIT_CONTRACT_ADDRESS`); the system will operate in `dry-run` mode if these are unconfigured, and strictly rejects Ethereum Mainnet (Chain ID 1).
- Frontend (`frontend/`) and Dockerfiles are strictly out of scope per user constraint.

---

## 4. Conclusion
The requirements, rule catalogs, testing scenarios, API contracts, and interface schemas for the Wealth Advisory Agent backend have been fully recovered, verified, and systematically compiled into:
`c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_3\analysis.md`.

This breakdown provides the exact blueprint for all downstream milestones (M1 Foundation, M2 Data Layer, M3 Agents Core, M4 Compliance/Execution/Health, M5 API/WS, and M6 Tests).

---

## 5. Verification Method
1. Inspect the comprehensive analysis deliverable:
   * View `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_survey_3\analysis.md`.
2. Inspect the authoritative source documents:
   * `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md` (lines 10–31)
   * `C:\Users\HP VICTUS\.gemini\antigravity\brain\9f1c4f1d-ef21-4c12-aa8c-d125e3bed282\implementation_plan.md`
   * `C:\Users\HP VICTUS\.gemini\antigravity\scratch\wealth-advisory-agent\generate_tech_doc.py` (lines 1100–1209, 1726–1753, 1804–1865)
   * `C:\Users\HP VICTUS\.gemini\antigravity\brain\5ffb5bec-9397-423f-876e-9572678af55f\backend_roadmap.md` (lines 273–287)
3. Target test execution once implemented:
   ```bash
   cd backend
   pytest -q --cov=. --cov-fail-under=80
   pytest tests/unit/test_compliance.py -v
   pytest tests/e2e/test_spec_scenarios.py -v
   ```

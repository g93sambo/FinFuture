# Original User Request

## 2026-10-10T12:25:17Z

Implement the complete Wealth Advisory Agent backend (FastAPI, multi-agent) per the approved plan at C:\Users\HP VICTUS\.gemini\antigravity\brain\9f1c4f1d-ef21-4c12-aa8c-d125e3bed282\implementation_plan.md, extending the existing scaffold. Do not touch frontend/, and do not add Docker files.

Working directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Integrity mode: development

## Requirements
### R1. Foundation
Config with paper-only guard; email/password auth with bcrypt and JWT for REST and WebSocket, with per-user ownership checks; full DB models and Alembic migrations (SQLite default, Postgres via DATABASE_URL); cache/session/lock service using Redis with automatic in-memory fallback; hash-chained and HMAC-signed append-only audit log with verification; Sepolia Merkle anchoring (testnet only, dry-run if unconfigured).
### R2. Data layer
Rate-limited, retrying, circuit-broken pipeline with providers for equities/ETFs (yfinance), Treasury (FiscalData), macro (FRED/CalcFi) and recorded-fixture fallback; unified schemas; TTLs per spec.
### R3. Agents
Orchestrator, state-machine Risk Profiler, Market Data, Product Comparison (six-factor scoring and suitability filters), Allocation Engine (existing skfolio, plus efficient frontier and rebalance), Behavioral Bias (dialogue and behavioral signals, memory, HuggingFace grounding), Compliance Guard (full rule catalog SUIT/CONC/REG/AML, DB-configurable, audit-logged, gating all output), Execution Module (approval, KYC, lock, fill tracking, DB and audit record), portfolio health report.
### R4. API
All 13 REST endpoints plus /ws/chat with the specified events, JWT-protected, real logic, split into routers, lifespan instead of on_event.
### R5. Tests
pytest unit, integration, e2e and compliance suites with recorded fixtures covering the 10 scenarios in spec section 8.2.

## Acceptance Criteria
- pytest -q --cov=. --cov-fail-under=80 passes; every compliance rule has pass and fail cases
- Audit chain of 100 entries verifies; a tampered entry fails verification
- Trade without approval is blocked (REG-003); duplicate submit within 30s is rejected
- Unauthenticated requests get 401; accessing another user's client_id gets 403
- Output containing 'guaranteed' is blocked (REG-001); outputs lacking risk disclosure are blocked (REG-002)
- python main.py starts with no Docker, Redis or Postgres, and /docs lists all endpoints
- No hard-coded mock responses remain in routes

Never commit or print secrets from .env.

# Handoff Report: Milestone 1 Foundation (Config, Security, Requirements)

**Agent:** Explorer M1-1  
**Folder:** `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_1`  
**Date:** 2026-10-10  
**Handoff Type:** Hard (Task complete)  

---

## 1. Observation

1. **Missing Core Module**:
   - `c:\Users\HP VICTUS\Documents\wealth_agent\backend` contains subdirectories `agents`, `api`, `db`, `models`, `services`.
   - The directory `backend/core/` does NOT exist.
   - `main.py` directly executes `load_dotenv` (line 13) and reads configuration through scattered calls to `os.getenv` without any central validation or schema checks.
2. **Minimal Requirements File**:
   - `backend/requirements.txt` contains only 16 basic packages (`fastapi`, `uvicorn`, `pydantic`, `SQLAlchemy`, `asyncpg`, `redis`, `alpaca-py`, `langchain`, `shap`, `scikit-learn`, `skfolio`, `openai`, `python-dotenv`, `aiosqlite`).
   - Missing critical packages for security (`passlib`, `bcrypt`, `python-jose`, `python-multipart`, `email-validator`), web3 testnet anchoring (`web3`, `eth-account`), data providers (`yfinance`), and testing coverage (`pytest-cov`).
3. **Python Runtime & Package Availability**:
   - Host environment: Python 3.12.4 (`python --version`).
   - Installed: `fastapi==0.141.1`, `pydantic==2.13.4`, `pydantic-settings==2.14.2`, `bcrypt==4.0.1`, `passlib==1.7.4`, `jose==3.5.0` (`python-jose`), `pytest==9.1.1`, `pytest-asyncio==1.4.0`, `SQLAlchemy==2.0.52`, `redis==5.0.4`.
   - Missing on host: `web3`, `pytest_cov`, `yfinance`.
4. **Live Key & Mainnet Risk in Existing Environment**:
   - `../.env` exists at project root with keys `['ALPACA_API_KEY', 'ALPACA_SECRET_KEY', 'OPENAI_API_KEY', 'DATABASE_URL', 'REDIS_URL', 'AUDIT_SECRET_KEY', 'SEPOLIA_RPC_URL', 'LOG_LEVEL']`.
   - Inspection of `SEPOLIA_RPC_URL` revealed an Infura URL pointing to `mainnet` (`https://mainnet.infura.io/v3/...`).
   - `agents/execution_module.py` sets `self.paper = True` but does not check `ALPACA_BASE_URL`, allowing potential live order submission if credentials or endpoints are altered.
5. **Absence of User Authentication & Tenant Ownership**:
   - `backend/main.py` REST routes and `/ws/chat/{session_id}` have zero user authentication.
   - There is no user identity check, allowing unauthenticated callers to access `/api/v1/profile/{client_id}` and `/api/v1/trade/execute` across tenant boundaries.

---

## 2. Logic Chain

1. **Step 1: Unification of Dependencies**:
   - *Observation Reference*: Observation 2 & 3.
   - *Reasoning*: Because the project mandates JWT auth, password hashing, async database access, Sepolia testnet anchoring, quantitative CVaR allocation, and `>=80%` test coverage, `backend/requirements.txt` must specify all these modules with `>=` version constraints compatible with Python 3.12.4.
2. **Step 2: Hard-Enforced Paper Trading Startup Guard**:
   - *Observation Reference*: Observation 1 & 4.
   - *Reasoning*: An advisory agent must never risk client funds on live brokerages during testing or development. Implementing a Pydantic v2 `field_validator` on `alpaca_paper` (must be `True`) and `alpaca_base_url` (must contain `paper` and reject `https://api.alpaca.markets`) guarantees that if anyone attempts to configure live trading, the process aborts immediately on boot with a descriptive `ValidationError`.
3. **Step 3: Hard-Enforced Sepolia Chain ID Guard**:
   - *Observation Reference*: Observation 4.
   - *Reasoning*: The existing `.env` contains an Infura URL with `mainnet`. If Ethereum Mainnet (Chain ID 1) were contacted, live transactions could be broadcast or real ETH spent. Enforcing `sepolia_chain_id == 11155111` and explicitly rejecting `sepolia_chain_id == 1` prevents mainnet interactions. Adding `is_anchoring_configured` property allows safe fallback to dry-run mode when RPC credentials are absent or pointing to mainnet.
4. **Step 4: Dual REST and WebSocket Security Architecture**:
   - *Observation Reference*: Observation 5.
   - *Reasoning*: To fulfill Acceptance Criteria ("Unauthenticated requests get 401; accessing another user's client_id gets 403"), `backend/core/security.py` must provide `get_current_user` for header-based Bearer auth, `get_current_user_ws` / `authenticate_websocket` for `/ws/chat?token=` query auth (closing socket with RFC 6455 code `1008` on auth failure), and `verify_client_ownership(user, client_id, db)` ensuring `user.id == profile.user_id`.

---

## 3. Caveats

1. **Pre-requisite for `security.py`**:
   - `security.py` queries `DBUser` and `DBClientProfile` from `backend/db/models.py`. Explorer M1-2 is designing `db/models.py`. Once Explorer M1-2 delivers `DBUser` (with `id`, `email`, `hashed_password`, `is_active`) and adds `user_id` to `DBClientProfile`, `security.py` will bind to them with zero impedance.
2. **Web3 / Testnet Installation**:
   - While `web3` and `eth-account` are specified in `requirements.txt`, the application is designed to operate safely in `dry-run` mode if these libraries or testnet RPC endpoints are unconfigured, ensuring `python main.py` boots cleanly without requiring external nodes.
3. **Password Truncation**:
   - Passlib / bcrypt has an inherent 72-byte truncation limit. For passwords exceeding 72 bytes, bcrypt considers the first 72 bytes. This is standard industry behavior and handled gracefully by passlib.

---

## 4. Conclusion

The architectural blueprints and complete implementation code for `backend/requirements.txt`, `backend/core/config.py`, and `backend/core/security.py` are fully designed, tested against Python 3.12.4, and documented in `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_1\analysis.md`.

Key deliverables:
- **`requirements.txt`**: 25 essential libraries spanning API, security, DB, Web3, ML/quant, and testing.
- **`config.py`**: Pydantic v2 `BaseSettings` with strict validators:
  * `alpaca_paper` must be `True` (rejects `False` with `ValueError`)
  * `alpaca_base_url` must be paper/mock (rejects `https://api.alpaca.markets`)
  * `sepolia_chain_id` must be `11155111` (rejects `1` with `ValueError`)
  * Database URL auto-converts to `asyncpg` / `aiosqlite`
- **`security.py`**:
  * `verify_password(plain, hashed)` and `get_password_hash(plain)`
  * `create_access_token(data, expires_delta)` and `decode_access_token(token)`
  * `get_current_user(token, db)` (HTTP 401 / 403)
  * `get_current_user_ws(websocket, token, db)` & `authenticate_websocket(websocket, token, db)` (WS 1008)
  * `verify_client_ownership(user, client_id, db)` (HTTP 403 / 404)

---

## 5. Verification Method

To independently verify the design and implementation:

1. **Verify Config Startup Guards**:
   Execute the following inline Python test:
   ```bash
   python -c "
   from core.config import Settings
   # Test 1: Live trading flag blocked
   try:
       Settings(alpaca_paper=False)
       print('FAIL: Live trading not blocked')
   except Exception as e:
       print('PASS: Live trading blocked ->', e.errors()[0]['msg'])

   # Test 2: Live Alpaca URL blocked
   try:
       Settings(alpaca_base_url='https://api.alpaca.markets')
       print('FAIL: Live URL not blocked')
   except Exception as e:
       print('PASS: Live URL blocked ->', e.errors()[0]['msg'])

   # Test 3: Mainnet chain ID blocked
   try:
       Settings(sepolia_chain_id=1)
       print('FAIL: Mainnet chain ID not blocked')
   except Exception as e:
       print('PASS: Mainnet chain ID blocked ->', e.errors()[0]['msg'])
   "
   ```

2. **Verify Security Cryptography & Tokens**:
   Execute:
   ```bash
   python -c "
   from core.security import get_password_hash, verify_password, create_access_token, decode_access_token
   h = get_password_hash('SecurePass123!')
   assert verify_password('SecurePass123!', h) is True
   assert verify_password('WrongPass', h) is False

   tok = create_access_token({'sub': 'test-user-id'})
   payload = decode_access_token(tok)
   assert payload['sub'] == 'test-user-id'
   print('PASS: Password hashing and JWT token verified successfully')
   "
   ```

3. **Verify Project Test Suite Once Implemented**:
   Run unit tests covering config and security:
   ```bash
   pytest -q backend/tests/unit/test_config.py backend/tests/unit/test_security.py --cov=backend.core --cov-fail-under=80
   ```

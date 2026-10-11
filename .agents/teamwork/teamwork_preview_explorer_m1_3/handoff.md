# Handoff Report: Cache, Audit Logger, and Anchoring Services (Milestone 1)

**Agent**: Explorer 3 (`teamwork_preview_explorer_m1_3`)  
**Parent / Recipient**: Orchestrator (`498f461a-015a-42ad-98d2-3a9070fe1d9a`)  
**Scope**: Exact architecture and implementation specifications for `backend/services/cache.py`, `backend/services/audit_logger.py`, and `backend/services/anchoring.py`.

---

## 1. Observation

1. **Service Directory State**:
   - Inspected `backend/services/` via directory listing:
     `{"DirectoryPath": "c:\\Users\\HP VICTUS\\Documents\\wealth_agent\\backend\\services"}` -> Returned `Empty directory`.
   - No implementations existed for `cache.py`, `audit_logger.py`, or `anchoring.py`.

2. **Project Requirements**:
   - `ORIGINAL_REQUEST.md` (lines 11-12):
     `"cache/session/lock service using Redis with automatic in-memory fallback; hash-chained and HMAC-signed append-only audit log with verification; Sepolia Merkle anchoring (testnet only, dry-run if unconfigured)."`
   - `ORIGINAL_REQUEST.md` (lines 24-28):
     - `"Audit chain of 100 entries verifies; a tampered entry fails verification"`
     - `"Duplicate submit within 30s is rejected"`
     - `"python main.py starts with no Docker, Redis or Postgres, and /docs lists all endpoints"`
   - `PROJECT.md` (lines 69-82):
     - Cache contracts: `get(key)`, `set(key, value, expire)`, `delete(key)`, `acquire_lock(lock_key, timeout_seconds=30)`, `release_lock(lock_key)`.
     - Audit logger contracts: `log_audit_entry(db, client_id, event_type, actor, details, status="PASS", hmac_key=None) -> DBAuditLog` and `verify_audit_chain(db, client_id, hmac_key=None) -> Tuple[bool, Optional[int]]`.
     - Anchoring requirements: Sepolia chain ID 11155111, hard-reject chain ID 1, dry-run if unconfigured.

3. **Database Model Interfacing**:
   - Existing `backend/db/models.py` (lines 33-47) defines `DBAuditLog`:
     `entry_id = Column(String, primary_key=True)`
     `timestamp = Column(DateTime, default=datetime.utcnow)`
     `event_type = Column(String, nullable=False)`
     `client_id = Column(String, ForeignKey("client_profiles.client_id"))`
     `session_id = Column(String, nullable=False)`
     `agent_id = Column(String, nullable=False)`
     `action = Column(JSON, nullable=False)`
     `entry_hash = Column(String, nullable=False)`
     `previous_hash = Column(String, nullable=True)`
     `hmac_signature = Column(String, nullable=False)`
   - Explorer 2 dispatch (`teamwork_preview_explorer_m1_2/DISPATCH.md` line 18) indicates an updated schema:
     `DBAuditLog (id, client_id, event_type, actor, details, timestamp, prev_hash, entry_hash, signature)`.

4. **Dependencies**:
   - `backend/requirements.txt` includes `fastapi`, `redis>=5.0.1`, `SQLAlchemy>=2.0.23`, `aiosqlite>=0.19.0`.
   - `web3` is not yet installed in requirements.txt (Explorer 1 is tasked with adding `web3` and `eth-account`).

---

## 2. Logic Chain

1. **Cache Service Auto-Failover (Deducing from Observation 1 & 2)**:
   - Because `python main.py` must boot and run with zero external services (no Docker, no Redis), `CacheService` cannot fail fast or raise connection errors on startup.
   - Therefore, `CacheService` must implement a transparent dual-backend: an async Redis client (`redis.asyncio`) and an in-memory TTL store (`InMemoryCache`) protected by `asyncio.Lock`.
   - When Redis is unreachable or throws `redis.ConnectionError`, the service logs a warning, switches to `InMemoryCache`, and institutes a 30-second cooldown timer to prevent connection timeouts from throttling downstream operations.
   - For trade submission locks (`lock:trade:{client_id}`), `acquire_lock` in Redis uses atomic `SET NX EX 30`, while in memory it atomically checks if the key exists and `expire_at > now`.

2. **Audit Logger Immutability & Serialization (Deducing from Observation 2 & 3)**:
   - For an unbroken chain per `client_id`, each entry must link to the immediately prior entry's hash. The first entry uses genesis hash `0 * 64`.
   - If two concurrent requests attempt to log entries for the same client simultaneously, both would read the same `prev_hash` and fork the chain. Therefore, writes must be protected by an asynchronous lock per `client_id` (`_client_locks[client_id]`).
   - To guarantee exact hash recomputation across environments, `details` must be serialized with deterministic sorting and separators (`json.dumps(details, sort_keys=True, separators=(',', ':'), default=str)`), and timestamps canonicalized as UTC ISO 8601 strings.
   - To prevent coupling failures between Explorer 2's planned schema and existing `models.py`, `AuditLogger` dynamically inspects column names (`actor` vs `agent_id`, `details` vs `action`, `prev_hash` vs `previous_hash`, `signature` vs `hmac_signature`).

3. **Anchoring & Mainnet Guardrail (Deducing from Observation 2 & 4)**:
   - User `.env` contains potential production keys, so accidental execution on Ethereum Mainnet represents severe catastrophic risk.
   - Therefore, `AnchoringService` enforces a hard invariant: `if chain_id == 1: raise MainnetForbiddenError(...)`.
   - When unconfigured (`SEPOLIA_RPC_URL` or `SEPOLIA_PRIVATE_KEY` missing) or when `web3` is not installed, the service computes the genuine Merkle root from audit entry hashes and returns an informational `dry_run` result with a simulated transaction hash.
   - Odd leaf counts at any tree level are handled by duplicating the final leaf (`current_layer.append(current_layer[-1])`), matching RFC 6962.

---

## 3. Caveats

1. **Redis Multi-Process Deployment**:
   - `InMemoryCache` maintains locks in memory within the current Python process. When Redis is absent, multiple worker processes (e.g., Uvicorn multi-worker) will maintain independent in-memory locks. For single-process development (default `uvicorn main:app`), concurrency is fully serialized via asyncio locks. For multi-worker production, Redis is required.
2. **Sepolia Gas & Nonce Contention**:
   - Live transaction submission relies on single-account nonce sequencing. If concurrent batch anchoring is invoked, a queue or sequential worker must manage transactions. In development/testing, anchoring runs in dry-run mode.
3. **Database Schema Harmonization**:
   - Explorer 2 is responsible for finalizing `models.py`. Our implementation provides dynamic property inspection, but once Explorer 2 commits the final migration, the field names should be standardized across the repo.

---

## 4. Conclusion

The architectural designs for `backend/services/cache.py`, `backend/services/audit_logger.py`, and `backend/services/anchoring.py` are completely finalized and documented in `analysis.md`. 
The designs satisfy all acceptance criteria:
- Transparent in-memory TTL caching and double-submit locking when Redis is unavailable.
- Strict SHA-256 hash-chaining and HMAC signatures with 100-entry verification and tamper detection.
- Merkle root computation with Sepolia testnet anchoring, unconditional Mainnet Chain ID 1 hard rejection, and graceful dry-run simulation.

---

## 5. Verification Method

1. **Inspect Analysis Report**:
   - View file: `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m1_3\analysis.md`.
2. **Unit Test Verification (Implementer Phase)**:
   - Cache unit tests:
     ```bash
     pytest tests/unit/test_cache.py -v
     ```
     - Test cache `get`/`set` with TTL expiration.
     - Test `acquire_lock` returns `True` initially and `False` on immediate retry within 30s.
     - Test `release_lock` allows immediate re-acquisition.
   - Audit logger unit tests:
     ```bash
     pytest tests/unit/test_audit_logger.py -v
     ```
     - Create 100 sequential audit log entries for a client and run `verify_audit_chain(db, client_id)` -> must return `(True, None)`.
     - Mutate any field (e.g. payload or timestamp) in entry #50 and re-run -> must return `(False, entry_50_id)`.
   - Anchoring unit tests:
     ```bash
     pytest tests/unit/test_anchoring.py -v
     ```
     - Test `compute_merkle_root` with 0, 1, 2, 3, and 10 leaves.
     - Test chain ID 1 check raises `MainnetForbiddenError`.
     - Test dry-run mode returns valid `AnchoringResult` with `status="dry_run"`.

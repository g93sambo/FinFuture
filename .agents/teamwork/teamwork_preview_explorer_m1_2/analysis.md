# Architectural Analysis: Database Models, Invariants, Compliance Catalog & Migrations (Milestone 1)

**Agent**: Explorer 2 (`teamwork_preview_explorer_m1_2`)  
**Scope**: Milestone 1 (Foundation) — Database Architecture & Persistence Layer  
**Date**: 2026-10-10  

---

## 1. Executive Summary

This investigation establishes the complete architectural design, schema specifications, and persistence invariants for the Wealth Advisory Agent backend foundation:

1. **All 7 SQLAlchemy ORM Models Designed**:
   - `DBUser`: Identity, authentication credentials, and client ownership anchor.
   - `DBClientProfile`: 100% complete with all 11 missing fields added (dependents, liquid assets, expenses, debts, investment experience, loss capacity, target return, specific goals, emotional risk score, panic sell likelihood, transcript) plus `user_id` foreign key and relationship.
   - `DBPortfolioSnapshot`: Time-series asset allocations, market values, and cash balance for drift/health monitoring.
   - `DBTrade`: Trade orders, fills, Alpaca order IDs, and regulatory compliance reports.
   - `DBAuditLog`: Cryptographically chained append-only audit trail with previous hash linking and HMAC signatures.
   - `DBBehavioralMemory`: Persistent memory of detected cognitive biases, triggers, and debiasing interventions.
   - `DBComplianceRule`: Dynamic, DB-configurable rule catalog.
2. **Strict Append-Only Invariant on `DBAuditLog`**:
   - Multi-layer defense-in-depth:
     - SQLAlchemy ORM instance-level event listeners (`before_update`, `before_delete`).
     - SQLAlchemy Session query-level event listener (`do_orm_execute`) blocking bulk `UPDATE` and `DELETE` queries.
     - SQLite SQL triggers (`trg_audit_log_no_update`, `trg_audit_log_no_delete`) embedded in `init.sql`.
   - Verified via automated test harness: 100% of mutation attempts raise `AppendOnlyViolationError`.
3. **Complete 12-Rule Compliance Catalog & Seed DDL**:
   - Full catalog covering `SUIT-001..003`, `CONC-001..003`, `REG-001..004`, and `AML-001..002` with explicit parameter dictionaries and severity levels (`BLOCK` vs `WARN`).
   - Self-contained `init.sql` script with schema DDL, indexes, triggers, and idempotently seeded rules.
4. **Async Alembic Migration Infrastructure**:
   - Configured `alembic.ini` pointing to `db/migrations`.
   - Async `env.py` utilizing `async_engine_from_config` and `render_as_batch=True` for seamless SQLite and PostgreSQL compatibility.
   - Initial migration `0001_initial_schema.py` creating all 7 tables, creating indexes, and bulk-inserting all 12 compliance rules.
   - End-to-end verified with live `upgrade -> verify -> downgrade` test cycle.

---

## 2. Existing Baseline vs Required Schema

### 2.1 Existing State (`wealth_advisor.db` and `backend/db/models.py`)
- SQLite database currently contains only 3 tables (`client_profiles`, `audit_log`, `trades`), all with 0 records.
- `DBClientProfile` is missing 11 critical financial and psychological fields present in the Pydantic `ClientProfile` schema (`models/client_profile.py`).
- No user entity (`DBUser`) or ownership relationship exists.
- No `DBPortfolioSnapshot`, `DBBehavioralMemory`, or `DBComplianceRule` tables exist.
- No append-only enforcement exists on `DBAuditLog`.
- No Alembic configuration or migration scripts exist in the repository.

### 2.2 Model Gap Analysis & Complete Resolution

| Entity | Current Status | Required Status | Gap / Missing Elements Resolved |
|---|---|---|---|
| **DBUser** | Missing | Complete | `id`, `email`, `hashed_password`, `is_active`, `created_at`, `updated_at`, relationship to `client_profiles`. |
| **DBClientProfile** | Partial (15 fields) | Complete (28 fields) | Added: `user_id` (FK), `dependents`, `liquid_assets`, `monthly_expenses`, `existing_debts`, `investment_experience`, `loss_capacity`, `target_return`, `specific_goals`, `emotional_risk_score`, `panic_sell_likelihood`, `profiling_session_transcript`. |
| **DBPortfolioSnapshot** | Missing | Complete | `id`, `client_id` (FK), `total_value`, `positions`, `cash`, `timestamp`. |
| **DBTrade** | Partial | Complete | `id` (with `trade_id` synonym), `client_id`, `symbol`, `qty` (with `quantity` synonym), `side`, `order_type`, `status`, `filled_price`, `filled_qty`, `alpaca_order_id`, `compliance_report`, `user_approved_at`, `filled_at`, `created_at`. |
| **DBAuditLog** | Mutable | Append-Only Chained | `id` (with `entry_id` synonym), `client_id`, `event_type`, `actor`, `details` (with `action` synonym), `timestamp`, `prev_hash` (`previous_hash` synonym), `entry_hash`, `signature` (`hmac_signature` synonym), `session_id`, `agent_id`, `status`. Enforced append-only. |
| **DBBehavioralMemory** | Missing | Complete | `id`, `client_id` (FK), `bias_type`, `severity`, `trigger_context`, `intervention_text`, `timestamp`. |
| **DBComplianceRule** | Missing | Complete | `rule_id`, `name`, `category`, `severity`, `parameters`, `description`, `is_active`, `created_at`, `updated_at`. |

---

## 3. Comprehensive Specifications of the 7 SQLAlchemy ORM Models

### 3.1 Model 1: `DBUser`
- **Table**: `users`
- **Purpose**: Authenticated user accounts for REST JWT bearer auth and WebSocket `?token=` query auth. Enforces tenant boundary so users can only access their own client profile.
- **Columns**:
  - `id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `email`: `String(255)`, Unique, Indexed, Nullable=False
  - `hashed_password`: `String(255)`, Nullable=False (bcrypt hash)
  - `is_active`: `Boolean`, Default=True, Nullable=False
  - `created_at`: `DateTime`, Default `datetime.utcnow`, Nullable=False
  - `updated_at`: `DateTime`, Default `datetime.utcnow`, OnUpdate `datetime.utcnow`, Nullable=False
- **Relationships**:
  - `client_profiles`: `relationship("DBClientProfile", back_populates="user", cascade="all, delete-orphan", passive_deletes=True)`

### 3.2 Model 2: `DBClientProfile`
- **Table**: `client_profiles`
- **Purpose**: Unified client financial profile, psychological traits, risk parameters, and KYC/AML compliance status.
- **Columns**:
  - `client_id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `user_id`: `String(64)`, ForeignKey `users.id` (ON DELETE CASCADE), Indexed, Nullable=True
  - `age`: `Integer`, Nullable=True
  - `employment_status`: `String(64)`, Nullable=True
  - `dependents`: `Integer`, Default=0, Nullable=True *(Missing Field 1)*
  - `annual_income`: `Float`, Nullable=True
  - `net_worth`: `Float`, Nullable=True
  - `liquid_assets`: `Float`, Default=0.0, Nullable=True *(Missing Field 2)*
  - `monthly_expenses`: `Float`, Default=0.0, Nullable=True *(Missing Field 3)*
  - `existing_debts`: `Float`, Default=0.0, Nullable=True *(Missing Field 4)*
  - `investment_experience`: `String(64)`, Nullable=True *(Missing Field 5)*
  - `risk_tolerance_score`: `Float`, Nullable=True (range 1.0 - 10.0)
  - `investment_horizon_years`: `Integer`, Nullable=True
  - `liquidity_needs`: `String(32)`, Nullable=True ("low", "medium", "high")
  - `loss_capacity`: `String(32)`, Nullable=True ("low", "medium", "high") *(Missing Field 6)*
  - `primary_goal`: `String(128)`, Nullable=True ("wealth_preservation", "capital_growth", etc.)
  - `target_return`: `Float`, Nullable=True *(Missing Field 7)*
  - `specific_goals`: `JSON`, Default `list` *(Missing Field 8)*
  - `suitability_category`: `String(64)`, Nullable=True ("conservative", "moderate", "aggressive")
  - `detected_biases`: `JSON`, Default `list`
  - `emotional_risk_score`: `Float`, Default=0.0, Nullable=True *(Missing Field 9)*
  - `panic_sell_likelihood`: `Float`, Default=0.0, Nullable=True *(Missing Field 10)*
  - `kyc_verified`: `Boolean`, Default=False, Nullable=False
  - `aml_flag`: `Boolean`, Default=False, Nullable=False
  - `profiling_session_transcript`: `Text`, Default="", Nullable=True *(Missing Field 11)*
  - `created_at`: `DateTime`, Default `datetime.utcnow`, Nullable=False
  - `updated_at`: `DateTime`, Default `datetime.utcnow`, OnUpdate `datetime.utcnow`, Nullable=False
- **Synonyms**:
  - `profile_created_at = synonym("created_at")`
  - `profile_updated_at = synonym("updated_at")`
- **Relationships**:
  - `user`: `relationship("DBUser", back_populates="client_profiles")`
  - `portfolio_snapshots`: `relationship("DBPortfolioSnapshot", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)`
  - `trades`: `relationship("DBTrade", back_populates="client")`
  - `audit_logs`: `relationship("DBAuditLog", back_populates="client")`
  - `behavioral_memories`: `relationship("DBBehavioralMemory", back_populates="client", cascade="all, delete-orphan", passive_deletes=True)`

### 3.3 Model 3: `DBPortfolioSnapshot`
- **Table**: `portfolio_snapshots`
- **Purpose**: Valuation and asset holdings snapshot for calculating drift (> 5%), tracking performance benchmarks, and generating rebalancing trades.
- **Columns**:
  - `id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `client_id`: `String(64)`, ForeignKey `client_profiles.client_id` (ON DELETE CASCADE), Indexed, Nullable=False
  - `total_value`: `Float`, Nullable=False
  - `positions`: `JSON`, Nullable=False, Default `dict` (e.g. `{"SPY": {"qty": 10, "market_value": 4500.0, "asset_class": "equity"}}`)
  - `cash`: `Float`, Default=0.0, Nullable=False
  - `timestamp`: `DateTime`, Default `datetime.utcnow`, Indexed, Nullable=False
- **Relationships**:
  - `client`: `relationship("DBClientProfile", back_populates="portfolio_snapshots")`

### 3.4 Model 4: `DBTrade`
- **Table**: `trades`
- **Purpose**: Persists order lifecycle details, Alpaca broker order IDs, regulatory compliance checks, and user approval timestamps.
- **Columns**:
  - `id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `client_id`: `String(64)`, ForeignKey `client_profiles.client_id`, Indexed, Nullable=False
  - `symbol`: `String(32)`, Indexed, Nullable=False
  - `qty`: `Float`, Nullable=False
  - `side`: `String(16)`, Nullable=False ("BUY" or "SELL")
  - `order_type`: `String(32)`, Default="MARKET", Nullable=False
  - `status`: `String(32)`, Default="PENDING", Nullable=False ("PENDING", "FILLED", "REJECTED", "CANCELLED")
  - `filled_price`: `Float`, Nullable=True
  - `filled_qty`: `Float`, Default=0.0, Nullable=True
  - `alpaca_order_id`: `String(64)`, Indexed, Nullable=True
  - `compliance_report`: `JSON`, Default `dict`, Nullable=True
  - `user_approved_at`: `DateTime`, Nullable=True
  - `filled_at`: `DateTime`, Nullable=True
  - `created_at`: `DateTime`, Default `datetime.utcnow`, Indexed, Nullable=False
- **Synonyms**:
  - `trade_id = synonym("id")`
  - `quantity = synonym("qty")`
- **Relationships**:
  - `client`: `relationship("DBClientProfile", back_populates="trades")`

### 3.5 Model 5: `DBAuditLog`
- **Table**: `audit_log`
- **Purpose**: Append-only audit record linked in a cryptographic SHA-256 hash chain with HMAC-SHA256 signatures for tamper detection and Sepolia Merkle anchoring.
- **Columns**:
  - `id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `client_id`: `String(64)`, ForeignKey `client_profiles.client_id`, Indexed, Nullable=True
  - `event_type`: `String(64)`, Indexed, Nullable=False ("USER_REGISTER", "TRADE_PROPOSED", "TRADE_EXECUTED", "COMPLIANCE_CHECK", etc.)
  - `actor`: `String(64)`, Nullable=False ("USER", "SYSTEM", "AGENT:RiskProfiler", "AGENT:ExecutionModule", etc.)
  - `details`: `JSON`, Nullable=False, Default `dict`
  - `timestamp`: `DateTime`, Default `datetime.utcnow`, Indexed, Nullable=False
  - `prev_hash`: `String(64)`, Nullable=True (SHA-256 hash of previous entry or "0"*64)
  - `entry_hash`: `String(64)`, Nullable=False (SHA-256 hash of payload + prev_hash)
  - `signature`: `String(128)`, Nullable=False (HMAC-SHA256 signature of entry_hash)
  - `session_id`: `String(64)`, Nullable=True
  - `agent_id`: `String(64)`, Nullable=True
  - `status`: `String(16)`, Default="PASS", Nullable=True
- **Synonyms**:
  - `entry_id = synonym("id")`
  - `previous_hash = synonym("prev_hash")`
  - `hmac_signature = synonym("signature")`
  - `action = synonym("details")`
- **Relationships**:
  - `client`: `relationship("DBClientProfile", back_populates="audit_logs")`

### 3.6 Model 6: `DBBehavioralMemory`
- **Table**: `behavioral_memory`
- **Purpose**: Stores psychological telemetry, identified cognitive biases, dialogue excerpts, and debiasing interventions.
- **Columns**:
  - `id`: `String(64)`, Primary Key, Default `generate_uuid()`
  - `client_id`: `String(64)`, ForeignKey `client_profiles.client_id` (ON DELETE CASCADE), Indexed, Nullable=False
  - `bias_type`: `String(64)`, Indexed, Nullable=False ("loss_aversion", "recency_bias", "overconfidence", "anchoring", "confirmation_bias")
  - `severity`: `String(32)`, Default="medium", Nullable=False ("low", "medium", "high")
  - `trigger_context`: `JSON`, Nullable=True
  - `intervention_text`: `Text`, Nullable=True
  - `timestamp`: `DateTime`, Default `datetime.utcnow`, Indexed, Nullable=False
- **Relationships**:
  - `client`: `relationship("DBClientProfile", back_populates="behavioral_memories")`

### 3.7 Model 7: `DBComplianceRule`
- **Table**: `compliance_rules`
- **Purpose**: Dynamic repository of regulatory rules evaluated before recommendation delivery and trade execution.
- **Columns**:
  - `rule_id`: `String(32)`, Primary Key (e.g. "SUIT-001", "CONC-001", "REG-001", "AML-001")
  - `name`: `String(128)`, Nullable=False
  - `category`: `String(32)`, Indexed, Nullable=False ("SUITABILITY", "CONCENTRATION", "REGULATORY", "AML")
  - `severity`: `String(16)`, Default="BLOCK", Nullable=False ("BLOCK" or "WARN")
  - `parameters`: `JSON`, Nullable=False, Default `dict`
  - `description`: `Text`, Nullable=True
  - `is_active`: `Boolean`, Default=True, Nullable=False
  - `created_at`: `DateTime`, Default `datetime.utcnow`, Nullable=False
  - `updated_at`: `DateTime`, Default `datetime.utcnow`, OnUpdate `datetime.utcnow`, Nullable=False

---

## 4. Cryptographic Invariants & Append-Only Enforcement

### 4.1 Invariant Rules
The audit log (`audit_log` / `DBAuditLog`) is legally and cryptographically binding. Once an audit record is created:
1. **Never Updated**: Modifying an existing entry invalidates the SHA-256 hash chain and HMAC signature.
2. **Never Deleted**: Deleting an entry breaks the chain pointer link (`prev_hash`) for all subsequent records.
3. **Defense-in-Depth**: Protection must operate at the ORM layer, Session query layer, and Database engine trigger layer.

### 4.2 SQLAlchemy ORM Event Listeners
```python
class AppendOnlyViolationError(RuntimeError):
    """Raised when an attempt is made to UPDATE or DELETE an append-only audit record."""
    pass

@event.listens_for(DBAuditLog, "before_update")
def prevent_audit_log_instance_update(mapper, connection, target):
    raise AppendOnlyViolationError(
        f"Append-only violation: UPDATE is strictly prohibited on DBAuditLog (entry_id={target.id})"
    )

@event.listens_for(DBAuditLog, "before_delete")
def prevent_audit_log_instance_delete(mapper, connection, target):
    raise AppendOnlyViolationError(
        f"Append-only violation: DELETE is strictly prohibited on DBAuditLog (entry_id={target.id})"
    )

@event.listens_for(Session, "do_orm_execute")
def prevent_audit_log_bulk_mutation(orm_execute_state):
    if orm_execute_state.is_delete or orm_execute_state.is_update:
        if orm_execute_state.bind_mapper and issubclass(orm_execute_state.bind_mapper.class_, DBAuditLog):
            action = "DELETE" if orm_execute_state.is_delete else "UPDATE"
            raise AppendOnlyViolationError(
                f"Append-only violation: Bulk {action} statement is strictly prohibited on DBAuditLog"
            )
```

### 4.3 Database Engine Triggers (SQLite & PostgreSQL)
```sql
CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_update
BEFORE UPDATE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Append-only violation: UPDATE is strictly prohibited on audit_log');
END;

CREATE TRIGGER IF NOT EXISTS trg_audit_log_no_delete
BEFORE DELETE ON audit_log
BEGIN
    SELECT RAISE(ABORT, 'Append-only violation: DELETE is strictly prohibited on audit_log');
END;
```

### 4.4 Automated Verification Proof
The test harness executed on SQLAlchemy 2.0.52 and SQLite verified:
1. Instance update (`log.actor = "tampered"; await session.commit()`) -> **BLOCKED** with `AppendOnlyViolationError`.
2. Instance delete (`await session.delete(log); await session.commit()`) -> **BLOCKED** with `AppendOnlyViolationError`.
3. Bulk update (`session.execute(update(DBAuditLog)...)`) -> **BLOCKED** with `AppendOnlyViolationError`.
4. Bulk delete (`session.execute(delete(DBAuditLog)...)`) -> **BLOCKED** with `AppendOnlyViolationError`.
5. Raw SQL direct update (`UPDATE audit_log SET actor='HACK'`) -> **BLOCKED** by SQLite trigger with `DatabaseError`.
6. Raw SQL direct delete (`DELETE FROM audit_log`) -> **BLOCKED** by SQLite trigger with `DatabaseError`.

---

## 5. Complete 12-Rule Compliance Catalog

All 12 rules are defined in the schema and seeded automatically into `compliance_rules`:

| Rule ID | Name | Category | Severity | Parameters (JSON) | Description & Evaluation Logic |
|---|---|---|---|---|---|
| **SUIT-001** | Risk Profile Alignment | `SUITABILITY` | **BLOCK** | `{"max_risk_delta": 1.0, "max_volatility_multiplier": 2.0}` | `rec.risk_level <= profile.risk_tolerance_score + 1` |
| **SUIT-002** | Investment Horizon Match | `SUITABILITY` | **BLOCK** | `{"max_duration_multiplier": 1.5}` | `rec.avg_duration <= profile.investment_horizon_years * 1.5` |
| **SUIT-003** | Liquidity Match | `SUITABILITY` | **WARN** | `{"min_daily_volume_usd": 1000000.0, "high_liquidity_threshold": "high"}` | If `profile.liquidity_needs == "high"`, require `product.daily_volume_usd >= 1,000,000` |
| **CONC-001** | Single Asset Limit | `CONCENTRATION` | **BLOCK** | `{"max_single_weight": 0.30}` | `all(weight <= 0.30 for weight in portfolio.weights.values())` and `rec.proposed_weight <= 0.30` |
| **CONC-002** | Sector Concentration | `CONCENTRATION` | **WARN** | `{"max_sector_weight": 0.40}` | `all(weight <= 0.40 for weight in portfolio.sector_weights.values())` |
| **CONC-003** | Asset Class Equity Cap | `CONCENTRATION` | **WARN** | `{"conservative_equity_max": 0.30, "target_category": "conservative"}` | If `profile.suitability_category == "conservative"`, then `equities_weight <= 0.30` |
| **REG-001** | No Guaranteed Returns | `REGULATORY` | **BLOCK** | `{"prohibited_phrases": ["guaranteed", "guarantee", "100% safe", "risk-free", "certain return", "will definitely"]}` | Output text must not contain any prohibited guarantee phrase. |
| **REG-002** | Risk Disclosure Required | `REGULATORY` | **BLOCK** | `{"required_phrases": ["past performance", "does not guarantee", "risk of loss", "investing involves risk"]}` | Recommendation output must contain at least one required risk disclosure phrase. |
| **REG-003** | Non-Discretionary Confirmation | `REGULATORY` | **BLOCK** | `{"require_explicit_approval": true}` | `trade.user_approved == True` and `trade.user_approved_at is not None` |
| **REG-004** | KYC Verification | `REGULATORY` | **BLOCK** | `{"require_kyc_verified": true}` | `profile.kyc_verified == True` before order placement |
| **AML-001** | Transaction Monitoring | `AML` | **BLOCK** | `{"max_single_trade_amount": 100000.0, "block_on_aml_flag": true}` | `profile.aml_flag == False` and `trade.dollar_amount < 100,000` |
| **AML-002** | Source of Funds Verification | `AML` | **WARN** | `{"disallowed_sources": ["unverified", "suspicious", "unknown"]}` | `getattr(profile, "source_of_funds", "verified") not in disallowed_sources` |

---

## 6. Async Alembic Migration Architecture

### 6.1 Design Highlights
- **Location**: `backend/alembic.ini`, `backend/db/migrations/env.py`, `backend/db/migrations/versions/`.
- **Async Execution**: Employs `async_engine_from_config` configured with `poolclass=pool.NullPool` to execute migrations over async drivers (`aiosqlite` and `asyncpg`).
- **Batch Operations**: Configures `render_as_batch=True` inside `context.configure()` so that SQLite table alterations, drops, and foreign key modifications succeed without driver errors.
- **Dynamic Config**: `get_url()` respects runtime `DATABASE_URL` environment variables while falling back to `DATABASE_URL` exported from `db.database`.

### 6.2 Lifecycle Verification
Executed on Windows using Alembic 1.19.2 and SQLite 3:
- Initial state: database empty.
- Run `alembic upgrade head`:
  - Output: `Running upgrade -> 0001_initial_schema`
  - Created 8 tables: `['alembic_version', 'audit_log', 'behavioral_memory', 'client_profiles', 'compliance_rules', 'portfolio_snapshots', 'trades', 'users']`.
  - Created 9 indexes.
  - Successfully seeded all 12 compliance rules.
- Run `alembic downgrade base`:
  - Output: `Running downgrade 0001_initial_schema -> `
  - Successfully dropped all 7 tables in reverse dependency order.
  - Return code: 0 (Clean).

---

## 7. Deliverable Artifact Manifest

All proposed drop-in files have been generated and validated inside `.agents/teamwork/teamwork_preview_explorer_m1_2/`:

| Source File in Explorer Folder | Destination Path in Backend | Status |
|---|---|---|
| `proposed_models.py` | `backend/db/models.py` | Complete, verified with all 7 models & listeners |
| `proposed_init.sql` | `backend/db/init.sql` | Complete, DDL + triggers + 12 seed rules verified |
| `proposed_alembic.ini` | `backend/alembic.ini` | Complete, configured for async migrations |
| `proposed_env.py` | `backend/db/migrations/env.py` | Complete, async runner with batch mode |
| `proposed_script.py.mako` | `backend/db/migrations/script.py.mako` | Complete, standard revision template |
| `proposed_0001_initial_schema.py` | `backend/db/migrations/versions/0001_initial_schema.py` | Complete, upgrade/downgrade verified |

---

## 8. Implementation Guidance for Developer / Implementer

1. **Copy Models**: Replace `backend/db/models.py` with `proposed_models.py`.
2. **Create Init Script**: Write `backend/db/init.sql` using `proposed_init.sql`.
3. **Configure Alembic**:
   - Place `proposed_alembic.ini` at `backend/alembic.ini`.
   - Create directories `backend/db/migrations/` and `backend/db/migrations/versions/`.
   - Place `proposed_env.py` at `backend/db/migrations/env.py`.
   - Place `proposed_script.py.mako` at `backend/db/migrations/script.py.mako`.
   - Place `proposed_0001_initial_schema.py` at `backend/db/migrations/versions/0001_initial_schema.py`.
4. **Update `backend/requirements.txt`**: Ensure `alembic>=1.13.0` is present alongside `SQLAlchemy>=2.0.23`, `aiosqlite>=0.19.0`, and `asyncpg>=0.29.0`.
5. **Update `backend/db/database.py`**:
   - Add URL normalization for `sqlite://` to `sqlite+aiosqlite://` and `postgres://` to `postgresql+asyncpg://`.
   - Add `connect_args={"check_same_thread": False}` when SQLite is active.
   - In `init_db()`, call `conn.run_sync(Base.metadata.create_all)` for zero-setup execution.

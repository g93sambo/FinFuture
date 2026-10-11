-- ============================================================================
-- Wealth Advisory Agent Database Initialization Schema & Compliance Seed Data
-- Target Database: SQLite 3 (aiosqlite) / PostgreSQL 15+ (asyncpg) Compatible
-- ============================================================================

PRAGMA foreign_keys = ON;

-- ----------------------------------------------------------------------------
-- 1. Users Table (Authentication & Ownership Security)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    hashed_password VARCHAR(255) NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ----------------------------------------------------------------------------
-- 2. Client Profiles Table (Financial, Demographics, Psychology & Suitability)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS client_profiles (
    client_id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64) REFERENCES users(id) ON DELETE CASCADE,
    age INTEGER,
    employment_status VARCHAR(64),
    dependents INTEGER DEFAULT 0,
    annual_income REAL,
    net_worth REAL,
    liquid_assets REAL DEFAULT 0.0,
    monthly_expenses REAL DEFAULT 0.0,
    existing_debts REAL DEFAULT 0.0,
    investment_experience VARCHAR(64),
    risk_tolerance_score REAL,
    investment_horizon_years INTEGER,
    liquidity_needs VARCHAR(32),
    loss_capacity VARCHAR(32),
    primary_goal VARCHAR(128),
    target_return REAL,
    specific_goals JSON DEFAULT '[]',
    suitability_category VARCHAR(64),
    detected_biases JSON DEFAULT '[]',
    emotional_risk_score REAL DEFAULT 0.0,
    panic_sell_likelihood REAL DEFAULT 0.0,
    kyc_verified BOOLEAN DEFAULT 0,
    aml_flag BOOLEAN DEFAULT 0,
    profiling_session_transcript TEXT DEFAULT '',
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_client_profiles_user_id ON client_profiles(user_id);

-- ----------------------------------------------------------------------------
-- 3. Portfolio Snapshots Table (Time-Series Valuations & Health Monitoring)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES client_profiles(client_id) ON DELETE CASCADE,
    total_value REAL NOT NULL,
    positions JSON NOT NULL DEFAULT '{}',
    cash REAL NOT NULL DEFAULT 0.0,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_portfolio_snapshots_client_time ON portfolio_snapshots(client_id, timestamp);

-- ----------------------------------------------------------------------------
-- 4. Trades Table (Execution Records & Alpaca Fills)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS trades (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES client_profiles(client_id),
    symbol VARCHAR(32) NOT NULL,
    qty REAL NOT NULL,
    side VARCHAR(16) NOT NULL,
    order_type VARCHAR(32) NOT NULL DEFAULT 'MARKET',
    status VARCHAR(32) NOT NULL DEFAULT 'PENDING',
    filled_price REAL,
    filled_qty REAL DEFAULT 0.0,
    alpaca_order_id VARCHAR(64),
    compliance_report JSON DEFAULT '{}',
    user_approved_at TIMESTAMP,
    filled_at TIMESTAMP,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_trades_client_id ON trades(client_id);
CREATE INDEX IF NOT EXISTS idx_trades_symbol ON trades(symbol);

-- ----------------------------------------------------------------------------
-- 5. Audit Log Table (Cryptographically Chained Append-Only Audit Trail)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) REFERENCES client_profiles(client_id),
    event_type VARCHAR(64) NOT NULL,
    actor VARCHAR(64) NOT NULL,
    details JSON NOT NULL DEFAULT '{}',
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    prev_hash VARCHAR(64),
    entry_hash VARCHAR(64) NOT NULL,
    signature VARCHAR(128) NOT NULL,
    session_id VARCHAR(64),
    agent_id VARCHAR(64),
    status VARCHAR(16) DEFAULT 'PASS'
);

CREATE INDEX IF NOT EXISTS idx_audit_log_client_id ON audit_log(client_id);
CREATE INDEX IF NOT EXISTS idx_audit_log_timestamp ON audit_log(timestamp);

-- Defense-in-depth: Triggers enforcing append-only invariant directly in SQL
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

-- ----------------------------------------------------------------------------
-- 6. Behavioral Memory Table (Detected Biases & Interventions)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS behavioral_memory (
    id VARCHAR(64) PRIMARY KEY,
    client_id VARCHAR(64) NOT NULL REFERENCES client_profiles(client_id) ON DELETE CASCADE,
    bias_type VARCHAR(64) NOT NULL,
    severity VARCHAR(32) NOT NULL DEFAULT 'medium',
    trigger_context JSON,
    intervention_text TEXT,
    timestamp TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_behavioral_memory_client_bias ON behavioral_memory(client_id, bias_type);

-- ----------------------------------------------------------------------------
-- 7. Compliance Rules Table (Configurable Dynamic Regulatory Rules)
-- ----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS compliance_rules (
    rule_id VARCHAR(32) PRIMARY KEY,
    name VARCHAR(128) NOT NULL,
    category VARCHAR(32) NOT NULL,
    severity VARCHAR(16) NOT NULL DEFAULT 'BLOCK',
    parameters JSON NOT NULL DEFAULT '{}',
    description TEXT,
    is_active BOOLEAN NOT NULL DEFAULT 1,
    created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_compliance_rules_category ON compliance_rules(category);

-- ============================================================================
-- Seed Data: All 12 Compliance Rules (SUIT-001..003, CONC-001..003, REG-001..004, AML-001..002)
-- ============================================================================
INSERT OR REPLACE INTO compliance_rules (rule_id, name, category, severity, parameters, description, is_active) VALUES
('SUIT-001', 'Risk Profile Alignment', 'SUITABILITY', 'BLOCK', '{"max_risk_delta": 1.0, "max_volatility_multiplier": 2.0}', 'Recommendations must match client risk profile', 1),
('SUIT-002', 'Investment Horizon Match', 'SUITABILITY', 'BLOCK', '{"max_duration_multiplier": 1.5}', 'Product duration must align with investment horizon', 1),
('SUIT-003', 'Liquidity Match', 'SUITABILITY', 'WARN', '{"min_daily_volume_usd": 1000000.0, "high_liquidity_threshold": "high"}', 'Product liquidity must meet client needs', 1),
('CONC-001', 'Single Asset Limit', 'CONCENTRATION', 'BLOCK', '{"max_single_weight": 0.30}', 'No single asset > 30% of portfolio', 1),
('CONC-002', 'Sector Concentration', 'CONCENTRATION', 'WARN', '{"max_sector_weight": 0.40}', 'No single sector > 40% of portfolio', 1),
('CONC-003', 'Asset Class Equity Cap', 'CONCENTRATION', 'WARN', '{"conservative_equity_max": 0.30, "target_category": "conservative"}', 'Conservative profiles: max 30% equities', 1),
('REG-001', 'No Guaranteed Returns', 'REGULATORY', 'BLOCK', '{"prohibited_phrases": ["guaranteed", "guarantee", "100% safe", "risk-free", "certain return", "will definitely"]}', 'Output must not promise or imply guaranteed returns', 1),
('REG-002', 'Risk Disclosure Required', 'REGULATORY', 'BLOCK', '{"required_phrases": ["past performance", "does not guarantee", "risk of loss", "investing involves risk"]}', 'Every recommendation must include risk disclosure', 1),
('REG-003', 'Non-Discretionary Confirmation', 'REGULATORY', 'BLOCK', '{"require_explicit_approval": true}', 'Trade execution requires explicit user approval', 1),
('REG-004', 'KYC Verification', 'REGULATORY', 'BLOCK', '{"require_kyc_verified": true}', 'Client must have verified KYC status before trading', 1),
('AML-001', 'Transaction Monitoring', 'AML', 'BLOCK', '{"max_single_trade_amount": 100000.0, "block_on_aml_flag": true}', 'Flag unusual transaction patterns or AML risks', 1),
('AML-002', 'Source of Funds Verification', 'AML', 'WARN', '{"disallowed_sources": ["unverified", "suspicious", "unknown"]}', 'Verify source of investment funds', 1);

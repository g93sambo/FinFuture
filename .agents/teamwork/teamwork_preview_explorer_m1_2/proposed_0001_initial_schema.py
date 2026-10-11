"""Initial schema: all 7 tables and 12 compliance rules seed data

Revision ID: 0001_initial_schema
Revises: None
Create Date: 2026-10-10 12:45:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql import table, column
import datetime

# revision identifiers, used by Alembic.
revision: str = "0001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. users table
    op.create_table(
        "users",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_users_email", "users", ["email"], unique=True)

    # 2. client_profiles table
    op.create_table(
        "client_profiles",
        sa.Column("client_id", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=64), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("age", sa.Integer(), nullable=True),
        sa.Column("employment_status", sa.String(length=64), nullable=True),
        sa.Column("dependents", sa.Integer(), server_default=sa.text("0"), nullable=True),
        sa.Column("annual_income", sa.Float(), nullable=True),
        sa.Column("net_worth", sa.Float(), nullable=True),
        sa.Column("liquid_assets", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("monthly_expenses", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("existing_debts", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("investment_experience", sa.String(length=64), nullable=True),
        sa.Column("risk_tolerance_score", sa.Float(), nullable=True),
        sa.Column("investment_horizon_years", sa.Integer(), nullable=True),
        sa.Column("liquidity_needs", sa.String(length=32), nullable=True),
        sa.Column("loss_capacity", sa.String(length=32), nullable=True),
        sa.Column("primary_goal", sa.String(length=128), nullable=True),
        sa.Column("target_return", sa.Float(), nullable=True),
        sa.Column("specific_goals", sa.JSON(), nullable=True),
        sa.Column("suitability_category", sa.String(length=64), nullable=True),
        sa.Column("detected_biases", sa.JSON(), nullable=True),
        sa.Column("emotional_risk_score", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("panic_sell_likelihood", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("kyc_verified", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("aml_flag", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.Column("profiling_session_transcript", sa.Text(), server_default="", nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_client_profiles_user_id", "client_profiles", ["user_id"])

    # 3. portfolio_snapshots table
    op.create_table(
        "portfolio_snapshots",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), sa.ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("total_value", sa.Float(), nullable=False),
        sa.Column("positions", sa.JSON(), nullable=False),
        sa.Column("cash", sa.Float(), server_default=sa.text("0.0"), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_portfolio_snapshots_client_time", "portfolio_snapshots", ["client_id", "timestamp"])

    # 4. trades table
    op.create_table(
        "trades",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), sa.ForeignKey("client_profiles.client_id"), nullable=False),
        sa.Column("symbol", sa.String(length=32), nullable=False),
        sa.Column("qty", sa.Float(), nullable=False),
        sa.Column("side", sa.String(length=16), nullable=False),
        sa.Column("order_type", sa.String(length=32), server_default="MARKET", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="PENDING", nullable=False),
        sa.Column("filled_price", sa.Float(), nullable=True),
        sa.Column("filled_qty", sa.Float(), server_default=sa.text("0.0"), nullable=True),
        sa.Column("alpaca_order_id", sa.String(length=64), nullable=True),
        sa.Column("compliance_report", sa.JSON(), nullable=True),
        sa.Column("user_approved_at", sa.DateTime(), nullable=True),
        sa.Column("filled_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_trades_client_id", "trades", ["client_id"])
    op.create_index("idx_trades_symbol", "trades", ["symbol"])

    # 5. audit_log table
    op.create_table(
        "audit_log",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), sa.ForeignKey("client_profiles.client_id"), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=64), nullable=False),
        sa.Column("details", sa.JSON(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("prev_hash", sa.String(length=64), nullable=True),
        sa.Column("entry_hash", sa.String(length=64), nullable=False),
        sa.Column("signature", sa.String(length=128), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("agent_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=16), server_default="PASS", nullable=True),
    )
    op.create_index("idx_audit_log_client_id", "audit_log", ["client_id"])
    op.create_index("idx_audit_log_timestamp", "audit_log", ["timestamp"])

    # 6. behavioral_memory table
    op.create_table(
        "behavioral_memory",
        sa.Column("id", sa.String(length=64), primary_key=True),
        sa.Column("client_id", sa.String(length=64), sa.ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False),
        sa.Column("bias_type", sa.String(length=64), nullable=False),
        sa.Column("severity", sa.String(length=32), server_default="medium", nullable=False),
        sa.Column("trigger_context", sa.JSON(), nullable=True),
        sa.Column("intervention_text", sa.Text(), nullable=True),
        sa.Column("timestamp", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_behavioral_memory_client_bias", "behavioral_memory", ["client_id", "bias_type"])

    # 7. compliance_rules table
    compliance_rules = op.create_table(
        "compliance_rules",
        sa.Column("rule_id", sa.String(length=32), primary_key=True),
        sa.Column("name", sa.String(length=128), nullable=False),
        sa.Column("category", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=16), server_default="BLOCK", nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("idx_compliance_rules_category", "compliance_rules", ["category"])

    # Seed all 12 compliance rules
    op.bulk_insert(
        compliance_rules,
        [
            {
                "rule_id": "SUIT-001",
                "name": "Risk Profile Alignment",
                "category": "SUITABILITY",
                "severity": "BLOCK",
                "parameters": {"max_risk_delta": 1.0, "max_volatility_multiplier": 2.0},
                "description": "Recommendations must match client risk profile",
                "is_active": True,
            },
            {
                "rule_id": "SUIT-002",
                "name": "Investment Horizon Match",
                "category": "SUITABILITY",
                "severity": "BLOCK",
                "parameters": {"max_duration_multiplier": 1.5},
                "description": "Product duration must align with investment horizon",
                "is_active": True,
            },
            {
                "rule_id": "SUIT-003",
                "name": "Liquidity Match",
                "category": "SUITABILITY",
                "severity": "WARN",
                "parameters": {"min_daily_volume_usd": 1000000.0, "high_liquidity_threshold": "high"},
                "description": "Product liquidity must meet client needs",
                "is_active": True,
            },
            {
                "rule_id": "CONC-001",
                "name": "Single Asset Limit",
                "category": "CONCENTRATION",
                "severity": "BLOCK",
                "parameters": {"max_single_weight": 0.30},
                "description": "No single asset > 30% of portfolio",
                "is_active": True,
            },
            {
                "rule_id": "CONC-002",
                "name": "Sector Concentration",
                "category": "CONCENTRATION",
                "severity": "WARN",
                "parameters": {"max_sector_weight": 0.40},
                "description": "No single sector > 40% of portfolio",
                "is_active": True,
            },
            {
                "rule_id": "CONC-003",
                "name": "Asset Class Equity Cap",
                "category": "CONCENTRATION",
                "severity": "WARN",
                "parameters": {"conservative_equity_max": 0.30, "target_category": "conservative"},
                "description": "Conservative profiles: max 30% equities",
                "is_active": True,
            },
            {
                "rule_id": "REG-001",
                "name": "No Guaranteed Returns",
                "category": "REGULATORY",
                "severity": "BLOCK",
                "parameters": {"prohibited_phrases": ["guaranteed", "guarantee", "100% safe", "risk-free", "certain return", "will definitely"]},
                "description": "Output must not promise or imply guaranteed returns",
                "is_active": True,
            },
            {
                "rule_id": "REG-002",
                "name": "Risk Disclosure Required",
                "category": "REGULATORY",
                "severity": "BLOCK",
                "parameters": {"required_phrases": ["past performance", "does not guarantee", "risk of loss", "investing involves risk"]},
                "description": "Every recommendation must include risk disclosure",
                "is_active": True,
            },
            {
                "rule_id": "REG-003",
                "name": "Non-Discretionary Confirmation",
                "category": "REGULATORY",
                "severity": "BLOCK",
                "parameters": {"require_explicit_approval": True},
                "description": "Trade execution requires explicit user approval",
                "is_active": True,
            },
            {
                "rule_id": "REG-004",
                "name": "KYC Verification",
                "category": "REGULATORY",
                "severity": "BLOCK",
                "parameters": {"require_kyc_verified": True},
                "description": "Client must have verified KYC status before trading",
                "is_active": True,
            },
            {
                "rule_id": "AML-001",
                "name": "Transaction Monitoring",
                "category": "AML",
                "severity": "BLOCK",
                "parameters": {"max_single_trade_amount": 100000.0, "block_on_aml_flag": True},
                "description": "Flag unusual transaction patterns or AML risks",
                "is_active": True,
            },
            {
                "rule_id": "AML-002",
                "name": "Source of Funds Verification",
                "category": "AML",
                "severity": "WARN",
                "parameters": {"disallowed_sources": ["unverified", "suspicious", "unknown"]},
                "description": "Verify source of investment funds",
                "is_active": True,
            },
        ],
    )


def downgrade() -> None:
    op.drop_table("compliance_rules")
    op.drop_table("behavioral_memory")
    op.drop_table("audit_log")
    op.drop_table("trades")
    op.drop_table("portfolio_snapshots")
    op.drop_table("client_profiles")
    op.drop_table("users")

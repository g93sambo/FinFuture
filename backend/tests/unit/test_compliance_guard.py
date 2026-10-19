"""
backend/tests/unit/test_compliance_guard.py
===========================================
Unit tests covering all 12 compliance rules, text output filtering, dynamic DB loading,
static fallback, cryptographic audit logging, and backward compatibility.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from db.models import DBClientProfile, DBComplianceRule, DBAuditLog, DBTrade
from services.audit_logger import get_audit_logger, verify_audit_chain
from agents.compliance_guard import (
    ComplianceGuard,
    ComplianceViolationError,
    ComplianceCheckResult,
    DEFAULT_COMPLIANCE_RULES,
)


@pytest.fixture
def compliance_guard():
    return ComplianceGuard()


@pytest.fixture
def mock_profile():
    class MockProfile:
        client_id = "client_test_001"
        risk_tolerance_score = 5.0
        investment_horizon_years = 5.0
        loss_capacity = "moderate"
        kyc_verified = True
        aml_flag = False
    return MockProfile()


# ============================================================================
# Rule SUIT-001 Tests: Risk Profile Alignment
# ============================================================================

@pytest.mark.asyncio
async def test_suit_001_pass(compliance_guard, mock_profile):
    rec = {"risk_level": 6.0}  # 6.0 <= 5.0 + 1.0
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True
    assert len(res.violations) == 0


@pytest.mark.asyncio
async def test_suit_001_fail(compliance_guard, mock_profile):
    rec = {"risk_level": 7.5}  # 7.5 > 5.0 + 1.0
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any("SUIT-001" in str(v) for v in exc_info.value.violations)


# ============================================================================
# Rule SUIT-002 Tests: Time Horizon Constraint
# ============================================================================

@pytest.mark.asyncio
async def test_suit_002_short_horizon_pass(compliance_guard, mock_profile):
    mock_profile.investment_horizon_years = 2.0  # < 3 years
    rec = {
        "risk_level": 4.0,
        "equity_weight": 0.35,  # <= 40%
        "avg_duration": 4.5,    # <= 7y
        "has_illiquid": False,
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_suit_002_short_horizon_fail_equity(compliance_guard, mock_profile):
    mock_profile.investment_horizon_years = 2.0
    rec = {
        "risk_level": 4.0,
        "equity_weight": 0.65,  # > 40%
        "avg_duration": 4.0,
        "has_illiquid": False,
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "SUIT-002" for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_suit_002_short_horizon_fail_duration_and_illiquid(compliance_guard, mock_profile):
    mock_profile.investment_horizon_years = 1.5
    rec = {
        "risk_level": 3.0,
        "equity_weight": 0.20,
        "avg_duration": 10.0,  # > 7.0y
        "has_illiquid": True,
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "SUIT-002" for v in exc_info.value.violations)


# ============================================================================
# Rule SUIT-003 Tests: Loss Capacity Ceiling
# ============================================================================

@pytest.mark.asyncio
async def test_suit_003_low_loss_capacity_pass(compliance_guard, mock_profile):
    mock_profile.loss_capacity = "low"
    rec = {
        "risk_level": 4.0,       # <= 5.0
        "equity_weight": 0.40,   # <= 50%
        "category": "Conservative Balanced",
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_suit_003_low_loss_capacity_fail(compliance_guard, mock_profile):
    mock_profile.loss_capacity = "low"
    rec = {
        "risk_level": 6.5,       # > 5.0
        "equity_weight": 0.70,   # > 50%
        "category": "Aggressive Growth",
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "SUIT-003" for v in exc_info.value.violations)


# ============================================================================
# Rule CONC-001 Tests: Single Stock Limit
# ============================================================================

@pytest.mark.asyncio
async def test_conc_001_single_stock_pass(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "single_stock_weight": 0.12,  # <= 15%
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_conc_001_single_stock_fail(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "single_stock_weight": 0.22,  # > 15%
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "CONC-001" for v in exc_info.value.violations)


# ============================================================================
# Rule CONC-002 Tests: Sector Concentration Limit
# ============================================================================

@pytest.mark.asyncio
async def test_conc_002_sector_limit_pass(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "sectors": {"Technology": 0.25, "Healthcare": 0.20, "Financials": 0.20, "Consumer": 0.20, "Industrials": 0.15},
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_conc_002_sector_limit_fail(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "sectors": {"Technology": 0.42, "Healthcare": 0.20, "Bonds": 0.38},
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(
            db_or_rec=None, client_id_or_profile="client_test_001",
            recommendation=rec, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "CONC-002" for v in exc_info.value.violations)


# ============================================================================
# Rule CONC-003 Tests: Minimum Asset Class Diversification (WARN)
# ============================================================================

@pytest.mark.asyncio
async def test_conc_003_diversification_pass(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "asset_classes": {"Equity": 0.60, "Fixed Income": 0.40},
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    assert res.passed is True
    assert len(res.warnings) == 0


@pytest.mark.asyncio
async def test_conc_003_diversification_warn(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "asset_classes": {"Equity": 1.00},  # Only 1 class
    }
    res = await compliance_guard.check_recommendation(
        db_or_rec=None, client_id_or_profile="client_test_001",
        recommendation=rec, profile=mock_profile
    )
    # CONC-003 is WARN by default, so it doesn't block
    assert res.passed is True
    assert len(res.warnings) >= 1
    assert "CONC-003" in res.warnings[0]


# ============================================================================
# Rule REG-001 & REG-002 Tests: Language Filter & Risk Disclosures
# ============================================================================

def test_reg_001_and_reg_002_text_output_filter(compliance_guard):
    # Prohibited words block
    bad_text = "This strategy provides guaranteed 15% profits risk-free!"
    passed, violations, sanitized = compliance_guard.check_text_output(bad_text)
    assert passed is False
    assert any("REG-001" in v for v in violations)
    assert any("guaranteed" in v.lower() for v in violations)

    # Missing disclosure appends standard disclosure
    plain_text = "The portfolio allocates 60% into diversified global equities and 40% into bonds."
    passed2, violations2, sanitized2 = compliance_guard.check_text_output(plain_text)
    assert passed2 is False
    assert any("REG-002" in v for v in violations2)
    assert "Past performance is no guarantee of future results" in sanitized2

    # Clean text with disclosure passes
    good_text = (
        "This portfolio targets 6.5% return with moderate risk. "
        "Please note that past performance is no guarantee of future results and investing involves risk."
    )
    passed3, violations3, sanitized3 = compliance_guard.check_text_output(good_text)
    assert passed3 is True
    assert len(violations3) == 0
    assert sanitized3 == good_text


# ============================================================================
# Rule REG-003 Tests: Non-Discretionary Confirmation
# ============================================================================

@pytest.mark.asyncio
async def test_reg_003_user_approval_pass(compliance_guard, mock_profile):
    trade = {
        "symbol": "SPY",
        "qty": 10.0,
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "notional_value": 5000.0,
    }
    res = await compliance_guard.check_trade(
        db=None, client_id="client_test_001", trade=trade, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_reg_003_user_approval_fail(compliance_guard, mock_profile):
    trade = {
        "symbol": "SPY",
        "qty": 10.0,
        "user_approved": False,
        "user_approved_at": datetime.now(timezone.utc),
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(
            db=None, client_id="client_test_001", trade=trade, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "REG-003" for v in exc_info.value.violations)


# ============================================================================
# Rule REG-004 Tests: Stale Approval Window
# ============================================================================

@pytest.mark.asyncio
async def test_reg_004_approval_freshness_pass(compliance_guard, mock_profile):
    # Approved 5 minutes ago (300s <= 900s)
    recent_time = datetime.now(timezone.utc) - timedelta(minutes=5)
    trade = {
        "symbol": "VTI",
        "qty": 5.0,
        "user_approved": True,
        "user_approved_at": recent_time,
        "notional_value": 1300.0,
    }
    res = await compliance_guard.check_trade(
        db=None, client_id="client_test_001", trade=trade, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_reg_004_approval_freshness_fail_stale(compliance_guard, mock_profile):
    # Approved 20 minutes ago (1200s > 900s)
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=20)
    trade = {
        "symbol": "VTI",
        "qty": 5.0,
        "user_approved": True,
        "user_approved_at": stale_time,
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(
            db=None, client_id="client_test_001", trade=trade, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "REG-004" for v in exc_info.value.violations)


# ============================================================================
# Rule AML-001 Tests: Single Transaction Limit ($100k)
# ============================================================================

@pytest.mark.asyncio
async def test_aml_001_standard_notional_pass(compliance_guard, mock_profile):
    trade = {
        "symbol": "AAPL",
        "qty": 100.0,
        "notional_value": 18500.0,  # <= $100,000
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
    }
    res = await compliance_guard.check_trade(
        db=None, client_id="client_test_001", trade=trade, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_aml_001_exceeds_notional_fail(compliance_guard, mock_profile):
    trade = {
        "symbol": "AAPL",
        "qty": 1000.0,
        "notional_value": 185000.0,  # > $100,000 without enhanced KYC
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "enhanced_kyc_approved": False,
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(
            db=None, client_id="client_test_001", trade=trade, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "AML-001" for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_aml_001_enhanced_kyc_pass(compliance_guard, mock_profile):
    trade = {
        "symbol": "AAPL",
        "qty": 1000.0,
        "notional_value": 185000.0,  # > $100,000 but enhanced KYC approved
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "enhanced_kyc_approved": True,
    }
    res = await compliance_guard.check_trade(
        db=None, client_id="client_test_001", trade=trade, profile=mock_profile
    )
    assert res.passed is True


# ============================================================================
# Rule AML-002 Tests: Rapid Velocity Limit (5 orders in 10 minutes)
# ============================================================================

@pytest.mark.asyncio
async def test_aml_002_velocity_pass(compliance_guard, mock_profile):
    trade = {
        "symbol": "BND",
        "qty": 10.0,
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "notional_value": 724.0,
        "recent_orders_count": 2,  # < 5
    }
    res = await compliance_guard.check_trade(
        db=None, client_id="client_test_001", trade=trade, profile=mock_profile
    )
    assert res.passed is True


@pytest.mark.asyncio
async def test_aml_002_velocity_fail(compliance_guard, mock_profile):
    trade = {
        "symbol": "BND",
        "qty": 10.0,
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "notional_value": 724.0,
        "recent_orders_count": 5,  # >= 5 orders in 10m
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(
            db=None, client_id="client_test_001", trade=trade, profile=mock_profile
        )
    assert any(getattr(v, "rule_id", "") == "AML-002" for v in exc_info.value.violations)


# ============================================================================
# Dynamic Database Loading & In-Memory Fallback Tests
# ============================================================================

@pytest.mark.asyncio
async def test_dynamic_db_rule_loading_and_fallback(db_session, compliance_guard):
    # 1. Fallback when DB has no rows
    fallback_rules = await compliance_guard.get_active_rules(db_session)
    assert len(fallback_rules) == 12
    assert any(getattr(r, "id", None) == "SUIT-001" for r in fallback_rules)

    # 2. Insert custom rule into database
    custom_rule = DBComplianceRule(
        rule_id="CUSTOM-001",
        name="Custom ESG Screen",
        category="SUITABILITY",
        severity="BLOCK",
        parameters={"screen_esg": True},
        description="Custom ESG test rule",
        is_active=True,
    )
    db_session.add(custom_rule)
    await db_session.commit()

    loaded_rules = await compliance_guard.get_active_rules(db_session)
    assert any(r.rule_id == "CUSTOM-001" for r in loaded_rules)


# ============================================================================
# Cryptographic Audit Logging Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_compliance_cryptographic_audit_logging(db_session, compliance_guard, mock_profile):
    client_id = "client_audit_test_01"

    # Seed client profile in DB
    db_prof = DBClientProfile(
        client_id=client_id,
        risk_tolerance_score=5.0,
        investment_horizon_years=5.0,
        kyc_verified=True,
    )
    db_session.add(db_prof)
    await db_session.commit()

    rec = {"risk_level": 4.5}
    res = await compliance_guard.check_recommendation(
        db_or_rec=db_session, client_id_or_profile=client_id,
        recommendation=rec, profile=db_prof
    )
    assert res.passed is True
    assert res.audit_entry_id is not None

    # Verify audit chain integrity using AuditLogger
    is_valid, tampered_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is True
    assert tampered_id is None


# ============================================================================
# Backward-Compatible Signatures & Properties
# ============================================================================

@pytest.mark.asyncio
async def test_backward_compatibility(compliance_guard, mock_profile):
    # 1. .rules property
    rules_list = compliance_guard.rules
    assert len(rules_list) == 12
    first_rule = rules_list[0]
    assert hasattr(first_rule, "id")
    assert hasattr(first_rule, "name")
    assert hasattr(first_rule, "severity")

    # 2. Legacy two-argument check_recommendation(rec, profile)
    rec = {"risk_level": 4.0}
    res = await compliance_guard.check_recommendation(rec, mock_profile)
    assert res["all_passed"] is True
    assert "checks" in res
    assert res.get("passed") is True
    assert res.get("non_existent", "default") == "default"


@pytest.mark.asyncio
async def test_conc_001_holdings_and_weights_formats(compliance_guard, mock_profile):
    # Test holdings list format
    rec1 = {
        "risk_level": 5.0,
        "holdings": [{"symbol": "AAPL", "weight": 0.25, "is_etf": False}],
    }
    with pytest.raises(ComplianceViolationError):
        await compliance_guard.check_recommendation(rec1, mock_profile)

    # Test weights dict format with single stock
    rec2 = {
        "risk_level": 5.0,
        "weights": {"AAPL": 0.20, "BND": 0.80},
    }
    with pytest.raises(ComplianceViolationError):
        await compliance_guard.check_recommendation(rec2, mock_profile)


@pytest.mark.asyncio
async def test_conc_002_sector_weights_dict(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "sector_weights": {"Technology": 0.45, "Financials": 0.55},
    }
    with pytest.raises(ComplianceViolationError):
        await compliance_guard.check_recommendation(rec, mock_profile)


@pytest.mark.asyncio
async def test_reg_001_in_recommendation_text(compliance_guard, mock_profile):
    rec = {
        "risk_level": 5.0,
        "rationale": "We offer a guaranteed return of 12% per annum.",
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_recommendation(rec, mock_profile)
    assert any(getattr(v, "rule_id", "") == "REG-001" for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_reg_004_iso_string_and_invalid(compliance_guard, mock_profile):
    # ISO string timestamp
    ts_str = datetime.now(timezone.utc).isoformat()
    trade_iso = {
        "symbol": "SPY",
        "qty": 5.0,
        "user_approved": True,
        "user_approved_at": ts_str,
    }
    res = await compliance_guard.check_trade(None, "c1", trade_iso, mock_profile)
    assert res.passed is True

    # Missing approval timestamp
    trade_no_ts = {
        "symbol": "SPY",
        "qty": 5.0,
        "user_approved": True,
        "user_approved_at": None,
    }
    with pytest.raises(ComplianceViolationError):
        await compliance_guard.check_trade(None, "c1", trade_no_ts, mock_profile)


@pytest.mark.asyncio
async def test_aml_002_with_db_recent_trades(db_session, compliance_guard, mock_profile):
    client_id = "client_aml_db_001"
    now = datetime.now(timezone.utc)

    # Insert 5 recent trades in DB
    for i in range(5):
        t = DBTrade(
            client_id=client_id,
            symbol="SPY",
            qty=1.0,
            side="BUY",
            created_at=now - timedelta(minutes=2),
        )
        db_session.add(t)
    await db_session.commit()

    trade = {
        "symbol": "SPY",
        "qty": 1.0,
        "user_approved": True,
        "user_approved_at": now,
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(db_session, client_id, trade, mock_profile)
    assert any(getattr(v, "rule_id", "") == "AML-002" for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_trade_conc_001_projected_weight(compliance_guard, mock_profile):
    trade = {
        "symbol": "AAPL",
        "qty": 10.0,
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "projected_weight": 0.25,  # > 0.15
    }
    with pytest.raises(ComplianceViolationError) as exc_info:
        await compliance_guard.check_trade(None, "c1", trade, mock_profile)
    assert any(getattr(v, "rule_id", "") == "CONC-001" for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_trade_conc_001_override_with_fiduciary_attestation(compliance_guard, mock_profile):
    trade = {
        "symbol": "AAPL",
        "qty": 10.0,
        "user_approved": True,
        "user_approved_at": datetime.now(timezone.utc),
        "projected_weight": 0.28,  # > 0.15
        "fiduciary_attested": True,  # Affirmative client waiver
        "proposal_id": "prop-482910-demo",
        "mfa_code": "482910",  # derived from the proposal_id digits
        "enforce_step_up_mfa": True,
    }
    res = await compliance_guard.check_trade(None, "c1", trade, mock_profile)
    assert res.passed is True
    assert any("CONC-001" in w for w in res.warnings)
    conc_rule = next(r for r in res.rule_results if r.rule_id == "CONC-001")
    assert conc_rule.passed is True
    assert conc_rule.severity == "WARN"



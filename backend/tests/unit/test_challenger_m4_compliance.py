"""
backend/tests/unit/test_challenger_m4_compliance.py
===================================================
Adversarial Empirical Stress Test Suite for Milestone 4:
- Adversarial text filter circumvention (REG-001 & REG-002)
- High-precision boundary tests for all 12 compliance rules
- HealthReportService drift stress (4.9% vs 5.0% vs 5.1%)
- Health score bounds [0.0, 100.0] under catastrophic drift & concentration
- Rebalancing trade generator (SELL-before-BUY ordering & dust threshold $10.00)
- ExecutionModule pre-trade validation gates (REG-003, REG-004, KYC, 30s lock, paper guard)
"""

import pytest
import pytest_asyncio
import random
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from db.models import DBClientProfile, DBComplianceRule, DBAuditLog, DBTrade
from services.audit_logger import get_audit_logger, verify_audit_chain
from services.cache import InMemoryCache, CacheService
from agents.compliance_guard import (
    ComplianceGuard,
    ComplianceViolationError,
    ComplianceCheckResult,
    DEFAULT_COMPLIANCE_RULES,
)
from agents.execution_module import (
    ExecutionModule,
    TradeExecutionResult,
    UnapprovedTradeError,
    ExpiredApprovalError,
    KYCUnverifiedError,
    DuplicateTradeError,
)
from services.health_report import (
    HealthReportService,
    DriftDirection,
    AlertSeverity,
    AlertType,
    HealthGrade,
)


@pytest.fixture
def compliance_guard():
    return ComplianceGuard()


@pytest.fixture
def health_service():
    return HealthReportService(openai_api_key="")


@pytest.fixture
def cache_service():
    service = CacheService()
    service.fallback = InMemoryCache()
    service._redis_available = False
    return service


@pytest.fixture
def execution_module(cache_service):
    return ExecutionModule(
        paper=True,
        cache_service=cache_service,
        audit_logger=get_audit_logger(),
    )


@pytest.fixture
def base_profile():
    class MockProfile:
        client_id = "challenger_client_001"
        risk_tolerance_score = 5.0
        investment_horizon_years = 5.0
        loss_capacity = "moderate"
        kyc_verified = True
        aml_flag = False
    return MockProfile()


# ============================================================================
# Section 1: Adversarial Text Filter Circumvention Stress Tests (REG-001 / REG-002)
# ============================================================================

class TestAdversarialTextFilter:
    """Stress tests verifying that REG-001 and REG-002 filters cannot be circumvented."""

    @pytest.mark.parametrize("adversarial_phrase", [
        "gUaRaNtEeD",
        "GUARANTEED",
        "GuArAnTeEd",
        "guaranteed!",
        "[guaranteed]",
        "100% risk free",
        "100% risk-free",
        "***risk-free***",
        "can't lose money",
        "cant lose money",
        "no risk whatsoever",
        "sure thing",
        "promise high returns",
        "100% safe",
        "certain return",
    ])
    def test_reg_001_adversarial_evasion_blocked(self, compliance_guard, adversarial_phrase):
        text = f"Our investment advisory provides a {adversarial_phrase} strategy. Investing involves risk."
        passed, violations, _ = compliance_guard.check_text_output(text)
        assert passed is False, f"Expected '{adversarial_phrase}' to be blocked by REG-001 filter"
        assert any("REG-001" in v for v in violations)

    def test_reg_002_zero_disclosure_blocked_and_sanitized(self, compliance_guard):
        raw_text = "We recommend a 60/40 asset allocation to optimize your portfolio returns."
        passed, violations, sanitized = compliance_guard.check_text_output(raw_text)
        assert passed is False
        assert any("REG-002" in v for v in violations)
        # Verify sanitized text appends mandatory regulatory disclosure
        assert "Investing involves risk" in sanitized
        assert "loss of principal" in sanitized

    @pytest.mark.parametrize("disclosure_keyword", [
        "past performance is no guarantee of future returns",
        "subject to possible loss of principal",
        "investing involves risk of market downturns",
    ])
    def test_reg_002_valid_disclosures_pass(self, compliance_guard, disclosure_keyword):
        text = f"We recommend this portfolio. {disclosure_keyword}."
        passed, violations, _ = compliance_guard.check_text_output(text)
        assert passed is True
        assert len(violations) == 0

    @pytest.mark.asyncio
    @pytest.mark.parametrize("field_name", ["rationale", "summary", "text", "notes"])
    async def test_recommendation_text_interception(self, compliance_guard, base_profile, field_name):
        rec = {
            "risk_level": 5.0,
            field_name: "This allocation provides a gUaRaNtEeD annual return. Investing involves risk.",
        }
        with pytest.raises(ComplianceViolationError) as exc_info:
            await compliance_guard.check_recommendation(
                db_or_rec=None, client_id_or_profile="c1", recommendation=rec, profile=base_profile
            )
        assert any(getattr(v, "rule_id", "") == "REG-001" for v in exc_info.value.violations)


# ============================================================================
# Section 2: High-Precision Boundary Tests for All 12 Compliance Rules
# ============================================================================

class TestComplianceRuleBoundaries:
    """Empirical boundary verification across all 12 regulatory rules."""

    # ------------------------------------------------------------------------
    # SUIT-001: Risk Profile Alignment (delta = 1.0)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_suit_001_boundary(self, compliance_guard, base_profile):
        base_profile.risk_tolerance_score = 5.0
        # 6.000 <= 5.0 + 1.0 -> PASS
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 6.000}, base_profile
        )
        assert res_pass.passed is True

        # 6.001 > 5.0 + 1.0 -> FAIL
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 6.001}, base_profile
            )
        assert any(v.rule_id == "SUIT-001" for v in exc.value.violations)

    # ------------------------------------------------------------------------
    # SUIT-002: Time Horizon Constraint (< 3y -> Equity <= 40%, Duration <= 7y)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_suit_002_short_horizon_equity_boundary(self, compliance_guard, base_profile):
        base_profile.investment_horizon_years = 2.99  # < 3.0 years
        # 40.0% equity -> PASS
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 4.0, "equity_weight": 0.4000, "avg_duration": 5.0}, base_profile
        )
        assert res_pass.passed is True

        # 40.01% equity -> FAIL
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 4.0, "equity_weight": 0.4001, "avg_duration": 5.0}, base_profile
            )
        assert any(v.rule_id == "SUIT-002" for v in exc.value.violations)

    @pytest.mark.asyncio
    async def test_suit_002_short_horizon_duration_boundary(self, compliance_guard, base_profile):
        base_profile.investment_horizon_years = 2.5
        # 7.0y duration -> PASS
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 4.0, "equity_weight": 0.30, "avg_duration": 7.000}, base_profile
        )
        assert res_pass.passed is True

        # 7.001y duration -> FAIL
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 4.0, "equity_weight": 0.30, "avg_duration": 7.001}, base_profile
            )
        assert any(v.rule_id == "SUIT-002" for v in exc.value.violations)

    @pytest.mark.asyncio
    async def test_suit_002_horizon_threshold_deactivation(self, compliance_guard, base_profile):
        base_profile.investment_horizon_years = 3.0  # Exactly 3.0 years (not < 3.0)
        # Equity 65% permitted when horizon >= 3.0y
        res = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 5.0, "equity_weight": 0.65}, base_profile
        )
        assert res.passed is True

    # ------------------------------------------------------------------------
    # SUIT-003: Loss Capacity Ceiling ('low' -> max risk <= 5.0, max equity <= 50%)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_suit_003_loss_capacity_boundaries(self, compliance_guard, base_profile):
        base_profile.loss_capacity = "low"

        # Risk 5.00 -> PASS; Risk 5.01 -> FAIL
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 5.00, "equity_weight": 0.40, "category": "Balanced"}, base_profile
        )
        assert res_pass.passed is True

        with pytest.raises(ComplianceViolationError) as exc_risk:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 5.01, "equity_weight": 0.40, "category": "Balanced"}, base_profile
            )
        assert any(v.rule_id == "SUIT-003" for v in exc_risk.value.violations)

        # Equity 50.0% -> PASS; Equity 50.01% -> FAIL
        res_eq_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 4.0, "equity_weight": 0.5000, "category": "Balanced"}, base_profile
        )
        assert res_eq_pass.passed is True

        with pytest.raises(ComplianceViolationError) as exc_eq:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 4.0, "equity_weight": 0.5001, "category": "Balanced"}, base_profile
            )
        assert any(v.rule_id == "SUIT-003" for v in exc_eq.value.violations)

        # Disallowed categories
        with pytest.raises(ComplianceViolationError) as exc_cat:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 4.0, "equity_weight": 0.40, "category": "Aggressive Growth"}, base_profile
            )
        assert any(v.rule_id == "SUIT-003" for v in exc_cat.value.violations)

    # ------------------------------------------------------------------------
    # CONC-001: Single Stock Limit (15.0% PASS vs 15.01% FAIL)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_conc_001_recommendation_boundary(self, compliance_guard, base_profile):
        # 15.00% single equity -> PASS
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 5.0, "single_stock_weight": 0.1500, "single_stock_symbol": "AAPL"}, base_profile
        )
        assert res_pass.passed is True

        # 15.01% single equity -> FAIL
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 5.0, "single_stock_weight": 0.1501, "single_stock_symbol": "AAPL"}, base_profile
            )
        assert any(v.rule_id == "CONC-001" for v in exc.value.violations)

    @pytest.mark.asyncio
    async def test_conc_001_trade_projected_weight_boundary(self, compliance_guard, base_profile):
        now = datetime.now(timezone.utc)
        # Projected weight 15.00% -> PASS
        trade_pass = {
            "symbol": "AAPL",
            "qty": 10.0,
            "user_approved": True,
            "user_approved_at": now,
            "projected_weight": 0.1500,
        }
        res_pass = await compliance_guard.check_trade(None, "c1", trade_pass, base_profile)
        assert res_pass.passed is True

        # Projected weight 15.01% -> FAIL
        trade_fail = {
            "symbol": "AAPL",
            "qty": 10.0,
            "user_approved": True,
            "user_approved_at": now,
            "projected_weight": 0.1501,
        }
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(None, "c1", trade_fail, base_profile)
        assert any(v.rule_id == "CONC-001" for v in exc.value.violations)

    # ------------------------------------------------------------------------
    # CONC-002: Sector Concentration Limit (30.0% PASS vs 30.01% FAIL)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_conc_002_sector_boundary(self, compliance_guard, base_profile):
        # 30.00% sector weight -> PASS
        res_pass = await compliance_guard.check_recommendation(
            None, "c1", {"risk_level": 5.0, "max_sector_weight": 0.3000, "max_sector_name": "Technology"}, base_profile
        )
        assert res_pass.passed is True

        # 30.01% sector weight -> FAIL
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_recommendation(
                None, "c1", {"risk_level": 5.0, "max_sector_weight": 0.3001, "max_sector_name": "Technology"}, base_profile
            )
        assert any(v.rule_id == "CONC-002" for v in exc.value.violations)

    # ------------------------------------------------------------------------
    # CONC-003: Minimum Asset Class Diversification (>= 2 classes with >= 5%)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_conc_003_asset_class_diversification(self, compliance_guard, base_profile):
        # 2 asset classes with >= 5% -> PASS without warnings
        rec_pass = {"risk_level": 5.0, "asset_classes": {"Equity": 0.80, "Fixed Income": 0.20}}
        res_pass = await compliance_guard.check_recommendation(None, "c1", rec_pass, base_profile)
        assert res_pass.passed is True
        assert len(res_pass.warnings) == 0

        # 1 asset class >= 5% -> PASS with WARN in warnings (non-blocking)
        rec_warn = {"risk_level": 5.0, "asset_classes": {"Equity": 0.98, "Fixed Income": 0.02}}
        res_warn = await compliance_guard.check_recommendation(None, "c1", rec_warn, base_profile)
        assert res_warn.passed is True
        assert any("CONC-003 Warning" in w for w in res_warn.warnings)

    # ------------------------------------------------------------------------
    # REG-003: Non-Discretionary Confirmation
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reg_003_user_approval(self, compliance_guard, base_profile):
        now = datetime.now(timezone.utc)
        # Approved -> PASS
        t_pass = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now}
        res_pass = await compliance_guard.check_trade(None, "c1", t_pass, base_profile)
        assert res_pass.passed is True

        # Unapproved -> FAIL
        t_fail = {"symbol": "SPY", "qty": 1.0, "user_approved": False, "user_approved_at": now}
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(None, "c1", t_fail, base_profile)
        assert any(v.rule_id == "REG-003" for v in exc.value.violations)

    # ------------------------------------------------------------------------
    # REG-004: Stale Approval Window (900 seconds)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_reg_004_approval_freshness(self, compliance_guard, base_profile):
        now = datetime.now(timezone.utc)
        # Fresh (899s ago) -> PASS
        t_fresh = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now - timedelta(seconds=899)}
        res_fresh = await compliance_guard.check_trade(None, "c1", t_fresh, base_profile)
        assert res_fresh.passed is True

        # Stale (901s ago) -> FAIL
        t_stale = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now - timedelta(seconds=901)}
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(None, "c1", t_stale, base_profile)
        assert any(v.rule_id == "REG-004" for v in exc.value.violations)

        # Missing timestamp -> FAIL
        t_none = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": None}
        with pytest.raises(ComplianceViolationError) as exc_none:
            await compliance_guard.check_trade(None, "c1", t_none, base_profile)
        assert any(v.rule_id == "REG-004" for v in exc_none.value.violations)

    # ------------------------------------------------------------------------
    # AML-001: Single Transaction Limit ($100,000 PASS vs $100,001 FAIL)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_aml_001_notional_boundary(self, compliance_guard, base_profile):
        now = datetime.now(timezone.utc)
        # $100,000.00 -> PASS
        t_100k = {
            "symbol": "SPY", "qty": 200.0, "price": 500.0, "notional_value": 100000.00,
            "user_approved": True, "user_approved_at": now,
        }
        res_100k = await compliance_guard.check_trade(None, "c1", t_100k, base_profile)
        assert res_100k.passed is True

        # $100,001.00 -> FAIL
        t_100k_1 = {
            "symbol": "SPY", "qty": 200.0, "price": 500.0, "notional_value": 100001.00,
            "user_approved": True, "user_approved_at": now,
        }
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(None, "c1", t_100k_1, base_profile)
        assert any(v.rule_id == "AML-001" for v in exc.value.violations)

        # $250,000 with enhanced KYC -> PASS
        t_enhanced = {
            "symbol": "SPY", "qty": 500.0, "price": 500.0, "notional_value": 250000.00,
            "user_approved": True, "user_approved_at": now,
            "enhanced_kyc_approved": True,
        }
        res_enhanced = await compliance_guard.check_trade(None, "c1", t_enhanced, base_profile)
        assert res_enhanced.passed is True

    # ------------------------------------------------------------------------
    # AML-002: Rapid Velocity Limit (5 orders in 10m PASS vs 6 orders FAIL)
    # ------------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_aml_002_velocity_boundary(self, compliance_guard, base_profile):
        now = datetime.now(timezone.utc)
        # 4 recent orders in window (current order is #5) -> PASS
        t_5th = {
            "symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now,
            "recent_orders_count": 4,
        }
        res_5th = await compliance_guard.check_trade(None, "c1", t_5th, base_profile)
        assert res_5th.passed is True

        # 5 recent orders in window (current order is #6) -> FAIL
        t_6th = {
            "symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now,
            "recent_orders_count": 5,
        }
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(None, "c1", t_6th, base_profile)
        assert any(v.rule_id == "AML-002" for v in exc.value.violations)

    @pytest.mark.asyncio
    async def test_aml_002_with_db_trades_velocity(self, db_session, compliance_guard, base_profile):
        client_id = "client_aml_boundary_test"
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # Insert 4 trades within last 10m -> 5th trade should PASS
        for _ in range(4):
            db_session.add(DBTrade(client_id=client_id, symbol="SPY", qty=1.0, side="BUY", created_at=now - timedelta(minutes=1)))
        await db_session.commit()

        trade_5 = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now_iso}
        res_5 = await compliance_guard.check_trade(db_session, client_id, trade_5, base_profile)
        assert res_5.passed is True

        # Insert 1 more trade (total 5 now in DB) -> 6th trade should FAIL
        db_session.add(DBTrade(client_id=client_id, symbol="SPY", qty=1.0, side="BUY", created_at=now - timedelta(minutes=1)))
        await db_session.commit()

        trade_6 = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now_iso}
        with pytest.raises(ComplianceViolationError) as exc:
            await compliance_guard.check_trade(db_session, client_id, trade_6, base_profile)
        assert any(v.rule_id == "AML-002" for v in exc.value.violations)

    @pytest.mark.asyncio
    async def test_empirical_finding_audit_log_datetime_serialization_failure(self, db_session, compliance_guard, base_profile):
        """
        EMPIRICAL CHALLENGER BUG DISCOVERY:
        When callers supply a Python datetime object for user_approved_at in check_trade,
        ComplianceGuard._record_audit_log attempts to persist payload={'trade': trade}
        in DBAuditLog.details. SQLAlchemy's JSON column fails with:
        TypeError: Object of type datetime is not JSON serializable.
        The audit entry is silently dropped (res.audit_entry_id is None) and db_session is left in a rolled-back state.
        """
        client_id = "client_audit_datetime_bug"
        now_dt = datetime.now(timezone.utc)
        trade = {"symbol": "SPY", "qty": 1.0, "user_approved": True, "user_approved_at": now_dt}

        res = await compliance_guard.check_trade(db_session, client_id, trade, base_profile)
        assert res.passed is True
        # Verify that audit logging now succeeds without serialization error:
        assert res.audit_entry_id is not None, "Audit log entry must successfully persist with serialized datetime"
        audit_entry = await db_session.get(DBAuditLog, res.audit_entry_id)
        assert audit_entry is not None
        assert audit_entry.event_type == "COMPLIANCE_TRADE_CHECK"



# ============================================================================
# Section 3: HealthReportService Drift & Alerts Stress Tests
# ============================================================================

class TestHealthReportDriftAndAlerts:
    """Stress tests on drift calculation threshold and structured alert rules."""

    @pytest.mark.asyncio
    async def test_drift_threshold_stress_4_9_vs_5_0_vs_5_1(self, health_service):
        target = {"SPY": 0.60, "BND": 0.40}

        # 1. 4.9% drift: SPY 64.9% / BND 35.1%
        cur_49 = {"SPY": 0.649, "BND": 0.351}
        drift_49 = health_service.calculate_drift(cur_49, target)
        assert drift_49.max_drift == 0.049
        assert drift_49.rebalance_required is False
        assert len(drift_49.drifted_assets) == 0

        bm_49 = await health_service.compare_to_benchmark(cur_49)
        alerts_49 = health_service.evaluate_alerts(
            drift_49, health_service.evaluate_concentration(cur_49), bm_49, 85.0
        )
        assert not any(a.alert_type == AlertType.DRIFT_ALERT for a in alerts_49)

        # 2. 5.0% drift (boundary): SPY 65.0% / BND 35.0%
        cur_50 = {"SPY": 0.650, "BND": 0.350}
        drift_50 = health_service.calculate_drift(cur_50, target)
        assert drift_50.max_drift == 0.05
        assert drift_50.rebalance_required is True
        assert len(drift_50.drifted_assets) == 2

        bm_50 = await health_service.compare_to_benchmark(cur_50)
        alerts_50 = health_service.evaluate_alerts(
            drift_50, health_service.evaluate_concentration(cur_50), bm_50, 85.0
        )
        assert any(a.alert_type == AlertType.DRIFT_ALERT for a in alerts_50)

        # 3. 5.1% drift: SPY 65.1% / BND 34.9%
        cur_51 = {"SPY": 0.651, "BND": 0.349}
        drift_51 = health_service.calculate_drift(cur_51, target)
        assert drift_51.max_drift == 0.051
        assert drift_51.rebalance_required is True
        assert "SPY" in drift_51.drifted_assets

        bm_51 = await health_service.compare_to_benchmark(cur_51)
        alerts_51 = health_service.evaluate_alerts(
            drift_51, health_service.evaluate_concentration(cur_51), bm_51, 85.0
        )
        drift_alert = next(a for a in alerts_51 if a.alert_type == AlertType.DRIFT_ALERT)
        assert drift_alert.severity == AlertSeverity.WARNING
        assert "5.0%" in drift_alert.message

    def test_turnover_calculation_accuracy(self, health_service):
        cur = {"SPY": 0.70, "BND": 0.30}
        tgt = {"SPY": 0.50, "BND": 0.50}
        res = health_service.calculate_drift(cur, tgt)
        # total drift = |0.70-0.50| + |0.30-0.50| = 0.20 + 0.20 = 0.40
        # turnover = 0.5 * 0.40 = 0.20
        assert res.total_drift == 0.40
        assert res.portfolio_turnover == 0.20


# ============================================================================
# Section 4: Health Score Bounds [0.0, 100.0] Stress Tests
# ============================================================================

class TestHealthScoreMathematicalBounds:
    """Verifies that health scores never drop below 0.0 or exceed 100.0 under any extreme."""

    def test_catastrophic_drift_and_single_asset_concentration(self, health_service):
        # 100% single speculative asset, completely drifted from target, extreme misalignment
        cur = {"NVDA": 1.0}
        tgt = {"BND": 1.0}
        drift = health_service.calculate_drift(cur, tgt)
        conc = health_service.evaluate_concentration(cur)

        class RiskAverseProfile:
            risk_tolerance_score = 1.0

        score = health_service.compute_health_score(drift, conc, RiskAverseProfile(), cur)
        breakdown = health_service.compute_health_score_breakdown(drift, conc, RiskAverseProfile(), cur)

        assert 0.0 <= score <= 100.0
        assert score == 0.0
        assert breakdown.health_grade == HealthGrade.CRITICAL
        assert breakdown.drift_penalty == 40.0
        assert breakdown.concentration_penalty == 20.0
        assert breakdown.risk_misalignment_penalty == 20.0

    def test_ideal_balanced_portfolio_bounds(self, health_service):
        cur = {"SPY": 0.30, "VTI": 0.20, "BND": 0.20, "AGG": 0.15, "SHY": 0.15}
        tgt = dict(cur)
        drift = health_service.calculate_drift(cur, tgt)
        conc = health_service.evaluate_concentration(cur)

        class AlignedProfile:
            risk_tolerance_score = 5.7  # ~50% equity target

        score = health_service.compute_health_score(drift, conc, AlignedProfile(), cur)
        assert 0.0 <= score <= 100.0
        assert score >= 90.0

    def test_health_score_randomized_stress_bounds(self, health_service):
        """Stress-test 100 randomized portfolios across asset universes and risk scores."""
        symbols = ["SPY", "QQQ", "AAPL", "MSFT", "BND", "AGG", "SHY", "GLD"]
        random.seed(42)

        for _ in range(100):
            # Generate random current and target weights
            cur_raw = {sym: random.uniform(0.0, 1.0) for sym in random.sample(symbols, random.randint(1, 8))}
            cur_sum = sum(cur_raw.values())
            cur_weights = {k: v / cur_sum for k, v in cur_raw.items()}

            tgt_raw = {sym: random.uniform(0.0, 1.0) for sym in random.sample(symbols, random.randint(1, 8))}
            tgt_sum = sum(tgt_raw.values())
            tgt_weights = {k: v / tgt_sum for k, v in tgt_raw.items()}

            drift = health_service.calculate_drift(cur_weights, tgt_weights)
            conc = health_service.evaluate_concentration(cur_weights)

            class RandomProfile:
                risk_tolerance_score = random.uniform(1.0, 10.0)

            score = health_service.compute_health_score(drift, conc, RandomProfile(), cur_weights)
            assert 0.0 <= score <= 100.0, f"Health score {score} out of [0.0, 100.0] bounds"


# ============================================================================
# Section 5: Rebalancing Trade Generator Mechanics
# ============================================================================

class TestRebalancingTradeGenerator:
    """Verifies SELL-before-BUY sequencing, tolerance bands, and $10.00 dust threshold."""

    def test_sell_before_buy_strict_ordering(self, health_service):
        # SPY heavily overweight (sell needed), BND heavily underweight (buy needed)
        cur_pos = {"SPY": 100.0, "BND": 10.0}
        prices = {"SPY": 500.0, "BND": 100.0}  # SPY=$50k, BND=$1k, Total=$51k
        target = {"SPY": 0.50, "BND": 0.50}

        plan = health_service.generate_rebalancing_orders(cur_pos, prices, target)
        assert plan.is_rebalance_needed is True
        assert len(plan.orders) >= 2

        # Verify SELL comes before BUY
        sides = [o.side for o in plan.orders]
        assert "SELL" in sides and "BUY" in sides
        first_buy_idx = sides.index("BUY")
        for i, side in enumerate(sides):
            if side == "SELL":
                assert i < first_buy_idx, f"SELL order at index {i} appears after BUY at index {first_buy_idx}"

    def test_dust_threshold_suppression(self, health_service):
        # Portfolio value $10,000
        # Delta of $5 (< $10 dust threshold) must be suppressed
        cur_pos = {"AAPL": 10.0, "MSFT": 90.0}
        prices = {"AAPL": 100.0, "MSFT": 100.0}  # total $10,000
        target_small_delta = {"AAPL": 0.1005, "MSFT": 0.8995}  # delta = $5.00

        plan_dust = health_service.generate_rebalancing_orders(
            cur_pos, prices, target_small_delta, tolerance_band=0.0001, min_trade_amount=10.0
        )
        assert len(plan_dust.orders) == 0, "Expected trade < $10.00 to be suppressed by dust threshold"

        # Delta of $15 (> $10 dust threshold) must generate orders
        target_large_delta = {"AAPL": 0.1015, "MSFT": 0.8985}  # delta = $15.00
        plan_valid = health_service.generate_rebalancing_orders(
            cur_pos, prices, target_large_delta, tolerance_band=0.0001, min_trade_amount=10.0
        )
        assert len(plan_valid.orders) == 2
        assert plan_valid.orders[0].side == "SELL"
        assert plan_valid.orders[1].side == "BUY"
        assert plan_valid.orders[0].estimated_amount == 15.0
        assert plan_valid.orders[1].estimated_amount == 15.0

    def test_tolerance_band_suppression(self, health_service):
        # Current 60.5% SPY / 39.5% BND vs target 60/40 (drift is 0.5% <= 1% tolerance band)
        cur_pos = {"SPY": 60.5, "BND": 39.5}
        prices = {"SPY": 100.0, "BND": 100.0}
        target = {"SPY": 0.60, "BND": 0.40}

        plan = health_service.generate_rebalancing_orders(
            cur_pos, prices, target, tolerance_band=0.01, min_trade_amount=10.0
        )
        assert len(plan.orders) == 0
        assert plan.is_rebalance_needed is False


# ============================================================================
# Section 6: Hardened Execution Module Pre-Trade Gate Stress Tests
# ============================================================================

class TestExecutionModulePreTradeGates:
    """Stress tests on paper trading enforcement, locks, freshness, KYC, and persistence."""

    def test_live_trading_enforcement_raises(self):
        with pytest.raises(RuntimeError) as exc:
            ExecutionModule(paper=False)
        assert "Live trading is strictly prohibited" in str(exc.value)

    @pytest.mark.asyncio
    async def test_gate_reg_003_unapproved_trade_rejected(self, db_session, execution_module):
        now = datetime.now(timezone.utc)
        with pytest.raises(UnapprovedTradeError):
            await execution_module.execute_trade(
                db=db_session,
                client_id="c_test_gate",
                proposal_id="p1",
                symbol="SPY",
                side="BUY",
                qty=10.0,
                approved=False,
                approval_timestamp=now,
            )

    @pytest.mark.asyncio
    async def test_gate_reg_004_stale_approval_rejected(self, db_session, execution_module):
        stale_time = datetime.now(timezone.utc) - timedelta(minutes=16)
        with pytest.raises(ExpiredApprovalError):
            await execution_module.execute_trade(
                db=db_session,
                client_id="c_test_gate",
                proposal_id="p1",
                symbol="SPY",
                side="BUY",
                qty=10.0,
                approved=True,
                approval_timestamp=stale_time,
            )

    @pytest.mark.asyncio
    async def test_gate_kyc_unverified_rejected(self, db_session, execution_module):
        client_id = "c_unverified_kyc"
        unverified_profile = DBClientProfile(
            client_id=client_id,
            risk_tolerance_score=5.0,
            investment_horizon_years=5.0,
            kyc_verified=False,  # Unverified!
        )
        db_session.add(unverified_profile)
        await db_session.commit()

        now = datetime.now(timezone.utc)
        with pytest.raises(KYCUnverifiedError):
            await execution_module.execute_trade(
                db=db_session,
                client_id=client_id,
                proposal_id="p1",
                symbol="SPY",
                side="BUY",
                qty=10.0,
                approved=True,
                approval_timestamp=now,
            )

    @pytest.mark.asyncio
    async def test_gate_duplicate_submit_30s_lock(self, db_session, execution_module):
        client_id = "c_dup_submit_lock"
        verified_profile = DBClientProfile(
            client_id=client_id,
            risk_tolerance_score=5.0,
            investment_horizon_years=5.0,
            kyc_verified=True,
        )
        db_session.add(verified_profile)
        await db_session.commit()

        now = datetime.now(timezone.utc)
        # First execution succeeds and sets 30s lock
        res1 = await execution_module.execute_trade(
            db=db_session,
            client_id=client_id,
            proposal_id="p1",
            symbol="SPY",
            side="BUY",
            qty=5.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
        assert res1.success is True

        # Second execution within 30s is rejected by distributed lock
        with pytest.raises(DuplicateTradeError):
            await execution_module.execute_trade(
                db=db_session,
                client_id=client_id,
                proposal_id="p2",
                symbol="SPY",
                side="BUY",
                qty=5.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )

    @pytest.mark.asyncio
    async def test_dry_run_execution_persists_trade_and_audit(self, db_session, execution_module):
        client_id = "c_dry_run_persist"
        profile = DBClientProfile(
            client_id=client_id,
            risk_tolerance_score=5.0,
            investment_horizon_years=5.0,
            kyc_verified=True,
        )
        db_session.add(profile)
        await db_session.commit()

        now = datetime.now(timezone.utc)
        result = await execution_module.execute_trade(
            db=db_session,
            client_id=client_id,
            proposal_id="prop_persist_01",
            symbol="BND",
            side="BUY",
            qty=20.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )

        assert result.success is True
        assert result.status == "FILLED"
        assert result.trade_id is not None
        assert result.filled_price == 72.40

        # Verify cryptographic audit chain integrity
        is_valid, tampered_id = await verify_audit_chain(db_session, client_id)
        assert is_valid is True
        assert tampered_id is None

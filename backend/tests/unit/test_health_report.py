"""
backend/tests/unit/test_health_report.py
========================================
Comprehensive unit tests covering portfolio drift analysis, 5% threshold triggers,
concentration metrics (HHI, Neff), bounded composite health scores [0.0, 100.0],
60/40 benchmark comparison, structured alerts, SELL-before-BUY rebalancing orders,
dual-mode narrative generation, and REG-001/REG-002 compliance.
"""

import pytest
import pytest_asyncio
from datetime import datetime, timezone

from db.models import DBClientProfile, DBPortfolioSnapshot
from services.health_report import (
    HealthReportService,
    DriftDirection,
    AlertSeverity,
    AlertType,
    HealthGrade,
    DriftAnalysisResult,
    ConcentrationMetrics,
    BenchmarkComparisonResult,
    HealthScoreComponents,
    RebalancingTradePlan,
    PortfolioNarrative,
    HealthReportResponse,
)


@pytest.fixture
def health_service():
    return HealthReportService(openai_api_key="")


# ============================================================================
# 1. Drift Analysis & 5% Threshold Trigger Tests
# ============================================================================

def test_drift_calculation_exceeds_threshold(health_service):
    # Current 66% SPY / 34% BND vs Target 60% SPY / 40% BND
    current_weights = {"SPY": 0.66, "BND": 0.34}
    target_weights = {"SPY": 0.60, "BND": 0.40}

    result = health_service.calculate_drift(current_weights, target_weights, threshold=0.05)

    assert result.max_drift == 0.06
    assert result.rebalance_required is True
    assert "SPY" in result.drifted_assets
    assert "BND" in result.drifted_assets
    assert result.asset_drifts["SPY"].exceeds_threshold is True
    assert result.asset_drifts["SPY"].drift_direction == DriftDirection.OVERWEIGHT
    assert result.asset_drifts["BND"].exceeds_threshold is True
    assert result.asset_drifts["BND"].drift_direction == DriftDirection.UNDERWEIGHT
    assert result.portfolio_turnover == 0.06


def test_drift_calculation_sub_threshold(health_service):
    # Current 63% SPY / 37% BND vs Target 60% SPY / 40% BND (3% drift < 5%)
    current_weights = {"SPY": 0.63, "BND": 0.37}
    target_weights = {"SPY": 0.60, "BND": 0.40}

    result = health_service.calculate_drift(current_weights, target_weights, threshold=0.05)

    assert result.max_drift == 0.03
    assert result.rebalance_required is False
    assert len(result.drifted_assets) == 0
    assert result.asset_drifts["SPY"].exceeds_threshold is False
    assert result.asset_drifts["BND"].exceeds_threshold is False


# ============================================================================
# 2. Concentration & Herfindahl Index Evaluation Tests
# ============================================================================

def test_concentration_metrics_equally_weighted_5_assets(health_service):
    # 5 assets at 20% each
    weights = {"SPY": 0.20, "VTI": 0.20, "BND": 0.20, "AGG": 0.20, "QQQ": 0.20}
    conc = health_service.evaluate_concentration(weights)

    assert conc.max_position_weight == 0.20
    assert conc.herfindahl_index == pytest.approx(0.20, abs=0.01)
    assert conc.effective_asset_count == pytest.approx(5.0, abs=0.1)
    assert conc.has_concentration_risk is False
    assert len(conc.concentrated_assets) == 0


def test_concentration_metrics_single_asset_100_percent(health_service):
    weights = {"AAPL": 1.00}
    conc = health_service.evaluate_concentration(weights)

    assert conc.max_position_weight == 1.00
    assert conc.herfindahl_index == 1.00
    assert conc.effective_asset_count == 1.00
    assert conc.has_concentration_risk is True
    assert "AAPL" in conc.concentrated_assets


def test_concentration_metrics_over_concentrated(health_service):
    weights = {"SPY": 0.45, "BND": 0.25, "QQQ": 0.15, "SHY": 0.15}
    conc = health_service.evaluate_concentration(weights)

    assert conc.max_position_symbol == "SPY"
    assert conc.max_position_weight == 0.45
    assert conc.has_concentration_risk is True
    assert "SPY" in conc.concentrated_assets


# ============================================================================
# 3. Portfolio Health Score Bounds [0.0, 100.0] Tests
# ============================================================================

def test_health_score_optimal_portfolio(health_service):
    # 5 balanced assets with 0 drift matching target
    weights = {"SPY": 0.20, "VTI": 0.20, "BND": 0.20, "AGG": 0.20, "SHY": 0.20}
    target = {"SPY": 0.20, "VTI": 0.20, "BND": 0.20, "AGG": 0.20, "SHY": 0.20}

    drift = health_service.calculate_drift(weights, target)
    conc = health_service.evaluate_concentration(weights)

    class Profile:
        risk_tolerance_score = 5.0

    breakdown = health_service.compute_health_score_breakdown(drift, conc, Profile(), weights)

    assert breakdown.final_score == 100.0
    assert breakdown.health_grade == HealthGrade.EXCELLENT
    assert breakdown.drift_penalty == 0.0
    assert breakdown.concentration_penalty == 0.0


def test_health_score_highly_degraded_portfolio(health_service):
    # Conservative client holding 100% single equity with 80% drift
    weights = {"AAPL": 1.00}
    target = {"BND": 0.80, "SPY": 0.20}

    drift = health_service.calculate_drift(weights, target)
    conc = health_service.evaluate_concentration(weights)

    class ConservativeProfile:
        risk_tolerance_score = 1.0

    score = health_service.compute_health_score(drift, conc, ConservativeProfile(), weights)

    assert score == 0.0
    assert 0.0 <= score <= 100.0


def test_health_score_fuzz_random_distributions(health_service):
    import random
    random.seed(42)

    symbols = ["SPY", "BND", "QQQ", "AGG", "VTI"]
    for _ in range(30):
        raw_cur = [random.uniform(0.01, 1.0) for _ in symbols]
        raw_tgt = [random.uniform(0.01, 1.0) for _ in symbols]
        s_cur = sum(raw_cur)
        s_tgt = sum(raw_tgt)

        cur_weights = {sym: w / s_cur for sym, w in zip(symbols, raw_cur)}
        tgt_weights = {sym: w / s_tgt for sym, w in zip(symbols, raw_tgt)}

        drift = health_service.calculate_drift(cur_weights, tgt_weights)
        conc = health_service.evaluate_concentration(cur_weights)

        class RandProfile:
            risk_tolerance_score = random.uniform(1.0, 10.0)

        score = health_service.compute_health_score(drift, conc, RandProfile(), cur_weights)
        assert 0.0 <= score <= 100.0, f"Score {score} out of bounds!"


# ============================================================================
# 4. Benchmark Comparison Tests (60/40 Standard)
# ============================================================================

@pytest.mark.asyncio
async def test_benchmark_comparison_60_40(health_service):
    weights = {"SPY": 0.60, "BND": 0.40}
    comp = await health_service.compare_to_benchmark(weights)

    assert comp.benchmark_name == "60/40 Standard (60% SPY / 40% BND)"
    assert comp.benchmark_annualized_return > 0.0
    assert comp.portfolio_annualized_return > 0.0
    assert comp.portfolio_volatility > 0.0
    assert comp.relative_volatility == pytest.approx(1.0, abs=0.1)
    assert "Portfolio" in comp.asset_mix_comparison
    assert "Benchmark" in comp.asset_mix_comparison


# ============================================================================
# 5. Structured Alert Rules Engine Tests
# ============================================================================

@pytest.mark.asyncio
async def test_evaluate_alerts(health_service):
    # Significant drift and concentration
    cur_weights = {"SPY": 0.75, "BND": 0.25}
    tgt_weights = {"SPY": 0.50, "BND": 0.50}

    drift = health_service.calculate_drift(cur_weights, tgt_weights)
    conc = health_service.evaluate_concentration(cur_weights)
    bench = await health_service.compare_to_benchmark(cur_weights)

    class Profile:
        risk_tolerance_score = 3.0

    score = health_service.compute_health_score(drift, conc, Profile(), cur_weights)
    alerts = health_service.evaluate_alerts(drift, conc, bench, score, Profile())

    alert_types = [a.alert_type for a in alerts]
    assert AlertType.DRIFT_ALERT in alert_types
    assert AlertType.CONCENTRATION_ALERT in alert_types
    assert AlertType.REBALANCE_RECOMMENDED in alert_types


# ============================================================================
# 6. Rebalancing Trade Generator Tests (SELL-Before-BUY & Constraints)
# ============================================================================

def test_rebalancing_orders_sell_strictly_before_buy(health_service):
    positions = {"SPY": 80.0, "QQQ": 40.0, "BND": 10.0}
    prices = {"SPY": 500.0, "QQQ": 400.0, "BND": 70.0}
    # Total positions value = 40,000 + 16,000 + 700 = $56,700
    target_weights = {"SPY": 0.40, "QQQ": 0.20, "BND": 0.40}

    plan = health_service.generate_rebalancing_orders(
        current_positions=positions,
        current_prices=prices,
        target_weights=target_weights,
        cash=1000.0,
        tolerance_band=0.01,
        min_trade_amount=10.0,
    )

    assert plan.is_rebalance_needed is True
    assert len(plan.orders) >= 2

    # Verify SELL strictly precedes BUY
    seen_buy = False
    for order in plan.orders:
        if order.side == "BUY":
            seen_buy = True
        elif order.side == "SELL":
            assert not seen_buy, "Found SELL order after BUY order! SELL must precede BUY."


def test_rebalancing_orders_tolerance_and_dusting(health_service):
    # Positions are very close to target (within 0.5% drift)
    positions = {"SPY": 60.2, "BND": 39.8}
    prices = {"SPY": 100.0, "BND": 100.0}
    target_weights = {"SPY": 0.60, "BND": 0.40}

    plan = health_service.generate_rebalancing_orders(
        current_positions=positions,
        current_prices=prices,
        target_weights=target_weights,
        cash=0.0,
        tolerance_band=0.01,  # 1% tolerance
        min_trade_amount=10.0,
    )

    # Within 1% tolerance, orders should be suppressed
    assert len(plan.orders) == 0
    assert plan.is_rebalance_needed is False


def test_rebalancing_orders_zero_portfolio(health_service):
    plan = health_service.generate_rebalancing_orders(
        current_positions={},
        current_prices={},
        target_weights={"SPY": 0.60, "BND": 0.40},
        cash=0.0,
    )
    assert plan.is_rebalance_needed is False
    assert plan.total_portfolio_value == 0.0
    assert len(plan.orders) == 0


# ============================================================================
# 7. Dual-Mode Narrative Generator & Regulatory Invariants
# ============================================================================

@pytest.mark.asyncio
async def test_narrative_deterministic_fallback_and_disclosures(health_service):
    cur_weights = {"SPY": 0.65, "BND": 0.35}
    tgt_weights = {"SPY": 0.60, "BND": 0.40}

    drift = health_service.calculate_drift(cur_weights, tgt_weights)
    conc = health_service.evaluate_concentration(cur_weights)
    bench = await health_service.compare_to_benchmark(cur_weights)
    plan = health_service.generate_rebalancing_orders(
        current_positions={"SPY": 65.0, "BND": 35.0},
        current_prices={"SPY": 100.0, "BND": 100.0},
        target_weights=tgt_weights,
    )

    narrative = await health_service.generate_narrative(
        client_id="client_narrative_001",
        profile_summary={"risk_tolerance_score": 5.0, "suitability_category": "Moderate"},
        health_score=88.5,
        drift_result=drift,
        concentration=conc,
        benchmark=bench,
        alerts=[],
        rebalance_plan=plan,
    )

    assert narrative.generation_mode == "DETERMINISTIC_FALLBACK"
    assert "88.5/100" in narrative.executive_summary
    assert len(narrative.actionable_recommendations) >= 1

    # REG-001 Verification: Zero prohibited promissory language
    full_narrative_text = (
        narrative.executive_summary + " " +
        narrative.drift_diagnosis + " " +
        narrative.risk_and_concentration_diagnosis + " " +
        narrative.benchmark_comparison_narrative + " " +
        " ".join(narrative.actionable_recommendations)
    ).lower()

    for prohibited in ["guaranteed", "risk-free", "can't lose", "no risk", "certain return"]:
        assert prohibited not in full_narrative_text, f"Found prohibited term '{prohibited}'!"

    # REG-002 Verification: Mandatory regulatory risk disclosure
    assert "Past performance does not guarantee future results" in narrative.regulatory_disclosure
    assert "possible loss of principal" in narrative.regulatory_disclosure


# ============================================================================
# 8. Full End-to-End generate_health_report Pipeline Test
# ============================================================================

@pytest.mark.asyncio
async def test_generate_health_report_end_to_end(db_session, health_service):
    client_id = "client_report_full_001"

    # Seed DBClientProfile
    profile = DBClientProfile(
        client_id=client_id,
        risk_tolerance_score=6.0,
        investment_horizon_years=7.0,
        suitability_category="Growth",
        kyc_verified=True,
    )
    db_session.add(profile)

    # Seed DBPortfolioSnapshot
    snapshot = DBPortfolioSnapshot(
        client_id=client_id,
        total_value=100000.0,
        positions={"SPY": 120.0, "BND": 400.0, "QQQ": 50.0},
        cash=5000.0,
        timestamp=datetime.now(timezone.utc),
    )
    db_session.add(snapshot)
    await db_session.commit()

    report = await health_service.generate_health_report(
        db=db_session,
        client_id=client_id,
    )

    assert isinstance(report, HealthReportResponse)
    assert report.client_id == client_id
    assert 0.0 <= report.health_score <= 100.0
    assert report.health_grade in (HealthGrade.EXCELLENT, HealthGrade.GOOD, HealthGrade.FAIR, HealthGrade.POOR, HealthGrade.CRITICAL)
    assert report.drift_analysis.max_drift >= 0.0
    assert report.concentration_metrics.effective_asset_count >= 1.0
    assert report.benchmark_comparison.benchmark_name.startswith("60/40")
    assert report.rebalancing_plan.total_portfolio_value > 0.0
    assert report.narrative.generation_mode == "DETERMINISTIC_FALLBACK"


@pytest.mark.asyncio
async def test_generate_health_report_missing_client_raises(db_session, health_service):
    with pytest.raises(ValueError) as exc_info:
        await health_service.generate_health_report(
            db=db_session,
            client_id="unknown_client_xyz",
        )
    assert "not found" in str(exc_info.value).lower()


@pytest.mark.asyncio
async def test_narrative_openai_mode():
    from unittest.mock import MagicMock, AsyncMock, patch
    from core.config import settings
    svc = HealthReportService(openai_api_key="mock-key-12345")
    mock_choice = MagicMock()
    mock_choice.message.content = "Executive Summary: Portfolio is in good standing with balanced growth and diversification."
    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]

    with patch.object(settings, "dry_run", False):
        with patch("services.health_report.AsyncOpenAI") as mock_openai_cls:
            mock_client_inst = MagicMock()
            mock_client_inst.chat.completions.create = AsyncMock(return_value=mock_resp)
            mock_openai_cls.return_value = mock_client_inst

            cur_weights = {"SPY": 0.60, "BND": 0.40}
            tgt_weights = {"SPY": 0.60, "BND": 0.40}
            drift = svc.calculate_drift(cur_weights, tgt_weights)
            conc = svc.evaluate_concentration(cur_weights)
            bench = await svc.compare_to_benchmark(cur_weights)
            plan = svc.generate_rebalancing_orders({}, {}, tgt_weights)

            narrative = await svc.generate_narrative(
                client_id="c_llm",
                profile_summary={"risk_tolerance_score": 5.0},
                health_score=95.0,
                drift_result=drift,
                concentration=conc,
                benchmark=bench,
                alerts=[],
                rebalance_plan=plan,
            )

            assert narrative.generation_mode == "LLM_OPENAI"
            assert "balanced growth" in narrative.executive_summary



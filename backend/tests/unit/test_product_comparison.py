"""
backend/tests/unit/test_product_comparison.py
=============================================
Unit tests for ProductComparisonAgent covering six-factor composite scoring,
suitability pre-filtering (SUIT-001), ETF and Bond pipelines, and deterministic rationales.
"""

import pytest
import pandas as pd
from agents.product_comparison import ProductComparisonAgent
from services.providers.screener import AssetScreenerProvider, AssetMetadata


@pytest.fixture
def comparison_agent():
    screener = AssetScreenerProvider()
    return ProductComparisonAgent(screener_provider=screener, openai_api_key=None)


def test_factor_weights_sum_to_one(comparison_agent):
    weights = comparison_agent.FACTOR_WEIGHTS
    total = sum(weights.values())
    assert abs(total - 1.00) < 1e-6, f"Factor weights sum to {total}, expected 1.00"


def test_expense_ratio_monotonicity(comparison_agent):
    score_vti = comparison_agent.score_expense_ratio(0.0003)  # 3 bps
    score_spy = comparison_agent.score_expense_ratio(0.0009)  # 9 bps
    score_qqq = comparison_agent.score_expense_ratio(0.0020)  # 20 bps
    score_high = comparison_agent.score_expense_ratio(0.0100) # 100 bps

    assert score_vti > score_spy > score_qqq > score_high
    assert score_vti == 9.70
    assert score_spy == 9.10
    assert score_qqq == 8.00
    assert score_high == 0.00


def test_tracking_error_monotonicity(comparison_agent):
    s_low, _ = comparison_agent.score_tracking_error(None, None, "equity", "large_cap_blend")
    s_med, _ = comparison_agent.score_tracking_error(None, None, "equity", "other")
    assert s_low >= s_med

    # Custom series with differing tracking error
    bench = pd.Series([0.01, -0.01, 0.02, 0.00, 0.01] * 5)
    diff_small = pd.Series([0.0001, -0.0001, 0.0002, -0.0002, 0.0001] * 5)
    diff_large = pd.Series([0.0050, -0.0050, 0.0080, -0.0080, 0.0040] * 5)
    close_fund = bench + diff_small
    far_fund = bench + diff_large

    s_close, te_close = comparison_agent.score_tracking_error(close_fund, bench)
    s_far, te_far = comparison_agent.score_tracking_error(far_fund, bench)

    assert te_close < te_far
    assert s_close > s_far


def test_liquidity_scoring(comparison_agent):
    # Tight spread + high volume
    class MockQuoteHigh:
        bid = 100.00
        ask = 100.01
        last_price = 100.00
        volume = 50_000_000

    # Wide spread + low volume
    class MockQuoteLow:
        bid = 98.00
        ask = 102.00
        last_price = 100.00
        volume = 5_000

    s_high, _, _ = comparison_agent.score_liquidity(MockQuoteHigh(), aum_billions=100.0)
    s_low, _, _ = comparison_agent.score_liquidity(MockQuoteLow(), aum_billions=0.05)

    assert s_high > s_low
    assert s_high >= 8.0
    assert s_low <= 5.0


def test_aum_scale_scoring(comparison_agent):
    assert comparison_agent.score_aum(525.0) == 10.0
    assert comparison_agent.score_aum(25.0) == 9.0
    assert comparison_agent.score_aum(5.0) == 7.5
    assert comparison_agent.score_aum(1.0) == 6.0
    assert comparison_agent.score_aum(0.2) == 4.5
    assert comparison_agent.score_aum(0.05) == 2.0


def test_reputation_tier_scoring(comparison_agent):
    assert comparison_agent.score_reputation("Vanguard Total Stock Market ETF", "VTI") == 10.0
    assert comparison_agent.score_reputation("iShares Core S&P 500 ETF", "IVV") == 10.0
    assert comparison_agent.score_reputation("Invesco QQQ Trust", "QQQ") == 8.5
    assert comparison_agent.score_reputation("Charles Schwab U.S. Large-Cap", "SCHX") == 8.5
    assert comparison_agent.score_reputation("WisdomTree U.S. Quality Dividend", "DGRW") == 7.0
    assert comparison_agent.score_reputation("Boutique Hedge Fund ETF", "XYZ") == 5.0


def test_suitability_prefilter_blocks_excess_risk(comparison_agent):
    conservative_profile = {
        "risk_tolerance_score": 2.0,
        "suitability_category": "Conservative",
        "investment_horizon_years": 3,
    }
    qqq_meta = comparison_agent.screener.get_by_symbol("QQQ")
    assert qqq_meta is not None
    assert qqq_meta.risk_level == 4

    is_suitable, reason = comparison_agent.evaluate_suitability(qqq_meta, conservative_profile)
    assert is_suitable is False
    assert "exceeds" in reason.lower()


def test_suitability_prefilter_allows_compliant(comparison_agent):
    moderate_profile = {
        "risk_tolerance_score": 6.0,
        "suitability_category": "Moderate",
        "investment_horizon_years": 10,
    }
    spy_meta = comparison_agent.screener.get_by_symbol("SPY")
    bnd_meta = comparison_agent.screener.get_by_symbol("BND")

    assert comparison_agent.evaluate_suitability(spy_meta, moderate_profile)[0] is True
    assert comparison_agent.evaluate_suitability(bnd_meta, moderate_profile)[0] is True


@pytest.mark.asyncio
async def test_etf_comparison_pipeline_ranking(comparison_agent):
    profile = {
        "risk_tolerance_score": 7.5,
        "suitability_category": "Growth",
        "investment_horizon_years": 15,
    }
    report = await comparison_agent.compare_etfs(["VTI", "SPY", "QQQ"], profile=profile)

    assert report.category == "ETF"
    assert len(report.ranked_products) == 3
    assert len(report.unsuitable_products) == 0

    assert report.winner_symbol in ["VTI", "SPY"]
    assert report.ranked_products[0].composite_score >= report.ranked_products[1].composite_score
    assert report.ranked_products[1].composite_score >= report.ranked_products[2].composite_score


@pytest.mark.asyncio
async def test_bond_comparison_pipeline_duration_check(comparison_agent):
    # Short horizon client (2 years) should flag TLT (duration 16.8y)
    short_horizon_profile = {
        "risk_tolerance_score": 4.0,
        "suitability_category": "Moderate Conservative",
        "investment_horizon_years": 2,
    }
    report = await comparison_agent.compare_bonds(["SHY", "TLT", "BND"], profile=short_horizon_profile)

    assert report.category == "BOND"
    unsuitable_symbols = [u.symbol for u in report.unsuitable_products]
    assert "TLT" in unsuitable_symbols

    # SHY and BND are evaluated
    ranked_symbols = [r.symbol for r in report.ranked_products]
    assert "SHY" in ranked_symbols


@pytest.mark.asyncio
async def test_offline_and_fixture_fallback(comparison_agent):
    # Tests that evaluation completes even without network access or live quotes
    report = await comparison_agent.compare_etfs(["VTI", "SPY"])
    assert report.winner_symbol in ["VTI", "SPY"]
    assert len(report.ranked_products) == 2
    assert report.summary_rationale is not None


@pytest.mark.asyncio
async def test_rationale_generation_without_openai(comparison_agent):
    profile = {"risk_tolerance_score": 5.0, "suitability_category": "Moderate", "investment_horizon_years": 5}
    report = await comparison_agent.compare_etfs(["SPY", "VTI"], profile=profile)
    assert "ranks #1" in report.summary_rationale
    assert "composite score" in report.summary_rationale


@pytest.mark.asyncio
async def test_all_unsuitable_scenario(comparison_agent):
    ultra_conservative = {"risk_tolerance_score": 1.0, "suitability_category": "Conservative"}
    # High risk symbols only (QQQ is level 4, VXUS is level 4)
    report = await comparison_agent.compare_etfs(["QQQ", "VXUS"], profile=ultra_conservative)
    assert len(report.ranked_products) == 0
    assert len(report.unsuitable_products) == 2
    assert "suitability criteria" in report.summary_rationale.lower()

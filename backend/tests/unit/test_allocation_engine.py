"""
backend/tests/unit/test_allocation_engine.py
============================================
Unit tests for AllocationEngine covering skfolio plural parameters, 5-tier fallback cascade,
profile-driven constraints, efficient frontier, SELL-first rebalance trades, and attribution.
"""

import pytest
import numpy as np
import pandas as pd
from agents.allocation_engine import AllocationEngine, AllocationResult, RebalancePlan


@pytest.fixture
def price_data():
    dates = pd.date_range("2023-01-01", periods=100, freq="B")
    np.random.seed(42)
    # 6 correlated assets
    returns = np.random.normal(0.0005, 0.01, (100, 6))
    prices = 100.0 * np.exp(np.cumsum(returns, axis=0))
    return pd.DataFrame(prices, index=dates, columns=["SPY", "VTI", "QQQ", "BND", "AGG", "SHY"])


@pytest.fixture
def engine():
    return AllocationEngine(market_data_agent=None, openai_api_key=None)


@pytest.mark.asyncio
async def test_mean_risk_plural_parameters_success(engine, price_data):
    # Tests that MeanRisk executes with max_weights and min_weights without raising TypeError
    profile = {"risk_tolerance_score": 6.0, "investment_horizon_years": 10, "liquidity_needs": "low"}
    res = await engine.generate_allocation(price_data, profile)

    assert isinstance(res, AllocationResult)
    assert len(res.weights) == 6
    total_weight = sum(res.weights.values())
    assert abs(total_weight - 1.0) < 0.05
    assert res.solver_method in ["cvar_ratio", "min_variance"]


@pytest.mark.asyncio
async def test_portfolio_volatility_attribute_access(engine, price_data):
    profile = {"risk_tolerance_score": 5.0}
    res = await engine.generate_allocation(price_data, profile)

    # Volatility must be populated from portfolio.standard_deviation
    assert "volatility" in res.metrics
    assert "annualized_volatility" in res.metrics
    assert res.metrics["volatility"] > 0.0
    assert res.metrics["annualized_volatility"] > res.metrics["volatility"]


@pytest.mark.asyncio
async def test_profile_constraints_conservative(engine, price_data):
    conservative_profile = {
        "risk_tolerance_score": 2.0,
        "suitability_category": "Conservative",
        "investment_horizon_years": 3,
        "liquidity_needs": "high",
    }
    res = await engine.generate_allocation(price_data, conservative_profile)

    assert isinstance(res, AllocationResult)
    # Individual weights should not exceed conservative cap (35%)
    for sym, w in res.weights.items():
        assert w <= 0.40, f"Weight for {sym} ({w}) exceeds conservative cap"


@pytest.mark.asyncio
async def test_profile_constraints_aggressive(engine, price_data):
    aggressive_profile = {
        "risk_tolerance_score": 9.5,
        "suitability_category": "Aggressive Growth",
        "investment_horizon_years": 25,
        "liquidity_needs": "low",
    }
    res = await engine.generate_allocation(price_data, aggressive_profile)
    assert isinstance(res, AllocationResult)
    assert res.metrics["sharpe_ratio"] is not None


@pytest.mark.asyncio
async def test_solver_fallback_on_negative_returns(engine):
    # Degraded price series where all asset returns are strictly negative
    dates = pd.date_range("2023-01-01", periods=20, freq="B")
    neg_prices = pd.DataFrame(
        {
            "SPY": np.linspace(100, 70, 20),
            "BND": np.linspace(50, 40, 20),
        },
        index=dates,
    )
    profile = {"risk_tolerance_score": 5.0}

    # Should not throw ConvexOptimizationError or ValueError; falls back gracefully to Tier 2 (MinVar)
    res = await engine.generate_allocation(neg_prices, profile)
    assert res.solver_method in ["min_variance", "inverse_volatility", "profile_heuristic"]
    assert len(res.weights) == 2


@pytest.mark.asyncio
async def test_solver_fallback_on_degenerate_data(engine):
    # Single row dataframe (cannot compute returns)
    single_row = pd.DataFrame({"SPY": [100.0], "BND": [50.0]})
    profile = {"risk_tolerance_score": 2.0}

    # Cleanly falls back to Tier 5 profile benchmark
    res = await engine.generate_allocation(single_row, profile)
    assert res.solver_method == "profile_heuristic"
    assert "SPY" in res.weights and "BND" in res.weights
    assert res.weights["BND"] >= res.weights["SPY"]  # Conservative benchmark tilt


def test_efficient_frontier_generation(engine, price_data):
    frontier = engine.generate_efficient_frontier(price_data, n_points=5)

    assert len(frontier) == 5
    for idx, pt in enumerate(frontier):
        assert pt.point_index == idx
        assert pt.volatility >= 0.0
        assert len(pt.weights) > 0


def test_rebalancing_trade_generator_orders(engine):
    current_positions = {"SPY": 10.0, "BND": 20.0}  # SPY=$1000, BND=$1000 -> Total $2000
    current_prices = {"SPY": 100.0, "BND": 50.0}
    target_weights = {"SPY": 0.80, "BND": 0.20}  # Target: SPY=$1600, BND=$400

    plan = engine.generate_rebalancing_trades(
        current_positions=current_positions,
        current_prices_or_target=current_prices,
        target_weights=target_weights,
        cash=0.0,
    )

    assert isinstance(plan, RebalancePlan)
    assert plan.total_portfolio_value == 2000.0
    assert plan.is_rebalance_needed is True
    assert len(plan.orders) == 2

    # Verify SELL-before-BUY ordering
    assert plan.orders[0].side == "SELL"
    assert plan.orders[0].symbol == "BND"
    assert plan.orders[0].estimated_amount == 600.0  # Sell $600 of BND

    assert plan.orders[1].side == "BUY"
    assert plan.orders[1].symbol == "SPY"
    assert plan.orders[1].estimated_amount == 600.0  # Buy $600 of SPY


def test_rebalancing_sells_precede_buys_multi(engine):
    positions = {"SPY": 50.0, "QQQ": 30.0, "BND": 10.0, "AGG": 5.0}
    prices = {"SPY": 100.0, "QQQ": 100.0, "BND": 100.0, "AGG": 100.0}
    # Total: $9500
    target_weights = {"SPY": 0.10, "QQQ": 0.10, "BND": 0.40, "AGG": 0.40}

    plan = engine.generate_rebalancing_trades(positions, prices, target_weights)
    sides = [order.side for order in plan.orders]

    # Verify all SELLs precede all BUYs
    first_buy_idx = sides.index("BUY") if "BUY" in sides else len(sides)
    for i in range(first_buy_idx):
        assert sides[i] == "SELL"
    for j in range(first_buy_idx, len(sides)):
        assert sides[j] == "BUY"


def test_rebalancing_threshold_suppression(engine):
    # Very minor drift (< $10)
    current_positions = {"SPY": 10.0, "BND": 20.0}
    current_prices = {"SPY": 100.0, "BND": 50.0}
    # Target values: SPY=$1002 (+$2), BND=$998 (-$2)
    target_weights = {"SPY": 0.501, "BND": 0.499}

    plan = engine.generate_rebalancing_trades(
        current_positions=current_positions,
        current_prices_or_target=current_prices,
        target_weights=target_weights,
        min_trade_amount=10.0,
    )
    # Trades below $10 should be suppressed
    assert len(plan.orders) == 0


def test_analytical_attribution_fallback(engine, price_data):
    from skfolio.preprocessing import prices_to_returns
    returns = prices_to_returns(price_data)
    weights = {"SPY": 0.30, "VTI": 0.20, "QQQ": 0.20, "BND": 0.15, "AGG": 0.10, "SHY": 0.05}

    attributions = engine.calculate_analytical_attribution(weights, returns)
    assert len(attributions) == 6
    total_contrib = sum(attributions.values())
    # Risk contributions should sum close to 1.0 (100% of portfolio risk)
    assert abs(total_contrib - 1.0) < 0.05


@pytest.mark.asyncio
async def test_llm_explanation_fallback(engine, price_data):
    profile = {"risk_tolerance_score": 7.0, "suitability_category": "Growth", "primary_goal": "growth"}
    res = await engine.generate_allocation(price_data, profile)

    assert res.explanation is not None
    assert "risk profile" in res.explanation.lower()
    assert "growth" in res.explanation.lower()


@pytest.mark.asyncio
async def test_generate_allocation_with_positions_rebalances(engine, price_data):
    profile = {"risk_tolerance_score": 6.0}
    current_positions = {"SPY": 5.0, "BND": 50.0}

    res = await engine.generate_allocation(
        data_or_profile=price_data,
        profile_or_positions=profile,
        current_positions=current_positions,
        include_frontier=True,
    )
    assert res.rebalance_plan is not None
    assert res.frontier is not None
    assert len(res.frontier) == 10


def test_rebalancing_zero_portfolio_value(engine):
    plan = engine.generate_rebalancing_trades(
        current_positions={},
        current_prices_or_target={},
        target_weights={"SPY": 0.6, "BND": 0.4},
        cash=0.0,
    )
    assert plan.total_portfolio_value == 0.0
    assert len(plan.orders) == 0


def test_efficient_frontier_with_profile_object(engine):
    profile = {"risk_tolerance_score": 5.0}
    frontier = engine.generate_efficient_frontier(profile, n_points=5)
    assert len(frontier) == 5
    assert frontier[0].volatility >= 0.0


@pytest.mark.asyncio
async def test_generate_allocation_client_id_from_db(engine, db_session):
    from db.models import DBClientProfile
    client = DBClientProfile(
        client_id="client_alloc_test",
        risk_tolerance_score=7.0,
        investment_horizon_years=10,
        liquidity_needs="medium",
        primary_goal="growth",
        suitability_category="Growth",
    )
    db_session.add(client)
    await db_session.commit()
    res = await engine.generate_allocation(
        data_or_profile="client_alloc_test",
        db=db_session,
    )
    assert res.solver_method is not None
    assert len(res.weights) > 0


@pytest.mark.asyncio
async def test_generate_allocation_with_profile_direct(engine):
    profile = {"risk_tolerance_score": 5.0, "investment_horizon_years": 8}
    positions = {"SPY": 10.0, "BND": 20.0}
    res = await engine.generate_allocation(profile, profile_or_positions=positions)
    assert len(res.weights) > 0
    assert res.rebalance_plan is not None


def test_fit_five_tier_cascade_tier3_and_tier4(engine):
    dates = pd.date_range("2023-01-01", periods=10, freq="B")
    returns = pd.DataFrame(
        {"A": [0.01, -0.01] * 5, "B": [0.02, -0.02] * 5},
        index=dates,
    )
    from unittest.mock import patch
    with patch("agents.allocation_engine.MeanRisk.fit", side_effect=RuntimeError("Solver failed")):
        _, method, weights = engine._fit_five_tier_cascade(returns, {"risk_tolerance_score": 5.0})
        assert method == "inverse_volatility"
        assert len(weights) == 2

    with patch("agents.allocation_engine.MeanRisk.fit", side_effect=RuntimeError("Solver failed")), \
         patch("agents.allocation_engine.InverseVolatility.fit", side_effect=RuntimeError("InvVol failed")):
        _, method4, weights4 = engine._fit_five_tier_cascade(returns, {"risk_tolerance_score": 5.0})
        assert method4 == "equal_weighted"
        assert abs(weights4["A"] - 0.5) < 1e-4


def test_analytical_attribution_edge_cases(engine):
    empty_df = pd.DataFrame()
    attr_empty = engine.calculate_analytical_attribution({"SPY": 1.0}, empty_df)
    assert attr_empty == {"SPY": 1.0}

    single_row = pd.DataFrame({"SPY": [0.01], "BND": [0.02]})
    attr_single = engine.calculate_analytical_attribution({"SPY": 0.5, "BND": 0.5}, single_row)
    assert len(attr_single) == 2


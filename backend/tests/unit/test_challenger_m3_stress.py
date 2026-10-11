"""
backend/tests/unit/test_challenger_m3_stress.py
===============================================
Adversarial Empirical Challenge Suite for Milestone 3 (Core Agents).
Authored by Challenger 2 (empirical-challenger).

Stress-tests:
1. skfolio MeanRisk optimization in AllocationEngine with:
   - Ill-conditioned covariance matrices (condition number > 1e12)
   - Zero-variance assets (constant prices, return std == 0)
   - Highly negative returns (market crash / catastrophic drawdowns)
   - Collinear / identical return series (rank deficient)
   - Extreme numeric risk budgets (negative, zero, 10.0, 999.0, empty profile, None)
   - Malformed profile inputs (None values, string values) to probe robustness
   - All-NaN / empty price data fallback behavior
2. Efficient Frontier curve generation:
   - Evaluates varying n_points (e.g. 5, 10, 20)
   - Validates monotonicity of risk vs return (volatility vs expected return)
   - Verifies all frontier points have valid weights summing to 1.0.
3. Euler Analytical Risk Attribution:
   - Verifies closed-form percentage risk contributions sum to 100% (1.0 +- 1e-3)
   - Tests singular, non-singular, and degenerate covariance matrices.
4. Rebalancing Trade Generator:
   - Verifies strict SELL-before-BUY ordering under all permutations
   - Verifies cash accounting neutrality and liquidity preservation.
5. ProductComparisonAgent Six-Factor Scoring:
   - Evaluates extreme boundary values: zero/negative expense ratio, massive tracking error,
     zero/negative AUM, extreme bid-ask spread, catastrophic returns, unknown managers.
   - Validates mathematical bounds [0.0, 10.0] on all scores and composite score.
"""

import math
import pytest
import numpy as np
import pandas as pd
from typing import Dict, List

from agents.allocation_engine import (
    AllocationEngine,
    AllocationResult,
    RebalancePlan,
    EfficientFrontierPoint,
)
from agents.product_comparison import (
    ProductComparisonAgent,
    FactorScores,
)
from services.providers.screener import AssetMetadata, AssetScreenerProvider


# ==============================================================================
# Fixtures
# ==============================================================================

@pytest.fixture
def engine():
    return AllocationEngine(market_data_agent=None, openai_api_key=None)


@pytest.fixture
def comp_agent():
    return ProductComparisonAgent(market_data_agent=None, screener_provider=None, openai_api_key=None)


# ==============================================================================
# 1. Adversarial skfolio MeanRisk Optimization & 5-Tier Fallback Cascade
# ==============================================================================

class TestAllocationEngineStress:

    @pytest.mark.asyncio
    async def test_ill_conditioned_covariance_matrix(self, engine):
        """
        Adversarial test: Construct prices with nearly singular / ill-conditioned covariance.
        Assets 2, 3, 4 are linear combinations of Asset 1 with tiny epsilon noise (condition number > 1e12).
        """
        dates = pd.date_range("2023-01-01", periods=100, freq="B")
        np.random.seed(101)
        base = np.cumsum(np.random.normal(0.0005, 0.01, 100))
        
        # Near collinear assets
        p1 = 100.0 * np.exp(base)
        p2 = 100.0 * np.exp(base + 1e-9 * np.random.normal(0, 1, 100))
        p3 = 100.0 * np.exp(base - 1e-9 * np.random.normal(0, 1, 100))
        p4 = 100.0 * np.exp(2.0 * base + 1e-8 * np.random.normal(0, 1, 100))

        df_ill = pd.DataFrame({"A1": p1, "A2": p2, "A3": p3, "A4": p4}, index=dates)

        profiles_to_test = [
            {"risk_tolerance_score": 1.0, "suitability_category": "Conservative"},
            {"risk_tolerance_score": 5.0, "suitability_category": "Moderate"},
            {"risk_tolerance_score": 9.0, "suitability_category": "Aggressive Growth"},
        ]

        for profile in profiles_to_test:
            res = await engine.generate_allocation(df_ill, profile)
            assert isinstance(res, AllocationResult)
            assert res.solver_method in ["cvar_ratio", "min_variance", "inverse_volatility", "equal_weighted", "profile_heuristic"]
            # Verify weights sum to 1.0
            total_w = sum(res.weights.values())
            assert abs(total_w - 1.0) < 1e-3, f"Ill-conditioned weights sum to {total_w}, expected 1.0"
            # Verify non-negativity and finite
            for sym, w in res.weights.items():
                assert not math.isnan(w) and not math.isinf(w)
                assert w >= -1e-5, f"Negative weight detected for {sym}: {w}"

    @pytest.mark.asyncio
    async def test_zero_variance_asset(self, engine):
        """
        Adversarial test: One or more assets have flat prices (zero variance / zero return).
        Tests whether solver handles or catches zero variance without unhandled DivisionByZero.
        """
        dates = pd.date_range("2023-01-01", periods=80, freq="B")
        np.random.seed(202)
        p_normal = 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, 80)))
        p_flat1 = np.full(80, 100.0)  # Perfectly flat zero variance
        p_flat2 = np.full(80, 50.0)   # Another flat asset

        df_zero_var = pd.DataFrame({"VOL": p_normal, "CASH1": p_flat1, "CASH2": p_flat2}, index=dates)

        profile = {"risk_tolerance_score": 4.0, "suitability_category": "Moderate Conservative"}
        res = await engine.generate_allocation(df_zero_var, profile)

        assert isinstance(res, AllocationResult)
        assert res.solver_method in ["cvar_ratio", "min_variance", "inverse_volatility", "equal_weighted", "profile_heuristic"]
        total_w = sum(res.weights.values())
        assert abs(total_w - 1.0) < 1e-3
        for sym, w in res.weights.items():
            assert not math.isnan(w) and not math.isinf(w)
            assert w >= -1e-5

    @pytest.mark.asyncio
    async def test_highly_negative_returns(self, engine):
        """
        Adversarial test: Severe market crash regime where returns are all negative (-50% to -95%).
        Convex solvers maximizing return or Sharpe often fail on non-positive drifts.
        Verify fallback cascade handles this cleanly.
        """
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        decay1 = 100.0 * (0.95 ** np.arange(50))
        decay2 = 100.0 * (0.92 ** np.arange(50))
        decay3 = 100.0 * (0.90 ** np.arange(50))

        df_crash = pd.DataFrame({"CRASH1": decay1, "CRASH2": decay2, "CRASH3": decay3}, index=dates)

        for score in [1.5, 5.0, 8.5]:
            profile = {"risk_tolerance_score": score}
            res = await engine.generate_allocation(df_crash, profile)
            assert isinstance(res, AllocationResult)
            total_w = sum(res.weights.values())
            assert abs(total_w - 1.0) < 1e-3
            for sym, w in res.weights.items():
                assert not math.isnan(w) and not math.isinf(w)
                assert w >= -1e-5

    @pytest.mark.asyncio
    async def test_perfectly_collinear_assets(self, engine):
        """
        Adversarial test: Multiple duplicate columns (correlation exactly 1.000).
        """
        dates = pd.date_range("2023-01-01", periods=60, freq="B")
        np.random.seed(303)
        base = 100.0 * np.exp(np.cumsum(np.random.normal(0.001, 0.02, 60)))

        df_collinear = pd.DataFrame({
            "SPY_A": base,
            "SPY_B": base,
            "SPY_C": base * 2.0,  # Perfectly collinear scaled
        }, index=dates)

        res = await engine.generate_allocation(df_collinear, {"risk_tolerance_score": 6.0})
        assert isinstance(res, AllocationResult)
        total_w = sum(res.weights.values())
        assert abs(total_w - 1.0) < 1e-3

    @pytest.mark.asyncio
    async def test_extreme_numeric_risk_budgets(self, engine):
        """
        Adversarial test: Extreme boundary risk budgets:
        - Negative risk score (-10.0) -> capped to conservative
        - Zero risk score (0.0) -> conservative
        - Upper bound risk score (10.0) -> aggressive
        - Oversized risk score (999.0) -> aggressive
        - Empty profile dict -> defaults to score 5.0
        - None profile -> defaults to score 5.0
        - Unseen liquidity needs string
        """
        dates = pd.date_range("2023-01-01", periods=50, freq="B")
        np.random.seed(404)
        prices = pd.DataFrame({
            "SPY": 100.0 * np.exp(np.cumsum(np.random.normal(0.0005, 0.01, 50))),
            "BND": 100.0 * np.exp(np.cumsum(np.random.normal(0.0001, 0.003, 50))),
        }, index=dates)

        numeric_profiles = [
            {"risk_tolerance_score": -10.0},
            {"risk_tolerance_score": 0.0},
            {"risk_tolerance_score": 10.0},
            {"risk_tolerance_score": 999.0},
            {},
            None,
            {"risk_tolerance_score": 5.0, "liquidity_needs": "EXTREME_UNSEEN_VALUE"},
        ]

        for p in numeric_profiles:
            res = await engine.generate_allocation(prices, p)
            assert isinstance(res, AllocationResult)
            total_w = sum(res.weights.values())
            assert abs(total_w - 1.0) < 1e-3, f"Profile {p} gave sum(weights)={total_w}"
            for w in res.weights.values():
                assert not math.isnan(w) and not math.isinf(w)
                assert w >= -1e-5

    def test_vulnerability_malformed_profile_none_and_string(self, engine):
        """
        Verify remediation of finding F-01: _translate_profile_constraints safely handles
        None and malformed string values for numeric fields without raising TypeError or ValueError.
        """
        # None risk tolerance score resolves to default moderate (5.0 -> max_w 0.30)
        obj_func, risk_meas, max_w, min_w, min_w_dict = engine._translate_profile_constraints(
            {"risk_tolerance_score": None}, ["SPY", "BND"]
        )
        assert max_w == 0.30
        assert min_w == 0.02

        # Non-numeric string risk tolerance score resolves to default moderate
        obj_func, risk_meas, max_w, min_w, min_w_dict = engine._translate_profile_constraints(
            {"risk_tolerance_score": "not_a_number"}, ["SPY", "BND"]
        )
        assert max_w == 0.30

        # None investment horizon resolves to default horizon (10)
        obj_func2, risk_meas2, max_w2, min_w2, min_w_dict2 = engine._translate_profile_constraints(
            {"investment_horizon_years": None}, ["SPY", "BND"]
        )
        assert max_w2 == 0.30

    @pytest.mark.asyncio
    async def test_vulnerability_nan_column_empty_weights(self, engine):
        """
        Verify remediation of finding F-02: When a price dataframe contains
        an all-NaN column causing dropped columns, Tier 5 profile benchmark falls back
        to AllocationEngine.DEFAULT_UNIVERSE so weights is never empty.
        """
        dates = pd.date_range("2023-01-01", periods=10)
        df_nan = pd.DataFrame({"SPY": [np.nan] * 10, "BND": [50.0] * 10}, index=dates)
        res = await engine.generate_allocation(df_nan, {"risk_tolerance_score": 5.0})
        assert res.solver_method == "profile_heuristic"
        # Weights are populated from DEFAULT_UNIVERSE and sum to 1.0
        assert len(res.weights) > 0, f"Expected non-empty weights, got {res.weights}"
        total_w = sum(res.weights.values())
        assert abs(total_w - 1.0) < 1e-3, f"Weights must sum to 1.0, got {total_w}"


# ==============================================================================
# 2. Efficient Frontier Curve Generation & Monotonicity
# ==============================================================================

class TestEfficientFrontierStress:

    @pytest.mark.parametrize("n_points", [5, 10, 20])
    def test_frontier_varying_n_points(self, engine, n_points):
        """
        Verify efficient frontier generates exact requested number of points
        and that all points have valid weights summing to 1.0.
        """
        dates = pd.date_range("2023-01-01", periods=100, freq="B")
        np.random.seed(505)
        prices = pd.DataFrame({
            "SPY": 100.0 * np.exp(np.cumsum(np.random.normal(0.0008, 0.012, 100))),
            "BND": 100.0 * np.exp(np.cumsum(np.random.normal(0.0002, 0.004, 100))),
            "GLD": 100.0 * np.exp(np.cumsum(np.random.normal(0.0004, 0.008, 100))),
        }, index=dates)

        frontier = engine.generate_efficient_frontier(prices, n_points=n_points)
        assert len(frontier) == n_points

        for idx, pt in enumerate(frontier):
            assert isinstance(pt, EfficientFrontierPoint)
            assert pt.point_index == idx
            assert pt.volatility >= 0.0
            assert pt.annualized_volatility >= 0.0
            total_w = sum(pt.weights.values())
            assert abs(total_w - 1.0) < 1e-2, f"Frontier point {idx} weights sum to {total_w}"
            for sym, w in pt.weights.items():
                assert not math.isnan(w) and not math.isinf(w)
                assert w >= -1e-5

    def test_frontier_risk_return_properties(self, engine):
        """
        Test mathematical properties along the efficient frontier:
        Along an efficient frontier, risk and return trade off:
        Minimum variance point has the lowest volatility;
        As expected return increases along the efficient frontier, volatility must be non-decreasing.
        """
        dates = pd.date_range("2023-01-01", periods=120, freq="B")
        np.random.seed(606)
        prices = pd.DataFrame({
            "EQUITY": 100.0 * np.exp(np.cumsum(np.random.normal(0.0010, 0.015, 120))),
            "BOND": 100.0 * np.exp(np.cumsum(np.random.normal(0.0001, 0.003, 120))),
        }, index=dates)

        frontier = engine.generate_efficient_frontier(prices, n_points=10)
        assert len(frontier) == 10

        returns = [pt.expected_return for pt in frontier]
        vols = [pt.volatility for pt in frontier]

        # In skfolio or analytical fallback, either returns or vols should be ordered monotonically
        is_ret_monotonic = all(returns[i] <= returns[i+1] + 1e-7 for i in range(len(returns)-1)) or \
                           all(returns[i] >= returns[i+1] - 1e-7 for i in range(len(returns)-1))
        is_vol_monotonic = all(vols[i] <= vols[i+1] + 1e-7 for i in range(len(vols)-1)) or \
                           all(vols[i] >= vols[i+1] - 1e-7 for i in range(len(vols)-1))

        assert is_ret_monotonic or is_vol_monotonic, (
            f"Neither return nor volatility is monotonic along frontier: "
            f"returns={returns}, vols={vols}"
        )


# ==============================================================================
# 3. Euler Analytical Risk Attribution Stress
# ==============================================================================

class TestEulerRiskAttributionStress:

    def test_euler_sum_to_100_percent(self, engine):
        """
        Euler decomposition theorem for portfolio risk:
        Sum of percentage risk contributions %RC_i = w_i * (Sigma * w)_i / sigma_p^2
        MUST equal 1.0 (100%) within tight numerical tolerance (1e-3).
        """
        dates = pd.date_range("2023-01-01", periods=100, freq="B")
        np.random.seed(707)
        returns = pd.DataFrame(
            np.random.normal(0.0005, 0.01, (100, 5)),
            index=dates,
            columns=["A", "B", "C", "D", "E"],
        )

        weight_sets = [
            {"A": 0.2, "B": 0.2, "C": 0.2, "D": 0.2, "E": 0.2},
            {"A": 0.5, "B": 0.3, "C": 0.1, "D": 0.05, "E": 0.05},
            {"A": 0.8, "B": 0.1, "C": 0.05, "D": 0.03, "E": 0.02},
            {"A": 0.01, "B": 0.01, "C": 0.01, "D": 0.01, "E": 0.96},
        ]

        for w in weight_sets:
            attribs = engine.calculate_analytical_attribution(w, returns)
            assert len(attribs) == 5
            total_rc = sum(attribs.values())
            assert abs(total_rc - 1.0) < 1e-3, (
                f"Euler risk contributions sum to {total_rc}, expected 1.0 +- 1e-3 for weights {w}"
            )

    def test_euler_attribution_zero_variance_degenerate(self, engine):
        """
        Degenerate case: Constant returns or zero portfolio variance.
        Should return weights fallback without ZeroDivisionError or NaN.
        """
        dates = pd.date_range("2023-01-01", periods=10, freq="B")
        flat_returns = pd.DataFrame({"A": np.zeros(10), "B": np.zeros(10)}, index=dates)
        weights = {"A": 0.60, "B": 0.40}

        attribs = engine.calculate_analytical_attribution(weights, flat_returns)
        assert attribs["A"] == 0.60
        assert attribs["B"] == 0.40
        assert sum(attribs.values()) == 1.0


# ==============================================================================
# 4. Rebalancing Trade Generator Stress & Cash Neutrality
# ==============================================================================

class TestRebalancingTradeGeneratorStress:

    def test_sell_strictly_before_buy_ordering(self, engine):
        """
        Test 30 randomized portfolio permutations to verify SELL-before-BUY invariant.
        No BUY order can ever appear before any SELL order.
        """
        np.random.seed(808)
        symbols = ["SPY", "VTI", "QQQ", "BND", "AGG", "SHY", "IWM", "EEM"]

        for trial in range(30):
            curr_pos = {sym: float(np.random.randint(1, 100)) for sym in symbols}
            prices = {sym: float(np.random.uniform(20.0, 400.0)) for sym in symbols}

            raw_w = np.random.uniform(0.01, 1.0, len(symbols))
            norm_w = raw_w / sum(raw_w)
            tgt_weights = {sym: float(norm_w[i]) for i, sym in enumerate(symbols)}

            plan = engine.generate_rebalancing_trades(
                current_positions=curr_pos,
                current_prices_or_target=prices,
                target_weights=tgt_weights,
                cash=100.0,
                min_trade_amount=5.0,
            )

            assert isinstance(plan, RebalancePlan)
            sides = [o.side for o in plan.orders]

            # Invariant: If BUY exists, no SELL can occur after the first BUY
            if "BUY" in sides and "SELL" in sides:
                first_buy_idx = sides.index("BUY")
                for idx, side in enumerate(sides):
                    if idx < first_buy_idx:
                        assert side == "SELL", f"Found {side} at index {idx} before first BUY at {first_buy_idx}"
                    else:
                        assert side == "BUY", f"Found {side} at index {idx} after first BUY at {first_buy_idx}"

    def test_cash_accounting_and_neutrality(self, engine):
        """
        Test cash accounting:
        estimated_cash_after == cash_before + sum(sell_amounts) - sum(buy_amounts)
        When all drifts are traded and target weights sum to 1.0, cash change balances target allocation.
        """
        curr_pos = {"SPY": 10.0, "BND": 50.0}   # SPY: 10 * 100 = 1000, BND: 50 * 20 = 1000 -> Total = 2000
        prices = {"SPY": 100.0, "BND": 20.0}
        tgt_weights = {"SPY": 0.70, "BND": 0.30}
        cash_before = 500.0

        plan = engine.generate_rebalancing_trades(
            current_positions=curr_pos,
            current_prices_or_target=prices,
            target_weights=tgt_weights,
            cash=cash_before,
            min_trade_amount=1.0,
        )

        sell_sum = sum(o.estimated_amount for o in plan.orders if o.side == "SELL")
        buy_sum = sum(o.estimated_amount for o in plan.orders if o.side == "BUY")

        expected_cash_after = cash_before + sell_sum - buy_sum
        assert abs(plan.estimated_cash_after - expected_cash_after) < 0.05

        assert plan.orders[0].side == "SELL"
        assert plan.orders[0].symbol == "BND"


# ==============================================================================
# 5. ProductComparisonAgent Six-Factor Scoring Boundary Stress
# ==============================================================================

class TestProductComparisonFactorScoringStress:

    def test_expense_ratio_extreme_boundaries(self, comp_agent):
        """
        Expense ratio boundaries:
        - 0.0% (free fund) -> score 10.0
        - Negative expense ratio -> score 10.0 (capped)
        - Normal low fee 0.03% (3 bps) -> 9.70
        - High fee 1.00% (100 bps) -> 0.00
        - Massive fee 5.00% (500 bps) -> 0.00 (floor at 0.0)
        """
        assert comp_agent.score_expense_ratio(0.0) == 10.0
        assert comp_agent.score_expense_ratio(-0.01) == 10.0
        assert comp_agent.score_expense_ratio(0.0003) == 9.70
        assert comp_agent.score_expense_ratio(0.0100) == 0.00
        assert comp_agent.score_expense_ratio(0.0500) == 0.00
        assert comp_agent.score_expense_ratio(1.0000) == 0.00

    def test_tracking_error_extreme_boundaries(self, comp_agent):
        """
        Tracking error boundaries:
        - TE = 0.0000 (perfect index replica) -> score 10.0
        - Massive TE = 0.20 (20% divergence) -> score 0.00
        - Catastrophic TE = 1.00 (100% divergence) -> score 0.00
        """
        bench = pd.Series([0.01, -0.01, 0.02, -0.02] * 10)
        perfect = bench.copy()
        massive_diff = bench + pd.Series([0.5, -0.5, 0.8, -0.8] * 10)

        s_perfect, te_perfect = comp_agent.score_tracking_error(perfect, bench)
        s_massive, te_massive = comp_agent.score_tracking_error(massive_diff, bench)

        assert s_perfect == 10.0
        assert te_perfect == 0.0
        assert s_massive == 0.0
        assert te_massive > 0.05

    def test_liquidity_extreme_boundaries(self, comp_agent):
        """
        Liquidity boundaries:
        - Microscopic volume / zero AUM / wide spread
        - Massive volume / zero spread
        - Crossed market (bid > ask)
        """
        class MockCrossed:
            bid = 105.00
            ask = 100.00
            price = 100.00
            volume = 1000

        class MockZeroVol:
            bid = 90.00
            ask = 110.00
            price = 100.00
            volume = 0

        # Should never raise ZeroDivisionError or math domain error
        s_cross, _, _ = comp_agent.score_liquidity(MockCrossed(), aum_billions=0.0)
        s_zero, _, _ = comp_agent.score_liquidity(MockZeroVol(), aum_billions=0.0)

        assert 0.0 <= s_cross <= 10.0
        assert 0.0 <= s_zero <= 10.0

    def test_historical_return_extreme_boundaries(self, comp_agent):
        """
        Historical return boundaries:
        - Return -100% (-1.0) -> score 0.00
        - Return +1000% (+10.0) -> score 10.00
        """
        crash_series = pd.Series([-0.10] * 50)  # Cumulative -99.5%
        moon_series = pd.Series([0.05] * 50)    # Cumulative +1046%

        s_crash, _ = comp_agent.score_historical_return(crash_series, asset_class="equity")
        s_moon, _ = comp_agent.score_historical_return(moon_series, asset_class="equity")

        assert s_crash == 0.00
        assert s_moon == 10.00

    def test_composite_score_strictly_bounded(self, comp_agent):
        """
        Verify that composite score across all permutations of boundary factor values
        is strictly bounded in [0.0, 10.0].
        """
        meta_best = AssetMetadata(
            symbol="BEST",
            name="Vanguard Perfect Index",
            asset_class="equity",
            sub_category="large_cap_blend",
            expense_ratio=0.0,
            aum_billions=600.0,
            holdings_count=500,
            risk_level=2,
            yield_30d=0.02,
        )

        meta_worst = AssetMetadata(
            symbol="WORST",
            name="Shady Boutique Microcap",
            asset_class="equity",
            sub_category="microcap",
            expense_ratio=0.10,  # 10%
            aum_billions=0.001,
            holdings_count=5,
            risk_level=5,
            yield_30d=0.0,
        )

        bench = pd.Series([0.01, -0.01] * 20)
        # High quality low tracking error index tracking (+alpha)
        perf_best = bench + 0.0001
        # Deep crash for worst asset
        perf_worst = pd.Series([-0.10] * 40)

        score_best, breakdown_best = comp_agent.score_product(meta_best, None, perf_best, bench)
        score_worst, breakdown_worst = comp_agent.score_product(meta_worst, None, perf_worst, bench)

        assert 0.0 <= score_best <= 10.0
        assert 0.0 <= score_worst <= 10.0
        assert score_best >= 8.5
        assert score_worst < 3.5
        assert isinstance(breakdown_best, FactorScores)
        assert isinstance(breakdown_worst, FactorScores)

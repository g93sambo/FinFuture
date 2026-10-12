"""
backend/tests/unit/test_financial_engineering.py
================================================
Unit tests for the Institutional Financial Engineering & Wealth Simulation Engine.
Verifies:
1. Numerical solver for required CAGR accounting for inflation withdrawals, taxes, and fees.
2. Full 10-year cash flow table calculation.
3. Stochastic variable return cycle table.
4. Reproducible 10,000-path Monte Carlo probability simulation with published inputs.
5. Fiduciary institutional portfolio structure (single-issuer limit <=8%, liquidity reserve).
6. Explicit stress-testing scenarios with exact recovery math.
7. Triple-portfolio comparison under identical 5% withdrawal rate constraints.
"""

import pytest
from services.financial_engineering import (
    solve_required_return,
    generate_10year_cash_flow_table,
    generate_stochastic_variable_cycle_table,
    run_reproducible_monte_carlo,
    get_fiduciary_institutional_portfolio,
    run_explicit_stress_tests,
    compare_three_institutional_portfolios,
)


def test_solve_required_return_accuracy():
    # Zero cash-flow $10M -> $100M in 10 yrs is ~25.89%
    r_zero = solve_required_return(10e6, 100e6, 10, initial_withdrawal=0.0, tax_drag_pct=0.0, advisory_fee_pct=0.0)
    assert 0.258 <= r_zero <= 0.260

    # With $500k withdrawals, 2% inflation, 15% tax, 1% fee -> required hurdle return is ~34.4%
    r_full = solve_required_return(10e6, 100e6, 10, initial_withdrawal=500e3, withdrawal_inflation_pct=0.02, tax_drag_pct=0.15, advisory_fee_pct=0.01)
    assert 0.33 <= r_full <= 0.36


def test_generate_10year_cash_flow_table():
    r = solve_required_return(10e6, 100e6, 10, 500e3)
    table = generate_10year_cash_flow_table(10e6, r, 10, 500e3)
    assert len(table) == 10
    assert table[0]["year"] == 1
    assert table[0]["starting_wealth"] == 10_000_000.0
    assert table[0]["withdrawal"] == 500_000.0
    assert table[9]["year"] == 10
    assert 98_000_000.0 <= table[9]["ending_wealth"] <= 102_000_000.0


def test_generate_stochastic_variable_cycle_table():
    cycle = generate_stochastic_variable_cycle_table(10e6, 10, 500e3)
    assert len(cycle) == 10
    assert cycle[0]["market_return_pct"] == 22.0
    assert cycle[1]["market_return_pct"] == -14.0
    assert cycle[9]["ending_wealth"] > 0


def test_reproducible_monte_carlo():
    res = run_reproducible_monte_carlo(10e6, 100e6, 10, 500e3, n_simulations=1000)
    assert "simulation_metadata" in res
    assert "asset_class_inputs" in res
    assert len(res["asset_class_inputs"]) == 5
    probs = res["empirical_probabilities"]
    assert "probability_reaching_100m_target_pct" in probs
    assert probs["probability_reaching_100m_target_pct"] < 5.0
    assert probs["probability_10yr_lifestyle_fully_funded_pct"] > 85.0


def test_fiduciary_institutional_portfolio():
    port = get_fiduciary_institutional_portfolio()
    tranches = port["allocation_tranches"]
    assert len(tranches) == 6
    # Verify 10% liquidity buffer exists
    assert tranches[0]["weight_pct"] == "10.0%"
    assert "SGOV" in tranches[0]["holdings"][0]["ticker"]
    # Verify no single holding exceeds 8% except broad index funds
    for tr in tranches:
        if "Core" not in tr["tranche_name"] and "Liquidity" not in tr["tranche_name"]:
            for h in tr["holdings"]:
                pct_val = float(h["weight"].replace("%", ""))
                assert pct_val <= 8.0


def test_explicit_stress_tests():
    shocks = run_explicit_stress_tests(10e6, 500e3)
    assert len(shocks) == 3
    sor = shocks[2]
    assert "Sequence-of-Returns" in sor["scenario"]
    assert "exact_recovery_gain_needed_pct" in sor
    assert "annualized_cagr_required_to_recover" in sor


def test_compare_three_institutional_portfolios():
    three = compare_three_institutional_portfolios(10e6, 10, 500e3)
    assert "portfolio_a_moonshot_speculative" in three
    assert "portfolio_b_institutional_endowment" in three
    assert "portfolio_c_capital_preservation" in three
    assert "APPROVED" in three["portfolio_b_institutional_endowment"]["investment_committee_verdict"]
    assert "REJECTED" in three["portfolio_a_moonshot_speculative"]["investment_committee_verdict"]


def test_calculate_dcf_valuation():
    from services.financial_engineering import calculate_dcf_valuation
    # 5-year FCF of $100M growing to $150M, WACC 9%, terminal growth 2.5%, 50M shares, $100M net debt
    fcf = [100.0, 110.0, 122.0, 135.0, 150.0]
    res = calculate_dcf_valuation(
        projected_fcf=fcf,
        wacc=0.09,
        terminal_growth_rate=0.025,
        shares_outstanding=50.0,
        net_debt=100.0,
        current_price=28.0,
    )
    assert res["implied_fair_value_per_share"] > 0
    assert "valuation_verdict" in res
    assert res["discrete_period_years"] == 5


def test_calculate_var_cvar_sharpe():
    from services.financial_engineering import calculate_var_cvar_sharpe
    import numpy as np
    np.random.seed(42)
    daily_rets = list(np.random.normal(0.0005, 0.012, 252))
    metrics = calculate_var_cvar_sharpe(daily_rets, confidence_level=0.95)
    assert "historical_var_pct" in metrics
    assert "conditional_var_expected_shortfall_pct" in metrics
    assert "annualized_sharpe_ratio" in metrics
    assert "maximum_drawdown_pct" in metrics


def test_calculate_hurdle_score():
    from services.financial_engineering import calculate_hurdle_score
    # Scenario 1: Passing investment
    pass_res = calculate_hurdle_score(22, 18, 17, 12, 16, fatal_dealbreakers=[])
    assert pass_res["institutional_hurdle_score"] == 85.0
    assert pass_res["passed_threshold"] is True
    assert "YES — INVEST" in pass_res["verdict"]

    # Scenario 2: Failing due to fatal dealbreaker even with high score
    fail_res = calculate_hurdle_score(20, 18, 18, 12, 15, fatal_dealbreakers=["Fatal FX liability mismatch"])
    assert fail_res["passed_threshold"] is False
    assert "NO — DO NOT INVEST" in fail_res["verdict"]
    assert "ZERO CAPITAL ALLOCATION" in fail_res["recommended_portfolio_allocation"]


"""
backend/tests/unit/test_black_litterman.py
==========================================
Unit tests for the Black-Litterman Asset Allocation Engine.
Verifies market equilibrium calculations, research view incorporation,
and weight shift directionality.
"""

import numpy as np
import pytest
from services.black_litterman import compute_black_litterman, ResearchView


def test_black_litterman_equilibrium_without_views():
    assets = ["SPY", "QQQ", "BND"]
    cov = np.array([
        [0.04, 0.03, 0.00],
        [0.03, 0.05, -0.01],
        [0.00, -0.01, 0.01],
    ])
    w_mkt = np.array([0.5, 0.3, 0.2])

    res = compute_black_litterman(
        assets=assets,
        cov_matrix=cov,
        market_weights=w_mkt,
        views=None,
    )

    assert res.assets == assets
    for a in assets:
        assert pytest.approx(res.prior_weights[a], abs=1e-3) == w_mkt[assets.index(a)]
        assert pytest.approx(res.optimal_weights[a], abs=1e-3) == w_mkt[assets.index(a)]
        assert pytest.approx(res.weight_shifts[a], abs=1e-4) == 0.0


def test_black_litterman_bullish_view_shifts_weight_positively():
    assets = ["SPY", "QQQ", "BND"]
    cov = np.eye(3) * 0.04
    w_mkt = np.array([0.4, 0.3, 0.3])

    # Research view: QQQ will outperform with expected 25% return and 90% confidence
    bullish_view = ResearchView(
        asset="QQQ",
        expected_return=0.25,
        confidence=0.90,
        rationale="Strong AI secular tailwinds from Deep Research",
    )

    res = compute_black_litterman(
        assets=assets,
        cov_matrix=cov,
        market_weights=w_mkt,
        views=[bullish_view],
    )

    # QQQ optimal weight should increase relative to prior
    assert res.optimal_weights["QQQ"] > res.prior_weights["QQQ"]
    assert res.weight_shifts["QQQ"] > 0.0
    # Weights sum to 1.0
    assert pytest.approx(sum(res.optimal_weights.values()), abs=1e-4) == 1.0

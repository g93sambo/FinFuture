"""
backend/agents/allocation_engine.py
===================================
Modern Portfolio Theory optimization engine built on skfolio Mean-Risk Conditional
Value at Risk (CVaR), profile-driven constraints, 5-tier resilient solver fallback cascade,
efficient frontier curve generator, rebalancing trade generator, and SHAP/analytical explainability.
"""

from __future__ import annotations

import os
import math
import logging
from typing import Dict, Any, List, Optional, Tuple, Union

import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from skfolio import RiskMeasure
from skfolio.optimization import (
    MeanRisk,
    InverseVolatility,
    EqualWeighted,
    ObjectiveFunction,
)
from skfolio.preprocessing import prices_to_returns

from agents.market_data import MarketDataAgent

logger = logging.getLogger("wealth_advisor.agents.allocation_engine")


def _safe_float(val: Any, default: float) -> float:
    try:
        return float(val) if val is not None else default
    except (ValueError, TypeError):
        return default


def _safe_int(val: Any, default: int) -> int:
    try:
        return int(val) if val is not None else default
    except (ValueError, TypeError):
        return default


class RebalanceOrder(BaseModel):
    symbol: str
    side: str  # "BUY" | "SELL"
    qty: float = Field(..., gt=0.0)
    estimated_price: float = Field(..., gt=0.0)
    estimated_amount: float = Field(..., gt=0.0)
    current_weight: float
    target_weight: float
    weight_delta: float


class RebalancePlan(BaseModel):
    client_id: Optional[str] = None
    total_portfolio_value: float
    cash_before: float
    estimated_cash_after: float
    max_drift: float
    portfolio_turnover: float
    is_rebalance_needed: bool
    orders: List[RebalanceOrder] = Field(default_factory=list)


class EfficientFrontierPoint(BaseModel):
    point_index: int
    expected_return: float
    volatility: float
    annualized_return: float
    annualized_volatility: float
    sharpe_ratio: float
    cvar_95: float
    weights: Dict[str, float]


class AllocationResult(BaseModel):
    weights: Dict[str, float]
    metrics: Dict[str, float]
    solver_method: str  # "cvar_ratio" | "min_variance" | "inverse_volatility" | "equal_weighted" | "profile_heuristic"
    explanation: str
    feature_attributions: Dict[str, float] = Field(default_factory=dict)
    frontier: Optional[List[EfficientFrontierPoint]] = None
    rebalance_plan: Optional[RebalancePlan] = None


class AllocationEngine:
    """
    Modern portfolio optimization engine built on skfolio with 5-tier fallback cascade,
    efficient frontier curves, SELL-first rebalancing trade generation, and explainability.
    """

    DEFAULT_UNIVERSE = ["SPY", "VTI", "QQQ", "BND", "AGG", "SHY"]

    def __init__(
        self,
        market_data_agent: Optional[MarketDataAgent] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
    ) -> None:
        self.market_data = market_data_agent or MarketDataAgent()
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        try:
            from core.config import settings
            default_model = getattr(settings, "openai_model", "gpt-4o")
        except Exception:
            default_model = "gpt-4o"
        self.openai_model = openai_model or os.getenv("OPENAI_MODEL", default_model)

    # ------------------------------------------------------------------
    # Profile Constraint Translation
    # ------------------------------------------------------------------

    def _translate_profile_constraints(
        self,
        profile: Any,
        asset_symbols: List[str],
    ) -> Tuple[str, RiskMeasure, float, float, Dict[str, float]]:
        """
        Translates client risk parameters into optimization constraints.
        Returns (objective_func_name, risk_measure, max_weights, min_weights, min_weights_dict).
        """
        score = 5.0
        horizon = 10
        liquidity = "medium"

        if isinstance(profile, dict):
            score = _safe_float(profile.get("risk_tolerance_score"), 5.0)
            horizon = _safe_int(profile.get("investment_horizon_years"), 10)
            liquidity = str(profile.get("liquidity_needs", "medium")).lower()
        elif profile is not None:
            score = _safe_float(getattr(profile, "risk_tolerance_score", 5.0), 5.0)
            horizon = _safe_int(getattr(profile, "investment_horizon_years", 10), 10)
            liquidity = str(getattr(profile, "liquidity_needs", "medium")).lower()

        # Constraints based on risk tolerance
        if score <= 3.5:  # Conservative
            obj_func = ObjectiveFunction.MINIMIZE_RISK
            risk_meas = RiskMeasure.CVAR
            max_w = 0.35
            min_w = 0.0
        elif score <= 6.5:  # Moderate
            obj_func = ObjectiveFunction.MAXIMIZE_RATIO
            risk_meas = RiskMeasure.CVAR
            max_w = 0.30
            min_w = 0.02
        elif score <= 8.5:  # Growth
            obj_func = ObjectiveFunction.MAXIMIZE_RATIO
            risk_meas = RiskMeasure.CVAR
            max_w = 0.35
            min_w = 0.0
        else:  # Aggressive Growth
            obj_func = ObjectiveFunction.MAXIMIZE_RATIO
            risk_meas = RiskMeasure.CVAR
            max_w = 0.40
            min_w = 0.0

        min_w_dict: Dict[str, float] = {}
        if liquidity == "high" and "SHY" in asset_symbols:
            min_w_dict["SHY"] = 0.15
        elif liquidity == "medium" and "SHY" in asset_symbols:
            min_w_dict["SHY"] = 0.05

        return obj_func, risk_meas, max_w, min_w, min_w_dict

    # ------------------------------------------------------------------
    # 5-Tier Resilient Fallback Cascade
    # ------------------------------------------------------------------

    def _fit_five_tier_cascade(
        self,
        returns: pd.DataFrame,
        profile: Any,
    ) -> Tuple[Any, str, Dict[str, float]]:
        """
        Executes optimization through 5-tier fallback cascade:
        Tier 1 (CVaR Ratio) -> Tier 2 (Minimum Variance QP) -> Tier 3 (Inverse Volatility) ->
        Tier 4 (Equal Weighted) -> Tier 5 (Profile Benchmark Rule-Based).
        """
        asset_symbols = returns.columns.tolist()
        obj_func, risk_meas, max_w, min_w, min_w_dict = self._translate_profile_constraints(
            profile, asset_symbols
        )

        # Tier 1: CVaR Ratio Optimization
        try:
            model = MeanRisk(
                risk_measure=risk_meas,
                objective_function=obj_func,
                max_weights=max_w,
                min_weights=min_w,
            )
            model.fit(returns)
            portfolio = model.predict(returns)
            weights = dict(portfolio.weights_dict)
            return portfolio, "cvar_ratio", weights
        except Exception as e1:
            logger.info(f"Tier 1 (CVaR Ratio) failed: {e1}. Proceeding to Tier 2 (Minimum Variance).")

        # Tier 2: Minimum Variance Quadratic Optimization
        try:
            model2 = MeanRisk(
                risk_measure=RiskMeasure.VARIANCE,
                objective_function=ObjectiveFunction.MINIMIZE_RISK,
                max_weights=max(max_w, 0.50),
                min_weights=0.0,
            )
            model2.fit(returns)
            portfolio2 = model2.predict(returns)
            weights2 = dict(portfolio2.weights_dict)
            return portfolio2, "min_variance", weights2
        except Exception as e2:
            logger.info(f"Tier 2 (Minimum Variance) failed: {e2}. Proceeding to Tier 3 (Inverse Volatility).")

        # Tier 3: Inverse Volatility (Risk Parity Heuristic)
        try:
            iv = InverseVolatility()
            iv.fit(returns)
            portfolio3 = iv.predict(returns)
            weights3 = dict(portfolio3.weights_dict)
            return portfolio3, "inverse_volatility", weights3
        except Exception as e3:
            logger.info(f"Tier 3 (Inverse Volatility) failed: {e3}. Proceeding to Tier 4 (Equal Weighted).")

        # Tier 4: Equal Weighted Diversification
        try:
            eq = EqualWeighted()
            eq.fit(returns)
            portfolio4 = eq.predict(returns)
            weights4 = dict(portfolio4.weights_dict)
            return portfolio4, "equal_weighted", weights4
        except Exception as e4:
            logger.info(f"Tier 4 (Equal Weighted) failed: {e4}. Proceeding to Tier 5 (Profile Benchmark).")

        # Tier 5: Profile Benchmark Rule-Based Allocation
        score = 5.0
        if isinstance(profile, dict):
            score = _safe_float(profile.get("risk_tolerance_score"), 5.0)
        elif profile is not None:
            score = _safe_float(getattr(profile, "risk_tolerance_score", 5.0), 5.0)

        if score <= 3.5:
            base_weights = {"SPY": 0.20, "BND": 0.80}
        elif score <= 6.5:
            base_weights = {"SPY": 0.60, "BND": 0.40}
        elif score <= 8.5:
            base_weights = {"SPY": 0.80, "BND": 0.20}
        else:
            base_weights = {"SPY": 0.90, "BND": 0.10}

        # Filter symbols present in universe; fallback to default universe if empty
        symbols = asset_symbols if asset_symbols else list(self.DEFAULT_UNIVERSE)
        weights5: Dict[str, float] = {}
        avail = [s for s in base_weights if s in symbols]
        if avail:
            total_b = sum(base_weights[s] for s in avail)
            for s in avail:
                weights5[s] = base_weights[s] / total_b
        else:
            n = len(symbols) if symbols else 1
            for s in symbols:
                weights5[s] = 1.0 / n

        return None, "profile_heuristic", weights5

    # ------------------------------------------------------------------
    # Analytical Risk & Return Attribution (SHAP Fallback)
    # ------------------------------------------------------------------

    def calculate_analytical_attribution(
        self,
        weights: Dict[str, float],
        returns: pd.DataFrame,
    ) -> Dict[str, float]:
        """
        Deterministic closed-form risk/return attribution fallback when SHAP is bypassed.
        Calculates Euler percentage risk contribution: %RC_i = w_i * (Sigma * w)_i / sigma_p^2.
        """
        symbols = [s for s in returns.columns if s in weights]
        if not symbols or len(returns) < 2:
            return {s: round(weights.get(s, 0.0), 4) for s in weights}

        try:
            cov = returns[symbols].cov()
            w_vec = np.array([weights.get(s, 0.0) for s in symbols])
            port_var = float(np.dot(w_vec.T, np.dot(cov.values, w_vec)))
            if port_var <= 0:
                return {s: round(weights.get(s, 0.0), 4) for s in symbols}

            mrc = np.dot(cov.values, w_vec)
            risk_contribs = (w_vec * mrc) / port_var
            return {s: round(float(rc), 4) for s, rc in zip(symbols, risk_contribs)}
        except Exception as e:
            logger.warning(f"Analytical attribution calculation failed: {e}")
            return {s: round(weights.get(s, 0.0), 4) for s in weights}

    # ------------------------------------------------------------------
    # SHAP & Natural Language Narrative Explanation
    # ------------------------------------------------------------------

    async def _explain_allocation(
        self,
        weights: Dict[str, float],
        returns: pd.DataFrame,
        asset_symbols: List[str],
        profile: Any,
    ) -> Tuple[str, Dict[str, float]]:
        """Generates SHAP or analytical factor attribution and explanatory narrative."""
        # Compute feature attributions
        attributions: Dict[str, float] = {}
        try:
            import shap
            w_vec = np.array([weights.get(s, 0.0) for s in asset_symbols])
            bg_size = min(50, len(returns))
            bg = returns[asset_symbols].sample(bg_size, random_state=42)

            def predict_portfolio_returns(X):
                return np.dot(X, w_vec)

            explainer = shap.KernelExplainer(predict_portfolio_returns, bg)
            recent_day = returns[asset_symbols].iloc[-1:]
            shap_values = explainer.shap_values(recent_day)
            shap_array = shap_values[0] if isinstance(shap_values, list) else shap_values[0]
            for sym, val in zip(asset_symbols, shap_array):
                attributions[sym] = round(float(val), 5)
        except Exception as e_shap:
            logger.info(f"SHAP explanation bypassed or failed ({e_shap}), using analytical attribution.")
            attributions = self.calculate_analytical_attribution(weights, returns)

        # Generate narrative (LLM or deterministic fallback)
        score = 5.0
        cat = "Moderate"
        horizon = 10
        goal = "growth"
        if isinstance(profile, dict):
            score = _safe_float(profile.get("risk_tolerance_score"), 5.0)
            cat = profile.get("suitability_category", "Moderate")
            horizon = _safe_int(profile.get("investment_horizon_years"), 10)
            goal = profile.get("primary_goal", "growth")
        elif profile is not None:
            score = _safe_float(getattr(profile, "risk_tolerance_score", 5.0), 5.0)
            cat = getattr(profile, "suitability_category", "Moderate")
            horizon = _safe_int(getattr(profile, "investment_horizon_years", 10), 10)
            goal = getattr(profile, "primary_goal", "growth")

        top_asset = max(weights.items(), key=lambda x: x[1])[0] if weights else "SPY"
        top_weight = weights.get(top_asset, 0.0)

        # Deterministic compliant narrative
        narrative = (
            f"Based on your {cat} risk profile (tolerance score {score}/10) and an investment horizon "
            f"of {horizon} years, the portfolio is structured to maximize risk-adjusted returns while "
            f"controlling downside tail risk. Core allocation is anchored by {top_asset} ({top_weight * 100:.1f}%), "
            f"balancing capital growth with downside risk management. This allocation is fully aligned with "
            f"your primary financial objective of {goal}."
        )

        if self.openai_api_key and self.openai_api_key != "your_openai_api_key_here":
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=self.openai_api_key)
                prompt = (
                    f"Explain this portfolio allocation in 2 paragraphs:\n"
                    f"Profile: Score {score}/10, Horizon {horizon}y, Category {cat}, Goal {goal}\n"
                    f"Weights: {weights}\n"
                    f"Factor Attributions: {attributions}"
                )
                resp = await client.chat.completions.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=250,
                )
                narrative = resp.choices[0].message.content.strip()
            except Exception:
                pass

        # Append mandatory regulatory risk disclosure (REG-002)
        mandatory_disclosure = (
            "Investing involves risk, including possible loss of principal. "
            "Past performance is no guarantee of future results."
        )
        if "loss of principal" not in narrative.lower() and "past performance" not in narrative.lower():
            narrative = f"{narrative}\n\n{mandatory_disclosure}"

        return narrative, attributions

    # ------------------------------------------------------------------
    # Efficient Frontier Curve Generator
    # ------------------------------------------------------------------

    def generate_efficient_frontier(
        self,
        data_or_profile: Any,
        n_points: int = 10,
        max_weights: float = 0.50,
        min_weights: float = 0.0,
    ) -> List[EfficientFrontierPoint]:
        """
        Computes series of risk/return points along the efficient frontier.
        """
        if isinstance(data_or_profile, pd.DataFrame):
            price_df = data_or_profile
        else:
            # Synthetic default dataframe for demonstration
            dates = pd.date_range("2023-01-01", periods=100, freq="B")
            price_df = pd.DataFrame(
                {
                    "SPY": np.linspace(100, 125, 100) + np.random.normal(0, 1, 100),
                    "BND": np.linspace(50, 52, 100) + np.random.normal(0, 0.3, 100),
                },
                index=dates,
            )

        returns = prices_to_returns(price_df)
        frontier_points: List[EfficientFrontierPoint] = []

        try:
            model = MeanRisk(
                efficient_frontier_size=n_points,
                risk_measure=RiskMeasure.VARIANCE,
                max_weights=max_weights,
                min_weights=min_weights,
            )
            model.fit(returns)
            population = model.predict(returns)

            for idx, p in enumerate(population):
                frontier_points.append(
                    EfficientFrontierPoint(
                        point_index=idx,
                        expected_return=round(float(p.mean), 6),
                        volatility=round(float(p.standard_deviation), 6),
                        annualized_return=round(float(getattr(p, "annualized_mean", p.mean * 252)), 6),
                        annualized_volatility=round(float(p.annualized_standard_deviation), 6),
                        sharpe_ratio=round(float(p.sharpe_ratio), 4),
                        cvar_95=round(float(getattr(p, "cvar", 0.0)), 6),
                        weights=dict(p.weights_dict),
                    )
                )
            return frontier_points
        except Exception as e:
            logger.warning(f"Optimization frontier generation failed ({e}), using analytical combination.")

        # Analytical fallback frontier
        symbols = returns.columns.tolist()
        for idx in range(n_points):
            alpha = idx / max(1, n_points - 1)
            # Convex combination between conservative and growth
            if len(symbols) >= 2:
                w_first = max(0.0, min(1.0, 1.0 - alpha))
                w_second = 1.0 - w_first
                w_dict = {symbols[0]: round(w_second, 4), symbols[1]: round(w_first, 4)}
            else:
                w_dict = {symbols[0]: 1.0}

            vol = 0.05 + 0.15 * alpha
            ret = 0.03 + 0.09 * alpha
            frontier_points.append(
                EfficientFrontierPoint(
                    point_index=idx,
                    expected_return=round(ret / 252.0, 6),
                    volatility=round(vol / math.sqrt(252), 6),
                    annualized_return=round(ret, 4),
                    annualized_volatility=round(vol, 4),
                    sharpe_ratio=round((ret - 0.02) / vol, 4),
                    cvar_95=round(vol * 1.65, 4),
                    weights=w_dict,
                )
            )

        return frontier_points

    # ------------------------------------------------------------------
    # Rebalancing Trade Generator
    # ------------------------------------------------------------------

    def generate_rebalancing_trades(
        self,
        current_positions: Dict[str, Any],
        current_prices_or_target: Any,
        target_weights: Optional[Dict[str, float]] = None,
        cash: float = 0.0,
        total_portfolio_value: Optional[float] = None,
        min_trade_amount: float = 10.0,
        drift_threshold: float = 0.05,
    ) -> RebalancePlan:
        """
        Calculates drift, turnover, and concrete SELL-before-BUY rebalancing orders.
        """
        # Support flexible arguments:
        # Case A: (current_positions, current_prices, target_weights)
        # Case B: (portfolio_dict, target_weights)
        if target_weights is None and isinstance(current_prices_or_target, dict):
            # Case B
            target_weights = current_prices_or_target
            positions = current_positions.get("positions", {}) if isinstance(current_positions, dict) else {}
            prices = current_positions.get("prices", {}) if isinstance(current_positions, dict) else {}
            cash = float(current_positions.get("cash", cash)) if isinstance(current_positions, dict) else cash
        else:
            # Case A
            positions = current_positions
            prices = current_prices_or_target

        # 1. Total portfolio valuation
        positions_val = 0.0
        for sym, qty in positions.items():
            if sym.upper() not in {"CASH", "USD"}:
                price = float(prices.get(sym, 100.0))
                positions_val += float(qty) * price

        tot_val = total_portfolio_value or (positions_val + cash)
        if tot_val <= 0:
            return RebalancePlan(
                total_portfolio_value=0.0,
                cash_before=cash,
                estimated_cash_after=cash,
                max_drift=0.0,
                portfolio_turnover=0.0,
                is_rebalance_needed=False,
                orders=[],
            )

        all_symbols = set(positions.keys()).union(set(target_weights.keys()))
        all_symbols.discard("CASH")
        all_symbols.discard("USD")

        sell_orders: List[RebalanceOrder] = []
        buy_orders: List[RebalanceOrder] = []
        drifts: List[float] = []

        cash_after = cash

        for sym in sorted(all_symbols):
            price = float(prices.get(sym, 100.0))
            cur_qty = float(positions.get(sym, 0.0))
            cur_val = cur_qty * price
            cur_weight = cur_val / tot_val

            tgt_weight = float(target_weights.get(sym, 0.0))
            tgt_val = tgt_weight * tot_val

            delta_val = tgt_val - cur_val
            weight_delta = tgt_weight - cur_weight
            drift = abs(weight_delta)
            drifts.append(drift)

            # Suppress small trades below dollar threshold
            if abs(delta_val) >= min_trade_amount and price > 0:
                if delta_val < 0:  # SELL
                    trade_amount = abs(delta_val)
                    qty = round(trade_amount / price, 4)
                    sell_orders.append(
                        RebalanceOrder(
                            symbol=sym,
                            side="SELL",
                            qty=qty,
                            estimated_price=price,
                            estimated_amount=round(trade_amount, 2),
                            current_weight=round(cur_weight, 4),
                            target_weight=round(tgt_weight, 4),
                            weight_delta=round(weight_delta, 4),
                        )
                    )
                    cash_after += trade_amount
                elif delta_val > 0:  # BUY
                    trade_amount = delta_val
                    qty = round(trade_amount / price, 4)
                    buy_orders.append(
                        RebalanceOrder(
                            symbol=sym,
                            side="BUY",
                            qty=qty,
                            estimated_price=price,
                            estimated_amount=round(trade_amount, 2),
                            current_weight=round(cur_weight, 4),
                            target_weight=round(tgt_weight, 4),
                            weight_delta=round(weight_delta, 4),
                        )
                    )
                    cash_after -= trade_amount

        # SELL orders strictly precede BUY orders to ensure liquidity
        orders = sell_orders + buy_orders
        max_drift = max(drifts) if drifts else 0.0
        turnover = 0.5 * sum(drifts) if drifts else 0.0
        is_rebalance_needed = max_drift >= drift_threshold

        return RebalancePlan(
            total_portfolio_value=round(tot_val, 2),
            cash_before=round(cash, 2),
            estimated_cash_after=round(cash_after, 2),
            max_drift=round(max_drift, 4),
            portfolio_turnover=round(turnover, 4),
            is_rebalance_needed=is_rebalance_needed,
            orders=orders,
        )

    # ------------------------------------------------------------------
    # Public Allocation Generation Interface
    # ------------------------------------------------------------------

    async def generate_allocation(
        self,
        data_or_profile: Any,
        profile_or_positions: Any = None,
        include_frontier: bool = False,
        frontier_points: int = 10,
        current_positions: Optional[Dict[str, float]] = None,
        db: Optional[Any] = None,
    ) -> AllocationResult:
        """
        Runs portfolio optimization with 5-tier fallback cascade, SHAP explainability,
        and optional efficient frontier and rebalance orders.
        """
        # Resolve parameters flexibly:
        if isinstance(data_or_profile, pd.DataFrame):
            price_df = data_or_profile
            profile = profile_or_positions
        else:
            profile = data_or_profile
            # If string client_id passed, attempt to fetch profile if db provided
            if isinstance(profile, str) and db:
                from agents.risk_profiler import RiskProfilerAgent
                rp = RiskProfilerAgent()
                db_prof = await rp.get_profile(profile, db=db)
                if db_prof:
                    profile = db_prof

            # Fetch price history for standard universe
            try:
                price_df = await self.market_data.get_history(self.DEFAULT_UNIVERSE, period="1y")
            except Exception as e:
                logger.warning(f"Could not fetch market data ({e}), constructing baseline series.")
                dates = pd.date_range("2023-01-01", periods=100, freq="B")
                price_df = pd.DataFrame(
                    {
                        "SPY": np.linspace(100, 125, 100),
                        "VTI": np.linspace(90, 112, 100),
                        "QQQ": np.linspace(110, 140, 100),
                        "BND": np.linspace(50, 52, 100),
                        "AGG": np.linspace(48, 50, 100),
                        "SHY": np.linspace(40, 41, 100),
                    },
                    index=dates,
                )

        # Convert prices to returns
        if len(price_df) < 2 or price_df.isna().all().all():
            # Degenerate price history -> trigger Tier 5 directly
            score = 5.0
            if isinstance(profile, dict):
                score = _safe_float(profile.get("risk_tolerance_score"), 5.0)
            elif profile is not None:
                score = _safe_float(getattr(profile, "risk_tolerance_score", 5.0), 5.0)

            if score <= 3.5:
                weights = {"SPY": 0.20, "BND": 0.80}
            elif score <= 6.5:
                weights = {"SPY": 0.60, "BND": 0.40}
            elif score <= 8.5:
                weights = {"SPY": 0.80, "BND": 0.20}
            else:
                weights = {"SPY": 0.90, "BND": 0.10}

            method = "profile_heuristic"
            portfolio = None
            returns = pd.DataFrame(columns=list(weights.keys()))
        else:
            returns = prices_to_returns(price_df)
            portfolio, method, weights = self._fit_five_tier_cascade(returns, profile)

        # Compute portfolio metrics
        metrics: Dict[str, float] = {}
        if portfolio is not None:
            metrics["expected_return"] = round(float(portfolio.mean), 6)
            metrics["volatility"] = round(float(portfolio.standard_deviation), 6)
            metrics["annualized_volatility"] = round(float(portfolio.annualized_standard_deviation), 6)
            metrics["sharpe_ratio"] = round(float(portfolio.sharpe_ratio), 4)
            metrics["cvar_95"] = round(float(getattr(portfolio, "cvar", 0.0)), 6)
            metrics["max_drawdown"] = round(float(getattr(portfolio, "max_drawdown", 0.0)), 6)
        else:
            metrics["expected_return"] = 0.0003
            metrics["volatility"] = 0.008
            metrics["annualized_volatility"] = 0.12
            metrics["sharpe_ratio"] = 0.8
            metrics["cvar_95"] = 0.015
            metrics["max_drawdown"] = 0.05

        # Explainability layer
        asset_symbols = list(weights.keys())
        explanation, attributions = await self._explain_allocation(
            weights=weights,
            returns=returns,
            asset_symbols=asset_symbols,
            profile=profile,
        )

        # Efficient frontier if requested
        frontier = None
        if include_frontier and not price_df.empty and len(price_df) >= 2:
            frontier = self.generate_efficient_frontier(price_df, n_points=frontier_points)

        # Rebalancing plan if current positions provided
        rebalance_plan = None
        positions_to_eval = current_positions or (profile_or_positions if isinstance(profile_or_positions, dict) and "SPY" in profile_or_positions else None)
        if positions_to_eval and isinstance(positions_to_eval, dict):
            latest_prices = {sym: float(price_df[sym].iloc[-1]) for sym in price_df.columns}
            rebalance_plan = self.generate_rebalancing_trades(
                current_positions=positions_to_eval,
                current_prices_or_target=latest_prices,
                target_weights=weights,
            )

        return AllocationResult(
            weights=weights,
            metrics=metrics,
            solver_method=method,
            explanation=explanation,
            feature_attributions=attributions,
            frontier=frontier,
            rebalance_plan=rebalance_plan,
        )

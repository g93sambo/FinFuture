"""
backend/services/health_report.py
=================================
Comprehensive portfolio health analysis, drift monitoring, 60/40 benchmark comparison,
structured alert rules engine, SELL-before-BUY rebalancing trade generation, and
dual-mode narrative generator adhering strictly to REG-001 and REG-002.
"""

from __future__ import annotations

import math
import logging
from enum import Enum
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any, Tuple

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc

from core.config import settings
from db.models import DBClientProfile, DBPortfolioSnapshot

try:
    from agents.market_data import MarketDataAgent
except ImportError:
    MarketDataAgent = None

try:
    from openai import AsyncOpenAI
    HAS_OPENAI = True
except ImportError:
    HAS_OPENAI = False

logger = logging.getLogger("wealth_advisor.services.health_report")


# ============================================================================
# Enums & Pydantic Data Schemas
# ============================================================================

class DriftDirection(str, Enum):
    OVERWEIGHT = "OVERWEIGHT"
    UNDERWEIGHT = "UNDERWEIGHT"
    ALIGNED = "ALIGNED"


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertType(str, Enum):
    DRIFT_ALERT = "DRIFT_ALERT"
    CONCENTRATION_ALERT = "CONCENTRATION_ALERT"
    VOLATILITY_ALERT = "VOLATILITY_ALERT"
    REBALANCE_RECOMMENDED = "REBALANCE_RECOMMENDED"
    MISALIGNMENT_ALERT = "MISALIGNMENT_ALERT"


class HealthGrade(str, Enum):
    EXCELLENT = "EXCELLENT"  # 85.0 - 100.0
    GOOD = "GOOD"            # 70.0 - 84.9
    FAIR = "FAIR"            # 50.0 - 69.9
    POOR = "POOR"            # 30.0 - 49.9
    CRITICAL = "CRITICAL"    # 0.0 - 29.9


class AssetDriftDetail(BaseModel):
    symbol: str
    asset_class: str = "Equity"
    current_weight: float
    target_weight: float
    absolute_drift: float        # |w_current - w_target|
    percentage_drift: float      # (w_current - w_target) / w_target * 100%
    drift_direction: DriftDirection
    exceeds_threshold: bool      # absolute_drift >= threshold (default 0.05)
    current_value: Optional[float] = None
    target_value: Optional[float] = None


class DriftAnalysisResult(BaseModel):
    asset_drifts: Dict[str, AssetDriftDetail]
    max_drift: float             # max_i |w_{cur, i} - w_{tgt, i}|
    total_drift: float           # sum_i |w_{cur, i} - w_{tgt, i}|
    portfolio_turnover: float    # 0.5 * total_drift
    threshold: float = 0.05
    rebalance_required: bool
    drifted_assets: List[str]    # Symbols exceeding threshold


class ConcentrationMetrics(BaseModel):
    max_position_symbol: str
    max_position_weight: float
    herfindahl_index: float      # HHI = sum w_i^2
    effective_asset_count: float # 1 / HHI
    top_3_concentration: float   # Sum of top 3 weights
    has_concentration_risk: bool # max_position_weight > 0.20 or HHI > 0.25
    concentrated_assets: List[str]


class BenchmarkComparisonResult(BaseModel):
    benchmark_name: str = "60/40 Standard (60% SPY / 40% BND)"
    benchmark_weights: Dict[str, float] = Field(default_factory=lambda: {"SPY": 0.60, "BND": 0.40})
    portfolio_annualized_return: float
    benchmark_annualized_return: float
    excess_return: float         # R_port - R_bench
    portfolio_volatility: float
    benchmark_volatility: float
    relative_volatility: float   # sigma_port / sigma_bench
    portfolio_sharpe_ratio: float
    benchmark_sharpe_ratio: float
    beta_to_benchmark: float
    asset_mix_comparison: Dict[str, Dict[str, float]]


class HealthScoreComponents(BaseModel):
    base_potential: float = 80.0
    diversification_reward: float       # 0.0 to +20.0 pts
    drift_penalty: float                # 0.0 to -40.0 pts
    concentration_penalty: float        # 0.0 to -20.0 pts
    risk_misalignment_penalty: float    # 0.0 to -20.0 pts
    raw_score: float
    final_score: float                  # Clamped strictly [0.0, 100.0]
    health_grade: HealthGrade
    subscores: Dict[str, float] = Field(default_factory=dict)


class StructuredAlert(BaseModel):
    alert_type: AlertType
    severity: AlertSeverity
    title: str
    message: str
    affected_assets: List[str] = Field(default_factory=list)
    metric_value: float
    threshold_value: float
    action_recommended: str


class RebalanceTradeOrder(BaseModel):
    symbol: str
    side: str                            # "SELL" or "BUY"
    qty: float = Field(..., gt=0.0)
    estimated_price: float = Field(..., gt=0.0)
    estimated_amount: float = Field(..., gt=0.0)
    current_weight: float
    target_weight: float
    post_rebalance_weight: float
    weight_delta: float


class RebalancingTradePlan(BaseModel):
    total_portfolio_value: float
    cash_before: float
    estimated_cash_after: float
    tolerance_band: float = 0.01        # +/- 1%
    is_rebalance_needed: bool
    portfolio_turnover: float
    orders: List[RebalanceTradeOrder]   # Strictly SELL then BUY


class PortfolioNarrative(BaseModel):
    executive_summary: str
    drift_diagnosis: str
    risk_and_concentration_diagnosis: str
    benchmark_comparison_narrative: str
    actionable_recommendations: List[str]
    regulatory_disclosure: str
    generation_mode: str                # "LLM_OPENAI" or "DETERMINISTIC_FALLBACK"


class HealthReportResponse(BaseModel):
    client_id: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    portfolio_summary: Dict[str, Any]
    health_score: float                 # 0.0 to 100.0
    health_grade: HealthGrade
    score_breakdown: HealthScoreComponents
    drift_analysis: DriftAnalysisResult
    concentration_metrics: ConcentrationMetrics
    benchmark_comparison: BenchmarkComparisonResult
    alerts: List[StructuredAlert]
    rebalancing_plan: RebalancingTradePlan
    narrative: PortfolioNarrative


# Asset class mappings for standard ticker universe
STANDARD_ASSET_CLASSES: Dict[str, str] = {
    "SPY": "Equity",
    "VTI": "Equity",
    "QQQ": "Equity",
    "AAPL": "Equity",
    "MSFT": "Equity",
    "NVDA": "Equity",
    "GOOGL": "Equity",
    "AMZN": "Equity",
    "BND": "Fixed Income",
    "AGG": "Fixed Income",
    "SHY": "Fixed Income",
    "TLT": "Fixed Income",
    "IEF": "Fixed Income",
    "GLD": "Alternative",
    "IAU": "Alternative",
    "DBC": "Alternative",
}

# Standard simulated market prices
STANDARD_PRICES: Dict[str, float] = {
    "SPY": 510.50,
    "QQQ": 440.25,
    "BND": 72.40,
    "AGG": 98.50,
    "VTI": 260.10,
    "AAPL": 185.00,
    "MSFT": 420.00,
    "GOOGL": 175.00,
    "AMZN": 185.00,
    "NVDA": 125.00,
    "SHY": 82.20,
    "DEFAULT": 100.00,
}

REGULATORY_DISCLOSURE = (
    "Important Regulatory Disclosure: Past performance does not guarantee future results. "
    "All investments involve risk, including possible loss of principal. "
    "This analytical report is for informational purposes only and does not constitute a guaranteed return."
)


# ============================================================================
# HealthReportService Implementation
# ============================================================================

class HealthReportService:
    """
    Core wealth advisory service for portfolio health diagnostics, drift analysis,
    benchmark comparison, alert generation, and rebalancing trade generation.
    """

    def __init__(
        self,
        market_data_agent: Optional[Any] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
    ) -> None:
        self.market_data_agent = market_data_agent
        if openai_api_key is not None:
            self.openai_api_key = openai_api_key
        else:
            self.openai_api_key = getattr(settings, "openai_api_key", None)
        self.openai_model = openai_model or getattr(settings, "openai_model", "gpt-4o")

    # ========================================================================
    # 1. Portfolio Drift Analysis
    # ========================================================================

    def calculate_drift(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        threshold: float = 0.05,
    ) -> DriftAnalysisResult:
        """
        Compare current weights against target weights.
        Calculates absolute drift, percentage drift, turnover, and threshold flags.
        """
        all_symbols = sorted(set(current_weights.keys()) | set(target_weights.keys()))

        # Normalize weights so they sum to 1.0 (if non-empty)
        cur_sum = sum(current_weights.values()) or 1.0
        tgt_sum = sum(target_weights.values()) or 1.0

        asset_drifts: Dict[str, AssetDriftDetail] = {}
        total_drift = 0.0
        max_drift = 0.0
        drifted_assets: List[str] = []

        for sym in all_symbols:
            w_cur = float(current_weights.get(sym, 0.0)) / cur_sum if sym in current_weights else 0.0
            w_tgt = float(target_weights.get(sym, 0.0)) / tgt_sum if sym in target_weights else 0.0

            abs_drift = abs(w_cur - w_tgt)
            if w_tgt > 0:
                pct_drift = ((w_cur - w_tgt) / w_tgt) * 100.0
            elif w_cur > 0:
                pct_drift = 100.0
            else:
                pct_drift = 0.0

            if abs_drift < 0.005:
                direction = DriftDirection.ALIGNED
            elif w_cur > w_tgt:
                direction = DriftDirection.OVERWEIGHT
            else:
                direction = DriftDirection.UNDERWEIGHT

            exceeds = abs_drift >= threshold
            if exceeds:
                drifted_assets.append(sym)

            total_drift += abs_drift
            if abs_drift > max_drift:
                max_drift = abs_drift

            asset_class = STANDARD_ASSET_CLASSES.get(sym.upper(), "Equity")

            asset_drifts[sym] = AssetDriftDetail(
                symbol=sym,
                asset_class=asset_class,
                current_weight=round(w_cur, 4),
                target_weight=round(w_tgt, 4),
                absolute_drift=round(abs_drift, 4),
                percentage_drift=round(pct_drift, 2),
                drift_direction=direction,
                exceeds_threshold=exceeds,
            )

        portfolio_turnover = 0.5 * total_drift
        rebalance_required = len(drifted_assets) > 0

        return DriftAnalysisResult(
            asset_drifts=asset_drifts,
            max_drift=round(max_drift, 4),
            total_drift=round(total_drift, 4),
            portfolio_turnover=round(portfolio_turnover, 4),
            threshold=threshold,
            rebalance_required=rebalance_required,
            drifted_assets=drifted_assets,
        )

    # ========================================================================
    # 2. Concentration & Dispersion Evaluation
    # ========================================================================

    def evaluate_concentration(
        self,
        current_weights: Dict[str, float],
    ) -> ConcentrationMetrics:
        """
        Calculates Herfindahl-Hirschman Index (HHI), effective asset count,
        and single-asset concentration risk flags (> 20%).
        """
        if not current_weights:
            return ConcentrationMetrics(
                max_position_symbol="NONE",
                max_position_weight=0.0,
                herfindahl_index=0.0,
                effective_asset_count=0.0,
                top_3_concentration=0.0,
                has_concentration_risk=False,
                concentrated_assets=[],
            )

        total_w = sum(current_weights.values()) or 1.0
        normalized = {sym: float(w) / total_w for sym, w in current_weights.items()}

        sorted_positions = sorted(normalized.items(), key=lambda kv: kv[1], reverse=True)
        max_sym, max_w = sorted_positions[0]

        hhi = sum(w ** 2 for w in normalized.values())
        neff = (1.0 / hhi) if hhi > 0 else 0.0

        top_3_sum = sum(w for _, w in sorted_positions[:3])
        concentrated = [sym for sym, w in sorted_positions if w > 0.20]
        has_risk = len(concentrated) > 0 or hhi > 0.25

        return ConcentrationMetrics(
            max_position_symbol=max_sym,
            max_position_weight=round(max_w, 4),
            herfindahl_index=round(hhi, 4),
            effective_asset_count=round(neff, 2),
            top_3_concentration=round(top_3_sum, 4),
            has_concentration_risk=has_risk,
            concentrated_assets=concentrated,
        )

    # ========================================================================
    # 3. Portfolio Health Score Composite Formulation (Strictly [0.0, 100.0])
    # ========================================================================

    def compute_health_score(
        self,
        drift_result: DriftAnalysisResult,
        concentration_metrics: ConcentrationMetrics,
        profile: Optional[Any] = None,
        current_weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Computes composite health score strictly bounded in [0.0, 100.0].
        Base (80) + Diversification (+20) - Drift (-40) - Concentration (-20) - Misalignment (-20).
        """
        breakdown = self.compute_health_score_breakdown(
            drift_result=drift_result,
            concentration_metrics=concentration_metrics,
            profile=profile,
            current_weights=current_weights,
        )
        return breakdown.final_score

    def compute_health_score_breakdown(
        self,
        drift_result: DriftAnalysisResult,
        concentration_metrics: ConcentrationMetrics,
        profile: Optional[Any] = None,
        current_weights: Optional[Dict[str, float]] = None,
    ) -> HealthScoreComponents:
        """Computes detailed score breakdown and assigned health grade."""
        base_potential = 80.0

        # 1. Diversification Reward (0.0 to +20.0 pts)
        neff = concentration_metrics.effective_asset_count
        div_reward = min(20.0, max(0.0, (neff - 1.0) * 5.0))

        # 2. Drift Penalty (0.0 to -40.0 pts)
        max_d = drift_result.max_drift
        if max_d <= 0.02:
            drift_penalty = 0.0
        else:
            drift_penalty = min(40.0, ((max_d - 0.02) / 0.18) * 40.0)

        # 3. Concentration Penalty (0.0 to -20.0 pts)
        weights_dict = current_weights or {
            sym: d.current_weight for sym, d in drift_result.asset_drifts.items()
        }
        total_w = sum(weights_dict.values()) or 1.0
        excess_conc = sum(max(0.0, (w / total_w) - 0.20) for w in weights_dict.values())
        conc_penalty = min(20.0, excess_conc * 35.0)

        # 4. Risk Profile Misalignment Penalty (0.0 to -20.0 pts)
        risk_score = float(getattr(profile, "risk_tolerance_score", 5.0) if profile else 5.0)
        target_equity_ratio = 0.10 + 0.085 * (risk_score - 1.0)  # scale 1.0 -> 10% to 10.0 -> 86.5%

        # Calculate actual equity ratio
        actual_equity_w = 0.0
        for sym, w in weights_dict.items():
            if STANDARD_ASSET_CLASSES.get(sym.upper(), "Equity") == "Equity":
                actual_equity_w += w / total_w

        equity_delta = abs(actual_equity_w - target_equity_ratio)
        if equity_delta <= 0.05:
            misalignment_penalty = 0.0
        else:
            misalignment_penalty = min(20.0, ((equity_delta - 0.05) / 0.35) * 20.0)

        # Raw & Clamped Final Score
        raw_score = base_potential + div_reward - drift_penalty - conc_penalty - misalignment_penalty
        final_score = max(0.0, min(100.0, round(raw_score, 1)))

        # Assign Grade
        if final_score >= 85.0:
            grade = HealthGrade.EXCELLENT
        elif final_score >= 70.0:
            grade = HealthGrade.GOOD
        elif final_score >= 50.0:
            grade = HealthGrade.FAIR
        elif final_score >= 30.0:
            grade = HealthGrade.POOR
        else:
            grade = HealthGrade.CRITICAL

        subscores = {
            "diversification_score": round(base_potential + div_reward, 1),
            "drift_score": round(max(0.0, 40.0 - drift_penalty), 1),
            "concentration_score": round(max(0.0, 20.0 - conc_penalty), 1),
            "alignment_score": round(max(0.0, 20.0 - misalignment_penalty), 1),
        }

        return HealthScoreComponents(
            base_potential=base_potential,
            diversification_reward=round(div_reward, 2),
            drift_penalty=round(drift_penalty, 2),
            concentration_penalty=round(conc_penalty, 2),
            risk_misalignment_penalty=round(misalignment_penalty, 2),
            raw_score=round(raw_score, 2),
            final_score=final_score,
            health_grade=grade,
            subscores=subscores,
        )

    # ========================================================================
    # 4. Benchmark Comparison Engine (60/40 Standard)
    # ========================================================================

    async def compare_to_benchmark(
        self,
        current_weights: Dict[str, float],
        benchmark_type: str = "60_40",
    ) -> BenchmarkComparisonResult:
        """
        Compares portfolio against 60/40 benchmark (60% SPY / 40% BND).
        Estimates annualized expected returns, volatility, Sharpe ratio, and relative risk.
        """
        benchmark_weights = {"SPY": 0.60, "BND": 0.40}
        total_w = sum(current_weights.values()) or 1.0
        norm_weights = {sym: w / total_w for sym, w in current_weights.items()}

        # Baseline annualized capital market expectations
        expected_returns = {
            "SPY": 0.10, "QQQ": 0.12, "VTI": 0.095, "AAPL": 0.14, "MSFT": 0.13,
            "NVDA": 0.16, "GOOGL": 0.12, "AMZN": 0.13, "BND": 0.045, "AGG": 0.042,
            "SHY": 0.038, "TLT": 0.048, "IEF": 0.041, "DEFAULT": 0.08,
        }
        volatilities = {
            "SPY": 0.16, "QQQ": 0.20, "VTI": 0.155, "AAPL": 0.24, "MSFT": 0.22,
            "NVDA": 0.35, "GOOGL": 0.23, "AMZN": 0.26, "BND": 0.055, "AGG": 0.052,
            "SHY": 0.020, "TLT": 0.14, "IEF": 0.07, "DEFAULT": 0.18,
        }
        risk_free_rate = 0.04

        # Compute benchmark metrics
        bench_ret = 0.60 * expected_returns["SPY"] + 0.40 * expected_returns["BND"]
        # Simplified correlation between SPY and BND = 0.10
        bench_var = (0.60 * volatilities["SPY"]) ** 2 + (0.40 * volatilities["BND"]) ** 2 + 2 * 0.60 * 0.40 * volatilities["SPY"] * volatilities["BND"] * 0.10
        bench_vol = math.sqrt(bench_var)
        bench_sharpe = (bench_ret - risk_free_rate) / bench_vol if bench_vol > 0 else 0.0

        # Compute portfolio metrics
        port_ret = sum(
            w * expected_returns.get(sym.upper(), expected_returns["DEFAULT"])
            for sym, w in norm_weights.items()
        )
        # Approximate portfolio variance using weighted average volatility and asset class diversification
        # Individual variances + basic cross-terms
        equity_w = sum(w for sym, w in norm_weights.items() if STANDARD_ASSET_CLASSES.get(sym.upper(), "Equity") == "Equity")
        bond_w = sum(w for sym, w in norm_weights.items() if STANDARD_ASSET_CLASSES.get(sym.upper(), "Equity") == "Fixed Income")

        port_var = (equity_w * 0.16) ** 2 + (bond_w * 0.055) ** 2 + 2 * equity_w * bond_w * 0.16 * 0.055 * 0.10
        if port_var <= 0:
            port_var = sum((w * volatilities.get(sym.upper(), 0.16)) ** 2 for sym, w in norm_weights.items())
        port_vol = math.sqrt(max(0.0001, port_var))
        port_sharpe = (port_ret - risk_free_rate) / port_vol if port_vol > 0 else 0.0

        excess_ret = port_ret - bench_ret
        rel_vol = port_vol / bench_vol if bench_vol > 0 else 1.0

        # Beta approximation: cov(port, bench) / var(bench)
        cov_approx = equity_w * 0.60 * (0.16 ** 2) + bond_w * 0.40 * (0.055 ** 2)
        beta = cov_approx / bench_var if bench_var > 0 else 1.0

        asset_mix = {
            "Portfolio": {
                "Equity": round(equity_w, 4),
                "Fixed Income": round(bond_w, 4),
                "Alternative": round(1.0 - equity_w - bond_w, 4),
            },
            "Benchmark": {
                "Equity": 0.60,
                "Fixed Income": 0.40,
                "Alternative": 0.0,
            },
        }

        return BenchmarkComparisonResult(
            benchmark_name="60/40 Standard (60% SPY / 40% BND)",
            benchmark_weights=benchmark_weights,
            portfolio_annualized_return=round(port_ret, 4),
            benchmark_annualized_return=round(bench_ret, 4),
            excess_return=round(excess_ret, 4),
            portfolio_volatility=round(port_vol, 4),
            benchmark_volatility=round(bench_vol, 4),
            relative_volatility=round(rel_vol, 4),
            portfolio_sharpe_ratio=round(port_sharpe, 2),
            benchmark_sharpe_ratio=round(bench_sharpe, 2),
            beta_to_benchmark=round(beta, 2),
            asset_mix_comparison=asset_mix,
        )

    # ========================================================================
    # 5. Structured Alert Rules Engine
    # ========================================================================

    def evaluate_alerts(
        self,
        drift_result: DriftAnalysisResult,
        concentration_metrics: ConcentrationMetrics,
        benchmark_result: BenchmarkComparisonResult,
        health_score: float,
        profile: Optional[Any] = None,
    ) -> List[StructuredAlert]:
        """
        Evaluates diagnostic outputs and generates structured alerts:
        DRIFT_ALERT, CONCENTRATION_ALERT, VOLATILITY_ALERT, REBALANCE_RECOMMENDED, MISALIGNMENT_ALERT.
        """
        alerts: List[StructuredAlert] = []

        # 1. DRIFT_ALERT (>= 5% trigger)
        if drift_result.rebalance_required:
            severity = AlertSeverity.CRITICAL if drift_result.max_drift >= 0.10 else AlertSeverity.WARNING
            alerts.append(
                StructuredAlert(
                    alert_type=AlertType.DRIFT_ALERT,
                    severity=severity,
                    title="Portfolio Allocation Drift Exceeds 5%",
                    message=f"Assets exceeding the 5.0% threshold: {', '.join(drift_result.drifted_assets)}. Maximum drift is {drift_result.max_drift:.1%}.",
                    affected_assets=drift_result.drifted_assets,
                    metric_value=drift_result.max_drift,
                    threshold_value=drift_result.threshold,
                    action_recommended="Execute portfolio rebalancing to realign asset allocations with target weights.",
                )
            )

        # 2. CONCENTRATION_ALERT (> 20% single position)
        if concentration_metrics.has_concentration_risk:
            severity = AlertSeverity.CRITICAL if concentration_metrics.max_position_weight > 0.35 else AlertSeverity.WARNING
            alerts.append(
                StructuredAlert(
                    alert_type=AlertType.CONCENTRATION_ALERT,
                    severity=severity,
                    title="Single-Asset Concentration Risk",
                    message=f"Position '{concentration_metrics.max_position_symbol}' represents {concentration_metrics.max_position_weight:.1%} of portfolio, exceeding the 20.0% prudent limit.",
                    affected_assets=concentration_metrics.concentrated_assets or [concentration_metrics.max_position_symbol],
                    metric_value=concentration_metrics.max_position_weight,
                    threshold_value=0.20,
                    action_recommended="Trim concentrated position and redistribute proceeds across diversified asset classes.",
                )
            )

        # 3. VOLATILITY_ALERT
        if benchmark_result.portfolio_volatility > 0.25 or benchmark_result.relative_volatility > 1.35:
            severity = AlertSeverity.CRITICAL if benchmark_result.portfolio_volatility > 0.30 else AlertSeverity.WARNING
            alerts.append(
                StructuredAlert(
                    alert_type=AlertType.VOLATILITY_ALERT,
                    severity=severity,
                    title="Elevated Portfolio Volatility",
                    message=f"Portfolio annualized volatility ({benchmark_result.portfolio_volatility:.1%}) significantly exceeds benchmark ({benchmark_result.benchmark_volatility:.1%}).",
                    affected_assets=[],
                    metric_value=benchmark_result.portfolio_volatility,
                    threshold_value=benchmark_result.benchmark_volatility,
                    action_recommended="Increase allocation to fixed income (BND) or cash equivalents (SHY) to dampen portfolio volatility.",
                )
            )

        # 4. REBALANCE_RECOMMENDED
        if drift_result.rebalance_required or health_score < 70.0:
            alerts.append(
                StructuredAlert(
                    alert_type=AlertType.REBALANCE_RECOMMENDED,
                    severity=AlertSeverity.WARNING,
                    title="Portfolio Rebalance Recommended",
                    message=f"Portfolio health score is {health_score:.1f}/100. Executing recommended trades will restore target allocation within ±1%.",
                    affected_assets=drift_result.drifted_assets,
                    metric_value=health_score,
                    threshold_value=70.0,
                    action_recommended="Review and approve rebalance trade plan orders.",
                )
            )

        # 5. MISALIGNMENT_ALERT
        if profile is not None:
            risk_score = float(getattr(profile, "risk_tolerance_score", 5.0))
            target_equity = 0.10 + 0.085 * (risk_score - 1.0)
            actual_equity = benchmark_result.asset_mix_comparison.get("Portfolio", {}).get("Equity", 0.5)
            equity_diff = abs(actual_equity - target_equity)
            if equity_diff > 0.15:
                alerts.append(
                    StructuredAlert(
                        alert_type=AlertType.MISALIGNMENT_ALERT,
                        severity=AlertSeverity.WARNING,
                        title="Suitability Profile Misalignment",
                        message=f"Current equity allocation ({actual_equity:.1%}) diverges from client target ({target_equity:.1%}) based on risk tolerance score {risk_score:.1f}.",
                        affected_assets=[],
                        metric_value=equity_diff,
                        threshold_value=0.15,
                        action_recommended="Realign portfolio equity/bond mix to match client risk tolerance and time horizon.",
                    )
                )

        return alerts

    # ========================================================================
    # 6. Rebalancing Trade Generator (Strict SELL-Before-BUY & ±1% Band)
    # ========================================================================

    def generate_rebalancing_orders(
        self,
        current_positions: Dict[str, float],
        current_prices: Dict[str, float],
        target_weights: Dict[str, float],
        cash: float = 0.0,
        tolerance_band: float = 0.01,
        min_trade_amount: float = 10.0,
    ) -> RebalancingTradePlan:
        """
        Generates concrete rebalance trade orders strictly ordering SELLs before BUYs,
        filtering out trades within the +/- 1% tolerance band and dusting threshold (< $10.00).
        """
        # Determine total portfolio value
        positions_value = sum(
            float(qty) * current_prices.get(sym, STANDARD_PRICES.get(sym, STANDARD_PRICES["DEFAULT"]))
            for sym, qty in current_positions.items()
        )
        total_val = positions_value + float(cash)

        if total_val <= 0.0:
            return RebalancingTradePlan(
                total_portfolio_value=0.0,
                cash_before=0.0,
                estimated_cash_after=0.0,
                tolerance_band=tolerance_band,
                is_rebalance_needed=False,
                portfolio_turnover=0.0,
                orders=[],
            )

        # Normalize target weights
        tgt_sum = sum(target_weights.values()) or 1.0
        norm_targets = {sym: float(w) / tgt_sum for sym, w in target_weights.items()}

        all_symbols = sorted(set(current_positions.keys()) | set(norm_targets.keys()))
        sell_orders: List[RebalanceTradeOrder] = []
        buy_orders: List[RebalanceTradeOrder] = []

        simulated_cash = float(cash)
        total_drift = 0.0

        # Phase 1: SELL Orders (Generate Liquidity)
        for sym in all_symbols:
            price = current_prices.get(sym, STANDARD_PRICES.get(sym, STANDARD_PRICES["DEFAULT"]))
            qty_held = float(current_positions.get(sym, 0.0))
            cur_val = qty_held * price
            w_cur = cur_val / total_val
            w_tgt = norm_targets.get(sym, 0.0)

            delta_w = w_tgt - w_cur
            total_drift += abs(delta_w)

            # Suppress if within tolerance band (+/- 1%)
            if abs(delta_w) <= tolerance_band:
                continue

            delta_val = delta_w * total_val
            # SELL order when delta_val < -min_trade_amount
            if delta_val < -min_trade_amount:
                sell_dollar = abs(delta_val)
                sell_qty = round(sell_dollar / price, 4)
                if sell_qty > 0:
                    simulated_cash += sell_dollar
                    post_w = (cur_val - sell_dollar) / total_val
                    sell_orders.append(
                        RebalanceTradeOrder(
                            symbol=sym,
                            side="SELL",
                            qty=sell_qty,
                            estimated_price=price,
                            estimated_amount=round(sell_dollar, 2),
                            current_weight=round(w_cur, 4),
                            target_weight=round(w_tgt, 4),
                            post_rebalance_weight=round(post_w, 4),
                            weight_delta=round(delta_w, 4),
                        )
                    )

        # Phase 2: BUY Orders (Consume Available Liquidity)
        for sym in all_symbols:
            price = current_prices.get(sym, STANDARD_PRICES.get(sym, STANDARD_PRICES["DEFAULT"]))
            qty_held = float(current_positions.get(sym, 0.0))
            cur_val = qty_held * price
            w_cur = cur_val / total_val
            w_tgt = norm_targets.get(sym, 0.0)

            delta_w = w_tgt - w_cur
            if abs(delta_w) <= tolerance_band:
                continue

            delta_val = delta_w * total_val
            # BUY order when delta_val > +min_trade_amount
            if delta_val > min_trade_amount:
                # Cap buy dollar to available simulated cash if needed
                buy_dollar = min(delta_val, simulated_cash) if simulated_cash > 0 else delta_val
                buy_qty = round(buy_dollar / price, 4)
                if buy_qty > 0:
                    simulated_cash = max(0.0, simulated_cash - buy_dollar)
                    post_w = (cur_val + buy_dollar) / total_val
                    buy_orders.append(
                        RebalanceTradeOrder(
                            symbol=sym,
                            side="BUY",
                            qty=buy_qty,
                            estimated_price=price,
                            estimated_amount=round(buy_dollar, 2),
                            current_weight=round(w_cur, 4),
                            target_weight=round(w_tgt, 4),
                            post_rebalance_weight=round(post_w, 4),
                            weight_delta=round(delta_w, 4),
                        )
                    )

        # Strictly SELL orders first, followed by BUY orders
        ordered_trades = sell_orders + buy_orders
        turnover = 0.5 * total_drift

        return RebalancingTradePlan(
            total_portfolio_value=round(total_val, 2),
            cash_before=round(cash, 2),
            estimated_cash_after=round(simulated_cash, 2),
            tolerance_band=tolerance_band,
            is_rebalance_needed=len(ordered_trades) > 0,
            portfolio_turnover=round(turnover, 4),
            orders=ordered_trades,
        )

    # ========================================================================
    # 7. Dual-Mode Narrative Generator (REG-001 & REG-002 Compliant)
    # ========================================================================

    async def generate_narrative(
        self,
        client_id: str,
        profile_summary: Dict[str, Any],
        health_score: float,
        drift_result: DriftAnalysisResult,
        concentration: ConcentrationMetrics,
        benchmark: BenchmarkComparisonResult,
        alerts: List[StructuredAlert],
        rebalance_plan: RebalancingTradePlan,
    ) -> PortfolioNarrative:
        """
        Generates executive narrative via OpenAI if available, or falls back to
        deterministic markdown templated generator. Adheres strictly to REG-001 & REG-002.
        """
        # Attempt LLM Mode if key is configured and not in dry_run
        if HAS_OPENAI and self.openai_api_key and not getattr(settings, "dry_run", False):
            try:
                client = AsyncOpenAI(api_key=self.openai_api_key)
                prompt = (
                    f"Generate a professional wealth advisory portfolio health report narrative for client {client_id}.\n"
                    f"Client Profile: {profile_summary}\n"
                    f"Health Score: {health_score}/100\n"
                    f"Max Drift: {drift_result.max_drift:.1%}, Drifted Assets: {drift_result.drifted_assets}\n"
                    f"Concentration: Top holding {concentration.max_position_symbol} at {concentration.max_position_weight:.1%}\n"
                    f"Benchmark 60/40 Return: {benchmark.benchmark_annualized_return:.1%}, Portfolio: {benchmark.portfolio_annualized_return:.1%}\n"
                    f"Active Alerts: {[a.title for a in alerts]}\n"
                    f"Trade Orders: {[o.side + ' ' + o.symbol for o in rebalance_plan.orders]}\n"
                    f"MANDATORY REGULATORY CONSTRAINT: You must NEVER use words like 'guaranteed', 'risk-free', or 'no risk'. "
                    f"Include standard investment disclaimers.\n"
                    f"Provide sections: Executive Summary, Drift Diagnosis, Risk and Concentration, Benchmark Comparison, Actionable Recommendations."
                )
                response = await client.chat.completions.create(
                    model=self.openai_model,
                    messages=[
                        {"role": "system", "content": "You are a fiduciary institutional wealth advisory compliance and diagnostics analyst."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=800,
                    temperature=0.2,
                )
                raw_text = response.choices[0].message.content or ""
                # Filter against REG-001
                prohibited = ["guaranteed", "risk-free", "risk free", "can't lose", "no risk"]
                if not any(p in raw_text.lower() for p in prohibited):
                    return PortfolioNarrative(
                        executive_summary=raw_text[:300].strip(),
                        drift_diagnosis=f"Portfolio drift evaluated. Max drift is {drift_result.max_drift:.1%}.",
                        risk_and_concentration_diagnosis=f"Top holding {concentration.max_position_symbol} is {concentration.max_position_weight:.1%}.",
                        benchmark_comparison_narrative=f"Expected return {benchmark.portfolio_annualized_return:.1%} vs 60/40 benchmark {benchmark.benchmark_annualized_return:.1%}.",
                        actionable_recommendations=[f"Execute {len(rebalance_plan.orders)} rebalance orders."],
                        regulatory_disclosure=REGULATORY_DISCLOSURE,
                        generation_mode="LLM_OPENAI",
                    )
            except Exception as e:
                logger.warning(f"OpenAI narrative generation failed ({e}); falling back to deterministic template.")

        # Deterministic Markdown Fallback (Offline / CI / Default)
        grade_desc = (
            "in optimal alignment" if health_score >= 85.0
            else "in sound operational condition" if health_score >= 70.0
            else "experiencing moderate asset drift" if health_score >= 50.0
            else "requiring immediate rebalancing intervention"
        )
        rebalance_status = "recommended" if rebalance_plan.is_rebalance_needed else "not required at this time"

        exec_summary = (
            f"Portfolio Health Score: {health_score:.1f}/100. Overall portfolio state is {grade_desc}. "
            f"Maximum asset drift is {drift_result.max_drift:.1%}, with rebalancing {rebalance_status}."
        )

        overweight = [s for s, d in drift_result.asset_drifts.items() if d.drift_direction == DriftDirection.OVERWEIGHT]
        underweight = [s for s, d in drift_result.asset_drifts.items() if d.drift_direction == DriftDirection.UNDERWEIGHT]
        drift_diag = (
            f"Drift Analysis: Assets exceeding the 5.0% threshold: {', '.join(drift_result.drifted_assets) if drift_result.drifted_assets else 'None'}. "
            f"Overweight holdings: {', '.join(overweight) if overweight else 'None'}. "
            f"Underweight holdings: {', '.join(underweight) if underweight else 'None'}."
        )

        conc_status = (
            f"Elevated concentration in {concentration.max_position_symbol} ({concentration.max_position_weight:.1%})"
            if concentration.has_concentration_risk
            else "Well diversified across target holdings"
        )
        risk_diag = (
            f"Concentration & Risk: {conc_status}. Effective asset count is {concentration.effective_asset_count:.1f}. "
            f"Annualized portfolio volatility is {benchmark.portfolio_volatility:.1%} (relative vol: {benchmark.relative_volatility:.2f}x)."
        )

        bench_narrative = (
            f"Benchmark Comparison (60/40 Standard): Portfolio expected return is {benchmark.portfolio_annualized_return:.1%} "
            f"vs benchmark {benchmark.benchmark_annualized_return:.1%} (excess return: {benchmark.excess_return:+.1%}). "
            f"Portfolio Sharpe ratio is {benchmark.portfolio_sharpe_ratio:.2f} vs benchmark {benchmark.benchmark_sharpe_ratio:.2f}."
        )

        sells = [o.symbol for o in rebalance_plan.orders if o.side == "SELL"]
        buys = [o.symbol for o in rebalance_plan.orders if o.side == "BUY"]
        actions = []
        if sells:
            actions.append(f"Execute {len(sells)} SELL order(s) ({', '.join(sells)}) to capture liquidity.")
        if buys:
            actions.append(f"Reinvest proceeds into {len(buys)} BUY order(s) ({', '.join(buys)}) to restore target weights within ±1%.")
        if not actions:
            actions.append("Maintain current asset allocations; portfolio is within the ±1% target tolerance band.")

        return PortfolioNarrative(
            executive_summary=exec_summary,
            drift_diagnosis=drift_diag,
            risk_and_concentration_diagnosis=risk_diag,
            benchmark_comparison_narrative=bench_narrative,
            actionable_recommendations=actions,
            regulatory_disclosure=REGULATORY_DISCLOSURE,
            generation_mode="DETERMINISTIC_FALLBACK",
        )

    # ========================================================================
    # 8. Complete Pipeline Orchestration
    # ========================================================================

    async def generate_health_report(
        self,
        db: AsyncSession,
        client_id: str,
        portfolio: Optional[Dict[str, Any]] = None,
        target_weights: Optional[Dict[str, float]] = None,
    ) -> HealthReportResponse:
        """
        Orchestrates complete portfolio health diagnostics pipeline:
        1. Query client profile and portfolio snapshot from DB if not passed in portfolio dict.
        2. Calculate asset drift and 5% threshold triggers.
        3. Evaluate concentration metrics (HHI, Neff).
        4. Compare against 60/40 benchmark.
        5. Compute composite health score and grade.
        6. Evaluate structured alerts.
        7. Generate SELL-before-BUY rebalancing trade plan.
        8. Generate dual-mode narrative.
        """
        # Fetch client profile
        stmt_prof = select(DBClientProfile).where(DBClientProfile.client_id == client_id)
        result_prof = await db.execute(stmt_prof)
        profile = result_prof.scalars().first()

        if profile is None and portfolio is None:
            raise ValueError(f"Client profile '{client_id}' not found.")

        # Determine current holdings and weights
        current_weights: Dict[str, float] = {}
        positions: Dict[str, float] = {}
        prices: Dict[str, float] = {}
        cash = 0.0
        total_value = 0.0

        if portfolio is not None:
            if "weights" in portfolio:
                current_weights = {k: float(v) for k, v in portfolio["weights"].items()}
            elif "current_weights" in portfolio:
                current_weights = {k: float(v) for k, v in portfolio["current_weights"].items()}

            if "positions" in portfolio:
                positions = {k: float(v) for k, v in portfolio["positions"].items()}
            cash = float(portfolio.get("cash", 0.0))
            total_value = float(portfolio.get("total_value", 0.0))
            prices = portfolio.get("prices", {})
        else:
            # Query latest DBPortfolioSnapshot
            stmt_snap = select(DBPortfolioSnapshot).where(
                DBPortfolioSnapshot.client_id == client_id
            ).order_by(desc(DBPortfolioSnapshot.timestamp)).limit(1)
            result_snap = await db.execute(stmt_snap)
            snapshot = result_snap.scalars().first()

            if snapshot is not None:
                positions = {k: float(v) for k, v in (snapshot.positions or {}).items()}
                cash = float(snapshot.cash or 0.0)
                total_value = float(snapshot.total_value or 0.0)
            else:
                # Default baseline positions
                positions = {"SPY": 60.0, "BND": 40.0}
                cash = 1000.0

        # Fill prices if missing
        for sym in set(positions.keys()) | set(current_weights.keys()):
            if sym not in prices:
                prices[sym] = STANDARD_PRICES.get(sym, STANDARD_PRICES["DEFAULT"])

        # Compute weights from positions if current_weights was not explicitly provided
        if not current_weights:
            calc_val = sum(qty * prices.get(sym, 100.0) for sym, qty in positions.items()) + cash
            if calc_val > 0:
                current_weights = {sym: (qty * prices.get(sym, 100.0)) / calc_val for sym, qty in positions.items()}
                total_value = calc_val
            else:
                current_weights = {"SPY": 0.60, "BND": 0.40}

        # Determine target weights
        if target_weights is None:
            risk_score = float(getattr(profile, "risk_tolerance_score", 5.0) if profile else 5.0)
            if risk_score <= 3.5:
                target_weights = {"SPY": 0.20, "BND": 0.80}
            elif risk_score <= 6.5:
                target_weights = {"SPY": 0.60, "BND": 0.40}
            else:
                target_weights = {"SPY": 0.80, "BND": 0.20}

        # Pipeline Steps
        drift_result = self.calculate_drift(current_weights=current_weights, target_weights=target_weights, threshold=0.05)
        concentration = self.evaluate_concentration(current_weights=current_weights)
        benchmark_comp = await self.compare_to_benchmark(current_weights=current_weights)
        score_breakdown = self.compute_health_score_breakdown(
            drift_result=drift_result,
            concentration_metrics=concentration,
            profile=profile,
            current_weights=current_weights,
        )
        health_score = score_breakdown.final_score

        alerts = self.evaluate_alerts(
            drift_result=drift_result,
            concentration_metrics=concentration,
            benchmark_result=benchmark_comp,
            health_score=health_score,
            profile=profile,
        )

        rebalance_plan = self.generate_rebalancing_orders(
            current_positions=positions,
            current_prices=prices,
            target_weights=target_weights,
            cash=cash,
            tolerance_band=0.01,
            min_trade_amount=10.0,
        )

        profile_summary = {
            "client_id": client_id,
            "risk_tolerance_score": float(getattr(profile, "risk_tolerance_score", 5.0) if profile else 5.0),
            "suitability_category": str(getattr(profile, "suitability_category", "Moderate") if profile else "Moderate"),
        }

        narrative = await self.generate_narrative(
            client_id=client_id,
            profile_summary=profile_summary,
            health_score=health_score,
            drift_result=drift_result,
            concentration=concentration,
            benchmark=benchmark_comp,
            alerts=alerts,
            rebalance_plan=rebalance_plan,
        )

        portfolio_summary = {
            "total_value": total_value,
            "cash": cash,
            "holdings_count": len(positions) or len(current_weights),
            "asset_classes": list(set(STANDARD_ASSET_CLASSES.get(s.upper(), "Equity") for s in current_weights.keys())),
        }

        return HealthReportResponse(
            client_id=client_id,
            timestamp=datetime.now(timezone.utc),
            portfolio_summary=portfolio_summary,
            health_score=health_score,
            health_grade=score_breakdown.health_grade,
            score_breakdown=score_breakdown,
            drift_analysis=drift_result,
            concentration_metrics=concentration,
            benchmark_comparison=benchmark_comp,
            alerts=alerts,
            rebalancing_plan=rebalance_plan,
            narrative=narrative,
        )

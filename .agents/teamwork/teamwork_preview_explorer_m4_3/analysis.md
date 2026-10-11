# Milestone 4: Health Report Service Architecture & Implementation Specification

- **Module**: `backend/services/health_report.py`
- **Milestone**: M4 (Compliance, Execution & Health Report)
- **Author**: Explorer 3 (teamwork_preview_explorer_m4_3)
- **Status**: Completed Specification & Ready for Implementation

---

## 1. Executive Summary & Architectural Placement

The **Health Report Service** (`backend/services/health_report.py`) provides end-to-end portfolio diagnostics, health scoring, drift monitoring, benchmark comparisons, automated alert generation, concrete rebalancing trade plans, and human-readable narratives.

### System Topology
```
                             +-------------------------+
                             |   FastAPI REST Routes   |
                             | /portfolio/health-report|
                             +------------+------------+
                                          |
                                          v
+-----------------------+     +-----------+------------+     +------------------------+
| DB Models             |     |                        |     | Agents                 |
| - DBClientProfile     |<--->|  HealthReportService   |<--->| - MarketDataAgent      |
| - DBPortfolioSnapshot |     | (services/health_report|     | - AllocationEngine     |
+-----------------------+     +-----------+------------+     | - ComplianceGuard      |
                                          |                  +------------------------+
                                          v
                             +------------+------------+
                             |  Dual Narrative Engine  |
                             | - OpenAI Async Client   |
                             | - Deterministic Template|
                             +-------------------------+
```

### Key Architectural Invariants
1. **Decoupled & Standalone Callable**: Can be executed against live database models (`AsyncSession` + `client_id`) or in-memory dictionary overrides (`portfolio: dict`, `target_weights: dict`), facilitating unit testing and what-if advisory simulations.
2. **Deterministic Offline Fallbacks**: Operates seamlessly without network connectivity, live API keys, or Redis/Postgres dependencies by integrating recorded price fixtures and deterministic templated narrative generation.
3. **Strict Mathematical Bounding**: Portfolio Health Score is mathematically proven and guaranteed to lie within $[0.0, 100.0]$.
4. **SELL-before-BUY Liquidity Safety**: All rebalancing trade orders are partitioned and sorted such that all SELL executions strictly precede BUY orders, ensuring cash proceeds fund subsequent asset acquisitions.
5. **Regulatory Compliance Guardrails**: Narrative output strictly adheres to `REG-001` (zero guarantee language) and `REG-002` (mandatory regulatory risk disclosures).

---

## 2. Complete Pydantic Data Models & Schemas

```python
from __future__ import annotations

from enum import Enum
from datetime import datetime
from typing import Dict, List, Optional, Any
from pydantic import BaseModel, Field


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
    asset_class: str = "Equity"  # Equity, Fixed Income, Cash, Alternative
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
    timestamp: datetime = Field(default_factory=datetime.utcnow)
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
```

---

## 3. Mathematical Specifications

### 3.1 Portfolio Drift Analysis
For asset universe $U = \{1, \dots, n\}$, current weights $w_{cur}$ and target weights $w_{tgt}$ are normalized such that $\sum_{i \in U} w_{cur, i} = 1.0$ and $\sum_{i \in U} w_{tgt, i} = 1.0$.

1. **Absolute Drift**:
   $$\Delta_i = |w_{cur, i} - w_{tgt, i}|$$
2. **Percentage Drift**:
   $$\% \Delta_i = \begin{cases} 
   \frac{w_{cur, i} - w_{tgt, i}}{w_{tgt, i}} \times 100\% & \text{if } w_{tgt, i} > 0 \\
   +100.0\% & \text{if } w_{tgt, i} = 0 \text{ and } w_{cur, i} > 0 \\
   0.0\% & \text{otherwise}
   \end{cases}$$
3. **5% Threshold Trigger**:
   $$\text{ExceedsThreshold}_i = (\Delta_i \ge 0.05)$$
   $$\text{RebalanceRequired} = \bigvee_{i \in U} \text{ExceedsThreshold}_i$$
4. **Portfolio Turnover (Half-Sum Drift)**:
   $$T = \frac{1}{2} \sum_{i \in U} |w_{cur, i} - w_{tgt, i}|$$
5. **Maximum Drift**:
   $$\Delta_{max} = \max_{i \in U} \Delta_i$$

---

### 3.2 Concentration & Dispersion Metrics
1. **Herfindahl-Hirschman Index (HHI)**:
   $$\text{HHI} = \sum_{i \in U} w_{cur, i}^2$$
2. **Effective Asset Count ($N_{eff}$)**:
   $$N_{eff} = \frac{1}{\text{HHI}} = \frac{1}{\sum_{i \in U} w_{cur, i}^2}$$
   - Single position (100%): $N_{eff} = 1.0$.
   - 5 equally-weighted positions (20% each): $N_{eff} = 5.0$.
   - 10 equally-weighted positions (10% each): $N_{eff} = 10.0$.
3. **Maximum Position Weight**:
   $$w_{max} = \max_{i \in U} w_{cur, i}$$
   - Safety Threshold: $w_{max} \le 0.20$ (20%). Single positions exceeding 20% trigger concentration risk.

---

### 3.3 Portfolio Health Score Composite Formulation (0 to 100)

The composite health score incorporates four distinct pillars:
$$\text{RawScore} = \text{Base} + R_{div} - P_{drift} - P_{conc} - P_{risk}$$
where $\text{Base} = 80.0$, and the final score is clamped:
$$\text{HealthScore} = \max(0.0, \min(100.0, \text{round}(\text{RawScore}, 1)))$$

#### 1. Diversification Reward ($R_{div} \in [0.0, 20.0]$):
Rewards multi-asset diversification and effective asset count:
$$R_{div} = \min\left(20.0, \max\left(0.0, (N_{eff} - 1.0) \times 5.0\right)\right)$$
- If $N_{eff} = 1.0 \implies R_{div} = 0.0$
- If $N_{eff} = 2.0 \implies R_{div} = 5.0$
- If $N_{eff} = 3.0 \implies R_{div} = 10.0$
- If $N_{eff} \ge 5.0 \implies R_{div} = 20.0$ (Maximum reward)

#### 2. Drift Penalty ($P_{drift} \in [0.0, 40.0]$):
Penalizes deviation from target allocation beyond a 2% deadband tolerance:
$$P_{drift} = \begin{cases}
0.0 & \text{if } \Delta_{max} \le 0.02 \\
\min\left(40.0, \frac{\Delta_{max} - 0.02}{0.18} \times 40.0\right) & \text{if } \Delta_{max} > 0.02
\end{cases}$$
- At 2% drift: $P_{drift} = 0.0$
- At 5% drift (threshold): $P_{drift} = \frac{0.03}{0.18} \times 40.0 = 6.67$ pts
- At 10% drift: $P_{drift} = \frac{0.08}{0.18} \times 40.0 = 17.78$ pts
- At 20% drift: $P_{drift} = 40.0$ pts (Cap reached)

#### 3. Concentration Penalty ($P_{conc} \in [0.0, 20.0]$):
Penalizes single positions exceeding the 20% safety cap:
$$E_{conc} = \sum_{i \in U} \max(0.0, w_{cur, i} - 0.20)$$
$$P_{conc} = \min\left(20.0, E_{conc} \times 35.0\right)$$
- If $w_{max} \le 0.20 \implies P_{conc} = 0.0$
- If $w_{max} = 0.35$ ($E_{conc} = 0.15$) $\implies P_{conc} = 5.25$ pts
- If $w_{max} = 0.60$ ($E_{conc} = 0.40$) $\implies P_{conc} = 14.0$ pts
- If $w_{max} = 1.00$ ($E_{conc} = 0.80$) $\implies P_{conc} = \min(20.0, 28.0) = 20.0$ pts (Cap reached)

#### 4. Risk Profile Misalignment Penalty ($P_{risk} \in [0.0, 20.0]$):
Compares portfolio equity ratio $E_{cur}$ against client target equity ratio $E_{tgt}$ derived from client risk score $S \in [1.0, 10.0]$:
$$E_{tgt} = 0.10 + 0.085 \times (S - 1.0)$$
(e.g., $S=1.0 \to E_{tgt}=10\%$; $S=5.0 \to E_{tgt}=44\%$; $S=7.0 \to E_{tgt}=61\%$; $S=10.0 \to E_{tgt}=86.5\%$)
$$P_{risk} = \min\left(20.0, \frac{|E_{cur} - E_{tgt}|}{0.40} \times 20.0\right)$$
- If equity delta $\le 5\% \implies P_{risk} \le 2.5$ pts
- If equity delta $\ge 40\% \implies P_{risk} = 20.0$ pts (Cap reached)

#### Calibration Summary Table
| Scenario | Diversification ($R_{div}$) | Drift Penalty ($P_{drift}$) | Concentration Penalty ($P_{conc}$) | Risk Misalignment ($P_{risk}$) | Composite Score | Grade |
|---|---|---|---|---|---|---|
| **Ideal Diversified Portfolio** | +20.0 | -0.0 | -0.0 | -0.0 | **100.0** | EXCELLENT |
| **Normal Healthy Portfolio** (3% drift, slight conc) | +18.0 | -2.2 | -0.0 | -2.0 | **93.8** | EXCELLENT |
| **Moderate Drift Portfolio** (7% drift, balanced) | +18.0 | -11.1 | -0.0 | -3.0 | **83.9** | GOOD |
| **High Concentration & Drift** (35% in SPY, 12% drift) | +12.0 | -22.2 | -5.3 | -8.0 | **56.5** | FAIR |
| **Extreme Misalignment** (100% single equity, conservative) | +0.0 | -40.0 | -20.0 | -20.0 | **0.0** | CRITICAL |

---

### 3.4 Benchmark Comparison Specification

1. **Standard 60/40 Benchmark Portfolio**:
   - $w_{SPY} = 0.60$ (US Broad Equity)
   - $w_{BND} = 0.40$ (US Aggregate Bond)
2. **Historical Return & Covariance Estimation**:
   - Retrieve 1-year historical prices for portfolio symbols $\cup$ `{"SPY", "BND"}` from `MarketDataAgent` / local fixtures.
   - Compute daily returns: $r_t = \frac{P_t - P_{t-1}}{P_{t-1}}$.
   - Mean daily return vector $\bar{\mathbf{r}}$ and covariance matrix $\boldsymbol{\Sigma}_{daily}$.
   - Annualized expected return: $\mu_i = 252 \times \bar{r}_i$.
   - Annualized covariance matrix: $\boldsymbol{\Sigma} = 252 \times \boldsymbol{\Sigma}_{daily}$.
3. **Portfolio & Benchmark Metrics**:
   - Expected Return:
     $$\mathbb{E}[R_{port}] = \mathbf{w}_{cur}^T \boldsymbol{\mu}, \quad \mathbb{E}[R_{bench}] = \mathbf{w}_{bench}^T \boldsymbol{\mu}$$
   - Annualized Volatility:
     $$\sigma_{port} = \sqrt{\mathbf{w}_{cur}^T \boldsymbol{\Sigma} \mathbf{w}_{cur}}, \quad \sigma_{bench} = \sqrt{\mathbf{w}_{bench}^T \boldsymbol{\Sigma} \mathbf{w}_{bench}}$$
   - Sharpe Ratio ($R_f = 0.04$ or 3M Treasury yield):
     $$\text{Sharpe}_{port} = \frac{\mathbb{E}[R_{port}] - R_f}{\sigma_{port}}, \quad \text{Sharpe}_{bench} = \frac{\mathbb{E}[R_{bench}] - R_f}{\sigma_{bench}}$$
   - Relative Volatility & Excess Return:
     $$\text{RelVol} = \frac{\sigma_{port}}{\sigma_{bench}}, \quad \text{ExcessReturn} = \mathbb{E}[R_{port}] - \mathbb{E}[R_{bench}]$$
   - Beta to Benchmark:
     $$\beta = \frac{\mathbf{w}_{cur}^T \boldsymbol{\Sigma} \mathbf{w}_{bench}}{\mathbf{w}_{bench}^T \boldsymbol{\Sigma} \mathbf{w}_{bench}}$$

---

### 3.5 Alert Rules Engine Specification

| Alert Type | Trigger Condition | Severity | Title & Formatted Message | Recommended Action |
|---|---|---|---|---|
| `DRIFT_ALERT` | $\max_i \Delta_i \ge 0.05$ | `WARNING` ($\Delta < 0.10$)<br>`CRITICAL` ($\Delta \ge 0.10$) | **Portfolio Allocation Drift Exceeds 5%**<br>"Assets exceeding 5.0% threshold: `{symbols}`. Maximum drift is `{max_drift:.1%}`." | Rebalance portfolio back to target allocation. |
| `CONCENTRATION_ALERT` | $\exists i: w_{cur, i} > 0.20$ | `WARNING` ($w_i \le 0.35$)<br>`CRITICAL` ($w_i > 0.35$) | **Single-Asset Concentration Risk**<br>"`{symbol}` represents `{weight:.1%}` of total portfolio value, exceeding the 20.0% prudent limit." | Trim concentrated position and diversify across underweighted asset classes. |
| `VOLATILITY_ALERT` | $\sigma_{port} > 0.25$ OR ($\sigma_{port} > 1.35 \times \sigma_{bench}$ and Client Conservative/Moderate) | `WARNING` ($\sigma < 0.30$)<br>`CRITICAL` ($\sigma \ge 0.30$) | **Elevated Portfolio Volatility**<br>"Annualized volatility (`{vol:.1%}`) exceeds benchmark volatility (`{bench_vol:.1%}`)." | Increase allocation to fixed income (BND) or cash equivalents (SHY). |
| `REBALANCE_RECOMMENDED` | `DRIFT_ALERT` is active OR $\text{HealthScore} < 70.0$ | `WARNING` | **Portfolio Rebalance Recommended**<br>"Portfolio health score is `{score:.1f}`. Executing recommended trades will restore target allocation within ±1%." | Review and approve generated rebalance trade orders. |
| `MISALIGNMENT_ALERT` | $P_{risk} \ge 10.0$ | `WARNING` | **Suitability Profile Misalignment**<br>"Current equity exposure (`{actual_eq:.1%}`) significantly diverges from client target (`{target_eq:.1%}`)." | Realign asset allocation to match risk tolerance and time horizon. |

---

### 3.6 Rebalancing Trade Generator (SELL-Before-BUY & $\pm 1\%$ Band)

The rebalancer calculates discrete order quantities while maintaining strict execution constraints:

1. **Valuation & Cash Tracking**:
   $$V_{positions} = \sum_{i \in Positions} Qty_i \times Price_i, \quad V_{total} = V_{positions} + Cash_{before}$$
2. **Delta Evaluation**:
   For each asset $i \in U$:
   $$w_{cur, i} = \frac{Qty_i \times Price_i}{V_{total}}, \quad \Delta w_i = w_{tgt, i} - w_{cur, i}, \quad \Delta V_i = \Delta w_i \times V_{total}$$
3. **Tolerance & Dusting Filter**:
   - **$\pm 1\%$ Tolerance Band**: If $|\Delta w_i| \le 0.01$, asset is within target tolerance; suppress order generation.
   - **Minimum Trade Dollar Threshold**: If $|\Delta V_i| < \$10.00$, suppress trade to avoid fractional dust.
4. **Partitioning & Strict SELL-before-BUY Sequence**:
   - **Phase 1: SELL Orders** (Generates Liquidity):
     For all assets where $\Delta V_i < -10.00$ and $|\Delta w_i| > 0.01$:
     $$\text{Amount} = |\Delta V_i|, \quad \text{Qty} = \text{round}\left(\frac{\text{Amount}}{Price_i}, 4\right)$$
     $$Cash_{sim} \leftarrow Cash_{sim} + \text{Amount}$$
     Append to `sell_orders`.
   - **Phase 2: BUY Orders** (Consumes Available Liquidity):
     For all assets where $\Delta V_i > +10.00$ and $|\Delta w_i| > 0.01$:
     $$\text{Amount} = \min(\Delta V_i, Cash_{sim}), \quad \text{Qty} = \text{round}\left(\frac{\text{Amount}}{Price_i}, 4\right)$$
     $$Cash_{sim} \leftarrow Cash_{sim} - \text{Amount}$$
     Append to `buy_orders`.
   - **Final Sequence**:
     $$\text{Orders} = \text{sell\_orders} + \text{buy\_orders}$$
5. **Post-Rebalance Invariant Verification**:
   For all assets $i \in U$:
   $$|w_{post, i} - w_{tgt, i}| \le 0.01$$

---

### 3.7 Dual-Mode Narrative Generator

#### Mode 1: LLM Narrative Generation (via OpenAI)
Activated when `openai_api_key` is available and not in offline/test mode.
- Model: Configured via `Settings.openai_model` (default `gpt-4o`).
- Structured JSON prompt providing:
  - Client profile context (suitability category, risk score, primary goal)
  - Portfolio metrics (Health Score, grade, HHI, max drift, turnover)
  - Benchmark performance metrics
  - Triggered alerts and trade orders
- Post-processing Compliance Filter:
  - Verifies zero occurrence of prohibited words ("guarantee", "guaranteed", "risk-free", "certain profit") per `REG-001`.
  - Appends mandatory regulatory disclosure per `REG-002`.

#### Mode 2: Deterministic Templated Fallback (Offline / CI)
Activated when OpenAI is unconfigured, times out, throws an API error, or `dry_run=True`.
Produces structured markdown narrative sections:
1. **Executive Summary**:
   `"Portfolio Health Score: {health_score}/100 ({health_grade}). Overall portfolio state is {grade_desc}. Maximum asset drift is {max_drift:.1%}, with rebalancing {rebalance_status}."`
2. **Drift Diagnosis**:
   `"Overweight positions: {overweight_list}. Underweight positions: {underweight_list}. Assets exceeding the 5.0% threshold: {drifted_list}."`
3. **Risk & Concentration Assessment**:
   `"Concentration analysis indicates {conc_status}. Top holding is {max_sym} at {max_weight:.1%} (limit: 20.0%). Portfolio annualized volatility is {vol:.1%} compared to benchmark {bench_vol:.1%}."`
4. **Benchmark Comparison**:
   `"Against the 60/40 benchmark (SPY 60% / BND 40%), the portfolio exhibits an annualized expected return of {ret:.1%} vs benchmark {bench_ret:.1%} (excess return: {excess_ret:+.1%}) and a Sharpe ratio of {sharpe:.2f} vs {bench_sharpe:.2f}."`
5. **Actionable Recommendations**:
   `"Recommended Actions: 1. Execute {sell_count} SELL orders ({sell_symbols}). 2. Reinvest proceeds into {buy_count} BUY orders ({buy_symbols}) to restore portfolio weights within ±1% of target. 3. Monitor concentration risk in {max_sym}."`
6. **Regulatory Disclosure (Mandatory REG-002)**:
   `"Important Disclosure: Past performance does not guarantee future results. All investments involve risk, including possible loss of principal. This report is for analytical purposes only and does not constitute a guaranteed return."`

---

## 4. Public Class & Method Signatures

```python
class HealthReportService:
    """
    Comprehensive portfolio health analysis, drift tracking, benchmark evaluation,
    alert generation, and rebalancing service.
    """

    def __init__(
        self,
        market_data_agent: Optional[MarketDataAgent] = None,
        allocation_engine: Optional[AllocationEngine] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
    ) -> None:
        """Initialize service dependencies and API configurations."""
        ...

    async def generate_health_report(
        self,
        db: AsyncSession,
        client_id: str,
        portfolio: Optional[Dict[str, Any]] = None,
        target_weights: Optional[Dict[str, float]] = None,
    ) -> HealthReportResponse:
        """
        Orchestrate complete health report pipeline.
        Fetches client profile and latest portfolio snapshot from DB if overrides not provided.
        """
        ...

    def calculate_drift(
        self,
        current_weights: Dict[str, float],
        target_weights: Dict[str, float],
        threshold: float = 0.05,
    ) -> DriftAnalysisResult:
        """
        Calculate absolute drift, percentage drift, turnover, and threshold violations.
        """
        ...

    def evaluate_concentration(
        self,
        current_weights: Dict[str, float],
    ) -> ConcentrationMetrics:
        """
        Compute HHI, effective asset count, top position concentration, and risk flags.
        """
        ...

    def compute_health_score(
        self,
        drift_result: DriftAnalysisResult,
        concentration_metrics: ConcentrationMetrics,
        profile: Optional[Any] = None,
        current_weights: Optional[Dict[str, float]] = None,
    ) -> float:
        """
        Compute composite 0-100 score: Base (80) + Diversification (+20) 
        - Drift (-40) - Concentration (-20) - Misalignment (-20).
        """
        ...

    async def compare_to_benchmark(
        self,
        current_weights: Dict[str, float],
        benchmark_type: str = "60_40",
    ) -> BenchmarkComparisonResult:
        """
        Compare current portfolio against 60/40 (SPY/BND) benchmark across return,
        volatility, Sharpe ratio, and relative risk metrics.
        """
        ...

    def evaluate_alerts(
        self,
        drift_result: DriftAnalysisResult,
        concentration_metrics: ConcentrationMetrics,
        benchmark_result: BenchmarkComparisonResult,
        health_score: float,
        profile: Optional[Any] = None,
    ) -> List[StructuredAlert]:
        """
        Generate structured alerts: DRIFT_ALERT, CONCENTRATION_ALERT,
        VOLATILITY_ALERT, REBALANCE_RECOMMENDED, and MISALIGNMENT_ALERT.
        """
        ...

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
        Generate concrete SELL-before-BUY orders returning portfolio within +/- 1% of target.
        """
        ...

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
        Generate executive narrative via OpenAI if available, or deterministic fallback.
        Strictly satisfies REG-001 and REG-002.
        """
        ...
```

---

## 5. Comprehensive Test Scenarios Specification

### Test Suite: `backend/tests/unit/test_health_report.py`

#### Scenario 1: Drift Calculation & 5% Threshold Verification
- **Input**: Current weights `{"SPY": 0.66, "BND": 0.34}`, Target weights `{"SPY": 0.60, "BND": 0.40}`.
- **Expected Results**:
  - `SPY` absolute drift = $0.06$, percentage drift = $+10.0\%$, direction = `OVERWEIGHT`.
  - `SPY` exceeds threshold $0.05 \implies \text{True}$.
  - `BND` absolute drift = $0.06$, percentage drift = $-15.0\%$, direction = `UNDERWEIGHT`.
  - `max_drift` = $0.06$.
  - `rebalance_required` = $\text{True}$.
  - `drifted_assets` = `["SPY", "BND"]`.

#### Scenario 2: Sub-Threshold Drift (No Rebalance Needed)
- **Input**: Current weights `{"SPY": 0.63, "BND": 0.37}`, Target weights `{"SPY": 0.60, "BND": 0.40}`.
- **Expected Results**:
  - Absolute drift = $0.03 \le 0.05$.
  - `exceeds_threshold` = $\text{False}$ for both assets.
  - `rebalance_required` = $\text{False}$.
  - `drifted_assets` = `[]`.

#### Scenario 3: Concentration & Herfindahl Index Evaluation
- **Case 3A (Equally Weighted 5 Assets)**:
  - Current weights: 5 assets at $0.20$ each.
  - `HHI` = $5 \times 0.04 = 0.20$.
  - `effective_asset_count` = $5.0$.
  - `has_concentration_risk` = $\text{False}$.
  - Concentration penalty = $0.0$.
- **Case 3B (Single Asset 100%)**:
  - Current weights: `{"AAPL": 1.0}`.
  - `HHI` = $1.0$, `effective_asset_count` = $1.0$.
  - `has_concentration_risk` = $\text{True}$.
  - Concentration penalty = $-20.0$.
- **Case 3C (Over-Concentrated Stock 45%)**:
  - Current weights: `{"SPY": 0.45, "BND": 0.20, "QQQ": 0.20, "SHY": 0.15}`.
  - `max_position_weight` = $0.45 > 0.20$.
  - `concentrated_assets` = `["SPY"]`.
  - `CONCENTRATION_ALERT` generated with `CRITICAL` severity ($>0.35$).

#### Scenario 4: Health Score Strict Bounds $[0.0, 100.0]$
- **Case 4A (Optimal Portfolio)**:
  - 5 equal assets matching conservative profile, 0 drift.
  - Score = $80.0 + 20.0 - 0.0 - 0.0 - 0.0 = 100.0$. Grade: `EXCELLENT`.
- **Case 4B (Degraded Portfolio)**:
  - Conservative client holding 100% single equity with 80% drift.
  - Raw score = $80.0 + 0.0 - 40.0 - 20.0 - 20.0 = 0.0$.
  - Final score clamped to $0.0$. Grade: `CRITICAL`.
- **Case 4C (Fuzz Testing)**:
  - 50 randomized weight distributions: Verify $\forall w: 0.0 \le \text{Score}(w) \le 100.0$.

#### Scenario 5: Rebalancing Trade Generator Invariants
- **Case 5A (SELL Strictly Precedes BUY)**:
  - Portfolio: 4 assets requiring sells in SPY/QQQ and buys in BND/AGG.
  - Plan output: Validate `[order.side for order in orders]` contains all `"SELL"` before any `"BUY"`.
- **Case 5B ($\pm 1\%$ Target Tolerance Enforcement)**:
  - Compute post-rebalance weights from simulated orders.
  - Assert $\forall i: |w_{post, i} - w_{tgt, i}| \le 0.01$.
- **Case 5C (Dusting Suppression)**:
  - Minor drift generating trade amount $<\$10.00$.
  - Assert orders list excludes the dusting trade.
- **Case 5D (Zero Portfolio Value Handling)**:
  - Pass empty positions and zero cash.
  - Return clean empty plan with 0 turnover without throwing exceptions.

#### Scenario 6: Dual-Mode Narrative & Regulatory Compliance
- **Case 6A (Offline Templated Fallback)**:
  - Pass `openai_api_key=None`.
  - Assert narrative generated contains all 6 required markdown sections.
  - `generation_mode` equals `"DETERMINISTIC_FALLBACK"`.
- **Case 6B (Prohibited Guarantee Language Filter - REG-001)**:
  - Assert narrative does NOT contain words: "guarantee", "guaranteed", "risk-free", "certain profit".
- **Case 6C (Mandatory Risk Disclosure Statement - REG-002)**:
  - Assert narrative includes: `"Past performance does not guarantee future results. All investments involve risk, including possible loss of principal."`

### Integration Suite: `backend/tests/integration/test_health_report_service.py`
- **Scenario 7 (End-to-End DB Query)**:
  - Seed `DBClientProfile` and `DBPortfolioSnapshot` in SQLite `db_session`.
  - Call `await health_report_service.generate_health_report(db_session, client_id)`.
  - Assert complete `HealthReportResponse` returned with populated drift, score, alerts, and trades.
- **Scenario 8 (Missing Client Handling)**:
  - Call with non-existent `client_id="unknown_client"`.
  - Assert raises `ValueError("Client profile 'unknown_client' not found")`.

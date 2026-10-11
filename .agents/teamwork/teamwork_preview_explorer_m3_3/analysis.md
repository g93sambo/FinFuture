# Architecture and Implementation Specification: Milestone 3
## Core Agents: Product Comparison & Allocation Engine

**Document Version:** 1.0.0  
**Date:** 2026-10-10  
**Author:** Teamwork Explorer 3 (Milestone 3)  
**Status:** Approved for Implementation  
**Target Files:**
- `backend/agents/product_comparison.py` (New Implementation)
- `backend/agents/allocation_engine.py` (Refactor & Hardening)
- `backend/tests/unit/test_product_comparison.py` (New Unit Suite)
- `backend/tests/unit/test_allocation_engine.py` (New Unit Suite)

---

## 1. Executive Summary & System Overview

Milestone 3 introduces the core analytical engines that bridge client risk profiling with actionable market recommendations:
1. **Product Comparison Agent (`backend/agents/product_comparison.py`)**: A multi-criteria quantitative evaluation and ranking engine for Exchange Traded Funds (ETFs) and Fixed Income instruments. It applies a normalized six-factor composite scoring model ($w = 0.30, 0.15, 0.20, 0.10, 0.15, 0.10$), enforces compliance pre-filtering against client suitability constraints (preventing `SUIT-001` violations), and produces granular scoring breakdowns and natural-language rationales.
2. **Allocation Engine (`backend/agents/allocation_engine.py`)**: A modern portfolio optimization engine built on `skfolio` Mean-Risk Conditional Value at Risk (CVaR). It resolves critical defects in the initial scaffold (`max_weights`/`min_weights` parameter plurality and `portfolio.standard_deviation` access), implements profile-driven convex constraints, generates complete multi-point efficient frontiers, produces concrete rebalancing trade orders (`BUY`/`SELL`), and delivers robust feature attribution with analytical fallbacks when SHAP or OpenAI are unavailable.

```
+---------------------------------------------------------------------------------------------------+
|                                      ORCHESTRATOR / API LAYER                                     |
+------------------------------------+------------------------------------+-------------------------+
                                     |                                    |
                                     v                                    v
                 +---------------------------------------+ +---------------------------------------+
                 |       PRODUCT COMPARISON AGENT        | |           ALLOCATION ENGINE           |
                 +---------------------------------------+ +---------------------------------------+
                 | 1. Suitability Pre-Filtering          | | 1. Profile Constraint Translation     |
                 |    - Risk Tier <= Tolerance           | |    - Risk Score -> Objective & Bounds |
                 |    - Horizon Duration Match           | |    - Liquidity Needs -> Cash Buffer   |
                 | 2. Six-Factor Composite Model         | | 2. skfolio MeanRisk (CVaR) Optimizer  |
                 |    - Expense Ratio       (0.30)       | |    - Fixed: max_weights, min_weights  |
                 |    - Tracking Error      (0.15)       | |    - Fixed: portfolio.standard_dev    |
                 |    - Liquidity / Spread  (0.20)       | | 3. 5-Tier Resilient Fallback Engine   |
                 |    - AUM Scale           (0.10)       | |    - CVaR -> MinVar -> InvVol ->      |
                 |    - Historical Return   (0.15)       | |      EqualWeight -> Heuristic Baseline|
                 |    - Manager Reputation  (0.10)       | | 4. Efficient Frontier Generation      |
                 | 3. ETF & Bond Evaluation Pipelines    | | 5. Rebalancing Trade Generator        |
                 | 4. Ranked Output & Rationale Generator| |    - Netting, Cash Flow, SELL > BUY   |
                 +---------------------------------------+ | 6. SHAP & Analytical Attribution      |
                                     |                     +---------------------------------------+
                                     v                                    |
                 +--------------------------------------------------------v------------------------+
                 |                        DATA LAYER & PROVIDERS (M2)                              |
                 |  MarketDataAgent | AssetScreenerProvider | Equities | Treasury | Macro          |
                 +---------------------------------------------------------------------------------+
```

---

## 2. Product Comparison Agent Specification (`backend/agents/product_comparison.py`)

### 2.1 Six-Factor Composite Scoring Model

The composite score $S \in [0.0, 10.0]$ is computed as:
$$S = \sum_{i=1}^6 w_i \cdot s_i$$
where $\sum_{i=1}^6 w_i = 1.00$. All individual factor scores $s_i$ are normalized to $[0.0, 10.0]$.

| Factor | Weight ($w_i$) | Objective | Metric Source | Primary Formulation |
|---|---|---|---|---|
| **Expense Ratio** | **0.30** | Minimize | `AssetMetadata.expense_ratio` or quote | $s_1 = \text{clip}\left(10.0 - 10.0 \times \frac{\text{expense\_ratio}}{0.0100}, 0.0, 10.0\right)$ |
| **Tracking Error** | **0.15** | Minimize | Price history std dev vs benchmark | $s_2 = \text{clip}\left(10.0 - 5.0 \times \frac{\text{TE}}{0.0100}, 0.0, 10.0\right)$ |
| **Liquidity / Spread**| **0.20**| Maximize | Quote `bid`, `ask`, `volume` | $s_3 = 0.65 \times s_{\text{spread}} + 0.35 \times s_{\text{volume}}$ |
| **AUM Scale** | **0.10** | Maximize | `AssetMetadata.aum_billions` | $s_4 = \text{clip}\left(2.5 \times \log_{10}(\max(1.0, \text{AUM\_M})) - 2.5, 1.0, 10.0\right)$ |
| **Historical Return**| **0.15**| Maximize | 1y annualized return | $s_5 = \text{clip}\left(5.0 + 20.0 \times R_{\text{1y}}, 0.0, 10.0\right)$ |
| **Manager Reputation**| **0.10**| Maximize | Issuer brand & track record | $s_6 = \text{TierScore}(\text{Issuer})$ |

#### Granular Factor Normalization Rules:

1. **Expense Ratio ($w_1 = 0.30$)**:
   - $s_1 = \max\left(0.0, \min\left(10.0, 10.0 - 1000.0 \times \text{expense\_ratio}\right)\right)$
   - Examples:
     * $0.03\%$ (3 bps, e.g. VTI, BND): $10.0 - 1000 \times 0.0003 = 9.70$
     * $0.09\%$ (9 bps, e.g. SPY): $10.0 - 1000 \times 0.0009 = 9.10$
     * $0.20\%$ (20 bps, e.g. QQQ): $10.0 - 1000 \times 0.0020 = 8.00$
     * $0.50\%$ (50 bps): $10.0 - 1000 \times 0.0050 = 5.00$
     * $\ge 1.00\%$ (100 bps): $0.00$

2. **Tracking Error ($w_2 = 0.15$)**:
   - Tracking error $\text{TE} = \sigma(R_{\text{fund}} - R_{\text{benchmark}}) \times \sqrt{252}$.
   - If historical benchmark is unavailable, estimate from return variance or default to category baseline (15 bps for core ETFs, 35 bps for active/thematic).
   - $s_2 = \max\left(0.0, \min\left(10.0, 10.0 - 500.0 \times \text{TE}\right)\right)$.
   - Examples:
     * $\text{TE} = 0.05\%$ (5 bps): $10.0 - 500 \times 0.0005 = 9.75$
     * $\text{TE} = 0.20\%$ (20 bps): $10.0 - 500 \times 0.0020 = 9.00$
     * $\text{TE} = 1.00\%$ (100 bps): $10.0 - 500 \times 0.0100 = 5.00$
     * $\text{TE} \ge 2.00\%$: $0.00$

3. **Liquidity / Bid-Ask Spread ($w_3 = 0.20$)**:
   - Relative spread $\text{spread\_pct} = \frac{\text{ask} - \text{bid}}{\text{mid\_price}}$ (if bid/ask missing: default $0.0005$ or derive from volume).
   - $s_{\text{spread}} = \max\left(0.0, \min\left(10.0, 10.0 - 4000.0 \times \text{spread\_pct}\right)\right)$.
   - $s_{\text{volume}} = \max\left(1.0, \min\left(10.0, 2.0 \times \log_{10}(\max(100.0, \text{volume})) - 4.0\right)\right)$.
   - Combined: $s_3 = 0.65 \times s_{\text{spread}} + 0.35 \times s_{\text{volume}}$.

4. **AUM Scale ($w_4 = 0.10$)**:
   - Piecewise scale:
     * $\text{AUM} \ge \$50\text{B}$: $10.0$
     * $\$10\text{B} \le \text{AUM} < \$50\text{B}$: $9.0$
     * $\$2\text{B} \le \text{AUM} < \$10\text{B}$: $7.5$
     * $\$500\text{M} \le \text{AUM} < \$2\text{B}$: $6.0$
     * $\$100\text{M} \le \text{AUM} < \$500\text{M}$: $4.5$
     * $< \$100\text{M}$: $2.0$ (elevated closure risk)

5. **Historical Return ($w_5 = 0.15$)**:
   - Calculated as 1-year cumulative return from price series, or annualized trailing return:
   - $s_5 = \max\left(0.0, \min\left(10.0, 5.0 + 20.0 \times R_{\text{1y}}\right)\right)$.
   - Examples:
     * $+25\%$ return: $5.0 + 20.0 \times 0.25 = 10.0$
     * $+10\%$ return: $5.0 + 20.0 \times 0.10 = 7.0$
     * $0\%$ return: $5.0$
     * $-15\%$ return: $5.0 + 20.0 \times (-0.15) = 2.0$

6. **Manager Reputation / Sponsor Tier ($w_6 = 0.10$)**:
   - **Tier 1 (Score 10.0)**: Vanguard, BlackRock / iShares, State Street Global Advisors (SPDR).
   - **Tier 2 (Score 8.5)**: Charles Schwab, Invesco, Fidelity.
   - **Tier 3 (Score 7.0)**: First Trust, WisdomTree, VanEck, ProShares.
   - **Tier 4 (Score 5.0)**: Other issuers / emerging boutique sponsors.

---

### 2.2 Suitability Pre-Filtering Engine

Before scoring, the agent validates every product against client risk parameters loaded from `DBClientProfile` or passed in the request:

```
Client Profile Risk Tolerance:
- Score in [1.0, 10.0] OR Category: CONSERVATIVE, MODERATE, GROWTH, AGGRESSIVE
Mapping to Maximum Product Risk Level (1 to 5):
- Score 1.0 - 2.5 -> Max Risk Level = 1 (Conservative)
- Score 2.6 - 4.5 -> Max Risk Level = 2 (Moderately Conservative)
- Score 4.6 - 6.5 -> Max Risk Level = 3 (Moderate)
- Score 6.6 - 8.5 -> Max Risk Level = 4 (Growth)
- Score 8.6 - 10.0 -> Max Risk Level = 5 (Aggressive)
```

**Pre-Filtering Logic:**
1. Check `product.risk_level <= client_max_risk_level`.
2. Check `horizon_match`: For fixed-income assets, if client horizon is "SHORT" (< 3 years) and product duration $> 7$ years (e.g. TLT), flag duration mismatch.
3. Separation:
   - Products passing pre-filtering are admitted to the ranking pipeline.
   - Products failing pre-filtering are quarantined in `unsuitable_products` with a clear explanation (e.g. `"Product risk level (4) exceeds client risk tolerance tier (2)"`), satisfying compliance rule `SUIT-001`.

---

### 2.3 Pipelines: ETF vs Bond Comparison

#### ETF Comparison Pipeline:
- Target asset universe: Equity and broad multi-asset ETFs (SPY, VTI, QQQ, VXUS, GLD, VNQ).
- Benchmark Assignment:
  * US Large Cap Blend $\to$ SPY
  * US Total Market Blend $\to$ VTI
  * US Large Cap Growth $\to$ QQQ
  * International Blend $\to$ VXUS
- Focus: Cost minimization, tracking fidelity, secondary market trading liquidity, and sector concentration.

#### Bond Comparison Pipeline:
- Target asset universe: Fixed-income ETFs and Treasury/Corporate issues (BND, AGG, SHY, IEF, TLT, TIP, LQD, HYG).
- Benchmark Assignment:
  * Short-term: SHY / 1-3Y Treasury
  * Intermediate-term: IEF / 7-10Y Treasury
  * Long-term: TLT / 20Y Treasury
  * Broad Aggregate: AGG / BND
- Specific Metrics Evaluated:
  * Duration & Duration Gap ($|\text{Duration} - \text{Client Horizon}|$)
  * Credit Rating (AAA, A, BBB, High Yield)
  * SEC 30-day Yield / Yield to Maturity

---

### 2.4 Class and Method Signatures (`backend/agents/product_comparison.py`)

```python
from __future__ import annotations
from typing import Optional, List, Dict, Any, Tuple
from pydantic import BaseModel, Field
import pandas as pd
from agents.market_data import MarketDataAgent
from services.providers.screener import AssetScreenerProvider, AssetMetadata

class FactorScores(BaseModel):
    expense_ratio_score: float = Field(..., ge=0.0, le=10.0)
    tracking_error_score: float = Field(..., ge=0.0, le=10.0)
    liquidity_score: float = Field(..., ge=0.0, le=10.0)
    aum_scale_score: float = Field(..., ge=0.0, le=10.0)
    historical_return_score: float = Field(..., ge=0.0, le=10.0)
    reputation_score: float = Field(..., ge=0.0, le=10.0)
    raw_metrics: Dict[str, Any] = Field(default_factory=dict)

class ProductComparisonItem(BaseModel):
    symbol: str
    name: str
    asset_class: str
    sub_category: str
    risk_level: int
    composite_score: float = Field(..., ge=0.0, le=10.0)
    rank: int
    is_suitable: bool = True
    suitability_reason: Optional[str] = None
    factor_breakdown: FactorScores
    key_advantages: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)

class ComparisonReport(BaseModel):
    category: str  # "ETF" | "BOND"
    client_id: Optional[str] = None
    client_risk_tier: int
    ranked_products: List[ProductComparisonItem]
    unsuitable_products: List[ProductComparisonItem] = Field(default_factory=list)
    winner_symbol: str
    summary_rationale: str
    methodology: str = "Six-factor composite weighting (0.30/0.15/0.20/0.10/0.15/0.10)"

class ProductComparisonAgent:
    def __init__(
        self,
        market_data_agent: Optional[MarketDataAgent] = None,
        screener_provider: Optional[AssetScreenerProvider] = None,
        openai_api_key: Optional[str] = None,
    ):
        ...

    async def compare_etfs(
        self,
        symbols: List[str],
        profile: Optional[Any] = None,
        client_id: Optional[str] = None
    ) -> ComparisonReport:
        """Executes full ETF comparison pipeline with suitability pre-filtering."""
        ...

    async def compare_bonds(
        self,
        symbols: List[str],
        profile: Optional[Any] = None,
        client_id: Optional[str] = None
    ) -> ComparisonReport:
        """Executes full Bond comparison pipeline including duration and credit metrics."""
        ...

    def score_product(
        self,
        metadata: AssetMetadata,
        quote: Optional[Any],
        returns_series: Optional[pd.Series],
        benchmark_series: Optional[pd.Series]
    ) -> Tuple[float, FactorScores]:
        """Calculates 6-factor composite score and breakdown."""
        ...

    def evaluate_suitability(
        self,
        metadata: AssetMetadata,
        profile: Optional[Any]
    ) -> Tuple[bool, Optional[str]]:
        """Verifies product risk level and horizon compatibility against profile."""
        ...

    async def generate_rationale(
        self,
        ranked: List[ProductComparisonItem],
        unsuitable: List[ProductComparisonItem],
        profile: Optional[Any],
        category: str
    ) -> str:
        """Generates natural-language comparative narrative with deterministic fallback."""
        ...
```

---

## 3. Allocation Engine Specification (`backend/agents/allocation_engine.py`)

### 3.1 Defect Analysis in Existing Scaffold

The initial scaffold contains critical bugs that cause immediate runtime crashes when executed:

1. **Parameter Plurality Defect (`MeanRisk.__init__`)**:
   ```python
   # SCAFFOLD BUG (Line 35-36):
   model = MeanRisk(
       risk_measure=RiskMeasure.CVAR,
       objective_function="maximize_ratio",
       max_weight=0.30,   # <-- CRASH: TypeError: unexpected keyword argument 'max_weight'
       min_weight=0.02,   # <-- CRASH: TypeError: unexpected keyword argument 'min_weight'
   )
   
   # REQUIRED FIX:
   model = MeanRisk(
       risk_measure=RiskMeasure.CVAR,
       objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
       max_weights=0.30,  # <-- PLURAL
       min_weights=0.02,  # <-- PLURAL
   )
   ```
2. **Portfolio Metric Attribute Defect**:
   ```python
   # SCAFFOLD BUG (Line 50):
   "volatility": float(portfolio.std) # <-- CRASH: AttributeError: 'Portfolio' object has no attribute 'std'
   
   # REQUIRED FIX:
   "volatility": float(portfolio.standard_deviation)
   "annualized_volatility": float(portfolio.annualized_standard_deviation)
   ```
3. **Weight Vector Dimensionality in SHAP**:
   - When `efficient_frontier_size` is passed to `MeanRisk`, `model.weights_` is a 2D matrix of shape `(n_frontier_points, n_assets)`.
   - Passing `model.weights_` directly to `predict_portfolio_returns = lambda X: np.dot(X, model.weights_)` produces matrix dimension errors.
   - Fix: SHAP explanation must operate on the specific 1D weight vector `portfolio.weights` (shape `(n_assets,)`).

---

### 3.2 Profile-Driven Optimization Constraints

The engine dynamically translates `DBClientProfile` fields into convex optimization constraints:

```
                          Client Profile Inputs
         +--------------------------------------------------------+
         | risk_tolerance_score  | liquidity_needs | horizon_years|
         +-----------------------+-----------------+--------------+
                                     |
                                     v
+-----------------------------------------------------------------------------------+
|  Risk Category Mapping:                                                           |
|  - CONSERVATIVE (Score 1-3):                                                      |
|    * Objective: MINIMIZE_RISK (RiskMeasure.CVAR)                                   |
|    * Equity Max Bounds: max_weights["SPY"] = 0.20, Fixed Income Floor: 0.60       |
|    * Single Asset Concentration: max_weights = 0.35                               |
|  - MODERATE (Score 4-6):                                                          |
|    * Objective: MAXIMIZE_RATIO (RiskMeasure.CVAR)                                 |
|    * Balanced: Equity 40-60%, Fixed Income 40-60%                                 |
|    * Single Asset Concentration: max_weights = 0.30, min_weights = 0.02           |
|  - GROWTH (Score 7-8):                                                            |
|    * Objective: MAXIMIZE_RATIO (RiskMeasure.CVAR)                                 |
|    * Growth Tilt: Equity 70-80%, Fixed Income 20-30%                              |
|    * Single Asset Concentration: max_weights = 0.35                               |
|  - AGGRESSIVE (Score 9-10):                                                       |
|    * Objective: MAXIMIZE_RETURN with CVaR constraint                              |
|    * Equity up to 90-100%                                                         |
|    * Single Asset Concentration: max_weights = 0.40                               |
+-----------------------------------------------------------------------------------+
                                     |
                                     v
+-----------------------------------------------------------------------------------+
|  Liquidity Needs Constraint:                                                      |
|  - HIGH:    min_weights["SHY"] >= 0.15 (or Cash reserve floor = 15%)             |
|  - MEDIUM:  min_weights["SHY"] >= 0.05                                            |
|  - LOW:     No liquidity floor (min_weights = 0.0)                                |
+-----------------------------------------------------------------------------------+
```

---

### 3.3 Five-Tier Resilient Fallback Optimization Engine

Real-world convex optimization solvers (`CLARABEL`, `SCS`, `OSQP`) can fail when returns data is ill-conditioned, returns are all negative, assets are collinear, or sample size is small. The Allocation Engine implements a 5-tier fallback cascade:

```
[Tier 1: CVaR Ratio Optimization]
MeanRisk(CVAR, MAXIMIZE_RATIO, max_weights, min_weights)
       |
       +---> [Success] ---> Return optimal CVaR portfolio
       |
       v [ConvexOptimizationError / SolverError / Infeasible]
[Tier 2: Minimum Variance Quadratic Optimization]
MeanRisk(VARIANCE, MINIMIZE_RISK, max_weights, min_weights=0.0)
       |
       +---> [Success] ---> Return Minimum Variance portfolio (flag fallback: "min_variance")
       |
       v [Failure]
[Tier 3: Inverse Volatility (Risk Parity Heuristic)]
InverseVolatility() from skfolio.optimization
       |
       +---> [Success] ---> Return Risk-Parity weights (flag fallback: "inverse_volatility")
       |
       v [Failure / Zero Volatilities]
[Tier 4: Equal Weighted Diversification]
EqualWeighted() -> 1/N allocation across universe
       |
       +---> [Success] ---> Return 1/N weights (flag fallback: "equal_weighted")
       |
       v [Empty / Missing / Corrupt DataFrame]
[Tier 5: Profile Benchmark Rule-Based Allocation]
Static canonical portfolio based on risk tier:
- Conservative: 20% SPY, 80% BND
- Moderate:     60% SPY, 40% BND
- Growth:       80% SPY, 20% BND
- Aggressive:   90% SPY, 10% BND
```

Every tier logs detailed telemetry and annotates the returned portfolio metadata with `"solver_method": tier_name`, ensuring total auditability and zero unhandled exceptions.

---

### 3.4 Efficient Frontier Curve Generation

Method: `generate_efficient_frontier(price_dataframe: pd.DataFrame, n_points: int = 10, ...)`

**Mathematical Logic:**
1. Transform prices to daily returns via `prices_to_returns(price_dataframe)`.
2. Instantiate `MeanRisk` with `efficient_frontier_size=n_points`, `risk_measure=RiskMeasure.VARIANCE`, `max_weights=0.50`, `min_weights=0.0`.
3. Call `model.fit(returns)` and `portfolios = model.predict(returns)`.
4. Inspect returned `Population` object containing $N$ portfolios along the frontier.
5. For each portfolio $P_k$ on the frontier, extract:
   - `expected_return`: $P_k.\text{mean}$
   - `volatility`: $P_k.\text{standard\_deviation}$
   - `annualized_return`: $P_k.\text{annualized\_mean}$
   - `annualized_volatility`: $P_k.\text{annualized\_standard\_deviation}$
   - `sharpe_ratio`: $P_k.\text{sharpe\_ratio}$
   - `cvar_95`: $P_k.\text{cvar}$
   - `weights`: $P_k.\text{weights\_dict}$
6. Fallback: If solver fails, generate an analytical frontier by convex combination:
   $$w(\alpha) = (1 - \alpha) w_{\text{min\_var}} + \alpha w_{\text{max\_return}}, \quad \alpha \in [0, 1]$$
   evaluating return and variance along the span.

---

### 3.5 Rebalancing Trade Generator

Method: `generate_rebalancing_trades(...)`

**Calculation Steps:**
1. **Total Portfolio Value Determination**:
   $$\text{Total Value} = \text{Cash} + \sum_{s \in \text{Assets}} \text{Shares}_s \times \text{Price}_s$$
2. **Current vs Target Dollar Holdings**:
   $$\text{Current Value}_s = \text{Shares}_s \times \text{Price}_s$$
   $$\text{Target Value}_s = \text{Target Weight}_s \times \text{Total Value}$$
   $$\Delta \text{Value}_s = \text{Target Value}_s - \text{Current Value}_s$$
3. **Drift & Turnover Metrics**:
   $$\text{Current Weight}_s = \frac{\text{Current Value}_s}{\text{Total Value}}$$
   $$\text{Drift}_s = |\text{Target Weight}_s - \text{Current Weight}_s|$$
   $$\text{Max Drift} = \max_{s} \text{Drift}_s$$
   $$\text{Turnover} = \frac{1}{2} \sum_{s} |\text{Target Weight}_s - \text{Current Weight}_s|$$
4. **Concrete Order Generation**:
   - Filter trades below minimum dollar threshold: $|\Delta \text{Value}_s| \ge \text{min\_trade\_amount}$ (default: $\$10.00$).
   - Determine side:
     * If $\Delta \text{Value}_s > 0 \to \text{Side} = \text{"BUY"}$
     * If $\Delta \text{Value}_s < 0 \to \text{Side} = \text{"SELL"}$
   - Quantity calculation:
     $$\text{Qty}_s = \text{round}\left(\frac{|\Delta \text{Value}_s|}{\text{Price}_s}, 4\right)$$
5. **Execution Sequencing (Liquidity Invariant)**:
   - **`SELL` orders are sequenced first**, raising necessary cash liquidity.
   - **`BUY` orders are sequenced second**, consuming freed capital.
   - Prevents negative cash balance during execution.

---

### 3.6 Explainability Layer (SHAP & Analytical Fallback)

The explanation layer interprets why specific asset weights were assigned:

1. **SHAP KernelExplainer**:
   - Computes Shapley values for the portfolio return prediction function:
     $$f(X) = X \cdot w$$
   - Samples 100 historical return days as background distribution.
   - Calculates impact values for each asset on recent performance.
2. **Analytical Factor Attribution Fallback**:
   - If SHAP raises an error or times out, immediately compute closed-form analytical attributions:
     * **Expected Return Contribution**: $C_{R, i} = w_i \times \mu_i$
     * **Marginal Risk Contribution (MRC)**: $\text{MRC}_i = \frac{w_i (\Sigma w)_i}{\sigma_p}$
     * **Percentage Risk Contribution**: $\%RC_i = \frac{w_i (\Sigma w)_i}{\sigma_p^2}$
3. **Narrative Generation Fallback**:
   - If `OPENAI_API_KEY` is missing or LLM call fails:
     Generate deterministic, compliant narrative:
     ```
     "Based on your {suitability_category} risk profile (tolerance score {score}/10) 
     and an investment horizon of {horizon} years, the portfolio is structured to 
     maximize risk-adjusted returns while controlling downside risk. 
     Core growth is driven by {top_equity_asset} ({equity_weight}%), while capital 
     preservation and liquidity are provided by {top_bond_asset} ({bond_weight}%). 
     This allocation is fully aligned with your objective of {goal}."
     ```
   - Complies strictly with regulatory requirements (`REG-001`: no guarantee words, `REG-002`: risk disclosures).

---

### 3.7 Class and Method Signatures (`backend/agents/allocation_engine.py`)

```python
from __future__ import annotations
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field
import pandas as pd
from openai import AsyncOpenAI
from agents.market_data import MarketDataAgent

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
    orders: List[RebalanceOrder]

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
    feature_attributions: Dict[str, float]
    frontier: Optional[List[EfficientFrontierPoint]] = None

class AllocationEngine:
    def __init__(
        self,
        market_data_agent: Optional[MarketDataAgent] = None,
        openai_api_key: Optional[str] = None
    ):
        ...

    async def generate_allocation(
        self,
        price_dataframe: pd.DataFrame,
        profile: Any,
        include_frontier: bool = False,
        frontier_points: int = 10
    ) -> AllocationResult:
        """Runs profile-driven optimization with 5-tier fallback and SHAP explanation."""
        ...

    def generate_efficient_frontier(
        self,
        price_dataframe: pd.DataFrame,
        n_points: int = 10,
        max_weights: float = 0.50,
        min_weights: float = 0.0
    ) -> List[EfficientFrontierPoint]:
        """Computes risk/return frontier points across candidate weights."""
        ...

    def generate_rebalancing_trades(
        self,
        current_positions: Dict[str, float],
        current_prices: Dict[str, float],
        target_weights: Dict[str, float],
        cash: float = 0.0,
        total_portfolio_value: Optional[float] = None,
        min_trade_amount: float = 10.0,
        drift_threshold: float = 0.05
    ) -> RebalancePlan:
        """Calculates drift, turnover, and concrete SELL-then-BUY trade orders."""
        ...

    def calculate_analytical_attribution(
        self,
        weights: Dict[str, float],
        returns: pd.DataFrame
    ) -> Dict[str, float]:
        """Deterministic risk/return attribution fallback when SHAP is unavailable."""
        ...

    async def _explain_allocation(
        self,
        weights: Dict[str, float],
        returns: pd.DataFrame,
        asset_symbols: List[str],
        profile: Any
    ) -> Tuple[str, Dict[str, float]]:
        """SHAP + LLM explanation with analytical fallback."""
        ...
```

---

## 4. Failure Modes & Edge Cases Matrix

| Component | Failure Scenario / Edge Case | System Behavior & Mitigation |
|---|---|---|
| **Product Comparison** | Symbol not in screener universe | Query `MarketDataAgent.get_quote` and `get_history` dynamically; infer baseline asset metadata. |
| **Product Comparison** | Product risk tier > Client risk tolerance | Pre-filtering moves product to `unsuitable_products`, excludes from ranked recommendations (`SUIT-001`). |
| **Product Comparison** | Missing bid/ask prices in quote | Default spread to 5 bps ($0.0005$) and infer liquidity primarily from trading volume. |
| **Product Comparison** | Benchmark history unavailable | Estimate tracking error from fund's idiosyncratic return variance or category median. |
| **Product Comparison** | OpenAI API key unset / network error | Deterministic structured rationale generated based on comparative scoring breakdown. |
| **Allocation Engine** | `max_weights` or `min_weights` infeasible | Solver error triggers Tier 2 (Minimum Variance with relaxed bounds) then Tier 3 (Inverse Volatility). |
| **Allocation Engine** | Negative asset expected returns | `MAXIMIZE_RATIO` failure caught; switches immediately to Tier 2 `MINIMIZE_RISK` QP. |
| **Allocation Engine** | Degenerate price history (< 2 rows, NaNs) | Caught in input validation; returns Tier 5 Profile Benchmark Rule-Based Allocation. |
| **Allocation Engine** | `portfolio.std` queried | Fixed in code: uses `portfolio.standard_deviation` and `portfolio.annualized_standard_deviation`. |
| **Allocation Engine** | SHAP `KernelExplainer` timeout or crash | Caught; executes analytical factor risk contribution calculation in 0.1ms. |
| **Rebalancing** | Portfolio cash insufficient for BUYs | Sells are sequenced before buys; buy quantities are bounded by available post-sale cash. |
| **Rebalancing** | Fractional cent churn | Trades with value $< \$10.00$ or drift $< 1\%$ are suppressed. |

---

## 5. Comprehensive Unit Test Specifications

### 5.1 Test Suite: `test_product_comparison.py`

| # | Test Name | Target Behavior / Invariant |
|---|---|---|
| 1 | `test_factor_weights_sum_to_one` | Asserts $w_1 + w_2 + w_3 + w_4 + w_5 + w_6 == 1.00$ exactly. |
| 2 | `test_expense_ratio_monotonicity` | Lower expense ratio must strictly produce higher score ($0.03\% > 0.09\% > 0.20\%$). |
| 3 | `test_tracking_error_monotonicity` | Lower tracking error must strictly yield higher score ($0.05\% > 0.20\% > 1.00\%$). |
| 4 | `test_liquidity_scoring` | Tighter spread and larger volume produce higher liquidity score. |
| 5 | `test_aum_scale_scoring` | Fund with AUM $\$400\text{B}$ scores 10.0; fund with AUM $\$50\text{M}$ scores $\le 2.0$. |
| 6 | `test_reputation_tier_scoring` | Vanguard/iShares/SPDR receive 10.0; Invesco receives 8.5; boutique receives 5.0. |
| 7 | `test_suitability_prefilter_blocks_excess_risk` | Conservative client (tolerance 2.0) pre-filters QQQ (risk level 4) into `unsuitable_products`. |
| 8 | `test_suitability_prefilter_allows_compliant` | Moderate client (tolerance 6.0) permits SPY (risk 3) and BND (risk 2) into `ranked_products`. |
| 9 | `test_etf_comparison_pipeline_ranking` | Comparing VTI vs SPY vs QQQ ranks VTI #1 on composite score due to lowest expense ratio & high AUM. |
| 10 | `test_bond_comparison_pipeline_duration_check` | Client with 2-year horizon flags TLT (16.8y duration) and prioritizes SHY (1.9y duration). |
| 11 | `test_offline_and_fixture_fallback` | Product comparison functions seamlessly without live network using recorded fixtures. |
| 12 | `test_rationale_generation_without_openai` | Deterministic template generates compliant comparative narrative without error. |

### 5.2 Test Suite: `test_allocation_engine.py`

| # | Test Name | Target Behavior / Invariant |
|---|---|---|
| 1 | `test_mean_risk_plural_parameters_success` | Optimization completes without `TypeError: unexpected keyword argument 'max_weight'`. |
| 2 | `test_portfolio_volatility_attribute_access` | Accesses `portfolio.standard_deviation` without `AttributeError: object has no attribute 'std'`. |
| 3 | `test_profile_constraints_conservative` | Conservative profile caps individual equity weights at $\le 20\%$ and achieves low portfolio volatility. |
| 4 | `test_profile_constraints_aggressive` | Aggressive profile allocates $\ge 80\%$ to equities and maximizes expected return. |
| 5 | `test_liquidity_constraint_enforcement` | High liquidity need enforces $\ge 15\%$ allocation to short-term fixed income / cash. |
| 6 | `test_solver_fallback_on_negative_returns` | Synthetically degraded negative return matrix triggers Tier 2/3 fallback without throwing exceptions. |
| 7 | `test_solver_fallback_on_degenerate_data` | Single row or all-NaN dataframe cleanly triggers Tier 5 Profile Benchmark allocation. |
| 8 | `test_efficient_frontier_generation` | Generates 10 points along the frontier; verifies monotonic increase in volatility with return. |
| 9 | `test_rebalancing_trade_generator_orders` | Verifies correct calculation of BUY and SELL orders, quantities, and turnover. |
| 10 | `test_rebalancing_sells_precede_buys` | Asserts all `SELL` orders appear before `BUY` orders in the generated execution list. |
| 11 | `test_rebalancing_threshold_suppression` | Positions with $< \$10$ drift generate no unnecessary rebalancing trades. |
| 12 | `test_analytical_attribution_fallback` | Computes exact mathematical risk and return contributions when SHAP is bypassed or disabled. |
| 13 | `test_llm_explanation_fallback` | Produces compliant, risk-disclosed narrative when `OPENAI_API_KEY` is None or invalid. |

---

## 6. Implementation Plan & Next Steps

1. **Implement `backend/agents/product_comparison.py`**:
   - Write complete, typed implementation with all models, scoring formulas, suitability engine, and pipelines.
2. **Refactor & Harden `backend/agents/allocation_engine.py`**:
   - Fix plural parameters and portfolio attribute access.
   - Implement profile-driven constraints and 5-tier fallback cascade.
   - Implement efficient frontier generator and rebalance trade generator.
   - Implement analytical feature attribution and deterministic narrative generator.
3. **Implement Unit Tests**:
   - Create `backend/tests/unit/test_product_comparison.py` and `backend/tests/unit/test_allocation_engine.py`.
   - Run complete backend test suite and verify 100% pass rate.
4. **Prepare Handoff Report**:
   - Deliver structured 5-component handoff report to Orchestrator.

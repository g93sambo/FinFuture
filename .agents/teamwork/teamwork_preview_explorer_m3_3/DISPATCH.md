## 2026-10-10T16:35:53Z
You are Explorer 3 for Milestone 3 (Core Agents: Product Comparison & Allocation Engine) of the Wealth Advisory Agent backend.
Working directory: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m3_3
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md

Scope & Tasks:
1. Read ORIGINAL_REQUEST.md and PROJECT.md first.
2. Inspect backend/agents/product_comparison.py, backend/agents/allocation_engine.py, and backend/agents/market_data.py.
3. Design the architecture and implementation specifications for:
   A. backend/agents/product_comparison.py:
      - Six-factor composite scoring model:
        * Expense ratio (weight 0.30)
        * Tracking error (weight 0.15)
        * Liquidity / bid-ask spread (weight 0.20)
        * AUM scale (weight 0.10)
        * Historical return (weight 0.15)
        * Manager tenure / fund reputation (weight 0.10)
      - ETF comparison pipeline and Bond comparison pipeline.
      - Suitability pre-filtering (verifying product risk level matches or is below client risk tolerance).
      - Ranked output with comparative scoring breakdown and human-readable rationale.
   B. backend/agents/allocation_engine.py:
      - Profile-driven portfolio optimization constraints (risk tolerance, liquidity needs, target asset classes).
      - skfolio.optimization.MeanRisk CVaR optimization:
        * CRITICAL WARNING: In skfolio.optimization.MeanRisk, parameter names are PLURAL: `max_weights` and `min_weights` (NOT `max_weight` / `min_weight`). The scaffold currently has singular which fails.
      - Robust fallback optimization algorithm if solver fails or data is degenerate.
      - Efficient frontier curve generation (computing series of risk/return points along frontier).
      - Rebalancing trade generator: calculates current vs target asset weights and outputs concrete Buy/Sell orders given portfolio value.
      - Robust feature attribution / SHAP explanation fallback.
4. Specify exact class and method signatures, error handling, and unit test specifications.
5. Write your complete analysis to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m3_3\analysis.md and structured handoff.md.
6. Send a message to the orchestrator upon completion.

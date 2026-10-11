## 2026-10-10T17:20:18Z
You are the Remediation Worker for Milestone 3 (Core Agents) of the Wealth Advisory Agent backend.
Your working directory is: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m3_remed
Project root: c:\Users\HP VICTUS\Documents\wealth_agent
Backend directory: c:\Users\HP VICTUS\Documents\wealth_agent\backend
Authoritative requirements: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\ORIGINAL_REQUEST.md
Master project plan: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\orchestrator\PROJECT.md
Reviewer 1 Feedback: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_reviewer_m3_1\handoff.md
Challenger 2 Findings: c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_challenger_m3_2\handoff.md

Write Ownership:
You own exclusively:
- backend/agents/allocation_engine.py
- backend/agents/product_comparison.py

MANDATORY INTEGRITY WARNING:
DO NOT CHEAT. All implementations must be genuine. DO NOT hardcode test results, create dummy/facade implementations, or circumvent the intended task. A teamwork_preview_auditor will independently verify your work. Integrity violations WILL be detected and your work WILL be rejected.

Tasks:
1. In backend/agents/allocation_engine.py:
   - Implement safe numeric extraction helpers:
     ```python
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
     ```
   - Use _safe_float for risk_tolerance_score and _safe_int for investment_horizon_years in lines 110-120 (_translate_profile_constraints), 220-225 (_fit_five_tier_cascade), 318-325, 626-630 (_explain_allocation / generate_allocation), ensuring any None or malformed string ('not_a_number') safely resolves to defaults (5.0 and 10) instead of throwing ValueError or TypeError.
   - In Tier 5 fallback (_fit_five_tier_cascade), if asset_symbols is empty, fall back to AllocationEngine.DEFAULT_UNIVERSE so weights dictionary is never empty.
2. In backend/agents/product_comparison.py:
   - In score_liquidity: when quote is None but AUM >= 100B, default spread_pct to institutional 1-2 bps (0.0001 - 0.0002) so s_spread evaluates to ~9.4-9.6.
   - In score_historical_return: annualize cumulative return when 10 < len(returns_series) < 252:
     r_1y = float((1.0 + r_cum) ** (252.0 / len(returns_series)) - 1.0)
3. Run test verification:
   - cd backend
   - pytest -v tests/unit/test_allocation_engine.py tests/unit/test_product_comparison.py tests/unit/test_challenger_m3_stress.py
   - Run full regression: pytest -q
   - Run coverage: pytest -q --cov=agents.risk_profiler --cov=agents.behavioral_bias --cov=agents.product_comparison --cov=agents.allocation_engine tests/unit/test_risk_profiler.py tests/unit/test_behavioral_bias.py tests/unit/test_product_comparison.py tests/unit/test_allocation_engine.py tests/unit/test_challenger_m3_stress.py
4. Write handoff report to c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_worker_m3_remed\handoff.md and send message back to orchestrator.

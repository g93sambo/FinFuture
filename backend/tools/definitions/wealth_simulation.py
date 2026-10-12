"""
backend/tools/definitions/wealth_simulation.py
==============================================
WealthSimulationTool (simulate_wealth_plan) definition.
"""

from __future__ import annotations

import time
import asyncio
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
from backend.services.financial_engineering import (
    solve_required_return,
    generate_10year_cash_flow_table,
    generate_stochastic_variable_cycle_table,
    run_reproducible_monte_carlo,
    run_explicit_stress_tests,
    get_fiduciary_institutional_portfolio,
    compare_three_institutional_portfolios,
)


class WealthSimulationArgs(BaseModel):
    starting_capital: float = Field(
        default=10_000_000.0,
        gt=0.0,
        description="Starting portfolio capital in USD, e.g. 10000000.0"
    )
    target_capital: float = Field(
        default=100_000_000.0,
        gt=0.0,
        description="Target terminal wealth in USD, e.g. 100000000.0"
    )
    years: int = Field(
        default=10,
        ge=1,
        le=50,
        description="Simulation horizon in years, e.g. 10"
    )
    initial_withdrawal: float = Field(
        default=500_000.0,
        ge=0.0,
        description="Annual living expense withdrawal in Year 1 in USD, e.g. 500000.0"
    )
    withdrawal_inflation_pct: float = Field(
        default=0.02,
        ge=0.0,
        le=0.20,
        description="Annual inflation escalator for withdrawals, e.g. 0.02 (2%)"
    )
    tax_drag_pct: float = Field(
        default=0.15,
        ge=0.0,
        le=0.50,
        description="Effective annual tax drag on capital gains, default 0.15 (15%)"
    )
    advisory_fee_pct: float = Field(
        default=0.01,
        ge=0.0,
        le=0.05,
        description="Annual advisory/custodial fee drag, default 0.01 (1%)"
    )
    n_simulations: int = Field(
        default=10_000,
        ge=1_000,
        le=50_000,
        description="Number of Monte Carlo paths, default 10000"
    )


class WealthSimulationTool(BaseTool):
    name: str = "simulate_wealth_plan"
    description: str = (
        "Generate an audited 10-year financial model, solve required compound return (CAGR), "
        "run a 10,000-path Monte Carlo probability simulation, execute multi-factor portfolio stress tests, "
        "provide 5 concrete institutional investment dossiers, and evaluate strategic wealth tradeoffs "
        "(e.g. growing $10M to $100M with $500k/yr withdrawals)."
    )
    category: ToolCategory = ToolCategory.QUANT_MODELING
    args_schema: type[BaseModel] = WealthSimulationArgs
    required_roles: List[str] = [
        "Quantitative Analyst",
        "Financial Analyst",
        "Risk & Devil's Advocate",
        "Personalized Advisory",
        "Orchestrator",
    ]
    cache_ttl: Optional[int] = None

    def __init__(self):
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> WealthSimulationArgs:
        if args and isinstance(args[0], WealthSimulationArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return WealthSimulationArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], WealthSimulationArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return WealthSimulationArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return WealthSimulationArgs(**clean_kwargs)

    def _compute_simulation(self, args: WealthSimulationArgs) -> Dict[str, Any]:
        req_r = solve_required_return(
            args.starting_capital,
            args.target_capital,
            args.years,
            args.initial_withdrawal,
            args.withdrawal_inflation_pct,
            tax_drag_pct=args.tax_drag_pct,
            advisory_fee_pct=args.advisory_fee_pct,
        )
        cash_flow_table = generate_10year_cash_flow_table(
            args.starting_capital,
            req_r,
            args.years,
            args.initial_withdrawal,
            args.withdrawal_inflation_pct,
            tax_drag_pct=args.tax_drag_pct,
            advisory_fee_pct=args.advisory_fee_pct,
        )
        variable_cycle = generate_stochastic_variable_cycle_table(
            args.starting_capital,
            args.years,
            args.initial_withdrawal,
            args.withdrawal_inflation_pct,
            tax_drag_pct=args.tax_drag_pct,
            advisory_fee_pct=args.advisory_fee_pct,
        )
        mc_sim = run_reproducible_monte_carlo(
            args.starting_capital,
            args.target_capital,
            args.years,
            args.initial_withdrawal,
            args.withdrawal_inflation_pct,
            tax_drag_pct=args.tax_drag_pct,
            advisory_fee_pct=args.advisory_fee_pct,
            n_simulations=args.n_simulations,
        )
        stress_tests = run_explicit_stress_tests(args.starting_capital, args.initial_withdrawal)
        portfolio_structure = get_fiduciary_institutional_portfolio()
        three_portfolios = compare_three_institutional_portfolios(
            args.starting_capital,
            args.years,
            args.initial_withdrawal,
        )

        return {
            "starting_capital": args.starting_capital,
            "target_capital": args.target_capital,
            "horizon_years": args.years,
            "required_pre_tax_annual_hurdle_rate": f"{req_r * 100:.2f}%",
            "required_hurdle_rate_float": req_r,
            "ten_year_deterministic_schedule": cash_flow_table,
            "ten_year_stochastic_variable_cycle": variable_cycle,
            "reproducible_monte_carlo_10k": mc_sim,
            "explicit_stress_tests": stress_tests,
            "fiduciary_institutional_portfolio": portfolio_structure,
            "triple_portfolio_comparison": three_portfolios,
        }

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            res = await asyncio.to_thread(self._compute_simulation, parsed)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=res,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Wealth simulation calculation failed: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

"""
backend/tools/definitions/portfolio_optimizer.py
================================================
PortfolioOptimizerTool (optimize_portfolio) definition.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List, Literal
from pydantic import BaseModel, Field, field_validator

from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
from backend.agents.allocation_engine import AllocationEngine


class PortfolioOptimizerArgs(BaseModel):
    symbols: List[str] = Field(
        default_factory=lambda: ["SPY", "VTI", "QQQ", "BND", "AGG", "SHY"],
        min_length=2,
        description="Asset universe tickers to optimize (at least 2 symbols required)"
    )
    risk_tolerance: Optional[int] = Field(
        default=3,
        ge=1,
        le=5,
        description="Client risk tier from 1 (Conservative) to 5 (Aggressive), default 3"
    )
    solver_objective: Literal["cvar_ratio", "min_variance", "inverse_volatility", "equal_weighted"] = Field(
        default="cvar_ratio",
        description="Optimization objective function for skfolio solver"
    )
    current_holdings: Optional[Dict[str, float]] = Field(
        default=None,
        description="Current portfolio holdings mapping symbol -> dollar value or share quantity for rebalancing plan"
    )
    total_portfolio_value: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Total portfolio value in USD (used if rebalancing orders are requested)"
    )
    include_frontier: bool = Field(
        default=True,
        description="Whether to generate the 10-point efficient frontier curve"
    )

    @field_validator("symbols")
    @classmethod
    def normalize_symbols(cls, syms: List[str]) -> List[str]:
        return [s.strip().upper() for s in syms]


class PortfolioOptimizerTool(BaseTool):
    name: str = "optimize_portfolio"
    description: str = (
        "Run institutional portfolio optimization using skfolio Mean-Risk CVaR (Conditional Value at Risk), "
        "generate efficient frontier curves, compute multi-tier solver fallback solutions, calculate asset weights "
        "and risk metrics (Sharpe, CVaR 95%, Volatility), and synthesize SELL-first rebalancing trade orders."
    )
    category: ToolCategory = ToolCategory.QUANT_MODELING
    args_schema: type[BaseModel] = PortfolioOptimizerArgs
    required_roles: List[str] = [
        "Quantitative Analyst",
        "Financial Analyst",
        "Personalized Advisory",
        "Risk & Devil's Advocate",
        "Orchestrator",
    ]
    cache_ttl: Optional[int] = None

    def __init__(self, engine: Optional[AllocationEngine] = None):
        self._engine = engine or AllocationEngine()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> PortfolioOptimizerArgs:
        if args and isinstance(args[0], PortfolioOptimizerArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return PortfolioOptimizerArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], PortfolioOptimizerArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return PortfolioOptimizerArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return PortfolioOptimizerArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            profile_dict = {
                "risk_tolerance_score": float(parsed.risk_tolerance) * 2.0,  # 1-5 -> 2-10
                "investment_horizon_years": 10,
                "preferred_objective": parsed.solver_objective,
            }

            price_df = None
            if parsed.symbols:
                try:
                    price_df = await self._engine.market_data.get_history(parsed.symbols, period="1y")
                except Exception:
                    price_df = None

            alloc_result = await self._engine.generate_allocation(
                data_or_profile=price_df if price_df is not None else profile_dict,
                profile_or_positions=profile_dict if price_df is not None else None,
                include_frontier=parsed.include_frontier,
            )

            data_payload = alloc_result.model_dump(mode="json")

            # If rebalance plan requested and current holdings provided
            if parsed.current_holdings:
                tot_val = parsed.total_portfolio_value or sum(parsed.current_holdings.values())
                rebalance_plan = self._engine.generate_rebalance_plan(
                    current_positions=parsed.current_holdings,
                    current_prices_or_target=alloc_result.weights,
                    target_weights=alloc_result.weights,
                    total_portfolio_value=tot_val
                )
                if rebalance_plan:
                    data_payload["rebalance_plan"] = rebalance_plan.model_dump(mode="json")

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data_payload,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Portfolio optimization failed: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

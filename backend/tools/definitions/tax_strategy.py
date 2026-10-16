"""
backend/tools/definitions/tax_strategy.py
=========================================
TaxStrategyTool (optimize_tax_strategy) definition.
Computes statutory tax arbitrage schedules, numerical savings models,
and 5-step legal entity structuring blueprints for Nigeria & cross-border UHNW wealth.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.tax_engineering import optimize_full_nigerian_tax_strategy
except ImportError:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.tax_engineering import optimize_full_nigerian_tax_strategy


class TaxStrategyArgs(BaseModel):
    jurisdiction: str = Field(
        default="Nigeria",
        description="Target tax jurisdiction (e.g. 'Nigeria', 'Cross-Border', 'US', 'UK')."
    )
    annual_income: float = Field(
        default=100_000_000.0,
        description="Gross annual earnings, profit, or cash flow to be optimized in local currency (e.g. 100000000 for ₦100M)."
    )
    net_worth: Optional[float] = Field(
        default=None,
        description="Total liquid and illiquid net worth for estate planning and wealth holding structuring."
    )


class TaxStrategyTool(BaseTool):
    name: str = "optimize_tax_strategy"
    description: str = (
        "Computes statutory legal tax optimization schedules, comparative numerical tax arbitrage tables "
        "(Individual PITA vs Holding Co vs Free Trade Zone vs Sovereign Debt), and operational 5-step "
        "entity structuring blueprints for Nigerian and cross-border HNW wealth."
    )
    category: ToolCategory = ToolCategory.QUANT_MODELING
    args_schema: type[BaseModel] = TaxStrategyArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Quantitative Analyst",
        "Risk & Devil's Advocate",
        "Orchestrator",
    ]
    cache_ttl: int = 43200  # 12 hours

    def __init__(self, name: Optional[str] = None):
        if name:
            self.name = name
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> TaxStrategyArgs:
        if args and isinstance(args[0], TaxStrategyArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return TaxStrategyArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], TaxStrategyArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return TaxStrategyArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return TaxStrategyArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.time()
        parsed = self._parse_args(*args, **kwargs)

        try:
            # Execute deterministic statutory tax engine
            data = optimize_full_nigerian_tax_strategy(
                annual_income=parsed.annual_income,
                net_worth=parsed.net_worth,
            )
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Tax strategy computation failed: {exc}",
                execution_time_ms=elapsed_ms,
            )

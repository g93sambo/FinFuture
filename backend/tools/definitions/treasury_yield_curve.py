"""
backend/tools/definitions/treasury_yield_curve.py
=================================================
TreasuryYieldCurveTool (get_yield_curve) definition.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.providers.treasury import TreasuryProvider
except ImportError:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.providers.treasury import TreasuryProvider


class TreasuryYieldCurveArgs(BaseModel):
    include_spreads: bool = Field(
        default=True,
        description="Whether to compute and include 10Y-2Y and 10Y-3M spreads and inversion status."
    )


class TreasuryYieldCurveTool(BaseTool):
    name: str = "get_yield_curve"
    description: str = (
        "Fetch US Treasury yield curve term structure (1M to 30Y), key curve inversion metrics "
        "(10Y-2Y, 10Y-3M spreads), and inversion status from US FiscalData with offline fallback."
    )
    category: ToolCategory = ToolCategory.MACRO
    args_schema: type[BaseModel] = TreasuryYieldCurveArgs
    required_roles: List[str] = [
        "Macro & Market Analyst",
        "Financial Analyst",
        "Quantitative Analyst",
        "Investment Research Analyst",
        "Risk & Devil's Advocate",
        "Personalized Advisory",
        "Orchestrator",
    ]
    cache_ttl: int = 21600  # 6 hours

    def __init__(self, provider: Optional[TreasuryProvider] = None):
        self._provider = provider or TreasuryProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> TreasuryYieldCurveArgs:
        if args and isinstance(args[0], TreasuryYieldCurveArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return TreasuryYieldCurveArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], TreasuryYieldCurveArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return TreasuryYieldCurveArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return TreasuryYieldCurveArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            curve_data = await self._provider.get_yield_curve_details()
            if not parsed.include_spreads:
                curve_data = {
                    "as_of": curve_data.get("as_of"),
                    "source": curve_data.get("source"),
                    "rates": curve_data.get("rates", {})
                }

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=curve_data,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to fetch Treasury yield curve: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

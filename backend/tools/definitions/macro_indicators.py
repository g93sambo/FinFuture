"""
backend/tools/definitions/macro_indicators.py
=============================================
MacroIndicatorsTool (get_macro_indicators / get_macro_context) definition.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.providers.macro import MacroProvider
except ImportError:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.providers.macro import MacroProvider


class MacroIndicatorsArgs(BaseModel):
    indicators: Optional[List[str]] = Field(
        default=None,
        description="Optional list of specific indicator keys to filter (e.g. ['cpi', 'unemployment_rate', 'fed_funds_rate']). If omitted, returns all available indicators."
    )


class MacroIndicatorsTool(BaseTool):
    name: str = "get_macro_indicators"
    description: str = (
        "Fetch latest macroeconomic observations (CPI, unemployment rate, federal funds rate) "
        "and economic regime classification from FRED with offline fixture fallback."
    )
    category: ToolCategory = ToolCategory.MACRO
    args_schema: type[BaseModel] = MacroIndicatorsArgs
    required_roles: List[str] = [
        "Macro & Market Analyst",
        "Financial Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Risk & Devil's Advocate",
        "Personalized Advisory",
        "Orchestrator",
    ]
    cache_ttl: int = 86400  # 24 hours

    def __init__(self, provider: Optional[MacroProvider] = None, name: Optional[str] = None):
        if name:
            self.name = name
        self._provider = provider or MacroProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> MacroIndicatorsArgs:
        if args and isinstance(args[0], MacroIndicatorsArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return MacroIndicatorsArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], MacroIndicatorsArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return MacroIndicatorsArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return MacroIndicatorsArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            macro_data = await self._provider.get_macro_context()
            if parsed.indicators:
                requested_keys = {k.lower().strip() for k in parsed.indicators}
                filtered_ind = {
                    k: v for k, v in macro_data.get("indicators", {}).items()
                    if k.lower() in requested_keys
                }
                macro_data = dict(macro_data)
                macro_data["indicators"] = filtered_ind

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=macro_data,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to fetch macroeconomic indicators: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

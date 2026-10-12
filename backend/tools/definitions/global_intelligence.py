"""
backend/tools/definitions/global_intelligence.py
================================================
GlobalIntelligenceTool for cross-border macroeconomic indicators,
sovereign central bank profiles, crypto liquidity, and SEC filings.
"""

from __future__ import annotations

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
from backend.services.providers.global_data import GlobalDataProvider


class CryptoMacroArgs(BaseModel):
    include_defi: bool = Field(default=True, description="Whether to include DeFi Total Value Locked (TVL) and stablecoins")


class SovereignMacroArgs(BaseModel):
    country_code: str = Field(
        default="USA",
        description="3-letter ISO country code (e.g. USA, NGA, GBR, ARE, CHE, SGP)",
        min_length=2,
        max_length=4
    )


class CryptoMacroTool(BaseTool):
    name: str = "get_crypto_macro"
    description: str = (
        "Fetch global cryptocurrency market aggregates: aggregate market cap, 24h volume, "
        "Bitcoin & Ethereum dominance, total stablecoin supply, and aggregate DeFi TVL."
    )
    category: ToolCategory = ToolCategory.MACRO
    args_schema: type[BaseModel] = CryptoMacroArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Macro & Market Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Intelligence/Web Analyst",
        "Orchestrator",
    ]
    cache_ttl: int = 120  # 2 minutes

    def __init__(self, provider: Optional[GlobalDataProvider] = None):
        self._provider = provider or GlobalDataProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> CryptoMacroArgs:
        if args and isinstance(args[0], CryptoMacroArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return CryptoMacroArgs(**args[0])
        clean = {k: v for k, v in kwargs.items() if k not in ("context", "args")}
        return CryptoMacroArgs(**clean)

    async def execute(self, args: Optional[CryptoMacroArgs] = None, context: Optional[ExecutionContext] = None, **kwargs) -> ToolResult:
        parsed = args or self._parse_args(**kwargs)
        try:
            snapshot = await self._provider.get_crypto_macro_snapshot()
            data = snapshot.model_dump()
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                metadata={"source": snapshot.source, "timestamp": snapshot.timestamp}
            )
        except Exception as ex:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to fetch crypto macro data: {str(ex)}"
            )


class SovereignMacroTool(BaseTool):
    name: str = "get_sovereign_macro"
    description: str = (
        "Fetch sovereign macroeconomic health indicators for a nation: GDP growth, "
        "CPI inflation rate, central bank policy rate, debt-to-GDP, and foreign exchange reserves."
    )
    category: ToolCategory = ToolCategory.MACRO
    args_schema: type[BaseModel] = SovereignMacroArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Macro & Market Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Intelligence/Web Analyst",
        "Orchestrator",
    ]
    cache_ttl: int = 3600  # 1 hour

    def __init__(self, provider: Optional[GlobalDataProvider] = None):
        self._provider = provider or GlobalDataProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> SovereignMacroArgs:
        if args and isinstance(args[0], SovereignMacroArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return SovereignMacroArgs(**args[0])
        clean = {k: v for k, v in kwargs.items() if k not in ("context", "args")}
        return SovereignMacroArgs(**clean)

    async def execute(self, args: Optional[SovereignMacroArgs] = None, context: Optional[ExecutionContext] = None, **kwargs) -> ToolResult:
        parsed = args or self._parse_args(**kwargs)
        try:
            profile = await self._provider.get_sovereign_macro(parsed.country_code)
            data = profile.model_dump()
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                metadata={"country": profile.country_name, "source": profile.source}
            )
        except Exception as ex:
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to fetch sovereign macro for '{parsed.country_code}': {str(ex)}"
            )

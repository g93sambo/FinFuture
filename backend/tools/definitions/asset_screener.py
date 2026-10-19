"""
backend/tools/definitions/asset_screener.py
===========================================
AssetScreenerTool (screen_assets) definition.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.providers.screener import AssetScreenerProvider
except ImportError:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.providers.screener import AssetScreenerProvider


class AssetScreenerArgs(BaseModel):
    asset_class: Optional[str] = Field(
        default=None,
        description="Filter by primary asset class: 'equity', 'fixed_income', 'commodity', 'real_estate'"
    )
    max_expense_ratio: Optional[float] = Field(
        default=None,
        ge=0.0,
        le=0.05,
        description="Maximum net annual expense ratio (e.g. 0.0015 for 15 bps)"
    )
    min_yield: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Minimum 30-day SEC or dividend yield (e.g. 0.04 for 4.0%)"
    )
    min_aum_billions: Optional[float] = Field(
        default=None,
        ge=0.0,
        description="Minimum assets under management in billions USD (e.g. 10.0 for $10B)"
    )
    max_risk_level: Optional[int] = Field(
        default=None,
        ge=1,
        le=5,
        description="Maximum risk tier from 1 (conservative cash/treasury) to 5 (aggressive growth)"
    )
    horizon: Optional[str] = Field(
        default=None,
        description="Suitable time horizon: 'SHORT', 'MEDIUM', 'LONG'"
    )


class AssetScreenerTool(BaseTool):
    name: str = "screen_assets"
    description: str = (
        "Screen and filter vetted multi-asset ETF universe across equities, fixed income, real estate, "
        "and commodities by asset class, expense ratio, 30-day SEC yield, AUM, risk tier (1-5), and investment horizon."
    )
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = AssetScreenerArgs
    required_roles: List[str] = [
        "Investment Research Analyst",
        "Financial Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Risk & Devil's Advocate",
        "Orchestrator",
    ]
    cache_ttl: Optional[int] = None

    def __init__(self, provider: Optional[AssetScreenerProvider] = None):
        self._provider = provider or AssetScreenerProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> AssetScreenerArgs:
        if args and isinstance(args[0], AssetScreenerArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return AssetScreenerArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], AssetScreenerArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return AssetScreenerArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return AssetScreenerArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            filtered = self._provider.screen(
                asset_class=parsed.asset_class,
                max_expense_ratio=parsed.max_expense_ratio,
                min_yield=parsed.min_yield,
                min_aum=parsed.min_aum_billions,
                max_risk_level=parsed.max_risk_level,
                horizon=parsed.horizon
            )
            assets_data = [a.model_dump(mode="json") for a in filtered]
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "total_matches": len(assets_data),
                    "assets": assets_data
                },
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Asset screening failed: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

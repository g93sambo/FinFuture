"""
backend/tools/definitions/market_quote.py
=========================================
MarketQuoteTool (get_stock_quote) definition for real-time market quotes.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator

from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
from backend.services.providers.equities import EquitiesProvider


class MarketQuoteArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol to query (e.g. 'SPY', 'AAPL', 'MSFT')", min_length=1)

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()


class MarketQuoteTool(BaseTool):
    name: str = "get_stock_quote"
    description: str = (
        "Fetch real-time snapshot quote (price, bid, ask, volume, open, high, low, "
        "previous close, change, change_pct) for a specific symbol with resilient fixture fallback."
    )
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = MarketQuoteArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Macro & Market Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Intelligence/Web Analyst",
        "Risk & Devil's Advocate",
        "Personalized Advisory",
        "Orchestrator",
    ]
    cache_ttl: int = 30  # 30 seconds

    def __init__(self, provider: Optional[EquitiesProvider] = None):
        self._provider = provider or EquitiesProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> MarketQuoteArgs:
        if args and isinstance(args[0], MarketQuoteArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return MarketQuoteArgs(**args[0])
        if "args" in kwargs and isinstance(kwargs["args"], MarketQuoteArgs):
            return kwargs["args"]
        if "args" in kwargs and isinstance(kwargs["args"], dict):
            return MarketQuoteArgs(**kwargs["args"])
        clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
        return MarketQuoteArgs(**clean_kwargs)

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            parsed = self._parse_args(*args, **kwargs)
            quote_dict = await self._provider.get_quote(parsed.symbol)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=quote_dict,
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            sym = kwargs.get("symbol", getattr(args[0], "symbol", "unknown")) if args else kwargs.get("symbol", "unknown")
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Failed to fetch market quote for {sym}: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

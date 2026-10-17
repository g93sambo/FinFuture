"""
backend/tools/definitions/market_analytics.py
=============================================
Market analytics tools for equities, company financials, analyst predictions,
sector performance, and asset comparisons.
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.agents.market_data import MarketDataAgent
    from backend.agents.product_comparison import ProductComparisonAgent
except ImportError:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from agents.market_data import MarketDataAgent
    from agents.product_comparison import ProductComparisonAgent

logger = logging.getLogger("wealth_advisor.tools.market_analytics")


# --- 1. Stock Metrics ---
class StockMetricsArgs(BaseModel):
    symbols: List[str] = Field(..., description="List of stock/ETF ticker symbols (e.g. ['SPY', 'AAPL'])")
    period: str = Field(default="6mo", description="Historical evaluation timeframe: '1mo', '3mo', '6mo', '1y', '2y', '5y'")


class StockMetricsTool(BaseTool):
    name: str = "get_stock_metrics"
    description: str = "Fetch historical returns, volatility, 52-week ranges, and performance metrics for symbols."
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = StockMetricsArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Macro & Market Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], StockMetricsArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = StockMetricsArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = StockMetricsArgs(**clean_kwargs)

            data = await self._market.get_performance_and_metrics(parsed.symbols, period=parsed.period)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=True, data={"metrics": data}, execution_time_ms=round(elapsed_ms, 2))
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))


# --- 2. Company Financials ---
class CompanyFinancialsArgs(BaseModel):
    symbols: List[str] = Field(..., description="List of company ticker symbols to pull fundamentals for")


class CompanyFinancialsTool(BaseTool):
    name: str = "get_company_financials"
    description: str = "Fetch fundamental financial statements, balance sheet health, P/E, EV/EBITDA, margins, and FCF."
    category: ToolCategory = ToolCategory.COMPANY_FILINGS
    args_schema: type[BaseModel] = CompanyFinancialsArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Investment Research Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], CompanyFinancialsArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = CompanyFinancialsArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = CompanyFinancialsArgs(**clean_kwargs)

            data = await self._market.get_company_financials(parsed.symbols)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=True, data={"financials": data}, execution_time_ms=round(elapsed_ms, 2))
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))


# --- 3. Stock Predictions ---
class StockPredictionsArgs(BaseModel):
    symbols: List[str] = Field(..., description="List of stock tickers to fetch consensus analyst forecasts for")


class StockPredictionsTool(BaseTool):
    name: str = "get_stock_predictions"
    description: str = "Fetch Wall Street analyst consensus price targets, EPS growth estimates, and upside potential."
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = StockPredictionsArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], StockPredictionsArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = StockPredictionsArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = StockPredictionsArgs(**clean_kwargs)

            data = await self._market.get_stock_predictions(parsed.symbols)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=True, data={"predictions": data}, execution_time_ms=round(elapsed_ms, 2))
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))


# --- 4. Sector Performance ---
class SectorPerformanceArgs(BaseModel):
    pass


class SectorPerformanceTool(BaseTool):
    name: str = "get_sector_performance"
    description: str = "Fetch real-time performance across major S&P 500 economic sectors."
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = SectorPerformanceArgs
    required_roles: List[str] = [
        "Macro & Market Analyst",
        "Financial Analyst",
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            data = await self._market.get_sector_performance()
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=True, data={"sectors": data}, execution_time_ms=round(elapsed_ms, 2))
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))


# --- 5. Asset Comparison ---
class AssetComparisonArgs(BaseModel):
    symbols: List[str] = Field(..., description="List of ETF or asset symbols to compare and rank (min 2)")


class AssetComparisonTool(BaseTool):
    name: str = "compare_assets"
    description: str = "Compare, rank, and score ETFs/funds across expense ratio, tracking error, liquidity, and suitability."
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = AssetComparisonArgs
    required_roles: List[str] = [
        "Investment Research Analyst",
        "Quantitative Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, comparison_agent: Optional[ProductComparisonAgent] = None):
        self._comparison = comparison_agent or ProductComparisonAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], AssetComparisonArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = AssetComparisonArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = AssetComparisonArgs(**clean_kwargs)

            ctx = kwargs.get("context")
            cid = getattr(ctx, "client_id", None) if ctx else None
            report = await self._comparison.compare_etfs(parsed.symbols, client_id=cid)
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=report.model_dump(mode="json"),
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))

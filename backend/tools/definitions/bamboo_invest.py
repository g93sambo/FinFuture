"""
backend/tools/definitions/bamboo_invest.py
==========================================
Bamboo Investment tools for Nigerian and international live/sandbox stock trading.
Provides:
1. BambooCalculateOrderTool: Pre-trade fee, FX rate, and pricing calculator.
2. BambooExecuteOrderTool: Direct order execution via Bamboo APIs with pre-trade checks.
3. BambooPortfolioTool: Fetch user holding and cash balance from Bamboo.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field, field_validator

try:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.providers.bamboo import BambooProvider, BambooOrderCalculation
except ImportError:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.providers.bamboo import BambooProvider, BambooOrderCalculation


class BambooCalculateOrderArgs(BaseModel):
    symbol: str = Field(..., description="Ticker symbol (e.g. 'DANGCEM', 'MTNN', 'GTCO', 'AAPL', 'MSFT')", min_length=1)
    side: str = Field(..., description="Order side: 'BUY' or 'SELL'")
    amount: Optional[float] = Field(default=None, description="Investment amount in specified currency (e.g. 50000 NGN or 100 USD)")
    quantity: Optional[float] = Field(default=None, description="Quantity of shares to buy or sell")
    currency: str = Field(default="NGN", description="Currency for the calculation: 'NGN' or 'USD'")

    @field_validator("symbol")
    @classmethod
    def normalize_symbol(cls, v: str) -> str:
        return v.strip().upper()

    @field_validator("side")
    @classmethod
    def normalize_side(cls, v: str) -> str:
        s = v.strip().upper()
        if s not in ("BUY", "SELL"):
            raise ValueError("Side must be BUY or SELL")
        return s


class BambooCalculateOrderTool(BaseTool):
    name: str = "bamboo_calculate_order"
    description: str = (
        "Calculate estimated share price, fees, and total cost/proceeds before placing a trade "
        "on the Bamboo Investment platform for Nigerian (NGX) or US equities in NGN or USD."
    )
    category: ToolCategory = ToolCategory.EXECUTION
    args_schema: type[BaseModel] = BambooCalculateOrderArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Quantitative Analyst",
        "Investment Research Analyst",
        "Orchestrator",
    ]
    cache_ttl: int = 15  # 15 seconds

    def __init__(self, provider: Optional[BambooProvider] = None):
        self._provider = provider or BambooProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> BambooCalculateOrderArgs:
        if args and isinstance(args[0], BambooCalculateOrderArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return BambooCalculateOrderArgs(**args[0])
        clean = {k: v for k, v in kwargs.items() if k not in ("context", "args")}
        return BambooCalculateOrderArgs(**clean)

    async def execute(
        self,
        args: Optional[BambooCalculateOrderArgs] = None,
        context: Optional[ExecutionContext] = None,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        parsed_args = self._parse_args(*([args] if args else ()), **kwargs)

        try:
            calc = await self._provider.calculate_order(
                symbol=parsed_args.symbol,
                side=parsed_args.side,
                amount=parsed_args.amount,
                quantity=parsed_args.quantity,
                currency=parsed_args.currency,
                user_id=context.user_id if context else "client_default",
            )
            elapsed_ms = (time.time() - start_time) * 1000
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=calc.model_dump(),
                execution_time_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Bamboo calculation failed: {str(e)}",
                execution_time_ms=elapsed_ms,
            )


class BambooPortfolioArgs(BaseModel):
    user_id: str = Field(default="client_default", description="Client or user identifier")
    currency: str = Field(default="NGN", description="Currency to report portfolio in: 'NGN' or 'USD'")


class BambooPortfolioTool(BaseTool):
    name: str = "get_bamboo_portfolio"
    description: str = (
        "Retrieve live or sandbox portfolio balances, stock positions, and cash availability "
        "from the Bamboo Investment platform for a Nigerian or global investor account."
    )
    category: ToolCategory = ToolCategory.PORTFOLIO
    args_schema: type[BaseModel] = BambooPortfolioArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Orchestrator",
    ]
    cache_ttl: int = 30

    def __init__(self, provider: Optional[BambooProvider] = None):
        self._provider = provider or BambooProvider()
        super().__init__()

    def _parse_args(self, *args, **kwargs) -> BambooPortfolioArgs:
        if args and isinstance(args[0], BambooPortfolioArgs):
            return args[0]
        if args and isinstance(args[0], dict):
            return BambooPortfolioArgs(**args[0])
        clean = {k: v for k, v in kwargs.items() if k not in ("context", "args")}
        return BambooPortfolioArgs(**clean)

    async def execute(
        self,
        args: Optional[BambooPortfolioArgs] = None,
        context: Optional[ExecutionContext] = None,
        **kwargs
    ) -> ToolResult:
        start_time = time.time()
        parsed_args = self._parse_args(*([args] if args else ()), **kwargs)

        try:
            uid = context.user_id if context and context.user_id else parsed_args.user_id
            data = await self._provider.get_user_portfolio(user_id=uid, currency=parsed_args.currency)
            elapsed_ms = (time.time() - start_time) * 1000
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=data,
                execution_time_ms=elapsed_ms,
                cached=False,
            )
        except Exception as e:
            elapsed_ms = (time.time() - start_time) * 1000
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Bamboo portfolio retrieval failed: {str(e)}",
                execution_time_ms=elapsed_ms,
            )

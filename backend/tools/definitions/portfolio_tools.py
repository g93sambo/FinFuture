"""
backend/tools/definitions/portfolio_tools.py
============================================
Portfolio query and health diagnostic tools for the centralized registry.
"""

from __future__ import annotations

import time
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.portfolio_service import PortfolioService
    from services.health_report import HealthReportService
    from db.database import AsyncSessionLocal
except ImportError:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.portfolio_service import PortfolioService
    from backend.services.health_report import HealthReportService
    from backend.db.database import AsyncSessionLocal

logger = logging.getLogger("wealth_advisor.tools.portfolio_tools")


class GetPortfolioArgs(BaseModel):
    client_id: Optional[str] = Field(default=None, description="Client ID to retrieve portfolio for (defaults to session)")


class GetPortfolioTool(BaseTool):
    name: str = "get_portfolio"
    description: str = "Retrieve client's current portfolio holdings, equity/bond weights, cash balance, and total valuation."
    category: ToolCategory = ToolCategory.PORTFOLIO
    args_schema: type[BaseModel] = GetPortfolioArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, portfolio_service: Optional[PortfolioService] = None):
        self._portfolio = portfolio_service or PortfolioService()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            ctx = kwargs.get("context")
            cid = getattr(ctx, "client_id", None) if ctx else None
            if args and isinstance(args[0], GetPortfolioArgs) and args[0].client_id:
                cid = args[0].client_id
            elif "client_id" in kwargs and kwargs["client_id"]:
                cid = kwargs["client_id"]

            if not cid:
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={"status": "no_portfolio", "message": "Client has not completed onboarding questionnaire."},
                    execution_time_ms=0.0,
                )

            async with AsyncSessionLocal() as db:
                pf = await self._portfolio.get_portfolio(db, cid)
                clean_pf = {k: v for k, v in pf.items() if k != "prices"}
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data=clean_pf,
                    execution_time_ms=round(elapsed_ms, 2),
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))


class GetPortfolioHealthArgs(BaseModel):
    client_id: Optional[str] = Field(default=None, description="Client ID to analyze portfolio health for")


class GetPortfolioHealthTool(BaseTool):
    name: str = "get_portfolio_health"
    description: str = "Generate a comprehensive health report: drift vs target allocation, diversification score, VaR, and rebalance triggers."
    category: ToolCategory = ToolCategory.PORTFOLIO
    args_schema: type[BaseModel] = GetPortfolioHealthArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Risk & Devil's Advocate",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]

    def __init__(self, health_service: Optional[HealthReportService] = None):
        self._health = health_service or HealthReportService()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            ctx = kwargs.get("context")
            cid = getattr(ctx, "client_id", None) if ctx else None
            if args and isinstance(args[0], GetPortfolioHealthArgs) and args[0].client_id:
                cid = args[0].client_id
            elif "client_id" in kwargs and kwargs["client_id"]:
                cid = kwargs["client_id"]

            if not cid:
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data={"status": "no_portfolio", "message": "Client has no active portfolio to review."},
                    execution_time_ms=0.0,
                )

            async with AsyncSessionLocal() as db:
                hr = await self._health.generate_health_report(db, cid)
                elapsed_ms = (time.perf_counter() - start_time) * 1000.0
                return ToolResult(
                    tool_name=self.name,
                    success=True,
                    data=hr.model_dump(mode="json"),
                    execution_time_ms=round(elapsed_ms, 2),
                )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(tool_name=self.name, success=False, error=str(exc), execution_time_ms=round(elapsed_ms, 2))

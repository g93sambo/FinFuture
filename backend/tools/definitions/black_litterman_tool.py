"""
backend/tools/definitions/black_litterman_tool.py
=================================================
BlackLittermanAllocationTool (optimize_black_litterman) definition.
Synthesizes market equilibrium returns with Research Engine views to produce
the mathematically optimal asset allocation.
"""

from __future__ import annotations

import time
import numpy as np
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.black_litterman import compute_black_litterman, ResearchView
except ImportError:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.black_litterman import compute_black_litterman, ResearchView


class ViewInput(BaseModel):
    asset: str
    relative_to: Optional[str] = None
    expected_return: float = Field(default=0.10, description="Expected annualized return (e.g. 0.12 for 12%)")
    confidence: float = Field(default=0.70, ge=0.01, le=0.99, description="Confidence level (0.01 to 0.99)")
    rationale: str = Field(default="", description="Investment rationale from research")


class BlackLittermanArgs(BaseModel):
    assets: List[str] = Field(default=["SPY", "QQQ", "BND", "VXUS", "GLD"], description="List of portfolio tickers")
    risk_aversion: float = Field(default=2.5, description="Client risk aversion parameter (delta)")
    views: List[ViewInput] = Field(default_factory=list, description="List of analyst views from Research Engine")


class BlackLittermanAllocationTool(BaseTool):
    name: str = "optimize_black_litterman"
    description: str = (
        "Run institutional Black-Litterman portfolio optimization that incorporates research-engine views, "
        "modulating market equilibrium weights into optimal research-driven asset allocation."
    )
    category: ToolCategory = ToolCategory.QUANT_MODELING
    args_schema: type[BaseModel] = BlackLittermanArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Quantitative Analyst",
        "Risk & Devil's Advocate",
        "Orchestrator",
    ]
    cache_ttl: int = 1800

    def __init__(self, name: Optional[str] = None):
        if name:
            self.name = name
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.time()
        if args and isinstance(args[0], BlackLittermanArgs):
            parsed = args[0]
        elif args and isinstance(args[0], dict):
            parsed = BlackLittermanArgs(**args[0])
        elif "args" in kwargs and isinstance(kwargs["args"], BlackLittermanArgs):
            parsed = kwargs["args"]
        elif "args" in kwargs and isinstance(kwargs["args"], dict):
            parsed = BlackLittermanArgs(**kwargs["args"])
        else:
            clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
            parsed = BlackLittermanArgs(**clean_kwargs)

        try:
            n = len(parsed.assets)
            # Default institutional covariance proxy
            cov = np.eye(n) * 0.04
            for i in range(n):
                for j in range(i + 1, n):
                    cov[i, j] = cov[j, i] = 0.015

            view_objs = [
                ResearchView(
                    asset=v.asset.upper(),
                    relative_to=v.relative_to.upper() if v.relative_to else None,
                    expected_return=v.expected_return,
                    confidence=v.confidence,
                    rationale=v.rationale,
                )
                for v in parsed.views
            ]

            res = compute_black_litterman(
                assets=[a.upper() for a in parsed.assets],
                cov_matrix=cov,
                views=view_objs,
                risk_aversion=parsed.risk_aversion,
            )

            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data=res.to_dict(),
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Black-Litterman optimization failed: {exc}",
                execution_time_ms=elapsed_ms,
            )

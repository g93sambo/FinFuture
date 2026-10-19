"""
backend/tools/definitions/legal_statutes.py
===========================================
SearchLegalStatutesTool (search_legal_statutes) definition.
Enables agents to retrieve verified statutory legal clauses and tax citations from PITA, CITA, CGTA, NEPZA, and PRA 2014.
"""

from __future__ import annotations

import time
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from services.legal_knowledge import retrieve_statutes
except ImportError:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.services.legal_knowledge import retrieve_statutes


class LegalStatuteArgs(BaseModel):
    query: str = Field(..., description="Legal topic, statutory question, or keyword (e.g. 'holding company dividend tax', 'FGN bond tax exemption', 'CRA relief', 'NEPZA holiday', 'capital gains tax').")
    jurisdiction: str = Field(default="Nigeria", description="Jurisdiction to query (e.g. 'Nigeria').")
    top_k: int = Field(default=3, description="Number of articles to retrieve.")


class SearchLegalStatutesTool(BaseTool):
    name: str = "search_legal_statutes"
    description: str = (
        "Search and retrieve verbatim statutory tax clauses and legal citations from official acts "
        "(PITA, CITA, CGTA, NEPZA, PRA 2014) to ground tax structuring and wealth advice in law."
    )
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = LegalStatuteArgs
    required_roles: List[str] = [
        "Financial Analyst",
        "Personalized Advisory",
        "Quantitative Analyst",
        "Risk & Devil's Advocate",
        "Orchestrator",
    ]
    cache_ttl: int = 86400  # 24 hours

    def __init__(self, name: Optional[str] = None):
        if name:
            self.name = name
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.time()
        if args and isinstance(args[0], LegalStatuteArgs):
            parsed = args[0]
        elif args and isinstance(args[0], dict):
            parsed = LegalStatuteArgs(**args[0])
        elif "args" in kwargs and isinstance(kwargs["args"], LegalStatuteArgs):
            parsed = kwargs["args"]
        elif "args" in kwargs and isinstance(kwargs["args"], dict):
            parsed = LegalStatuteArgs(**kwargs["args"])
        else:
            clean_kwargs = {k: v for k, v in kwargs.items() if k != "context"}
            parsed = LegalStatuteArgs(**clean_kwargs)

        try:
            articles = retrieve_statutes(query=parsed.query, jurisdiction=parsed.jurisdiction, top_k=parsed.top_k)
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "query": parsed.query,
                    "jurisdiction": parsed.jurisdiction,
                    "citations_count": len(articles),
                    "statutes": [a.to_dict() for a in articles],
                },
                execution_time_ms=elapsed_ms,
            )
        except Exception as exc:
            elapsed_ms = (time.time() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Statute retrieval failed: {exc}",
                execution_time_ms=elapsed_ms,
            )

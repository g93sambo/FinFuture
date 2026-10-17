"""
backend/tools/definitions/web_intelligence.py
=============================================
Web intelligence tools for live financial research, SEC filings,
and prospectus extraction with prompt-injection defense via SanitizerService.
"""

from __future__ import annotations

import time
import json
import logging
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

try:
    from backend.tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from backend.agents.market_data import MarketDataAgent
    from backend.services.sanitizer import sanitize_untrusted_text
except ImportError:
    from tools.base import BaseTool, ToolCategory, ToolResult, ExecutionContext
    from agents.market_data import MarketDataAgent
    from services.sanitizer import sanitize_untrusted_text

logger = logging.getLogger("wealth_advisor.tools.web_intelligence")


class SearchFinancialWebArgs(BaseModel):
    query: str = Field(..., description="Financial search query, entity name, or filing topic", min_length=1)
    max_results: int = Field(default=5, ge=1, le=10, description="Maximum number of search results to retrieve")


class SearchFinancialWebTool(BaseTool):
    name: str = "search_financial_web"
    description: str = (
        "Search the live web for prospectuses, regulatory filings, debt figures, revenues, "
        "valuations, and emerging market / IPO intelligence with prompt injection sanitization."
    )
    category: ToolCategory = ToolCategory.WEB_INTELLIGENCE
    args_schema: type[BaseModel] = SearchFinancialWebArgs
    required_roles: List[str] = [
        "Intelligence/Web Analyst",
        "Financial Analyst",
        "Investment Research Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]
    timeout_seconds: float = 30.0

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], SearchFinancialWebArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = SearchFinancialWebArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = SearchFinancialWebArgs(**clean_kwargs)

            raw_results = await self._market.search_financial_web(parsed.query, max_results=parsed.max_results)

            # Sanitize search results to neutralize prompt injection threats
            sanitized_results = []
            if isinstance(raw_results, list):
                for item in raw_results:
                    if isinstance(item, dict):
                        snippet = item.get("snippet", "") or item.get("body", "") or ""
                        url = item.get("link", "") or item.get("url", "") or "web_search"
                        res = sanitize_untrusted_text(snippet, source=url)
                        item_copy = dict(item)
                        item_copy["snippet"] = res.sanitized_text
                        item_copy["framed_content"] = res.framed_content
                        item_copy["threat_score"] = res.threat_score
                        sanitized_results.append(item_copy)
                    else:
                        sanitized_results.append(item)
            elif isinstance(raw_results, dict):
                snippet = raw_results.get("snippet", "") or raw_results.get("body", "") or ""
                url = raw_results.get("link", "") or raw_results.get("url", "") or "web_search"
                res = sanitize_untrusted_text(snippet, source=url)
                sanitized_results = {**raw_results, "snippet": res.sanitized_text, "framed_content": res.framed_content}
            else:
                sanitized_results = raw_results

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={"query": parsed.query, "results": sanitized_results},
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("search_financial_web failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Web search error: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )


class FetchWebPageArgs(BaseModel):
    url: str = Field(..., description="Target web URL, prospectus PDF link, or filing page", min_length=5)
    max_chars: int = Field(default=4000, ge=100, le=20000, description="Max characters of content to parse")


class FetchWebPageTool(BaseTool):
    name: str = "fetch_web_page"
    description: str = (
        "Retrieve and parse text content from an external web page, HTML investor note, or "
        "PDF filing, sanitizing all content through tri-layer prompt injection isolation."
    )
    category: ToolCategory = ToolCategory.WEB_INTELLIGENCE
    args_schema: type[BaseModel] = FetchWebPageArgs
    required_roles: List[str] = [
        "Intelligence/Web Analyst",
        "Financial Analyst",
        "Investment Research Analyst",
        "Personalized Advisory",
        "Orchestrator",
        "WealthAdvisor",
    ]
    timeout_seconds: float = 30.0

    def __init__(self, market_agent: Optional[MarketDataAgent] = None):
        self._market = market_agent or MarketDataAgent()
        super().__init__()

    async def execute(self, *args, **kwargs) -> ToolResult:
        start_time = time.perf_counter()
        try:
            if args and isinstance(args[0], FetchWebPageArgs):
                parsed = args[0]
            elif args and isinstance(args[0], dict):
                parsed = FetchWebPageArgs(**args[0])
            else:
                clean_kwargs = {k: v for k, v in kwargs.items() if k not in ("context", "self")}
                parsed = FetchWebPageArgs(**clean_kwargs)

            raw_res = await self._market.fetch_web_page(parsed.url, max_chars=parsed.max_chars)
            content = ""
            if isinstance(raw_res, dict):
                content = raw_res.get("content", "") or raw_res.get("text", "") or ""
            elif isinstance(raw_res, str):
                content = raw_res

            # Run tri-layer sanitization and unforgeable XML framing
            sanitized = sanitize_untrusted_text(content, source=parsed.url, is_html=True)

            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            return ToolResult(
                tool_name=self.name,
                success=True,
                data={
                    "url": parsed.url,
                    "content": sanitized.framed_content,
                    "sanitized_text": sanitized.sanitized_text,
                    "threat_score": sanitized.threat_score,
                    "is_safe": sanitized.is_safe,
                    "provenance_hash": sanitized.sanitized_hash,
                },
                execution_time_ms=round(elapsed_ms, 2),
            )
        except Exception as exc:
            elapsed_ms = (time.perf_counter() - start_time) * 1000.0
            logger.error("fetch_web_page failed: %s", exc)
            return ToolResult(
                tool_name=self.name,
                success=False,
                error=f"Page fetch error: {str(exc)}",
                execution_time_ms=round(elapsed_ms, 2),
            )

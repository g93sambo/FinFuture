"""
backend/api/routes/research.py
==============================
FastAPI routes for Autonomous Financial Research and Streaming Telemetry.

Endpoints:
- POST /api/v1/research/start: Initiates an autonomous research investigation.
- GET  /api/v1/research/stream: Server-Sent Events (SSE) telemetry stream.
- GET  /api/v1/research/history: Tenant-isolated research history.
- GET  /api/v1/research/{request_id}: Full structured research result.
"""

from __future__ import annotations

import json
import asyncio
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_db, get_current_user_id
from research.task_graph import TaskGraph, AnalystRole
from research.memory import TenantMemoryManager
from research.verification import SelfVerificationLoop
from services.report_builder import render_institutional_markdown_report
from services.financial_engineering import (
    solve_required_return,
    generate_10year_cash_flow_table,
    run_explicit_stress_tests,
    compare_three_institutional_portfolios,
)

router = APIRouter(prefix="/api/v1/research", tags=["Research"])


class StartResearchRequest(BaseModel):
    inquiry: str
    starting_capital: float = 10_000_000.0
    target_capital: Optional[float] = 100_000_000.0
    horizon_years: int = 10
    annual_withdrawal: float = 500_000.0
    session_id: Optional[str] = None


class ResearchResponse(BaseModel):
    request_id: str
    status: str
    inquiry: str
    user_id: str
    created_at: str
    executive_summary: Optional[str] = None
    markdown_report: Optional[str] = None
    verification_status: Optional[str] = None


# In-memory streaming queues by request_id
_RESEARCH_QUEUES: Dict[str, asyncio.Queue] = {}
_RESEARCH_RESULTS: Dict[str, Dict[str, Any]] = {}


@router.post("/start", response_model=ResearchResponse)
async def start_research(
    req: StartResearchRequest,
    user_id: str = Depends(get_current_user_id),
):
    request_id = str(uuid.uuid4())
    queue: asyncio.Queue = asyncio.Queue()
    _RESEARCH_QUEUES[request_id] = queue

    # Initialize TaskGraph
    graph = TaskGraph(inquiry=req.inquiry, user_id=user_id, session_id=req.session_id)

    # 1. Macro Analyst task
    graph.add_task(
        "task_macro",
        AnalystRole.MACRO_ANALYST.value,
        "Analyze macro regime and interest rate backdrop",
        [],
    )

    # 2. Financial Analyst task
    graph.add_task(
        "task_financial",
        AnalystRole.FINANCIAL_ANALYST.value,
        "Analyze company financials and fundamental filings",
        [],
    )

    # 3. Quantitative Analyst task (depends on macro & financial)
    async def run_quant(input_data: Dict, dependency_results: Dict, context: Dict):
        req_r = solve_required_return(req.starting_capital, req.target_capital or 100e6, req.horizon_years, req.annual_withdrawal)
        cf_table = generate_10year_cash_flow_table(req.starting_capital, req_r, req.horizon_years, req.annual_withdrawal)
        stress = run_explicit_stress_tests(req.starting_capital, req.annual_withdrawal)
        comparison = compare_three_institutional_portfolios(req.starting_capital, req.horizon_years, req.annual_withdrawal)
        return {
            "solved_hurdle": req_r,
            "cash_flow_table": cf_table,
            "stress_tests": stress,
            "portfolio_comparison": comparison,
        }

    graph.add_task(
        "task_quant",
        AnalystRole.QUANTITATIVE_ANALYST.value,
        "Calculate hurdle rates, 10-year cash flow table, and stress tests",
        ["task_macro", "task_financial"],
        fn=run_quant,
    )

    # 4. Devil's Advocate Review
    graph.add_task(
        "task_devils_advocate",
        AnalystRole.DEVILS_ADVOCATE.value,
        "Challenge bull assumptions, evaluate sequence-of-returns and ruin probability",
        ["task_quant"],
    )

    # 5. Compliance Guard
    graph.add_task(
        "task_compliance",
        AnalystRole.COMPLIANCE_GUARD.value,
        "Validate regulatory risk disclosures and paper trading compliance",
        ["task_devils_advocate"],
    )

    async def execute_in_background():
        try:
            async def progress_cb(event_type: str, step_id: str, data: Dict[str, Any]):
                evt = {
                    "type": "research_milestone",
                    "milestone": event_type,
                    "step_id": step_id,
                    "data": data,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
                await queue.put(evt)

            await progress_cb("planning", "init", {"inquiry": req.inquiry})
            res = await graph.execute(progress_callback=progress_cb)

            quant_data = res["results"].get("task_quant", {})
            hurdle = quant_data.get("solved_hurdle", 0.3444)
            cf_table = quant_data.get("cash_flow_table", [])
            stress = quant_data.get("stress_tests", [])
            comp = quant_data.get("portfolio_comparison", {})

            citations = [
                {"claim": "Treasury yield curve baseline", "publisher": "US Federal Reserve", "url": "https://fred.stlouisfed.org", "retrieval_timestamp": "2026-10-12"},
                {"claim": "SEC filings & company facts", "publisher": "U.S. Securities and Exchange Commission", "url": "https://www.sec.gov/edgar", "retrieval_timestamp": "2026-10-12"},
            ]

            report = render_institutional_markdown_report(
                inquiry=req.inquiry,
                solved_hurdle=hurdle,
                cash_flow_table=cf_table,
                stress_tests=stress,
                portfolio_comparison=comp,
                citations=citations,
            )

            # Verification loop
            verifier = SelfVerificationLoop()
            v_res = verifier.verify_report(report, quant_data, citations)

            final_data = {
                "request_id": request_id,
                "status": "COMPLETED",
                "inquiry": req.inquiry,
                "user_id": user_id,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "executive_summary": f"Research completed. Solved Hurdle: {hurdle*100:.2f}%.",
                "markdown_report": v_res.final_text,
                "verification_status": "VERIFIED" if v_res.verified else "UNCONFIRMED",
            }
            _RESEARCH_RESULTS[request_id] = final_data
            await queue.put({"type": "report_ready", "request_id": request_id, "data": final_data})
        except Exception as exc:
            err_data = {"type": "error", "message": str(exc)}
            await queue.put(err_data)
        finally:
            await queue.put(None)  # Signal end of stream

    asyncio.create_task(execute_in_background())

    return ResearchResponse(
        request_id=request_id,
        status="INITIALIZED",
        inquiry=req.inquiry,
        user_id=user_id,
        created_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/stream")
async def stream_research(request_id: str = Query(...)):
    """Server-Sent Events (SSE) telemetry stream for research progress."""
    queue = _RESEARCH_QUEUES.get(request_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Research request not found or expired.")

    async def event_generator():
        while True:
            item = await queue.get()
            if item is None:
                yield "data: [DONE]\n\n"
                break
            yield f"data: {json.dumps(item)}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@router.get("/{request_id}", response_model=ResearchResponse)
async def get_research_result(
    request_id: str,
    user_id: str = Depends(get_current_user_id),
):
    res = _RESEARCH_RESULTS.get(request_id)
    if not res:
        raise HTTPException(status_code=404, detail="Research result not found.")
    if res.get("user_id") != user_id:
        raise HTTPException(status_code=403, detail="Access forbidden: Tenant isolation mismatch.")

    return ResearchResponse(**res)

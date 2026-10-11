"""Portfolio routes: portfolio holdings, health report, and allocation recommendations."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


class HealthReportRequest(BaseModel):
    client_id: str


class AllocationRequest(BaseModel):
    client_id: str


@router.get("/portfolio/{client_id}")
async def get_portfolio(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, client_id, db)
    pf = await c.portfolio.get_portfolio(db, client_id, persist_snapshot=True)
    return {k: v for k, v in pf.items() if k not in ("prices", "position_qty")}


async def _generate_health_report(client_id: str, user: DBUser, db: AsyncSession, c: AgentContainer):
    await verify_client_ownership(user, client_id, db)
    await c.bias.record_portfolio_check(client_id, db=db)
    pf = await c.portfolio.get_portfolio(db, client_id)
    portfolio_arg = {
        "weights": pf["weights"],
        "positions": pf["position_qty"],
        "cash": pf["cash"],
        "total_value": pf["total_value"],
        "prices": pf["prices"],
    } if pf["position_qty"] else None
    report = await c.health.generate_health_report(db, client_id, portfolio=portfolio_arg)
    return report.model_dump(mode="json")


@router.post("/portfolio/health-report")
async def health_report_body(
    req: HealthReportRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _generate_health_report(req.client_id, user, db, c)


@router.post("/portfolio/{client_id}/health-report")
async def health_report_path(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _generate_health_report(client_id, user, db, c)


@router.post("/allocation/recommend")
async def recommend_allocation(
    req: AllocationRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, req.client_id, db)
    events = await c.orchestrator.recommend_allocation(db, req.client_id)
    return {"client_id": req.client_id, "events": events}

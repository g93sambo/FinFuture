"""Product comparison routes: multi-factor ETF and bond evaluation."""

from __future__ import annotations

from typing import List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["compare"])


class CompareRequest(BaseModel):
    symbols: List[str] = Field(min_length=2, max_length=15)
    client_id: str


async def _compare(req: CompareRequest, bonds: bool, user: DBUser, db: AsyncSession, c: AgentContainer):
    profile = await verify_client_ownership(user, req.client_id, db)
    fn = c.comparison.compare_bonds if bonds else c.comparison.compare_etfs
    report = await fn(req.symbols, profile=profile, client_id=req.client_id)
    rationale = await c.orchestrator.gate_text(report.summary_rationale, db, req.client_id)
    data = report.model_dump()
    data["summary_rationale"] = rationale
    return {
        "ranked_products": data["ranked_products"],
        "unsuitable_products": data["unsuitable_products"],
        "winner_symbol": data["winner_symbol"],
        "rationale": rationale,
        "report": data,
    }


@router.post("/compare/etfs")
async def compare_etfs(
    req: CompareRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _compare(req, False, user, db, c)


@router.post("/compare/bonds")
async def compare_bonds(
    req: CompareRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _compare(req, True, user, db, c)

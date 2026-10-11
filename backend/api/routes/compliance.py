"""Compliance routes: regulatory rule catalog inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["compliance"])


@router.get("/compliance/rules")
async def get_compliance_rules(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    rules = await c.compliance.get_active_rules(db)
    out = []
    for r in rules:
        out.append(
            {
                "id": getattr(r, "rule_id", None) or getattr(r, "id", None),
                "name": r.name,
                "category": r.category,
                "severity": r.severity,
                "description": r.description,
                "parameters": getattr(r, "parameters", {}) or {},
            }
        )
    return {"rules": sorted(out, key=lambda x: x["id"])}

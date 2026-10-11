"""Session routes: session initialization and lifecycle."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBClientProfile, DBUser

router = APIRouter(prefix="/api/v1", tags=["session"])


class SessionStartResponse(BaseModel):
    session_id: str
    message: str
    stage: str
    client_id: Optional[str] = None


@router.post("/session/start", response_model=SessionStartResponse)
async def start_session(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    existing = (
        await db.execute(
            select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
        )
    ).scalars().first()
    started = await c.orchestrator.start_session(user.id, client_id=existing.client_id if existing else None)
    s = started["session"]
    return SessionStartResponse(
        session_id=s["session_id"], message=started["message"], stage=s["stage"], client_id=s["client_id"]
    )

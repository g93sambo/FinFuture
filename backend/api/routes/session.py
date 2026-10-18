"""Session routes: session initialization and lifecycle."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBChatSession, DBClientProfile, DBUser
from services.cache import key_session

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

    # Resume the user's latest session if one already exists in the database
    latest_sess = (
        await db.execute(
            select(DBChatSession)
            .where(DBChatSession.user_id == user.id)
            .order_by(desc(DBChatSession.updated_at))
        )
    ).scalars().first()

    if latest_sess:
        session = await c.orchestrator.load_session(latest_sess.id, user.id, db=db)
        return SessionStartResponse(
            session_id=latest_sess.id,
            message="Welcome back! Ask me for an allocation, compare ETFs, or request a portfolio health report.",
            stage=session.get("stage", latest_sess.stage),
            client_id=session.get("client_id") or (existing.client_id if existing else None),
        )

    started = await c.orchestrator.start_session(user.id, client_id=existing.client_id if existing else None, db=db)
    s = started["session"]
    return SessionStartResponse(
        session_id=s["session_id"], message=started["message"], stage=s["stage"], client_id=s["client_id"]
    )

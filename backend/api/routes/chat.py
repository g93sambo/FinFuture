"""Chat routes: conversational interaction with the advisory system."""

from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatMessage(BaseModel):
    session_id: str
    message: str = Field(min_length=1, max_length=4000)


class ChatResponse(BaseModel):
    text: str
    agent: str
    type: str
    events: List[Dict[str, Any]]


@router.post("/chat/message", response_model=ChatResponse)
async def chat_message(
    req: ChatMessage,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    events = await c.orchestrator.process_user_message(
        session_id=req.session_id,
        user_id=user.id,
        client_id=None,
        message=req.message,
        db=db,
    )
    replies = [e for e in events if e.get("event") not in ("user_message",)]
    last_text = next((e for e in reversed(replies) if e.get("text")), None)
    return ChatResponse(
        text=last_text["text"] if last_text else "",
        agent=last_text.get("agent", "Orchestrator") if last_text else "Orchestrator",
        type=last_text.get("event", "agent_response") if last_text else "agent_response",
        events=events,
    )

"""Chat routes: conversational interaction with the advisory system and persistent session history."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, desc, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from agents.orchestrator import AgentContainer, TradeBlocked
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBChatMessage, DBChatSession, DBClientProfile, DBUser
from services.attachments import AttachmentError, validate_attachments

router = APIRouter(prefix="/api/v1", tags=["chat"])


class ChatMessageAttachment(BaseModel):
    type: str = "image"
    name: Optional[str] = None
    mime_type: Optional[str] = None
    url: Optional[str] = None
    data: Optional[str] = None


class ChatMessage(BaseModel):
    session_id: str
    message: str = Field(default="", max_length=10000)
    attachments: Optional[List[Dict[str, Any]]] = Field(default_factory=list)


class ChatResponse(BaseModel):
    text: str
    agent: str
    type: str
    events: List[Dict[str, Any]]


class ChatSessionSummary(BaseModel):
    session_id: str
    title: str
    stage: str
    last_message: Optional[str] = None
    created_at: str
    updated_at: str
    message_count: int = 0


class ChatSessionDetail(BaseModel):
    session_id: str
    title: str
    stage: str
    created_at: str
    updated_at: str
    messages: List[Dict[str, Any]]


class ChatSessionCreateRequest(BaseModel):
    title: Optional[str] = None


class ChatSessionRenameRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)


@router.get("/chat/sessions", response_model=List[ChatSessionSummary])
async def list_chat_sessions(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve list of chat sessions for the current authenticated user."""
    stmt = (
        select(DBChatSession)
        .where(DBChatSession.user_id == user.id)
        .options(selectinload(DBChatSession.messages))
        .order_by(desc(DBChatSession.updated_at))
    )
    result = await db.execute(stmt)
    sessions = result.scalars().all()

    summaries: List[ChatSessionSummary] = []
    for s in sessions:
        last_msg = s.messages[-1].text if s.messages else None
        summaries.append(
            ChatSessionSummary(
                session_id=s.id,
                title=s.title,
                stage=s.stage,
                last_message=last_msg,
                created_at=s.created_at.isoformat(),
                updated_at=s.updated_at.isoformat(),
                message_count=len(s.messages),
            )
        )
    return summaries


@router.post("/chat/sessions", response_model=Dict[str, Any])
async def create_chat_session(
    req: Optional[ChatSessionCreateRequest] = None,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Create a new chat conversation session."""
    existing_profile = (
        await db.execute(
            select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
        )
    ).scalars().first()

    title = req.title if req and req.title else "New Advisory Conversation"
    started = await c.orchestrator.start_session(
        user_id=user.id,
        client_id=existing_profile.client_id if existing_profile else None,
        title=title,
        db=db,
    )
    s = started["session"]
    return {
        "session_id": s["session_id"],
        "title": s.get("title", title),
        "stage": s["stage"],
        "message": started["message"],
        "client_id": s.get("client_id"),
    }


@router.get("/chat/sessions/{session_id}", response_model=ChatSessionDetail)
async def get_chat_session(
    session_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve detailed transcript and messages for a specific session."""
    stmt = (
        select(DBChatSession)
        .where(DBChatSession.id == session_id, DBChatSession.user_id == user.id)
        .options(selectinload(DBChatSession.messages))
    )
    result = await db.execute(stmt)
    sess = result.scalars().first()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    messages_payload: List[Dict[str, Any]] = []
    for m in sess.messages:
        messages_payload.append(
            {
                "id": m.id,
                "sender": m.sender,
                "agent": m.agent,
                "text": m.text,
                "attachments": m.attachments or [],
                "events": m.events or [],
                "created_at": m.created_at.isoformat(),
            }
        )

    return ChatSessionDetail(
        session_id=sess.id,
        title=sess.title,
        stage=sess.stage,
        created_at=sess.created_at.isoformat(),
        updated_at=sess.updated_at.isoformat(),
        messages=messages_payload,
    )


@router.patch("/chat/sessions/{session_id}", response_model=Dict[str, Any])
async def rename_chat_session(
    session_id: str,
    req: ChatSessionRenameRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Rename a chat session title."""
    stmt = select(DBChatSession).where(DBChatSession.id == session_id, DBChatSession.user_id == user.id)
    result = await db.execute(stmt)
    sess = result.scalars().first()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    sess.title = req.title.strip()
    sess.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
    await db.commit()

    # Also update cache if active
    try:
        from services.cache import key_session
        cached = await c.cache.get_json(key_session(session_id))
        if cached:
            cached["title"] = sess.title
            await c.cache.set_json(key_session(session_id), cached, expire=86400)
    except Exception:
        pass

    return {"session_id": sess.id, "title": sess.title, "updated_at": sess.updated_at.isoformat()}


@router.delete("/chat/sessions/{session_id}", response_model=Dict[str, Any])
async def delete_chat_session(
    session_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Delete a chat session and all associated messages."""
    stmt = select(DBChatSession).where(DBChatSession.id == session_id, DBChatSession.user_id == user.id)
    result = await db.execute(stmt)
    sess = result.scalars().first()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Chat session not found")

    await db.execute(delete(DBChatSession).where(DBChatSession.id == session_id))
    await db.commit()

    # Clear cache
    try:
        from services.cache import key_session
        await c.cache.delete(key_session(session_id))
    except Exception:
        pass

    return {"deleted": True, "session_id": session_id}


@router.post("/chat/message", response_model=ChatResponse)
async def chat_message(
    req: ChatMessage,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Send a user message with optional image attachments."""
    try:
        attachments = validate_attachments(req.attachments)
    except AttachmentError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    try:
        events = await c.orchestrator.process_user_message(
            session_id=req.session_id,
            user_id=user.id,
            client_id=None,
            message=req.message,
            db=db,
            attachments=attachments,
        )
    except TradeBlocked as blocked:
        # Same shape the WebSocket endpoint sends for a blocked approval
        events = blocked.events or [
            {
                "event": "error",
                "agent": "ComplianceGuard",
                "error": blocked.error_type,
                "text": blocked.reason,
                "violations": [v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in blocked.violations],
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        ]
    replies = [e for e in events if e.get("event") not in ("user_message",)]
    last_text = next((e for e in reversed(replies) if e.get("text")), None)
    return ChatResponse(
        text=last_text["text"] if last_text else "",
        agent=last_text.get("agent", "Orchestrator") if last_text else "Orchestrator",
        type=last_text.get("event", "agent_response") if last_text else "agent_response",
        events=events,
    )

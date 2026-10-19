"""WebSocket chat endpoint: /ws/chat and /ws/chat/{session_id}?token=<jwt>

Client -> server: plain text, or JSON {"type": "message"|"approve"|"reject", ...}
Server -> client: JSON events: agent_response, bias_alert, compliance_check,
trade_proposal, trade_approved, trade_filled, portfolio_update, error.
Streams all 8 canonical events: session_started, agent_thought, profile_updated,
bias_detected, recommendation_ready, trade_proposed, trade_executed, error.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Set

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from sqlalchemy import select

from agents.orchestrator import TradeBlocked, build_container
from core.security import decode_access_token
from db.database import AsyncSessionLocal
from db.models import DBClientProfile, DBUser
from services.attachments import AttachmentError, validate_attachments

logger = logging.getLogger("wealth_advisor.api.ws")
router = APIRouter(tags=["websocket"])


class ConnectionManager:
    """Thread-safe WebSocket active connection manager."""

    def __init__(self) -> None:
        self.active_sessions: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.active_users: Dict[str, Set[WebSocket]] = defaultdict(set)
        self.socket_meta: Dict[WebSocket, Dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def connect(
        self, websocket: WebSocket, user_id: str, session_id: str, client_id: Optional[str] = None
    ) -> None:
        async with self._lock:
            self.active_sessions[session_id].add(websocket)
            self.active_users[user_id].add(websocket)
            self.socket_meta[websocket] = {
                "user_id": user_id,
                "session_id": session_id,
                "client_id": client_id,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }

    async def disconnect(self, websocket: WebSocket) -> None:
        async with self._lock:
            meta = self.socket_meta.pop(websocket, None)
            if meta:
                user_id = meta.get("user_id")
                session_id = meta.get("session_id")
                if user_id and user_id in self.active_users:
                    self.active_users[user_id].discard(websocket)
                    if not self.active_users[user_id]:
                        del self.active_users[user_id]
                if session_id and session_id in self.active_sessions:
                    self.active_sessions[session_id].discard(websocket)
                    if not self.active_sessions[session_id]:
                        del self.active_sessions[session_id]

    async def send_event(self, websocket: WebSocket, event: Dict[str, Any]) -> bool:
        try:
            await websocket.send_json(event)
            return True
        except Exception:
            return False

    async def broadcast_to_session(self, session_id: str, event: Dict[str, Any]) -> None:
        async with self._lock:
            sockets = list(self.active_sessions.get(session_id, []))
        for ws in sockets:
            await self.send_event(ws, event)

    async def disconnect_all(self, code: int = 1001, reason: str = "Server shutdown") -> None:
        async with self._lock:
            all_sockets = list(self.socket_meta.keys())
        for ws in all_sockets:
            try:
                await ws.close(code=code, reason=reason)
            except Exception:
                pass


ws_manager = ConnectionManager()


async def _auth(token: Optional[str], db) -> Optional[DBUser]:
    if not token:
        return None
    try:
        payload = decode_access_token(token)
    except (HTTPException, Exception):
        return None
    user_id = str(payload.get("sub", ""))
    if not user_id:
        return None
    user = (await db.execute(select(DBUser).where(DBUser.id == user_id))).scalars().first()
    return user if user and user.is_active else None


async def _handle_connection(websocket: WebSocket, session_id: Optional[str], token: Optional[str]):
    async with AsyncSessionLocal() as db:
        user = await _auth(token, db)
        if user is None:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or missing token")
            return

        if not hasattr(websocket.app.state, "container") or websocket.app.state.container is None:
            websocket.app.state.container = build_container()
        orch = websocket.app.state.container.orchestrator

        # Resolve or create session
        session = None
        if session_id:
            try:
                session = await orch.load_session(session_id, user.id, db=db)
            except HTTPException as exc:
                if exc.status_code == 403:
                    await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Forbidden: session ownership mismatch")
                    return
                logger.warning("Session %s not found for user %s; starting fresh session", session_id, user.id)
                session = None
            except Exception:
                logger.warning("Session %s not found for user %s; starting fresh session", session_id, user.id)
                session = None

        if not session:
            existing = (
                await db.execute(
                    select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
                )
            ).scalars().first()
            started = await orch.start_session(user.id, client_id=existing.client_id if existing else None, db=db)
            session_id = started["session"]["session_id"]
            session = started["session"]

        await websocket.accept()
        await ws_manager.connect(websocket, user.id, session_id, session.get("client_id"))

        try:
            # Emit session_started with backward-compatible agent_response format
            welcome_text = (
                "Connected! How can I help you navigate your wealth and portfolio today?"
                if session.get("stage") in ("ADVICE_GENERATION", "advising")
                else "Connected! I'm your AI Wealth Advisor. Ask me anything about stocks, market trends, or company supply chains — or let me know whenever you'd like to build your personalized investment portfolio."
            )
            await websocket.send_json(
                {
                    "event": "agent_response",
                    "structured_event": "session_started",
                    "agent": "WealthAdvisor",
                    "session_id": session_id,
                    "stage": session.get("stage"),
                    "client_id": session.get("client_id"),
                    "text": welcome_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            while True:
                raw = await websocket.receive_text()
                text, action, proposal_id, obj = raw, "message", None, None
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        obj = parsed
                        action = obj.get("type", "message")
                        text = obj.get("text") or obj.get("message") or ""
                        proposal_id = obj.get("proposal_id")
                except (json.JSONDecodeError, TypeError):
                    obj = None

                try:
                    if action in ("approve", "reject"):
                        if not proposal_id or str(proposal_id).lower() in ("undefined", "null", ""):
                            sess = await orch.load_session(session_id, user.id, db=db)
                            proposal_id = sess.get("pending_proposal_id")
                        if action == "approve" and proposal_id:
                            events = await orch.handle_trade_approval(db, user.id, str(proposal_id), approved=True, session_id=session_id)
                        elif action == "reject" and proposal_id:
                            await orch.c.cache.delete(f"proposal:{proposal_id}")
                            events = [
                                {
                                    "event": "agent_response",
                                    "agent": "Orchestrator",
                                    "text": "Proposal cancelled; nothing was sent to the broker.",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            ]
                        else:
                            events = [
                                {
                                    "event": "error",
                                    "agent": "Orchestrator",
                                    "text": "No active trade proposal found to approve or reject.",
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            ]
                    else:
                        try:
                            attachments = validate_attachments(obj.get("attachments") if isinstance(obj, dict) else None)
                        except AttachmentError as exc:
                            await websocket.send_json(
                                {
                                    "event": "error",
                                    "agent": "Orchestrator",
                                    "text": str(exc),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                            )
                            continue
                        if not text.strip() and not attachments:
                            continue
                        events = await orch.process_user_message(
                            session_id=session_id,
                            user_id=user.id,
                            client_id=session.get("client_id"),
                            message=text,
                            db=db,
                            attachments=attachments,
                        )
                except TradeBlocked as blocked:
                    events = blocked.events if blocked.events else [
                        {
                            "event": "error",
                            "structured_event": "error",
                            "agent": "ComplianceGuard",
                            "error": blocked.error_type,
                            "text": blocked.reason,
                            "violations": [v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in blocked.violations],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                except HTTPException as exc:
                    events = [
                        {
                            "event": "error",
                            "structured_event": "error",
                            "agent": "Orchestrator",
                            "text": str(exc.detail),
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ]
                except Exception as exc:  # noqa: BLE001
                    logger.exception("WebSocket handler failure")
                    events = [
                        {
                            "event": "error",
                            "structured_event": "error",
                            "agent": "Orchestrator",
                            "text": "Something went wrong while handling that message. Please try again.",
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                        }
                    ]

                for ev in events:
                    await websocket.send_json(ev)
        except WebSocketDisconnect:
            logger.info("WebSocket %s disconnected", session_id)
        finally:
            await ws_manager.disconnect(websocket)


@router.websocket("/ws/chat/{session_id}")
async def chat_ws_session(websocket: WebSocket, session_id: str, token: Optional[str] = Query(None)):
    await _handle_connection(websocket, session_id, token)


@router.websocket("/ws/chat")
async def chat_ws_root(websocket: WebSocket, session_id: Optional[str] = Query(None), token: Optional[str] = Query(None)):
    await _handle_connection(websocket, session_id, token)


@router.get(
    "/ws/chat",
    summary="WebSocket Chat (Specification)",
    description=(
        "**WebSocket Endpoint**: `ws://<host>:<port>/ws/chat?token=<jwt>`\n\n"
        "Connect via a WebSocket client (e.g., Postman, browser WebSocket, or frontend).\n"
        "- **Protocol**: WebSocket (`ws://` or `wss://`)\n"
        "- **Auth**: Pass JWT access token via `?token=<jwt>` query parameter.\n"
        "- **Client Payload**: Send JSON `{\"type\": \"message\", \"text\": \"...\"}` or `{\"type\": \"approve\", \"proposal_id\": \"...\"}`\n"
        "- **Server Events**: Emits `agent_response`, `agent_thought`, `profile_updated`, `bias_alert`, `compliance_check`, `trade_proposal`, `trade_executed`, `error`."
    ),
    tags=["websocket"],
)
async def ws_chat_docs(token: Optional[str] = Query(None, description="JWT Bearer token")):
    """Documentation endpoint for Swagger UI."""
    return {
        "endpoint": "/ws/chat",
        "protocol": "websocket",
        "usage": "Connect using ws://<host>:<port>/ws/chat?token=<JWT_TOKEN>",
        "query_params": {"token": "JWT Bearer access token", "session_id": "Optional existing session ID"},
        "client_messages": [
            {"type": "message", "text": "Your query or conversation"},
            {"type": "approve", "proposal_id": "<uuid>"},
            {"type": "reject", "proposal_id": "<uuid>"},
        ],
    }


@router.get(
    "/ws/chat/{session_id}",
    summary="WebSocket Chat with Session ID (Specification)",
    description=(
        "**WebSocket Endpoint**: `ws://<host>:<port>/ws/chat/{session_id}?token=<jwt>`\n\n"
        "Connect via WebSocket specifying the `session_id` in the URL path."
    ),
    tags=["websocket"],
)
async def ws_chat_session_docs(
    session_id: str,
    token: Optional[str] = Query(None, description="JWT Bearer token"),
):
    """Documentation endpoint for Swagger UI."""
    return {
        "endpoint": f"/ws/chat/{session_id}",
        "protocol": "websocket",
        "session_id": session_id,
        "usage": f"Connect using ws://<host>:<port>/ws/chat/{session_id}?token=<JWT_TOKEN>",
    }

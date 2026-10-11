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

from agents.orchestrator import TradeBlocked
from core.security import decode_access_token
from db.database import AsyncSessionLocal
from db.models import DBClientProfile, DBUser

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

        orch = websocket.app.state.container.orchestrator

        # Resolve or create session
        if not session_id:
            existing = (
                await db.execute(
                    select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
                )
            ).scalars().first()
            started = await orch.start_session(user.id, client_id=existing.client_id if existing else None)
            session_id = started["session"]["session_id"]
            session = started["session"]
        else:
            try:
                session = await orch.load_session(session_id, user.id)
            except HTTPException as exc:
                await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason=str(exc.detail))
                return

        await websocket.accept()
        await ws_manager.connect(websocket, user.id, session_id, session.get("client_id"))

        try:
            # Emit session_started with backward-compatible agent_response format
            welcome_text = (
                "Connected. How can I help with your portfolio?"
                if session.get("stage") in ("ADVICE_GENERATION", "advising")
                else "Connected. Let's build your risk profile - tell me a bit about yourself."
            )
            await websocket.send_json(
                {
                    "event": "agent_response",
                    "structured_event": "session_started",
                    "agent": "Orchestrator",
                    "session_id": session_id,
                    "stage": session.get("stage"),
                    "client_id": session.get("client_id"),
                    "text": welcome_text,
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                }
            )

            while True:
                raw = await websocket.receive_text()
                text, action, proposal_id = raw, "message", None
                try:
                    obj = json.loads(raw)
                    if isinstance(obj, dict):
                        action = obj.get("type", "message")
                        text = obj.get("text") or obj.get("message") or ""
                        proposal_id = obj.get("proposal_id")
                except (json.JSONDecodeError, TypeError):
                    pass

                try:
                    if action in ("approve", "reject") and proposal_id:
                        if action == "approve":
                            events = await orch.handle_trade_approval(db, user.id, proposal_id, approved=True, session_id=session_id)
                        else:
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
                        if not text.strip():
                            continue
                        events = await orch.process_user_message(
                            session_id=session_id,
                            user_id=user.id,
                            client_id=session.get("client_id"),
                            message=text,
                            db=db,
                        )
                except TradeBlocked as blocked:
                    events = blocked.events + [
                        {
                            "event": "error",
                            "structured_event": "error",
                            "agent": "ExecutionModule",
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
                            "text": f"Internal error: {type(exc).__name__}",
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

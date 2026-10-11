"""FastAPI shared dependencies."""

from __future__ import annotations

from fastapi import Request

from agents.orchestrator import AgentContainer


def get_container(request: Request) -> AgentContainer:
    return request.app.state.container

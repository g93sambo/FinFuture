from typing import Optional
from fastapi import Request, Depends

from agents.orchestrator import AgentContainer
from db.database import get_db
from core.security import get_current_user
from db.models import DBUser


def get_container(request: Request) -> AgentContainer:
    return request.app.state.container


async def get_current_user_id(user: DBUser = Depends(get_current_user)) -> str:
    return user.id

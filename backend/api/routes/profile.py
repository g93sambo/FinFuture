"""Profile routes: client risk profile and suitability metrics."""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBClientProfile, DBUser

router = APIRouter(prefix="/api/v1", tags=["profile"])


def _profile_dict(p: DBClientProfile) -> Dict[str, Any]:
    return {c.name: getattr(p, c.name) for c in p.__table__.columns if c.name != "profiling_session_transcript"}


@router.get("/profile/{client_id}")
async def get_profile(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await verify_client_ownership(user, client_id, db)
    return _profile_dict(profile)

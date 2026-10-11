"""
Advisory routes: backward-compatible composite router.

Re-exports and includes routes for session, chat, profile, allocation,
product comparison, market data, and compliance.
"""

from __future__ import annotations

from fastapi import APIRouter

from api.routes import chat, compare, compliance, market, profile, session
from api.routes.portfolio import recommend_allocation

router = APIRouter(tags=["advisory"])

# Include modular sub-routers under this backward-compatible router
router.include_router(session.router)
router.include_router(chat.router)
router.include_router(profile.router)
router.include_router(compare.router)
router.include_router(market.router)
router.include_router(compliance.router)

# Also expose recommend_allocation on /api/v1/allocation/recommend
router.add_api_route(
    "/api/v1/allocation/recommend",
    recommend_allocation,
    methods=["POST"],
    tags=["allocation"],
)

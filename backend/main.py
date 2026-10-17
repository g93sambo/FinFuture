"""Wealth Advisory Agent API - application entrypoint."""

from __future__ import annotations

import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import func, select

from agents.compliance_guard import DEFAULT_COMPLIANCE_RULES
from agents.orchestrator import build_container
from api.routes import (
    asyncapi,
    audit,
    auth,
    chat,
    compare,
    compliance,
    market,
    portfolio,
    profile,
    session,
    trade,
    ws,
    research,
)
from api.routes.ws import ws_manager
from core.config import settings
from db.database import AsyncSessionLocal, engine, init_db
from db.models import DBComplianceRule
from services.cache import CacheService

logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
logger = logging.getLogger("wealth_advisor.main")


async def seed_compliance_rules() -> int:
    """Insert the default 12-rule catalog if the table is empty."""
    async with AsyncSessionLocal() as db:
        count = (await db.execute(select(func.count()).select_from(DBComplianceRule))).scalar_one()
        if count:
            return 0
        for r in DEFAULT_COMPLIANCE_RULES.values():
            db.add(
                DBComplianceRule(
                    rule_id=r["rule_id"],
                    name=r["name"],
                    category=r["category"],
                    severity=r["severity"],
                    parameters=r.get("parameters", {}),
                    description=r.get("description"),
                    is_active=r.get("is_active", True),
                )
            )
        await db.commit()
        return len(DEFAULT_COMPLIANCE_RULES)


async def warm_market_fixtures(cache: CacheService) -> None:
    """Pre-warm market data fixtures from test fixture directory for offline/zero-dependency startup."""
    import os

    fixtures_dir = Path(__file__).resolve().parent / "tests" / "fixtures"
    if not fixtures_dir.exists():
        return

    offline_or_dev = (
        settings.environment.lower() != "production"
        or os.getenv("FINFUTURE_OFFLINE_MODE") == "1"
    )

    # Warm market quotes (in production, store under fallback key so live market APIs are not shadowed)
    quotes_file = fixtures_dir / "market_quotes.json"
    if quotes_file.exists():
        try:
            with open(quotes_file, "r", encoding="utf-8") as f:
                quotes = json.load(f)
            for symbol, data in quotes.items():
                sym = symbol.upper()
                await cache.set_json(f"data:fixture_quotes:{sym}", data, expire=86400)
                if offline_or_dev:
                    await cache.set_json(f"data:quotes:{sym}", data, expire=3600)
                    await cache.set_json(f"data:quote:{sym}", data, expire=3600)
        except Exception as e:
            logger.debug("Failed to warm market quotes: %s", e)

    # Warm yield curve
    yc_file = fixtures_dir / "yield_curve.json"
    if yc_file.exists():
        try:
            with open(yc_file, "r", encoding="utf-8") as f:
                yc = json.load(f)
            rates = yc.get("rates", yc)
            await cache.set_json("data:fixture_treasury:yield_curve", rates, expire=86400)
            if offline_or_dev:
                await cache.set_json("data:treasury:yield_curve", rates, expire=86400)
        except Exception as e:
            logger.debug("Failed to warm yield curve: %s", e)

    # Warm macro indicators
    macro_file = fixtures_dir / "macro_indicators.json"
    if macro_file.exists():
        try:
            with open(macro_file, "r", encoding="utf-8") as f:
                macro = json.load(f)
            indicators = macro.get("indicators", macro)
            await cache.set_json("data:fixture_macro:indicators", indicators, expire=86400)
            if offline_or_dev:
                await cache.set_json("data:macro:indicators", indicators, expire=86400)
        except Exception as e:
            logger.debug("Failed to warm macro indicators: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # --- STARTUP ---
    await init_db()
    seeded = await seed_compliance_rules()
    app.state.container = build_container()

    # Pre-warm market data cache fixtures for zero-dependency resilience
    await warm_market_fixtures(app.state.container.cache)

    logger.info(
        "Startup complete (compliance rules seeded: %s, redis online: %s)",
        seeded,
        app.state.container.cache.is_redis_online,
    )
    yield
    # --- SHUTDOWN ---
    await ws_manager.disconnect_all()
    if hasattr(app.state.container.market, "pipeline") and hasattr(app.state.container.market.pipeline, "close"):
        try:
            await app.state.container.market.pipeline.close()
        except Exception:
            pass
    await app.state.container.cache.close()
    await engine.dispose()
    logger.info("Shutdown complete: WebSockets, cache and database engine disposed.")


app = FastAPI(
    title=settings.app_name,
    description="Non-discretionary multi-agent wealth advisory system: profiling, comparison, allocation, compliance, human-approved paper execution.",
    version=settings.app_version,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Modular API routers mounted under /api/v1
app.include_router(auth.router)
app.include_router(session.router)
app.include_router(chat.router)
app.include_router(profile.router)
app.include_router(compare.router)
app.include_router(portfolio.router)
app.include_router(trade.router)
app.include_router(audit.router)
app.include_router(market.router)
app.include_router(compliance.router)
app.include_router(ws.router)
app.include_router(asyncapi.router)
app.include_router(research.router)


@app.get("/", tags=["health"])
async def root():
    return {"status": "ok", "service": settings.app_name, "version": settings.app_version}


@app.get("/chat", include_in_schema=False)
async def chat_ui():
    if settings.environment.lower() == "production":
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Debug chat UI is disabled in production.")
    html_file = Path(__file__).resolve().parent / "chat_client.html"
    return HTMLResponse(content=html_file.read_text(encoding="utf-8"))


@app.get("/health", tags=["health"])
async def health():
    c = app.state.container
    return {
        "status": "ok",
        "redis": c.cache.is_redis_online,
        "paper_trading": True,
        "broker_connected": c.execution.client is not None,
    }


if __name__ == "__main__":
    import os
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    print(f"Starting Wealth Advisor API on http://127.0.0.1:{port}")
    uvicorn.run("main:app", host="127.0.0.1", port=port, reload=True)

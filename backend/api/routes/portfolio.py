"""Portfolio routes: portfolio holdings, health report, and allocation recommendations."""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBClientProfile, DBUser

router = APIRouter(prefix="/api/v1", tags=["portfolio"])


class HealthReportRequest(BaseModel):
    client_id: str


class AllocationRequest(BaseModel):
    client_id: str


class ShockSimulationRequest(BaseModel):
    client_id: str
    scenario: str = "bull_drift_30d"


SHOCK_SCENARIOS = {
    "bull_drift_30d": {
        "id": "bull_drift_30d",
        "title": "+30 Days: Equity Tech Rally (+14% Drift)",
        "description": "Simulates 30 days of strong equity outperformance (QQQ +18%, SPY/VTI +12%, Bonds -2%), pushing equity weights above target bands.",
        "multipliers": {"QQQ": 1.18, "SPY": 1.12, "VTI": 1.12, "VXUS": 1.08, "BND": 0.98, "AGG": 0.98, "SHY": 1.00},
        "behavioral_nudge": "Recency Bias Alert: After a 14% equity rally, investors often resist trimming winners. Disciplined SELL-before-BUY rebalancing locks in gains and restores your target risk ceiling.",
    },
    "rate_hike_150bps": {
        "id": "rate_hike_150bps",
        "title": "Macro Shock: +150 bps Rate Hike",
        "description": "Simulates an unexpected 150 bps central bank tightening cycle (Growth Equities -14%, Long/Intermediate Bonds -9%, Short-Term Treasuries +1%).",
        "multipliers": {"QQQ": 0.86, "SPY": 0.90, "VTI": 0.90, "VXUS": 0.91, "BND": 0.91, "AGG": 0.91, "SHY": 1.01},
        "behavioral_nudge": "Duration & Rate Shock Coaching: Rising yields temporarily depress bond NAVs while raising forward yield-to-maturity. Avoid panic-liquidating fixed income at cycle highs.",
    },
    "crash_2008_gfc": {
        "id": "crash_2008_gfc",
        "title": "Tail Risk: 2008 GFC Drawdown (-32% Equity)",
        "description": "Simulates a severe systemic liquidity and credit contraction (Equities -32%, Flight-to-Quality Treasuries +6%).",
        "multipliers": {"QQQ": 0.65, "SPY": 0.68, "VTI": 0.68, "VXUS": 0.66, "BND": 1.05, "AGG": 1.05, "SHY": 1.03},
        "behavioral_nudge": "Loss Aversion Guard: Selling equities after a 32% drawdown crystallizes permanent capital loss. Counter-cyclical rebalancing from outperforming bonds into discounted equities accelerates recovery.",
    },
    "stagflation_shock": {
        "id": "stagflation_shock",
        "title": "2022 Stagflation Replay ( CPI Spike )",
        "description": "Simulates simultaneous equity and bond correlation breakdown (Equities -19%, Nominal Bonds -12%, Cash/Short Bills +2%).",
        "multipliers": {"QQQ": 0.78, "SPY": 0.81, "VTI": 0.81, "VXUS": 0.83, "BND": 0.88, "AGG": 0.88, "SHY": 1.02},
        "behavioral_nudge": "Correlation Shock Note: When both stocks and nominal bonds fall together, maintaining short-duration liquidity buffers (SHY/Cash) prevents forced selling.",
    },
}


@router.get("/portfolio/{client_id}")
async def get_portfolio(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, client_id, db)
    pf = await c.portfolio.get_portfolio(db, client_id, persist_snapshot=True)
    return {k: v for k, v in pf.items() if k not in ("prices", "position_qty")}


async def _generate_health_report(client_id: str, user: DBUser, db: AsyncSession, c: AgentContainer):
    await verify_client_ownership(user, client_id, db)
    await c.bias.record_portfolio_check(client_id, db=db)
    pf = await c.portfolio.get_portfolio(db, client_id)
    portfolio_arg = {
        "weights": pf["weights"],
        "positions": pf["position_qty"],
        "cash": pf["cash"],
        "total_value": pf["total_value"],
        "prices": pf["prices"],
    } if pf["position_qty"] else None
    report = await c.health.generate_health_report(db, client_id, portfolio=portfolio_arg)
    return report.model_dump(mode="json")


@router.post("/portfolio/health-report")
async def health_report_body(
    req: HealthReportRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _generate_health_report(req.client_id, user, db, c)


@router.post("/portfolio/{client_id}/health-report")
async def health_report_path(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    return await _generate_health_report(client_id, user, db, c)


@router.post("/portfolio/simulate-shock")
async def simulate_portfolio_shock(
    req: ShockSimulationRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Simulates a Time-Machine / Macro Shock scenario on the client's portfolio without mutating real holdings."""
    await verify_client_ownership(user, req.client_id, db)
    scenario = SHOCK_SCENARIOS.get(req.scenario, SHOCK_SCENARIOS["bull_drift_30d"])
    multipliers = scenario["multipliers"]

    pf = await c.portfolio.get_portfolio(db, req.client_id)
    base_positions = dict(pf.get("position_qty") or {})
    base_prices = dict(pf.get("prices") or {})
    cash = float(pf.get("cash", 5000.0))

    # If the client has not placed trades yet, use a realistic baseline model portfolio so the simulator works immediately
    if not base_positions:
        base_positions = {"VTI": 140.0, "QQQ": 45.0, "BND": 320.0, "SHY": 110.0}
        base_prices = {"VTI": 265.0, "QQQ": 480.0, "BND": 72.5, "SHY": 82.0}
        cash = 4500.0

    shocked_prices = {}
    invested_after = 0.0
    for sym, qty_val in base_positions.items():
        p0 = float(base_prices.get(sym, 100.0))
        mult = float(multipliers.get(sym.upper(), 0.95))
        p1 = round(p0 * mult, 2)
        shocked_prices[sym] = p1
        invested_after += qty_val * p1

    total_after = invested_after + cash
    shocked_weights = {
        sym: (qty_val * shocked_prices[sym]) / total_after if total_after > 0 else 0.0
        for sym, qty_val in base_positions.items()
    }

    shocked_portfolio = {
        "weights": shocked_weights,
        "positions": base_positions,
        "cash": cash,
        "total_value": total_after,
        "prices": shocked_prices,
    }

    report = await c.health.generate_health_report(db, req.client_id, portfolio=shocked_portfolio)
    data = report.model_dump(mode="json")
    data["scenario_meta"] = scenario
    return data


@router.post("/allocation/recommend")
async def recommend_allocation(
    req: AllocationRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    await verify_client_ownership(user, req.client_id, db)
    events = await c.orchestrator.recommend_allocation(db, req.client_id)
    return {"client_id": req.client_id, "events": events}


class AllocationOptimizeRequest(BaseModel):
    client_id: Optional[str] = None
    target_return: Optional[float] = None
    risk_tolerance: Optional[float] = None


@router.post("/allocation/optimize")
async def optimize_allocation(
    req: Optional[AllocationOptimizeRequest] = None,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Prompt alias for /allocation/recommend."""
    cid = req.client_id if req and req.client_id else None
    if not cid:
        profile = (
            await db.execute(
                select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
            )
        ).scalars().first()
        if not profile:
            raise HTTPException(status_code=404, detail="Client profile not found. Complete onboarding first.")
        cid = profile.client_id
    await verify_client_ownership(user, cid, db)
    events = await c.orchestrator.recommend_allocation(db, cid)
    return {"status": "ok", "client_id": cid, "events": events}


@router.get("/allocation/current")
async def get_current_allocation(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """Prompt alias for /portfolio/{client_id}."""
    profile = (
        await db.execute(
            select(DBClientProfile).where(DBClientProfile.user_id == user.id).order_by(DBClientProfile.created_at.desc())
        )
    ).scalars().first()
    if not profile:
        raise HTTPException(status_code=404, detail="Client profile not found. Complete onboarding first.")
    pf = await c.portfolio.get_portfolio(db, profile.client_id, persist_snapshot=True)
    return {k: v for k, v in pf.items() if k not in ("prices", "position_qty")}



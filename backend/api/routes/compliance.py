"""Compliance routes: regulatory rule catalog inspection."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["compliance"])


@router.get("/compliance/rules")
async def get_compliance_rules(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    rules = await c.compliance.get_active_rules(db)
    out = []
    for r in rules:
        out.append(
            {
                "id": getattr(r, "rule_id", None) or getattr(r, "id", None),
                "name": r.name,
                "category": r.category,
                "severity": r.severity,
                "description": r.description,
                "parameters": getattr(r, "parameters", {}) or {},
            }
        )
    return {"rules": sorted(out, key=lambda x: x["id"])}


@router.get("/compliance/permission-tiers")
async def get_permission_tiers(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Returns the 2026 FinTechathon 3-Tier Permission Matrix, 5 Security Pillars, Known-Risk Register, and Circuit Breaker status."""
    cb_status = c.compliance.get_circuit_breaker_status(str(user.id))
    return {
        "permission_tiers": c.compliance.get_permission_tier_catalog(),
        "known_risks": c.compliance.get_known_risk_register(),
        "circuit_breaker": cb_status,
        "security_pillars": [
            {"id": "PILLAR-1", "name": "Hallucination Defense", "status": "ACTIVE", "detail": "Zero LLM arithmetic; all prices, MPT, Student-t MC & trades verified deterministically."},
            {"id": "PILLAR-2", "name": "Prompt Injection Defense", "status": "ACTIVE", "detail": "Tri-layer HTML/Unicode stripping, XML tag isolation & regex heuristic screening."},
            {"id": "PILLAR-3", "name": "Cryptographic Audit Trail", "status": "ACTIVE", "detail": "Append-only SHA-256 hash chain + HMAC signatures + Sepolia Merkle anchoring."},
            {"id": "PILLAR-4", "name": "Anomaly Circuit Breaker", "status": "LOCKED" if cb_status["is_locked"] else "ACTIVE", "detail": "Auto-locks execution on >= 3 blocked compliance/injection attempts in 60s."},
            {"id": "PILLAR-5", "name": "Sandbox Isolation", "status": "ACTIVE", "detail": "Strict paper-trading enforcement (Alpaca Paper API; Ethereum Mainnet Chain ID 1 hard-blocked)."},
        ],
    }


@router.post("/compliance/circuit-breaker/simulate")
async def simulate_circuit_breaker_incident(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Simulates a blocked adversarial/compliance anomaly for judges to see the Circuit Breaker trip."""
    status = c.compliance.record_security_incident(
        str(user.id),
        reason="Simulated adversarial prompt injection / rapid concentration override attempt blocked by ComplianceGuard.",
        incident_type="ADVERSARIAL_OVERRIDE_BLOCKED",
    )
    return {"circuit_breaker": status}


@router.post("/compliance/circuit-breaker/reset")
async def reset_circuit_breaker_endpoint(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Resets the Anomaly Circuit Breaker back to CLOSED_NORMAL."""
    status = c.compliance.reset_circuit_breaker(str(user.id))
    return {"circuit_breaker": status}


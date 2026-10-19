"""Compliance routes: regulatory rule catalog inspection."""

from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from agents.orchestrator import AgentContainer
from api.deps import get_container
from core.security import get_current_user
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1", tags=["compliance"])


class CheckInputRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=10000, description="User input text to inspect for prompt injection and PII redaction")
    client_id: Optional[str] = Field(default=None, description="Optional client_id for Anomaly Circuit Breaker tracking")


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
    """Returns the 5-Tier Permission Implementation, Code-Enforced Limits, 5 Security Pillars, Known-Risk Register, and Circuit Breaker status."""
    cb_status = c.compliance.get_circuit_breaker_status(str(user.id))
    return {
        "permission_tiers": c.compliance.get_permission_tier_catalog(),
        "enforced_limits": {
            "allow_autonomous_execution": False,
            "max_single_trade_notional_usd": c.compliance.MAX_SINGLE_TRADE_NOTIONAL_USD,
            "max_daily_trade_notional_usd": c.compliance.MAX_DAILY_TRADE_NOTIONAL_USD,
            "step_up_mfa_threshold_usd": c.compliance.STEP_UP_MFA_THRESHOLD_USD,
            "max_single_stock_weight": 0.15,
            "whitelisted_symbols": sorted(c.compliance.ALLOWED_TRADING_SYMBOLS),
        },
        "known_risks": c.compliance.get_known_risk_register(),
        "circuit_breaker": cb_status,
        "security_pillars": [
            {"id": "PILLAR-1", "name": "Prompt Injection Defense", "status": "ACTIVE", "detail": "Pre-LLM input firewall (RULE-09) + <untrusted_external_content> XML isolation on web/filing text."},
            {"id": "PILLAR-2", "name": "Data Minimization & PII Redaction", "status": "ACTIVE", "detail": "Market APIs receive only tickers; LLM prompts use ANON-ID pseudonyms with direct PII stripped (RULE-10)."},
            {"id": "PILLAR-3", "name": "5-Tier Permission & Hard Limits", "status": "ACTIVE", "detail": "Read-Only -> Advise -> Propose -> Approved Execution ($100k/trade, $250k/day, symbol whitelist); Autonomous disabled."},
            {"id": "PILLAR-4", "name": "Execution Gate & Circuit Breaker", "status": "LOCKED" if cb_status["is_locked"] else "ACTIVE", "detail": "Non-discretionary approval + Step-Up MFA (> $1,000) + auto-lock on >= 3 blocked attempts in 60s."},
            {"id": "PILLAR-5", "name": "Dual-Ledger Audit (Sepolia + WeBank FISCO BCOS)", "status": "ACTIVE", "detail": "Append-only SHA-256 hash chain + HMAC signatures + RFC 6962 Merkle roots anchored on Ethereum Sepolia & WeBank FISCO BCOS v3.6."},
        ],
        "webank_ecosystem": {
            "consortium_chain": {
                "engine": "WeBank FISCO BCOS v3.6.0",
                "consensus": "PBFT (4 Validator Nodes · Sub-second Finality)",
                "group_id": "group0",
                "contract": "AuditAnchorConsortium.sol",
                "endpoint": "/api/v1/audit/{client_id}/anchor/fisco-bcos",
            },
            "event_mesh": {
                "engine": "WeBank WeEvent v1.12 Event-Driven Governance Mesh",
                "topic": "com.webank.finfuture.audit.anchor",
                "protocol": "STOMP / JSON-RPC 2.0",
            },
            "federated_privacy": {
                "engine": "WeBank FATE v2.0 (Federated AI Technology Enabler)",
                "mode": "Discretized Suitability Feature Envelope + SHA-256 Commitment + ANON-ID Pseudonymization",
                "raw_pii_transmitted": False,
            },
            "wealth_shelf": {
                "platform": "WeBank Smart Wealth (微众银行财富+) & GBA Cross-Border Wealth Connect (跨境理财通)",
                "instruments": [
                    {"symbol": "WBKCASH", "name": "WeBank Live+ Cash Management Fund (微众活期+ R1)", "risk_level": "R1"},
                    {"symbol": "WBK6M", "name": "WeBank Steady+ 180D Short-Duration Bond Note (微众稳健+ R2)", "risk_level": "R2"},
                    {"symbol": "GBAHK", "name": "WeBank GBA Wealth Connect Multi-Asset Income ETF (跨境理财通南向通)", "risk_level": "R2"},
                    {"symbol": "WBKGLD", "name": "WeBank Digital Gold Accumulation Trust (微众黄金 Inflation Hedge)", "risk_level": "R3"},
                ],
            },
        },
    }


@router.post("/compliance/check-input")
async def check_input_endpoint(
    req: CheckInputRequest,
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Inspects user input for prompt injection (RULE-09) and redacts direct PII/secrets (RULE-10)."""
    target_id = req.client_id or str(user.id)
    result = c.compliance.check_input_safety(req.text, client_id=target_id)
    return {
        **result,
        "circuit_breaker": c.compliance.get_circuit_breaker_status(target_id),
    }


@router.post("/compliance/check")
async def check_compliance_alias(
    req: CheckInputRequest,
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Prompt alias for /compliance/check-input."""
    return await check_input_endpoint(req, user=user, c=c)


@router.post("/compliance/circuit-breaker/simulate")
async def simulate_circuit_breaker_incident(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Simulates a blocked adversarial/compliance anomaly for judges to see the Circuit Breaker trip."""
    status = c.compliance.record_security_incident(
        str(user.id),
        reason="Simulated adversarial prompt injection / rapid concentration override attempt blocked by ComplianceGuard.",
        incident_type=c.compliance.SIMULATED_INCIDENT_TYPE,
    )
    return {"circuit_breaker": status}


@router.post("/compliance/circuit-breaker/reset")
async def reset_circuit_breaker_endpoint(
    user: DBUser = Depends(get_current_user),
    c: AgentContainer = Depends(get_container),
):
    """Resets the Anomaly Circuit Breaker back to CLOSED_NORMAL (simulated drills only)."""
    allowed, reason = c.compliance.can_user_reset_circuit_breaker(str(user.id))
    if not allowed:
        raise HTTPException(status_code=423, detail=reason)
    status = c.compliance.reset_circuit_breaker(str(user.id))
    return {"circuit_breaker": status}



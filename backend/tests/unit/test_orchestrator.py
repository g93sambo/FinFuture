"""
backend/tests/unit/test_orchestrator.py
======================================
Comprehensive unit tests for the OrchestratorAgent (Milestone 5).

Covers:
1. 5-State Session State Machine (PROFILING, ADVICE_GENERATION, PROPOSAL_REVIEW, EXECUTION, HEALTH_MONITORING)
2. Intent Routing (Profiling, Quotes, Macro, Comparison, Allocation, Rebalancing, Health, General)
3. Universal Compliance Output Gating (REG-001 promissory replacement, REG-002 risk disclosure)
4. Trade Proposal & Approval Flow (Staging, 15m window, Affirmative Approval REG-003, Rejection)
5. Canonical Milestone 5 Methods & Backward-Compatible Facades
"""

import uuid
from datetime import datetime, timezone
import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from agents.orchestrator import (
    OrchestratorAgent,
    SessionStage,
    TradeBlocked,
    _normalize_stage,
    build_container,
)
from db.models import DBClientProfile, DBUser
from core.security import get_password_hash


@pytest_asyncio.fixture
async def container(db_session):
    c = build_container()
    return c


@pytest_asyncio.fixture
async def registered_user(db_session):
    user_id = str(uuid.uuid4())
    user = DBUser(
        id=user_id,
        email=f"test_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=get_password_hash("password123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def client_profile(db_session, registered_user):
    cid = str(uuid.uuid4())
    profile = DBClientProfile(
        client_id=cid,
        user_id=registered_user.id,
        age=35,
        annual_income=120000.0,
        liquid_assets=60000.0,
        investment_horizon_years=10,
        risk_tolerance_score=7.0,
        suitability_category="Growth",
        kyc_verified=True,
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)
    return profile


# ============================================================================
# 1. 5-State Session State Machine Tests
# ============================================================================
@pytest.mark.asyncio
async def test_session_state_machine_initial_states(container, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator

    # Un-profiled user starts in PROFILING
    unprofiled = await orch.start_session(registered_user.id, client_id=None)
    assert unprofiled["session"]["stage"] == SessionStage.PROFILING.value
    assert "how old are you" in unprofiled["message"].lower() or "basics" in unprofiled["message"].lower()

    # Profiled user starts in ADVICE_GENERATION
    profiled = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    assert profiled["session"]["stage"] == SessionStage.ADVICE_GENERATION.value
    assert "welcome back" in profiled["message"].lower()


@pytest.mark.asyncio
async def test_stage_normalization():
    assert _normalize_stage(None) == SessionStage.PROFILING
    assert _normalize_stage("PROFILING") == SessionStage.PROFILING
    assert _normalize_stage("profiling") == SessionStage.PROFILING
    assert _normalize_stage("ADVISING") == SessionStage.ADVICE_GENERATION
    assert _normalize_stage("advising") == SessionStage.ADVICE_GENERATION
    assert _normalize_stage("ADVICE_GENERATION") == SessionStage.ADVICE_GENERATION
    assert _normalize_stage("PROPOSAL_REVIEW") == SessionStage.PROPOSAL_REVIEW
    assert _normalize_stage("EXECUTION") == SessionStage.EXECUTION
    assert _normalize_stage("HEALTH_MONITORING") == SessionStage.HEALTH_MONITORING


@pytest.mark.asyncio
async def test_session_load_and_ownership(container, registered_user):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id)
    sid = s["session"]["session_id"]

    # Same user loads session successfully
    loaded = await orch.load_session(sid, registered_user.id)
    assert loaded["session_id"] == sid

    # Different user gets 403 Forbidden
    other_user_id = str(uuid.uuid4())
    with pytest.raises(HTTPException) as exc_info:
        await orch.load_session(sid, other_user_id)
    assert exc_info.value.status_code == 403

    # Non-existent session gets 404
    with pytest.raises(HTTPException) as exc_info404:
        await orch.load_session("non-existent-sid", registered_user.id)
    assert exc_info404.value.status_code == 404


# ============================================================================
# 2. Universal Compliance Output Gating Tests
# ============================================================================
@pytest.mark.asyncio
async def test_compliance_gate_promissory_language_replacement(container, db_session, client_profile):
    orch: OrchestratorAgent = container.orchestrator

    promissory_text = "This asset is guaranteed to return 20% risk-free every single year!"
    gated = await orch.gate_text(promissory_text, db_session, client_profile.client_id)

    assert "guaranteed" not in gated.lower()
    assert "risk-free" not in gated.lower()
    assert "loss of principal" in gated.lower() or "past performance" in gated.lower()


@pytest.mark.asyncio
async def test_compliance_gate_clean_text_appends_risk_disclosure(container, db_session, client_profile):
    orch: OrchestratorAgent = container.orchestrator

    clean_text = "Diversification across equities and fixed income helps manage volatility."
    gated = await orch.gate_text(clean_text, db_session, client_profile.client_id)

    assert "diversification across equities" in gated.lower()
    assert "investing involves risk" in gated.lower() or "loss of principal" in gated.lower()


# ============================================================================
# 3. Intent Routing Tests
# ============================================================================
@pytest.mark.asyncio
async def test_intent_routing_market_quote(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="Quote SPY",
        db=db_session,
    )
    quote_ev = next((e for e in events if e.get("agent") == "MarketData"), None)
    assert quote_ev is not None
    assert "SPY" in quote_ev["text"]


@pytest.mark.asyncio
async def test_intent_routing_macro(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="what is the current macro and yield curve context?",
        db=db_session,
    )
    macro_ev = next((e for e in events if e.get("agent") == "MarketData"), None)
    assert macro_ev is not None
    assert "macroeconomic" in macro_ev["text"].lower() or "treasury" in macro_ev["text"].lower()


@pytest.mark.asyncio
async def test_intent_routing_compare_etfs(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="compare SPY VTI QQQ",
        db=db_session,
    )
    comp_ev = next((e for e in events if e.get("agent") == "ProductComparison"), None)
    assert comp_ev is not None
    assert "ranking" in comp_ev["text"].lower()


@pytest.mark.asyncio
async def test_intent_routing_allocation(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="recommend an asset allocation portfolio for me",
        db=db_session,
    )
    alloc_ev = next((e for e in events if e.get("agent") == "AllocationEngine"), None)
    assert alloc_ev is not None
    assert "recommended allocation" in alloc_ev["text"].lower()
    assert abs(sum(alloc_ev["weights"].values()) - 1.0) < 1e-2


@pytest.mark.asyncio
async def test_intent_routing_portfolio_health(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="how is my portfolio health and drift?",
        db=db_session,
    )
    health_ev = next((e for e in events if e.get("agent") == "HealthReport"), None)
    assert health_ev is not None
    assert health_ev.get("event") == "portfolio_update"


# ============================================================================
# 4. Trade Proposal & Approval Lifecycle Tests
# ============================================================================
@pytest.mark.asyncio
async def test_trade_proposal_creation_and_state_transition(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    # Propose trade via dialogue message
    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="buy 10 shares of BND",
        db=db_session,
    )
    prop_ev = next((e for e in events if e.get("event") == "trade_proposal"), None)
    assert prop_ev is not None
    assert prop_ev["proposal"]["symbol"] == "BND"
    assert prop_ev["proposal"]["qty"] == 10

    # Session state must transition to PROPOSAL_REVIEW
    session = await orch.load_session(sid, registered_user.id)
    assert session["stage"] == SessionStage.PROPOSAL_REVIEW.value
    assert session["pending_proposal_id"] == prop_ev["proposal"]["proposal_id"]


@pytest.mark.asyncio
async def test_trade_rejection_clears_proposal_and_reverts_state(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    # 1. Propose
    await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="buy 5 BND",
        db=db_session,
    )

    # 2. Reject
    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="cancel",
        db=db_session,
    )
    cancel_ev = next((e for e in events if "cancelled" in e.get("text", "").lower()), None)
    assert cancel_ev is not None

    # State returns to ADVICE_GENERATION and pending proposal is cleared
    session = await orch.load_session(sid, registered_user.id)
    assert session["stage"] == SessionStage.ADVICE_GENERATION.value
    assert "pending_proposal_id" not in session


@pytest.mark.asyncio
async def test_trade_approval_executes_and_returns_events(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    # 1. Propose
    await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="buy 2 BND",
        db=db_session,
    )

    # 2. Approve
    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="approve",
        db=db_session,
    )
    event_names = {e.get("event") for e in events}
    assert {"trade_approved", "compliance_check", "trade_filled", "portfolio_update"} <= event_names

    # State returns to ADVICE_GENERATION
    session = await orch.load_session(sid, registered_user.id)
    assert session["stage"] == SessionStage.ADVICE_GENERATION.value


@pytest.mark.asyncio
async def test_unapproved_trade_fails_reg003(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    proposal = await orch.create_trade_proposal(db_session, client_profile.client_id, "BND", "BUY", 2.0)

    # Calling handle_trade_approval with approved=False raises TradeBlocked under REG-003
    with pytest.raises(TradeBlocked) as exc_info:
        await orch.handle_trade_approval(db_session, registered_user.id, proposal["proposal_id"], approved=False)
    assert any("REG-003" in str(v.rule_id if hasattr(v, "rule_id") else v) for v in exc_info.value.violations)


@pytest.mark.asyncio
async def test_proposal_recovered_from_audit_log_after_cache_loss(container, db_session, registered_user, client_profile):
    """A restart that drops the cache still lets the user approve within the TTL, and blocks replays."""
    orch: OrchestratorAgent = container.orchestrator
    proposal = await orch.create_trade_proposal(db_session, client_profile.client_id, "BND", "BUY", 2.0)
    pid = proposal["proposal_id"]
    await orch.c.cache.delete(f"proposal:{pid}")

    events = await orch.handle_trade_approval(db_session, registered_user.id, pid, approved=True)
    assert any(e.get("event") == "trade_filled" for e in events)

    await orch.c.cache.delete(f"proposal:{pid}")
    await orch.c.cache.delete(f"executed_proposal:{pid}")
    with pytest.raises(TradeBlocked) as exc_info:
        await orch.handle_trade_approval(db_session, registered_user.id, pid, approved=True)
    assert exc_info.value.error_type == "DuplicateTradeError"


# ============================================================================
# 5. Facade & Canonical Method Equivalence Tests
# ============================================================================
@pytest.mark.asyncio
async def test_facade_methods_equivalence(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    # handle_message calls process_user_message
    res1 = await orch.handle_message(db_session, registered_user.id, sid, "Quote SPY")
    assert any(e.get("agent") == "MarketData" for e in res1)

    # create_proposal calls create_trade_proposal
    prop = await orch.create_proposal(db_session, client_profile.client_id, "BND", "BUY", 1.0)
    assert prop["symbol"] == "BND"

    # execute_proposal calls handle_trade_approval
    res2 = await orch.execute_proposal(db_session, registered_user.id, prop["proposal_id"], approved=True)
    assert any(e.get("event") == "trade_filled" for e in res2)


# ============================================================================
# 6. Rebalancing & Edge Coverage Tests
# ============================================================================
@pytest.mark.asyncio
async def test_rebalance_flow(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="rebalance my portfolio please",
        db=db_session,
    )
    assert any(e.get("agent") == "AllocationEngine" for e in events)


@pytest.mark.asyncio
async def test_general_reply_fallback(container, db_session, registered_user, client_profile):
    orch: OrchestratorAgent = container.orchestrator
    s = await orch.start_session(registered_user.id, client_id=client_profile.client_id)
    sid = s["session"]["session_id"]

    events = await orch.process_user_message(
        session_id=sid,
        user_id=registered_user.id,
        client_id=client_profile.client_id,
        message="Hello, can you help me today?",
        db=db_session,
    )
    assert any("recommend a portfolio" in e.get("text", "").lower() or "portfolio" in e.get("text", "").lower() for e in events)


@pytest.mark.asyncio
async def test_api_routes_direct_coverage(container):
    from starlette.testclient import TestClient
    from main import app
    from db.models import DBTrade
    from db.database import AsyncSessionLocal

    with TestClient(app) as client:
        # Register and login through API so user exists in app DB
        email = f"cov_test_{uuid.uuid4().hex[:6]}@example.com"
        r_reg = client.post("/api/v1/auth/register", json={"email": email, "password": "Password123!"})
        assert r_reg.status_code == 201
        uid = r_reg.json()["id"]

        r_login = client.post("/api/v1/auth/login", data={"username": email, "password": "Password123!"})
        assert r_login.status_code == 200
        token = r_login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # GET /auth/me
        r_me = client.get("/api/v1/auth/me", headers=headers)
        assert r_me.status_code == 200
        assert r_me.json()["email"] == email

        # Complete profiling to get client_id
        r_start = client.post("/api/v1/session/start", headers=headers)
        assert r_start.status_code == 200
        sid = r_start.json()["session_id"]

        profiling_answers = [
            "I am 35 years old and employed.",
            "My income is 120k and liquid savings 60k.",
            "Investment horizon is 10 years for growth.",
            "Risk tolerance score is 7 out of 10.",
            "Intermediate experience, salary source, not PEP.",
        ]
        cid = None
        for ans in profiling_answers:
            r_msg = client.post("/api/v1/chat/message", headers=headers, json={"session_id": sid, "message": ans})
            assert r_msg.status_code == 200
            for ev in r_msg.json()["events"]:
                cid = ev.get("client_id") or cid

        assert cid is not None

        # Propose and execute trade to create a real trade
        r_prop = client.post(
            "/api/v1/trade/propose",
            headers=headers,
            json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 3.0},
        )
        assert r_prop.status_code == 200
        prop_id = r_prop.json()["proposal"]["proposal_id"]

        r_exec = client.post(
            "/api/v1/trade/execute",
            headers=headers,
            json={"client_id": cid, "proposal_id": prop_id, "user_approved": True},
        )
        assert r_exec.status_code == 200
        trade_id = r_exec.json()["execution"]["trade_id"]

        # GET /trade/{order_id}
        r_trade = client.get(f"/api/v1/trade/{trade_id}", headers=headers)
        assert r_trade.status_code == 200
        assert r_trade.json()["trade_id"] == trade_id

        # GET /trade/nonexistent -> 404
        r_bad_trade = client.get(f"/api/v1/trade/{uuid.uuid4()}", headers=headers)
        assert r_bad_trade.status_code == 404

        # GET /trades/{client_id}
        r_trades = client.get(f"/api/v1/trades/{cid}", headers=headers)
        assert r_trades.status_code == 200
        assert len(r_trades.json()["trades"]) >= 1

        # POST /compare/bonds
        r_bonds = client.post(
            "/api/v1/compare/bonds",
            headers=headers,
            json={"client_id": cid, "symbols": ["BND", "AGG"]},
        )
        assert r_bonds.status_code == 200

        # POST /portfolio/{client_id}/health-report (path-based)
        r_hr = client.post(f"/api/v1/portfolio/{cid}/health-report", headers=headers)
        assert r_hr.status_code == 200

        # POST /audit/{client_id}/anchor
        r_anchor = client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)
        assert r_anchor.status_code == 200

        # Error branches for auth, compare, trade, audit
        r_bad_login = client.post("/api/v1/auth/login", data={"username": email, "password": "wrong"})
        assert r_bad_login.status_code == 401

        r_bad_compare = client.post("/api/v1/compare/etfs", headers=headers, json={"client_id": cid, "symbols": ["SPY"]})
        assert r_bad_compare.status_code == 422

        r_bad_propose = client.post("/api/v1/trade/propose", headers=headers, json={"client_id": cid, "symbol": "BND", "side": "INVALID", "qty": -1})
        assert r_bad_propose.status_code == 422

        r_bad_exec = client.post("/api/v1/trade/execute", headers=headers, json={"client_id": cid, "proposal_id": str(uuid.uuid4()), "user_approved": True})
        assert r_bad_exec.status_code == 404

        r_audit = client.get(f"/api/v1/audit/{cid}", headers=headers)
        assert r_audit.status_code == 200
        r_verify = client.get(f"/api/v1/audit/{cid}/verify", headers=headers)
        assert r_verify.status_code == 200

        # WebSocket root /ws/chat?token=... without session_id in path
        with client.websocket_connect(f"/ws/chat?token={token}") as ws:
            first_ev = ws.receive_json()
            assert first_ev["event"] == "agent_response"
            ws.send_text("Hello")
            resp = ws.receive_json()
            assert "event" in resp


@pytest.mark.asyncio
async def test_navigation_help_routing(container, registered_user, client_profile, db_session):
    """Verify that asking how to use the app or navigate returns the full platform guide."""
    orch: OrchestratorAgent = container.orchestrator
    user_id = registered_user.id
    cid = client_profile.client_id

    s = await orch.start_session(user_id, client_id=cid)
    sid = s["session"]["session_id"]

    for query in [
        "How do I use this app?",
        "Where do I find what information and all that",
        "Can you help me navigate the app?",
    ]:
        events = await orch.process_user_message(sid, user_id, cid, query, db_session)
        advisor_event = next(e for e in events if e.get("agent") == "WealthAdvisor")
        text = advisor_event.get("text", "")
        assert "Advice" in text
        assert "Overview" in text
        assert "Health review" in text
        assert "Audit trail" in text



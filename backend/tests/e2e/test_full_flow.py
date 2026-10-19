"""
End-to-end API tests (registration -> profiling -> advice -> proposal -> approval -> fill -> audit).

Runs the real FastAPI app (lifespan, routers, agents, DB, cache) in-process with
simulated paper fills (DRY_RUN) and no network access to the LLM or broker.
"""

import sqlite3
import uuid

import pytest
from starlette.testclient import TestClient

from main import app

PROFILING_MESSAGES = [
    "I am 35 years old and employed as a software engineer.",
    "My income is 150k and I have 80k in liquid savings. Monthly expenses are 5k.",
    "My investment horizon is 15 years and my primary goal is long-term growth.",
    "My risk tolerance score is 7 out of 10. In a crash I would hold or buy more.",
    "I have intermediate experience, source of funds is salary, and I am not a PEP.",
]


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def _register(client, email=None, password="S3cure-pass!"):
    email = email or f"{uuid.uuid4().hex[:10]}@example.com"
    r = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    tok = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert tok.status_code == 200, tok.text
    return email, {"Authorization": f"Bearer {tok.json()['access_token']}"}


def _profile(client, headers):
    sid = client.post("/api/v1/session/start", headers=headers).json()["session_id"]
    client_id = None
    for msg in PROFILING_MESSAGES:
        r = client.post("/api/v1/chat/message", headers=headers, json={"session_id": sid, "message": msg})
        assert r.status_code == 200, r.text
        for ev in r.json()["events"]:
            client_id = ev.get("client_id") or client_id
    return sid, client_id


@pytest.fixture(scope="module")
def user_a(client):
    email, headers = _register(client)
    sid, client_id = _profile(client, headers)
    return {"email": email, "headers": headers, "session_id": sid, "client_id": client_id}


# --------------------------- auth & isolation ----------------------------- #
def test_unauthenticated_requests_get_401(client):
    for path in ("/api/v1/profile/x", "/api/v1/portfolio/x", "/api/v1/audit/x", "/api/v1/compliance/rules"):
        assert client.get(path).status_code == 401, path
    assert client.post("/api/v1/session/start").status_code == 401


def test_register_login_me_and_duplicates(client):
    email, headers = _register(client)
    assert client.get("/api/v1/auth/me", headers=headers).json()["email"] == email
    dup = client.post("/api/v1/auth/register", json={"email": email, "password": "S3cure-pass!"})
    assert dup.status_code == 409
    bad = client.post("/api/v1/auth/login", data={"username": email, "password": "wrong-password"})
    assert bad.status_code == 401
    weak = client.post("/api/v1/auth/register", json={"email": "x@example.com", "password": "short"})
    assert weak.status_code == 422


def test_profiling_completes_and_persists(client, user_a):
    assert user_a["client_id"], "profiling conversation must yield a client_id"
    r = client.get(f"/api/v1/profile/{user_a['client_id']}", headers=user_a["headers"])
    assert r.status_code == 200
    body = r.json()
    assert body["age"] == 35 and body["suitability_category"]


def test_cross_user_access_is_forbidden(client, user_a):
    _, other = _register(client)
    cid = user_a["client_id"]
    for method, path in (
        ("get", f"/api/v1/profile/{cid}"),
        ("get", f"/api/v1/portfolio/{cid}"),
        ("get", f"/api/v1/audit/{cid}"),
        ("get", f"/api/v1/audit/{cid}/verify"),
    ):
        assert getattr(client, method)(path, headers=other).status_code == 403, path
    r = client.post("/api/v1/trade/execute", headers=other,
                    json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 1, "user_approved": True})
    assert r.status_code == 403


def test_compliance_rules_catalog_has_12_rules(client, user_a):
    rules = client.get("/api/v1/compliance/rules", headers=user_a["headers"]).json()["rules"]
    ids = {r["id"] for r in rules}
    assert len(ids) == 12
    assert {"SUIT-001", "CONC-001", "REG-001", "REG-002", "REG-003", "AML-001"} <= ids


# --------------------------- advice flows --------------------------------- #
def test_allocation_recommendation_is_compliant_and_explained(client, user_a):
    r = client.post("/api/v1/allocation/recommend", headers=user_a["headers"], json={"client_id": user_a["client_id"]})
    assert r.status_code == 200, r.text
    events = r.json()["events"]
    alloc = next(e for e in events if e["agent"] == "AllocationEngine")
    assert abs(sum(alloc["weights"].values()) - 1.0) < 1e-3
    assert "loss of principal" in alloc["text"].lower() or "past performance" in alloc["text"].lower()
    assert "guaranteed" not in alloc["text"].lower()


def test_compare_etfs_ranks_products(client, user_a):
    r = client.post("/api/v1/compare/etfs", headers=user_a["headers"],
                    json={"client_id": user_a["client_id"], "symbols": ["SPY", "VTI", "QQQ"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["winner_symbol"] in {"SPY", "VTI", "QQQ"}
    assert body["rationale"]


def test_output_gate_blocks_prohibited_language(client, user_a):
    orch = app.state.container.orchestrator
    import asyncio

    out = asyncio.run(orch.gate_text("This fund is guaranteed to double your money, risk-free!", None, None))
    assert "guaranteed" not in out.lower() and "risk-free" not in out.lower()
    assert "loss of principal" in out.lower() or "past performance" in out.lower()


def test_bias_alert_surfaces_in_chat(client, user_a):
    r = client.post("/api/v1/chat/message", headers=user_a["headers"],
                    json={"session_id": user_a["session_id"],
                          "message": "The market is crashing, I am terrified and want to sell everything right now!"})
    assert r.status_code == 200
    assert any(e["event"] == "bias_alert" for e in r.json()["events"])


# --------------------------- trading gates -------------------------------- #
def test_trade_without_approval_is_blocked_reg003(client, user_a):
    r = client.post("/api/v1/trade/execute", headers=user_a["headers"],
                    json={"client_id": user_a["client_id"], "symbol": "BND", "side": "BUY", "qty": 2, "user_approved": False})
    assert r.status_code == 403
    assert "REG-003" in str(r.json()["detail"])


def test_approved_trade_fills_updates_portfolio_and_blocks_duplicates(client, user_a):
    cid, h = user_a["client_id"], user_a["headers"]
    prop = client.post("/api/v1/trade/propose", headers=h,
                       json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 5}).json()["proposal"]
    ok = client.post("/api/v1/trade/execute", headers=h,
                     json={"client_id": cid, "proposal_id": prop["proposal_id"], "user_approved": True})
    assert ok.status_code == 200, ok.text
    assert ok.json()["execution"]["status"] == "FILLED"

    pf = client.get(f"/api/v1/portfolio/{cid}", headers=h).json()
    assert any(p["symbol"] == "BND" and p["qty"] == 5 for p in pf["positions"])

    dup = client.post("/api/v1/trade/execute", headers=h,
                      json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 5, "user_approved": True})
    assert dup.status_code == 409, dup.text

    trades = client.get(f"/api/v1/trades/{cid}", headers=h).json()["trades"]
    assert len(trades) >= 1


def test_oversized_single_position_blocked_by_concentration_rule(client):
    _, h = _register(client)
    _, cid = _profile(client, h)
    r = client.post("/api/v1/trade/execute", headers=h,
                    json={"client_id": cid, "symbol": "AAPL", "side": "BUY", "qty": 500, "user_approved": True})
    assert r.status_code == 403, r.text


def test_health_report(client, user_a):
    r = client.post("/api/v1/portfolio/health-report", headers=user_a["headers"], json={"client_id": user_a["client_id"]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert 0 <= body["health_score"] <= 100
    assert "regulatory_disclosure" in body["narrative"]


def test_market_endpoints(client, user_a):
    q = client.get("/api/v1/market/quote/SPY", headers=user_a["headers"])
    assert q.status_code == 200 and q.json()["symbol"] == "SPY"
    m = client.get("/api/v1/market/macro", headers=user_a["headers"])
    assert m.status_code == 200 and "macro" in m.json()


# --------------------------- audit integrity ------------------------------ #
def test_audit_chain_verifies_then_detects_tampering(client, user_a):
    cid, h = user_a["client_id"], user_a["headers"]
    entries = client.get(f"/api/v1/audit/{cid}", headers=h).json()["entries"]
    assert len(entries) >= 3
    assert client.get(f"/api/v1/audit/{cid}/verify", headers=h).json()["valid"] is True

    # Use the engine the app actually connected to; another conftest may have changed DATABASE_URL since.
    from db.database import engine
    db_path = engine.url.database
    con = sqlite3.connect(db_path)
    con.execute("UPDATE audit_log SET details = '{\"tampered\": true}' WHERE id = ?", (entries[-1]["entry_id"],))
    con.commit()
    con.close()

    res = client.get(f"/api/v1/audit/{cid}/verify", headers=h).json()
    assert res["valid"] is False and res["first_invalid_entry"] == entries[-1]["entry_id"]


# --------------------------- websocket ------------------------------------ #
def test_websocket_requires_valid_token(client):
    _, h = _register(client)
    sid = client.post("/api/v1/session/start", headers=h).json()["session_id"]
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/chat/{sid}") as ws:
            ws.receive_json()
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/chat/{sid}?token=not-a-jwt") as ws:
            ws.receive_json()


def test_websocket_propose_and_approve_flow(client):
    _, h = _register(client)
    _, cid = _profile(client, h)
    sid = client.post("/api/v1/session/start", headers=h).json()["session_id"]
    token = h["Authorization"].split()[1]

    with client.websocket_connect(f"/ws/chat/{sid}?token={token}") as ws:
        assert ws.receive_json()["event"] == "agent_response"
        ws.send_text("buy 3 BND")
        proposal_evt = None
        for _ in range(6):
            ev = ws.receive_json()
            if ev["event"] == "trade_proposal":
                proposal_evt = ev
                break
        assert proposal_evt and proposal_evt["proposal"]["symbol"] == "BND"

        ws.send_text("approve")
        seen = set()
        for _ in range(8):
            ev = ws.receive_json()
            seen.add(ev["event"])
            if ev["event"] == "portfolio_update":
                break
        assert {"trade_approved", "compliance_check", "trade_filled", "portfolio_update"} <= seen

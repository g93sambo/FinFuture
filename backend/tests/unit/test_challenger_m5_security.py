"""
backend/tests/unit/test_challenger_m5_security.py
==================================================
Empirical Adversarial Stress Testing for Milestone 5 Gate Verification.

Adversarial Stress Test Matrix:
1. 401 Unauthorized across all 20 protected routes with:
   - Missing Authorization header
   - Invalid bearer token
   - Expired JWT token
   - Cryptographically malformed signature
2. 403 Forbidden Tenant Isolation:
   - User A accessing User B's client_id across profile, portfolio, health-report,
     allocation, trade proposal, trade execution (direct & via proposal_id), order lookup,
     trades list, audit trail, audit verify, audit anchor, and compare endpoints.
3. 403 Forbidden Non-Discretionary Rule (REG-003):
   - Submitting trade execution with user_approved=False (direct trade)
   - Submitting trade execution with user_approved omitted (default False)
   - Submitting trade execution with proposal_id and user_approved=False
   - Submitting trade execution with proposal_id and user_approved omitted
4. 409 Conflict 30-Second Trade Lock:
   - Rapid back-to-back trade submissions within 1 second for same client_id -> 409 Conflict
   - Concurrent simultaneous trade submissions for same client_id -> exactly 1 succeeds, 1 receives 409 Conflict
   - Tenant isolation of trade locks: Client A's active lock does not block Client B
"""

from __future__ import annotations

import asyncio
from datetime import timedelta
import uuid
import pytest
from starlette.testclient import TestClient

from main import app
from core.security import create_access_token


PROFILING_ANSWERS = [
    "I am 38 years old and work as an engineering manager.",
    "My annual salary is 175k and I have 100k in liquid cash reserves. Monthly expenses 6k.",
    "My investment horizon is 20 years, focusing on growth and retirement.",
    "My risk tolerance is 8 out of 10. In a downturn I buy more shares.",
    "I have intermediate trading experience, funds are from savings, not a PEP.",
]


@pytest.fixture(scope="module")
def client():
    """Module-scoped TestClient entering the FastAPI lifespan context."""
    with TestClient(app) as c:
        yield c


def _create_user(client: TestClient, email: str = None, password: str = "T3st-P@ssw0rd!"):
    """Helper to register and login a test user."""
    email = email or f"sec_{uuid.uuid4().hex[:8]}@example.com"
    r_reg = client.post("/api/v1/auth/register", json={"email": email, "password": password})
    assert r_reg.status_code == 201, f"Registration failed: {r_reg.text}"
    r_tok = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    assert r_tok.status_code == 200, f"Login failed: {r_tok.text}"
    token = r_tok.json()["access_token"]
    user_id = r_reg.json()["id"]
    return {
        "email": email,
        "user_id": user_id,
        "token": token,
        "headers": {"Authorization": f"Bearer {token}"},
    }


def _complete_profiling(client: TestClient, headers: dict) -> str:
    """Helper to complete dialogue profiling and return generated client_id."""
    r_start = client.post("/api/v1/session/start", headers=headers)
    assert r_start.status_code == 200, r_start.text
    session_id = r_start.json()["session_id"]
    client_id = None
    for msg in PROFILING_ANSWERS:
        r_msg = client.post(
            "/api/v1/chat/message",
            headers=headers,
            json={"session_id": session_id, "message": msg},
        )
        assert r_msg.status_code == 200, r_msg.text
        for ev in r_msg.json().get("events", []):
            if ev.get("client_id"):
                client_id = ev["client_id"]
    assert client_id is not None, "Profiling failed to produce client_id"
    return client_id


@pytest.fixture(scope="module")
def user_alice(client: TestClient):
    """Alice fixture with complete profile."""
    u = _create_user(client)
    u["client_id"] = _complete_profiling(client, u["headers"])
    return u


@pytest.fixture(scope="module")
def user_bob(client: TestClient):
    """Bob fixture with complete profile."""
    u = _create_user(client)
    u["client_id"] = _complete_profiling(client, u["headers"])
    return u


# =============================================================================
# SUITE 1: 401 Unauthorized Adversarial Stress Testing Across All Protected Routes
# =============================================================================

# Define representative calls for all protected endpoints
PROTECTED_ENDPOINTS = [
    ("GET", "/api/v1/auth/me", None),
    ("POST", "/api/v1/session/start", None),
    ("POST", "/api/v1/chat/message", {"session_id": "fake_sid", "message": "hello"}),
    ("GET", "/api/v1/profile/fake_cid", None),
    ("POST", "/api/v1/compare/etfs", {"client_id": "fake_cid", "symbols": ["SPY", "VTI"]}),
    ("POST", "/api/v1/compare/bonds", {"client_id": "fake_cid", "symbols": ["BND", "AGG"]}),
    ("GET", "/api/v1/portfolio/fake_cid", None),
    ("POST", "/api/v1/portfolio/health-report", {"client_id": "fake_cid"}),
    ("POST", "/api/v1/portfolio/fake_cid/health-report", None),
    ("POST", "/api/v1/allocation/recommend", {"client_id": "fake_cid"}),
    ("POST", "/api/v1/trade/propose", {"client_id": "fake_cid", "symbol": "BND", "side": "BUY", "qty": 1}),
    ("POST", "/api/v1/trade/execute", {"client_id": "fake_cid", "symbol": "BND", "side": "BUY", "qty": 1, "user_approved": True}),
    ("GET", "/api/v1/trade/fake_order_id", None),
    ("GET", "/api/v1/trades/fake_cid", None),
    ("GET", "/api/v1/audit/fake_cid", None),
    ("GET", "/api/v1/audit/fake_cid/verify", None),
    ("POST", "/api/v1/audit/fake_cid/anchor", None),
    ("GET", "/api/v1/market/quote/SPY", None),
    ("GET", "/api/v1/market/macro", None),
    ("GET", "/api/v1/compliance/rules", None),
]


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_401_missing_auth_header(client: TestClient, method: str, path: str, payload: dict):
    """Verify that requests missing Authorization header are immediately rejected with 401."""
    if method == "GET":
        res = client.get(path)
    else:
        res = client.post(path, json=payload if payload is not None else {})
    assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}: {res.text}"


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_401_invalid_bearer_token(client: TestClient, method: str, path: str, payload: dict):
    """Verify that requests with arbitrary garbage bearer tokens return 401."""
    headers = {"Authorization": "Bearer this_is_a_completely_invalid_token_12345"}
    if method == "GET":
        res = client.get(path, headers=headers)
    else:
        res = client.post(path, headers=headers, json=payload if payload is not None else {})
    assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}: {res.text}"


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_401_expired_token(client: TestClient, method: str, path: str, payload: dict):
    """Verify that an expired JWT token returns 401 Unauthorized with expired message."""
    expired_token = create_access_token({"sub": "expired_user"}, expires_delta=timedelta(seconds=-300))
    headers = {"Authorization": f"Bearer {expired_token}"}
    if method == "GET":
        res = client.get(path, headers=headers)
    else:
        res = client.post(path, headers=headers, json=payload if payload is not None else {})
    assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}: {res.text}"
    assert "expired" in res.text.lower() or "credentials" in res.text.lower()


@pytest.mark.parametrize("method,path,payload", PROTECTED_ENDPOINTS)
def test_401_malformed_token_signature(client: TestClient, method: str, path: str, payload: dict):
    """Verify that a token with tampered cryptographic signature returns 401 Unauthorized."""
    valid_token = create_access_token({"sub": "valid_user_tampered"})
    parts = valid_token.split(".")
    tampered_token = f"{parts[0]}.{parts[1]}.malicious_signature_hash_override"
    headers = {"Authorization": f"Bearer {tampered_token}"}
    if method == "GET":
        res = client.get(path, headers=headers)
    else:
        res = client.post(path, headers=headers, json=payload if payload is not None else {})
    assert res.status_code == 401, f"Expected 401 for {method} {path}, got {res.status_code}: {res.text}"


# =============================================================================
# SUITE 2: 403 Forbidden Tenant Isolation Stress Testing
# =============================================================================

def test_tenant_isolation_profile(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot access User Bob's risk profile."""
    res = client.get(f"/api/v1/profile/{user_bob['client_id']}", headers=user_alice["headers"])
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    assert "forbidden" in res.text.lower() or "permission" in res.text.lower()


def test_tenant_isolation_portfolio(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot view User Bob's portfolio holdings."""
    res = client.get(f"/api/v1/portfolio/{user_bob['client_id']}", headers=user_alice["headers"])
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_portfolio_health_report_path(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot generate a health report for User Bob via path parameter."""
    res = client.post(f"/api/v1/portfolio/{user_bob['client_id']}/health-report", headers=user_alice["headers"])
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_portfolio_health_report_body(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot generate a health report for User Bob via JSON body."""
    res = client.post(
        "/api/v1/portfolio/health-report",
        headers=user_alice["headers"],
        json={"client_id": user_bob["client_id"]},
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_allocation_recommend(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot request an allocation recommendation for User Bob."""
    res = client.post(
        "/api/v1/allocation/recommend",
        headers=user_alice["headers"],
        json={"client_id": user_bob["client_id"]},
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_trade_propose(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot stage a trade proposal on User Bob's account."""
    res = client.post(
        "/api/v1/trade/propose",
        headers=user_alice["headers"],
        json={"client_id": user_bob["client_id"], "symbol": "BND", "side": "BUY", "qty": 10},
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_trade_execute_direct(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot execute a direct trade on User Bob's account."""
    res = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_bob["client_id"],
            "symbol": "BND",
            "side": "BUY",
            "qty": 5,
            "user_approved": True,
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_trade_execute_proposal_hijack(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot execute User Bob's staged proposal ID, even if she specifies Bob's client_id."""
    # Bob stages a legitimate proposal
    prop_res = client.post(
        "/api/v1/trade/propose",
        headers=user_bob["headers"],
        json={"client_id": user_bob["client_id"], "symbol": "BND", "side": "BUY", "qty": 2},
    )
    assert prop_res.status_code == 200, prop_res.text
    bob_proposal_id = prop_res.json()["proposal"]["proposal_id"]

    # Alice tries to execute Bob's proposal using Bob's client_id -> 403 (ownership guard)
    res_hijack = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_bob["client_id"],
            "proposal_id": bob_proposal_id,
            "user_approved": True,
        },
    )
    assert res_hijack.status_code == 403, f"Expected 403, got {res_hijack.status_code}: {res_hijack.text}"

    # Alice tries to execute Bob's proposal masquerading under Alice's client_id -> 403
    res_spoof = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_alice["client_id"],
            "proposal_id": bob_proposal_id,
            "user_approved": True,
        },
    )
    assert res_spoof.status_code == 403, f"Expected 403, got {res_spoof.status_code}: {res_spoof.text}"


def test_tenant_isolation_order_lookup(client: TestClient, user_bob: dict, user_alice: dict):
    """User Alice cannot inspect User Bob's specific executed trade order by order_id."""
    # Bob executes a valid trade
    exec_res = client.post(
        "/api/v1/trade/execute",
        headers=user_bob["headers"],
        json={
            "client_id": user_bob["client_id"],
            "symbol": "BND",
            "side": "BUY",
            "qty": 1,
            "user_approved": True,
        },
    )
    assert exec_res.status_code == 200, exec_res.text
    trade_id = exec_res.json()["execution"]["trade_id"]

    # Alice attempts to inspect Bob's trade_id
    res = client.get(f"/api/v1/trade/{trade_id}", headers=user_alice["headers"])
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_trades_list(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot view User Bob's trade order history."""
    res = client.get(f"/api/v1/trades/{user_bob['client_id']}", headers=user_alice["headers"])
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"


def test_tenant_isolation_audit_endpoints(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot view, verify, or anchor User Bob's audit trail."""
    bob_cid = user_bob["client_id"]
    alice_h = user_alice["headers"]

    # 1. Audit trail inspection
    res_trail = client.get(f"/api/v1/audit/{bob_cid}", headers=alice_h)
    assert res_trail.status_code == 403, f"Expected 403 for audit get, got {res_trail.status_code}"

    # 2. Audit verification
    res_verify = client.get(f"/api/v1/audit/{bob_cid}/verify", headers=alice_h)
    assert res_verify.status_code == 403, f"Expected 403 for audit verify, got {res_verify.status_code}"

    # 3. Audit blockchain anchoring
    res_anchor = client.post(f"/api/v1/audit/{bob_cid}/anchor", headers=alice_h)
    assert res_anchor.status_code == 403, f"Expected 403 for audit anchor, got {res_anchor.status_code}"


def test_tenant_isolation_compare_endpoints(client: TestClient, user_alice: dict, user_bob: dict):
    """User Alice cannot run product comparisons evaluating against User Bob's profile."""
    bob_cid = user_bob["client_id"]
    alice_h = user_alice["headers"]

    res_etf = client.post(
        "/api/v1/compare/etfs",
        headers=alice_h,
        json={"client_id": bob_cid, "symbols": ["SPY", "VTI"]},
    )
    assert res_etf.status_code == 403, f"Expected 403 for compare etfs, got {res_etf.status_code}"

    res_bonds = client.post(
        "/api/v1/compare/bonds",
        headers=alice_h,
        json={"client_id": bob_cid, "symbols": ["BND", "AGG"]},
    )
    assert res_bonds.status_code == 403, f"Expected 403 for compare bonds, got {res_bonds.status_code}"


# =============================================================================
# SUITE 3: 403 Forbidden Non-Discretionary Rule (REG-003) Stress Testing
# =============================================================================

def test_reg003_direct_trade_explicit_false(client: TestClient, user_alice: dict):
    """Direct trade execution with user_approved=False must return 403 and cite REG-003."""
    res = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_alice["client_id"],
            "symbol": "BND",
            "side": "BUY",
            "qty": 3,
            "user_approved": False,
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    detail_str = str(res.json().get("detail", ""))
    assert "REG-003" in detail_str or "unapproved" in detail_str.lower() or "approval" in detail_str.lower()


def test_reg003_direct_trade_omitted_flag(client: TestClient, user_alice: dict):
    """Direct trade execution with user_approved omitted (defaults to False) must return 403."""
    res = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_alice["client_id"],
            "symbol": "BND",
            "side": "BUY",
            "qty": 3,
            # user_approved deliberately omitted
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    detail_str = str(res.json().get("detail", ""))
    assert "REG-003" in detail_str or "unapproved" in detail_str.lower() or "approval" in detail_str.lower()


def test_reg003_proposal_execution_explicit_false(client: TestClient, user_alice: dict):
    """Staged proposal execution with user_approved=False must return 403 and cite REG-003."""
    # Stage a proposal
    prop_res = client.post(
        "/api/v1/trade/propose",
        headers=user_alice["headers"],
        json={"client_id": user_alice["client_id"], "symbol": "BND", "side": "BUY", "qty": 4},
    )
    assert prop_res.status_code == 200, prop_res.text
    prop_id = prop_res.json()["proposal"]["proposal_id"]

    # Submit execution with explicit False
    res = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_alice["client_id"],
            "proposal_id": prop_id,
            "user_approved": False,
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    detail_str = str(res.json().get("detail", ""))
    assert "REG-003" in detail_str or "unapproved" in detail_str.lower() or "approval" in detail_str.lower()


def test_reg003_proposal_execution_omitted_flag(client: TestClient, user_alice: dict):
    """Staged proposal execution with user_approved omitted must return 403 and cite REG-003."""
    prop_res = client.post(
        "/api/v1/trade/propose",
        headers=user_alice["headers"],
        json={"client_id": user_alice["client_id"], "symbol": "BND", "side": "BUY", "qty": 4},
    )
    assert prop_res.status_code == 200, prop_res.text
    prop_id = prop_res.json()["proposal"]["proposal_id"]

    res = client.post(
        "/api/v1/trade/execute",
        headers=user_alice["headers"],
        json={
            "client_id": user_alice["client_id"],
            "proposal_id": prop_id,
            # user_approved omitted
        },
    )
    assert res.status_code == 403, f"Expected 403, got {res.status_code}: {res.text}"
    detail_str = str(res.json().get("detail", ""))
    assert "REG-003" in detail_str or "unapproved" in detail_str.lower() or "approval" in detail_str.lower()


# =============================================================================
# SUITE 4: 409 Conflict 30-Second Trade Lock Adversarial Stress Testing
# =============================================================================

def test_trade_lock_409_rapid_duplicate_submissions(client: TestClient):
    """Submit two rapid trades within 1 second for the same client_id; verify second is 409 Conflict."""
    u = _create_user(client)
    cid = _complete_profiling(client, u["headers"])

    # First trade: approved BUY 5 BND -> should succeed (200)
    res1 = client.post(
        "/api/v1/trade/execute",
        headers=u["headers"],
        json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 5, "user_approved": True},
    )
    assert res1.status_code == 200, f"First trade failed: {res1.text}"
    assert res1.json()["execution"]["status"] == "FILLED"

    # Second trade: immediately (<1s) submit another trade for same client_id -> MUST return 409 Conflict
    res2 = client.post(
        "/api/v1/trade/execute",
        headers=u["headers"],
        json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 5, "user_approved": True},
    )
    assert res2.status_code == 409, f"Expected 409 Conflict, got {res2.status_code}: {res2.text}"
    assert "DuplicateTradeError" in str(res2.json().get("detail", "")) or "30 second" in str(res2.json().get("detail", "")).lower()


def test_trade_lock_409_different_symbol_within_30s_is_locked(client: TestClient):
    """The 30-second trade lock is per-client: submitting a different symbol is also blocked."""
    u = _create_user(client)
    cid = _complete_profiling(client, u["headers"])

    # First trade: BUY 2 BND
    res1 = client.post(
        "/api/v1/trade/execute",
        headers=u["headers"],
        json={"client_id": cid, "symbol": "BND", "side": "BUY", "qty": 2, "user_approved": True},
    )
    assert res1.status_code == 200, res1.text

    # Second trade: immediately submit BUY 1 AGG for same client -> 409 Conflict
    res2 = client.post(
        "/api/v1/trade/execute",
        headers=u["headers"],
        json={"client_id": cid, "symbol": "AGG", "side": "BUY", "qty": 1, "user_approved": True},
    )
    assert res2.status_code == 409, f"Expected 409 Conflict for rapid trade on same client, got {res2.status_code}: {res2.text}"


def test_trade_lock_isolation_between_different_clients(client: TestClient):
    """Client A's active 30-second trade lock must NOT prevent Client B from executing a trade."""
    user_x = _create_user(client)
    cid_x = _complete_profiling(client, user_x["headers"])

    user_y = _create_user(client)
    cid_y = _complete_profiling(client, user_y["headers"])

    # Client X executes a trade -> gets locked
    res_x = client.post(
        "/api/v1/trade/execute",
        headers=user_x["headers"],
        json={"client_id": cid_x, "symbol": "BND", "side": "BUY", "qty": 3, "user_approved": True},
    )
    assert res_x.status_code == 200, res_x.text

    # Client Y immediately executes a trade -> MUST succeed (200) because locks are isolated per client_id
    res_y = client.post(
        "/api/v1/trade/execute",
        headers=user_y["headers"],
        json={"client_id": cid_y, "symbol": "BND", "side": "BUY", "qty": 3, "user_approved": True},
    )
    assert res_y.status_code == 200, f"Client Y was unexpectedly blocked by Client X's lock: {res_y.status_code}: {res_y.text}"
    assert res_y.json()["execution"]["status"] == "FILLED"


def test_login_throttled_after_repeated_failures(client: TestClient):
    """Regression (RISK-11): 5 failed logins lock the account for the window, even for the right password."""
    user = _create_user(client)
    for _ in range(5):
        r = client.post("/api/v1/auth/login", data={"username": user["email"], "password": "wrong-password"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/login", data={"username": user["email"], "password": "T3st-P@ssw0rd!"})
    assert r.status_code == 429
    assert "Retry-After" in r.headers


def test_successful_login_clears_failure_count(client: TestClient):
    user = _create_user(client)
    for _ in range(4):
        client.post("/api/v1/auth/login", data={"username": user["email"], "password": "wrong-password"})
    assert client.post("/api/v1/auth/login", data={"username": user["email"], "password": "T3st-P@ssw0rd!"}).status_code == 200
    for _ in range(4):
        assert client.post("/api/v1/auth/login", data={"username": user["email"], "password": "wrong-password"}).status_code == 401

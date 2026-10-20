"""RISK-26: every Sepolia anchor spends the server wallet's test ETH, so anchoring is rate
limited per client (cooldown) and server-wide (hourly cap)."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

import api.routes.audit as audit_routes
from core.config import Settings, settings
from main import app

ONBOARDING = {
    "age": 35, "employment_status": "employed", "annual_income": 150000, "liquid_assets": 100000,
    "monthly_expenses": 4000, "risk_tolerance_score": 7, "investment_horizon_years": 15,
}


class FakeAnchoring:
    def __init__(self):
        self.sent = 0
        self.fail = False

    async def anchor_client_audit_trail(self, db, client_id):
        if self.fail:
            return SimpleNamespace(tx_hash=None, merkle_root="ab" * 32, explorer_url=None, chain_id=11155111,
                                   block_number=None, entries_count=1, status="failed", error="rpc down")
        self.sent += 1
        return SimpleNamespace(tx_hash="0x" + "cd" * 32, merkle_root="ab" * 32, explorer_url="https://sepolia.etherscan.io/tx/x",
                               chain_id=11155111, block_number=1, entries_count=1, status="submitted", error=None)


@pytest.fixture
def fake_wallet(monkeypatch):
    fake = FakeAnchoring()
    monkeypatch.setattr(Settings, "is_anchoring_configured", property(lambda self: True))
    monkeypatch.setattr(settings, "dry_run", False)
    monkeypatch.setattr(audit_routes, "get_anchoring_service", lambda: fake)
    monkeypatch.setattr(audit_routes, "_recent_anchors", audit_routes.deque())
    return fake


async def _client_with_profile(client: AsyncClient) -> tuple[str, dict]:
    email, pw = f"anchor_{uuid.uuid4().hex[:8]}@example.com", "Harbor-Lights-7392"
    await client.post("/api/v1/auth/register", json={"email": email, "password": pw})
    token = (await client.post("/api/v1/auth/login", data={"username": email, "password": pw})).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    profile = (await client.post("/api/v1/profile/onboarding", json=ONBOARDING, headers=headers)).json()
    return profile["client_id"], headers


@pytest.mark.asyncio
async def test_anchoring_has_a_per_client_cooldown(fake_wallet):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cid, headers = await _client_with_profile(client)
            assert (await client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)).status_code == 200
            second = await client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)
            assert second.status_code == 429
            assert int(second.headers["Retry-After"]) > 0
            assert fake_wallet.sent == 1


@pytest.mark.asyncio
async def test_failed_send_does_not_use_up_the_cooldown(fake_wallet):
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            cid, headers = await _client_with_profile(client)
            fake_wallet.fail = True
            assert (await client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)).status_code == 200
            fake_wallet.fail = False
            assert (await client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)).status_code == 200
            assert fake_wallet.sent == 1


@pytest.mark.asyncio
async def test_anchoring_has_a_server_wide_hourly_cap(fake_wallet, monkeypatch):
    monkeypatch.setattr(settings, "anchor_max_per_hour", 2)
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            statuses = []
            for _ in range(3):
                cid, headers = await _client_with_profile(client)
                statuses.append((await client.post(f"/api/v1/audit/{cid}/anchor", headers=headers)).status_code)
            assert statuses == [200, 200, 429]
            assert fake_wallet.sent == 2

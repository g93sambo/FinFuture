"""Regressions for issues found in team testing: rebalance crash, vague navigation answers,
off-topic review rewrites, and forgetting earlier images."""

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from agents.orchestrator import HISTORY_IMAGE_TURNS, _trim_history_images
from agents.review_stage import RISK_NOTE, ReviewStage
from main import app


async def _client_with_holdings(client: AsyncClient) -> str:
    email = f"chat-{uuid.uuid4().hex[:8]}@example.com"
    await client.post("/api/v1/auth/register", json={"email": email, "password": "Sup3r-secret!"})
    token = (await client.post("/api/v1/auth/login", data={"username": email, "password": "Sup3r-secret!"})).json()["access_token"]
    client.headers["Authorization"] = f"Bearer {token}"
    cid = (await client.post("/api/v1/profile/onboarding", json={
        "age": 35, "employment_status": "employed", "annual_income": 150000, "liquid_assets": 100000,
        "monthly_expenses": 4000, "risk_tolerance_score": 7, "investment_horizon_years": 15,
    })).json()["client_id"]
    p = (await client.post("/api/v1/trade/propose", json={"client_id": cid, "symbol": "SPY", "side": "BUY", "qty": 1})).json()
    await client.post("/api/v1/trade/execute", json={"client_id": cid, "proposal_id": p["proposal"]["proposal_id"], "user_approved": True})
    return (await client.post("/api/v1/session/start", json={})).json()["session_id"]


@pytest.mark.asyncio
async def test_rebalance_command_lists_plan_and_stages_first_order():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            sid = await _client_with_holdings(client)
            r = await client.post("/api/v1/chat/message", json={"session_id": sid, "message": "Execute 5 rebalance orders."})
            assert r.status_code == 200
            proposals = [e for e in r.json()["events"] if e.get("kind") == "trade_proposal" or e.get("proposal_id")]
            assert proposals, r.json()["events"]
            assert "Rebalancing plan" in proposals[0]["text"]


@pytest.mark.asyncio
async def test_navigation_question_gets_the_specific_page():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            sid = await _client_with_holdings(client)
            r = await client.post("/api/v1/chat/message", json={"session_id": sid, "message": "what page do I go to to buy?"})
            text = r.json()["text"]
            assert "/app/trade" in text and "quick guide" not in text
            r = await client.post("/api/v1/chat/message", json={"session_id": sid, "message": "where can I see my audit history?"})
            assert "/app/audit" in r.json()["text"]


@pytest.mark.asyncio
async def test_missing_risk_mention_adds_note_without_rewriting():
    draft = "I can't create images, but I recommend checking the Markets page; you could invest in a broad ETF."
    res = await ReviewStage().review_and_revise(draft, client_context=None, openai_client=None)
    assert res.passed and not res.escalated_to_human
    assert res.final_text == draft + RISK_NOTE


@pytest.mark.asyncio
async def test_passing_mention_of_portfolio_is_not_flagged():
    res = await ReviewStage().review_and_revise("Your portfolio page shows holdings and cash.", client_context=None)
    assert res.passed and res.final_text == "Your portfolio page shows holdings and cash."


def test_history_keeps_only_recent_images():
    history = [{"role": "user", "content": f"img {i}", "images": [f"data:image/png;base64,{i}"]} for i in range(5)]
    _trim_history_images(history)
    kept = [t for t in history if t.get("images")]
    assert len(kept) == HISTORY_IMAGE_TURNS
    assert kept[-1]["content"] == "img 4"

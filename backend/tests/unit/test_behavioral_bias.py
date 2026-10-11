"""
backend/tests/unit/test_behavioral_bias.py
==========================================
Unit tests for BehavioralBiasAgent covering dual-layer bias scoring, 5 cognitive biases,
4 telemetry channels, database persistence and profile sync, offline fallback, and fixtures.
"""

import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from pathlib import Path

from agents.behavioral_bias import BehavioralBiasAgent
from services.cache import CacheService
from db.models import DBClientProfile, DBBehavioralMemory


@pytest.fixture
def bias_agent():
    cache_svc = CacheService()
    cache_svc._redis_available = False
    return BehavioralBiasAgent(cache_service=cache_svc, openai_client=None, heuristic_threshold=0.60)


@pytest.fixture
def client_profile_in_db(db_session):
    async def _create(client_id="c_test_bias"):
        profile = DBClientProfile(
            client_id=client_id,
            age=35,
            employment_status="employed",
            annual_income=100000.0,
            emotional_risk_score=20.0,
            panic_sell_likelihood=0.10,
            detected_biases=[],
        )
        db_session.add(profile)
        await db_session.commit()
        await db_session.refresh(profile)
        return profile
    return _create


# --- Heuristic Layer Tests ---

def test_heuristic_loss_aversion_panic(bias_agent):
    text = "The market dropped 4% today, I can't take the pain! Sell everything right now and put it all in cash."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert len(detections) > 0
    top = detections[0]
    assert top.bias_type == "loss_aversion"
    assert top.score >= 0.80
    assert top.severity == "high"


def test_heuristic_loss_aversion_fear(bias_agent):
    text = "I cannot afford to lose any money in this portfolio. I am terrified of losing my savings."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert any(d.bias_type == "loss_aversion" and d.score >= 0.65 for d in detections)


def test_heuristic_recency_bias_bull(bias_agent):
    text = "Tech stocks only go up, look at the last week! It will keep going up forever, so let's put more in."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert any(d.bias_type == "recency_bias" and d.score >= 0.70 for d in detections)


def test_heuristic_recency_bias_bear(bias_agent):
    text = "The market has been dropping every day this week, it will keep falling forever. It is never going to recover."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert any(d.bias_type == "recency_bias" and d.score >= 0.70 for d in detections)


def test_heuristic_overconfidence(bias_agent):
    text = "I'm 100% sure this stock is guaranteed to double in 3 months. Diversification is for idiots, let's go all in."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert len(detections) > 0
    over = next((d for d in detections if d.bias_type == "overconfidence"), None)
    assert over is not None
    assert over.score >= 0.85
    assert over.severity == "high"


def test_heuristic_herd_mentality(bias_agent):
    text = "Everyone on Reddit and WallStreetBets is buying this coin. All my friends are making money, I have huge FOMO!"
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert any(d.bias_type == "herd_mentality" and d.score >= 0.75 for d in detections)


def test_heuristic_disposition_effect(bias_agent):
    text = "I want to sell my winners to lock in this small profit, but for my losing positions I refuse to sell at a loss until they get back to even."
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert any(d.bias_type == "disposition_effect" and d.score >= 0.80 for d in detections)


def test_heuristic_neutral_message(bias_agent):
    text = "Can you explain the difference between broad market index funds and intermediate Treasury bonds for a 10-year retirement goal?"
    detections = bias_agent.evaluate_heuristic_layer(text)
    assert len(detections) == 0


def test_heuristic_multiple_biases(bias_agent):
    text = "Everyone on Reddit is buying this stock and I have FOMO! Plus I am 100% sure diversification is for idiots."
    detections = bias_agent.evaluate_heuristic_layer(text)
    bias_types = [d.bias_type for d in detections]
    assert "herd_mentality" in bias_types
    assert "overconfidence" in bias_types


# --- Layer 2 & Fallback Tests ---

@pytest.mark.asyncio
async def test_llm_confirmation_online_mock(bias_agent):
    mock_client = MagicMock()
    mock_response = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = json.dumps([
        {
            "bias_type": "loss_aversion",
            "confidence": 0.92,
            "severity": "high",
            "reasoning": "User is panicked over market drop.",
            "intervention": "Cool off for 24h.",
            "cool_off_recommended": True
        }
    ])
    mock_response.choices = [mock_choice]
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)

    bias_agent.client = mock_client
    # Temporarily set OPENAI_API_KEY
    import os
    orig = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "mock_key"
    try:
        results = await bias_agent.detect_bias("c1", "Sell everything right now!")
        assert len(results) == 1
        assert results[0].bias_type == "loss_aversion"
        assert results[0].trigger_source == "dialogue_llm"
        assert results[0].confidence == 0.92
    finally:
        if orig is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = orig
        bias_agent.client = None


@pytest.mark.asyncio
async def test_llm_fallback_no_api_key(bias_agent):
    # No client, no API key -> should use Layer 1 heuristics without raising error
    results = await bias_agent.detect_bias("c1", "The market dropped 4%, sell everything!")
    assert len(results) > 0
    assert results[0].trigger_source == "dialogue_heuristic"
    assert results[0].bias_type == "loss_aversion"


@pytest.mark.asyncio
async def test_llm_fallback_on_api_exception(bias_agent):
    mock_client = MagicMock()
    mock_client.chat.completions.create = AsyncMock(side_effect=Exception("Connection timeout"))
    bias_agent.client = mock_client

    import os
    orig = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "mock_key"
    try:
        results = await bias_agent.detect_bias("c1", "Diversification is for idiots, guaranteed to double!")
        assert len(results) > 0
        assert results[0].trigger_source == "dialogue_heuristic"
        assert results[0].bias_type == "overconfidence"
    finally:
        if orig is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = orig
        bias_agent.client = None


@pytest.mark.asyncio
async def test_llm_fallback_on_malformed_json(bias_agent):
    mock_client = MagicMock()
    mock_choice = MagicMock()
    mock_choice.message.content = "Not valid JSON output here"
    mock_response = MagicMock(choices=[mock_choice])
    mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
    bias_agent.client = mock_client

    import os
    orig = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = "mock_key"
    try:
        results = await bias_agent.detect_bias("c1", "Everyone on reddit is buying, big fomo!")
        assert len(results) > 0
        assert results[0].trigger_source == "dialogue_heuristic"
    finally:
        if orig is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = orig
        bias_agent.client = None


# --- Telemetry Channel Tests ---

@pytest.mark.asyncio
async def test_telemetry_rapid_portfolio_checks(bias_agent):
    client_id = "c_rapid_check"
    # First 2 checks: under threshold
    s1 = await bias_agent.record_portfolio_check(client_id)
    assert s1 is None
    s2 = await bias_agent.record_portfolio_check(client_id)
    assert s2 is None

    # 3rd check: breaches threshold
    s3 = await bias_agent.record_portfolio_check(client_id)
    assert s3 is not None
    assert s3.signal_type == "rapid_checks"
    assert s3.bias_type == "loss_aversion"
    assert s3.metrics["check_count"] == 3


def test_telemetry_panic_dip_sell(bias_agent):
    sig = bias_agent.check_panic_dip_sell(
        trade_side="SELL",
        symbol="NVDA",
        asset_price_change_24h=-5.2,
    )
    assert sig is not None
    assert sig.signal_type == "panic_dip_sell"
    assert sig.severity == "high"
    assert sig.cool_off_recommended is True


def test_telemetry_normal_sell_pass(bias_agent):
    sig = bias_agent.check_panic_dip_sell(
        trade_side="SELL",
        symbol="NVDA",
        asset_price_change_24h=2.1,
    )
    assert sig is None


def test_telemetry_concentration_bias(bias_agent):
    positions = {"TSLA": 42000.0, "SPY": 8000.0}
    total_val = 50000.0  # TSLA = 84%
    sig = bias_agent.check_concentration_bias(positions, total_val)
    assert sig is not None
    assert sig.signal_type == "concentration_risk"
    assert sig.bias_type == "overconfidence"
    assert sig.severity == "high"
    assert sig.metrics["symbol"] == "TSLA"


def test_telemetry_excessive_trading(bias_agent):
    sig = bias_agent.check_trading_frequency(trades_count_recent=6, window_hours=24)
    assert sig is not None
    assert sig.signal_type == "excessive_trading"
    assert sig.bias_type == "overconfidence"
    assert sig.cool_off_recommended is True


@pytest.mark.asyncio
async def test_evaluate_telemetry_multi(bias_agent):
    telemetry = {
        "trade_side": "SELL",
        "symbol": "QQQ",
        "asset_price_change_24h": -4.0,
        "positions": {"NVDA": 40000.0, "SPY": 10000.0},
        "total_value": 50000.0,
        "trades_count_recent": 6,
    }
    signals = await bias_agent.evaluate_telemetry("c_multi_tel", telemetry)
    sig_types = [s.signal_type for s in signals]
    assert "panic_dip_sell" in sig_types
    assert "concentration_risk" in sig_types
    assert "excessive_trading" in sig_types


# --- Database Persistence & Profile Sync Tests ---

@pytest.mark.asyncio
async def test_database_persistence_and_profile_sync(bias_agent, db_session, client_profile_in_db):
    client_id = "c_db_sync_1"
    client = await client_profile_in_db(client_id=client_id)
    init_emotional = client.emotional_risk_score
    init_panic = client.panic_sell_likelihood

    # Record bias event
    mem = await bias_agent.record_bias_event(
        db=db_session,
        client_id=client_id,
        bias_type="loss_aversion",
        severity="high",
        trigger_context={"test": True},
        intervention_text="Cool off recommended.",
    )
    assert mem.id is not None
    assert mem.bias_type == "loss_aversion"

    # Verify profile synchronization
    await db_session.refresh(client)
    assert "loss_aversion" in client.detected_biases
    assert client.emotional_risk_score > init_emotional
    assert client.panic_sell_likelihood > init_panic

    # Verify history retrieval
    history = await bias_agent.get_bias_history(db_session, client_id)
    assert len(history) >= 1
    assert history[0].bias_type == "loss_aversion"

    # Verify summary profile
    summary = await bias_agent.get_client_bias_profile(db_session, client_id)
    assert summary["total_bias_events"] >= 1
    assert "loss_aversion" in summary["bias_distribution"]


@pytest.mark.asyncio
async def test_backwards_compatible_analyze_message(bias_agent):
    res = await bias_agent.analyze_message("I am terrified of losing money, sell everything!")
    assert isinstance(res, list)
    assert len(res) > 0
    assert "bias_type" in res[0]
    assert "intervention" in res[0]


# --- Fixture Scenarios Evaluation ---

def test_fixture_scenarios_file_evaluation(bias_agent):
    fixture_path = Path(__file__).parent.parent / "fixtures" / "behavioral_scenarios.json"
    assert fixture_path.exists(), "behavioral_scenarios.json must exist"

    with open(fixture_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    scenarios = data.get("scenarios", {})
    assert len(scenarios) >= 12

    for name, sc in scenarios.items():
        if sc.get("type") == "dialogue":
            text = sc["text"]
            detections = bias_agent.evaluate_heuristic_layer(text)
            expected = sc.get("expected_bias")
            if expected is None:
                assert len(detections) == 0, f"Expected no bias for {name}"
            else:
                top = next((d for d in detections if d.bias_type == expected), None)
                assert top is not None, f"Expected {expected} for scenario {name}"
                assert top.score >= sc["expected_min_score"], f"Score for {name} too low: {top.score}"

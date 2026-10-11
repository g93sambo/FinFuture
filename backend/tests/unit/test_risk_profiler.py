"""
backend/tests/unit/test_risk_profiler.py
========================================
Unit tests for RiskProfilerAgent covering FSM state transitions, draft caching,
quantitative scoring, KYC/AML validation, DB persistence, and legacy compatibility.
"""

import pytest
from agents.risk_profiler import (
    RiskProfilerAgent,
    STATE_DEMOGRAPHICS,
    STATE_FINANCIAL_SITUATION,
    STATE_TIME_HORIZON,
    STATE_RISK_TOLERANCE,
    STATE_EXPERIENCE,
    STATE_COMPLETE,
)
from services.cache import InMemoryCache, CacheService, key_profile_draft
from db.models import DBClientProfile


@pytest.fixture
def agent():
    cache_svc = CacheService()
    cache_svc._redis_available = False
    return RiskProfilerAgent(cache_service=cache_svc, openai_client=None)


@pytest.mark.asyncio
async def test_fsm_initial_state_demographics(agent):
    res = await agent.process_input("session_1", "Hello, I want to invest.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_DEMOGRAPHICS
    assert "age" in res["response"].lower() or "employment" in res["response"].lower()


@pytest.mark.asyncio
async def test_fsm_demographics_transition(agent):
    res = await agent.process_input("session_2", "I am 35 years old and I am employed as a software engineer.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_FINANCIAL_SITUATION
    assert agent._parse_currency_value("100") == 100.0


@pytest.mark.asyncio
async def test_fsm_financial_situation_transition(agent):
    # Step 1: demographics
    await agent.process_input("session_3", "I am 40 years old and employed with 2 kids.")
    # Step 2: financial situation
    res = await agent.process_input("session_3", "My income is 150k and I have 80k in savings. Monthly expenses are 5k.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_TIME_HORIZON


@pytest.mark.asyncio
async def test_fsm_time_horizon_transition(agent):
    await agent.process_input("session_4", "I am 40 years old and employed.")
    await agent.process_input("session_4", "My income is 120k and liquid savings are 50k.")
    res = await agent.process_input("session_4", "My investment horizon is 10 years and primary goal is long-term growth.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_RISK_TOLERANCE


@pytest.mark.asyncio
async def test_fsm_risk_tolerance_transition(agent):
    await agent.process_input("session_5", "I am 30 years old and employed.")
    await agent.process_input("session_5", "Income is 90k, savings 40k.")
    await agent.process_input("session_5", "Horizon is 15 years, goal is growth.")
    res = await agent.process_input("session_5", "My risk tolerance score is 7 out of 10. In a crash I would hold or buy more.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_EXPERIENCE


@pytest.mark.asyncio
async def test_fsm_experience_to_synthesis_transition(agent, db_session):
    sid = "session_full"
    await agent.process_input(sid, "I am 32 years old, employed.")
    await agent.process_input(sid, "Income is 110k, liquid savings 60k.")
    await agent.process_input(sid, "Horizon is 12 years for growth.")
    await agent.process_input(sid, "Risk tolerance is 7.5/10 and I would buy more at discount.")
    res = await agent.process_input(
        sid,
        "I have intermediate experience, source of funds is salary, not a PEP.",
        db=db_session,
    )
    assert res["status"] == "complete"
    assert res["current_state"] == STATE_COMPLETE
    assert res["profile"] is not None
    assert res["profile"]["suitability_category"] in ["Moderate", "Growth", "Aggressive Growth"]
    assert res["profile"]["kyc_verified"] is True
    assert res["profile"]["aml_flag"] is False


@pytest.mark.asyncio
async def test_fsm_incomplete_input_stays_in_state(agent):
    # Only age, missing employment
    res = await agent.process_input("session_inc", "I am 28 years old.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_DEMOGRAPHICS
    assert "employment" in res["response"].lower()


@pytest.mark.asyncio
async def test_fsm_multi_field_extraction(agent, db_session):
    full_message = (
        "I am 38 years old, employed full-time with 1 dependent. "
        "My annual salary is $160,000 with $90,000 in liquid savings, $4,000 monthly expenses, and zero debt. "
        "My investment timeline is 15 years for wealth growth. "
        "My risk score is 8 out of 10 and in a dip I buy more. "
        "I have advanced investment experience, funds come from salary, and I am not a PEP."
    )
    res = await agent.process_input("session_multi", full_message, db=db_session)
    assert res["status"] == "complete"
    assert res["profile"]["age"] == 38
    assert res["profile"]["employment_status"] == "employed"
    assert res["profile"]["annual_income"] == 160000.0
    assert res["profile"]["liquid_assets"] == 90000.0
    assert res["profile"]["investment_horizon_years"] == 15
    assert res["profile"]["risk_tolerance_score"] == 8.0
    assert res["profile"]["suitability_category"] == "Growth"


@pytest.mark.asyncio
async def test_fsm_underage_rejection(agent):
    res = await agent.process_input("session_underage", "I am 16 years old and student.")
    assert res["status"] == "in_progress"
    assert res["current_state"] == STATE_DEMOGRAPHICS
    assert "18 years old" in res["response"]


@pytest.mark.asyncio
async def test_cache_draft_persistence_and_resume(agent):
    sid = "session_resume"
    await agent.process_input(sid, "I am 45 years old and employed.")
    draft_key = key_profile_draft(sid)
    draft = await agent.cache.get_json(draft_key)
    assert draft is not None
    assert draft["extracted_data"]["age"] == 45
    assert draft["current_state"] == STATE_FINANCIAL_SITUATION

    # Resumed turn
    res = await agent.process_input(sid, "My income is 200k with 100k liquid savings.")
    assert res["current_state"] == STATE_TIME_HORIZON


@pytest.mark.asyncio
async def test_cache_draft_eviction_on_completion(agent, db_session):
    sid = "session_evict"
    full_text = (
        "I am 30 years old, employed. Income 100k, liquid savings 50k. "
        "Horizon 10 years for growth. Risk tolerance 6 out of 10, I hold steady. "
        "Intermediate experience, salary source, not a PEP."
    )
    res = await agent.process_input(sid, full_text, db=db_session)
    assert res["status"] == "complete"
    draft_key = key_profile_draft(sid)
    assert await agent.cache.get_json(draft_key) is None


def test_scoring_suitability_mapping(agent):
    # 1. Conservative
    s1, cat1 = agent.calculate_suitability_score({
        "risk_tolerance_score": 2.0,
        "loss_capacity": "low",
        "investment_horizon_years": 1,
        "primary_goal": "capital_preservation",
        "investment_experience": "none",
        "liquid_assets": 10000.0,
        "monthly_expenses": 2000.0,
    })
    assert cat1 == "Conservative"

    # 2. Moderate Conservative
    s2, cat2 = agent.calculate_suitability_score({
        "risk_tolerance_score": 4.0,
        "loss_capacity": "medium",
        "investment_horizon_years": 2,
        "primary_goal": "income",
        "investment_experience": "novice",
        "liquid_assets": 20000.0,
        "monthly_expenses": 2000.0,
    })
    assert cat2 == "Moderate Conservative"

    # 3. Moderate
    s3, cat3 = agent.calculate_suitability_score({
        "risk_tolerance_score": 6.0,
        "loss_capacity": "medium",
        "investment_horizon_years": 7,
        "primary_goal": "balanced",
        "investment_experience": "intermediate",
        "liquid_assets": 50000.0,
        "monthly_expenses": 3000.0,
    })
    assert cat3 == "Moderate"

    # 4. Growth
    s4, cat4 = agent.calculate_suitability_score({
        "risk_tolerance_score": 7.5,
        "loss_capacity": "high",
        "investment_horizon_years": 15,
        "primary_goal": "growth",
        "investment_experience": "advanced",
        "liquid_assets": 100000.0,
        "monthly_expenses": 4000.0,
    })
    assert cat4 == "Growth"

    # 5. Aggressive Growth
    s5, cat5 = agent.calculate_suitability_score({
        "risk_tolerance_score": 9.5,
        "loss_capacity": "high",
        "investment_horizon_years": 25,
        "primary_goal": "aggressive_growth",
        "investment_experience": "expert",
        "liquid_assets": 200000.0,
        "monthly_expenses": 5000.0,
    })
    assert cat5 == "Aggressive Growth"


def test_scoring_suitability_regulatory_guardrails(agent):
    # Short horizon guard: high risk but horizon < 3 years -> capped at <= 4.0 (Moderate Conservative)
    s_short, cat_short = agent.calculate_suitability_score({
        "risk_tolerance_score": 9.0,
        "loss_capacity": "high",
        "investment_horizon_years": 1,
        "primary_goal": "growth",
        "investment_experience": "advanced",
        "liquid_assets": 100000.0,
        "monthly_expenses": 3000.0,
    })
    assert s_short <= 4.0
    assert cat_short in ["Conservative", "Moderate Conservative"]

    # Low loss capacity guard: capped at <= 5.0 (Moderate)
    s_low, cat_low = agent.calculate_suitability_score({
        "risk_tolerance_score": 9.5,
        "loss_capacity": "low",
        "investment_horizon_years": 15,
        "primary_goal": "aggressive_growth",
        "investment_experience": "expert",
        "liquid_assets": 1000.0,
        "monthly_expenses": 2000.0,
    })
    assert s_low <= 5.0
    assert cat_low in ["Conservative", "Moderate Conservative", "Moderate"]


def test_scoring_emotional_risk_score(agent):
    # Disciplined investor
    e_low = agent.calculate_emotional_risk_score({
        "drawdown_reaction": "buy_more",
        "monitoring_frequency": "annually",
        "detected_biases": [],
        "annual_income": 150000.0,
        "liquid_assets": 100000.0,
        "monthly_expenses": 3000.0,
        "existing_debts": 0.0,
    })
    assert e_low < 30.0

    # Panicky investor
    e_high = agent.calculate_emotional_risk_score({
        "drawdown_reaction": "sell_all",
        "monitoring_frequency": "multiple daily",
        "detected_biases": ["loss_aversion", "recency_bias"],
        "annual_income": 50000.0,
        "liquid_assets": 2000.0,
        "monthly_expenses": 3000.0,
        "existing_debts": 35000.0,
    })
    assert e_high > 75.0


def test_scoring_panic_sell_likelihood(agent):
    data_panic = {
        "drawdown_reaction": "sell_all",
        "risk_tolerance_score": 3.0,
        "investment_experience": "novice",
        "investment_horizon_years": 2,
    }
    p_panic = agent.calculate_panic_sell_likelihood(data_panic, emotional_risk=85.0, composite_score=3.0)
    assert p_panic >= 0.70

    data_calm = {
        "drawdown_reaction": "buy_more",
        "risk_tolerance_score": 8.0,
        "investment_experience": "advanced",
        "investment_horizon_years": 15,
    }
    p_calm = agent.calculate_panic_sell_likelihood(data_calm, emotional_risk=15.0, composite_score=8.0)
    assert p_calm <= 0.10
    assert 0.0 <= p_calm <= 1.0


def test_kyc_aml_rules(agent):
    # Standard pass
    kyc_ok, aml_flag = agent.evaluate_compliance_kyc_aml({
        "age": 30,
        "employment_status": "employed",
        "annual_income": 100000.0,
        "source_of_funds": "salary",
        "pep_status": False,
        "high_risk_jurisdiction": False,
    })
    assert kyc_ok is True
    assert aml_flag is False

    # PEP flag
    kyc_pep, aml_pep = agent.evaluate_compliance_kyc_aml({
        "age": 45,
        "employment_status": "employed",
        "annual_income": 200000.0,
        "source_of_funds": "salary",
        "pep_status": True,
    })
    assert aml_pep is True
    assert kyc_pep is False

    # High risk jurisdiction
    kyc_jur, aml_jur = agent.evaluate_compliance_kyc_aml({
        "age": 40,
        "employment_status": "employed",
        "annual_income": 120000.0,
        "source_of_funds": "business",
        "high_risk_jurisdiction": True,
    })
    assert aml_jur is True
    assert kyc_jur is False

    # Suspicious funds
    kyc_fund, aml_fund = agent.evaluate_compliance_kyc_aml({
        "age": 35,
        "employment_status": "employed",
        "annual_income": 80000.0,
        "source_of_funds": "crypto_mixing",
    })
    assert aml_fund is True
    assert kyc_fund is False


@pytest.mark.asyncio
async def test_db_save_profile_new_and_update(agent, db_session):
    client_id = "test_client_profile_123"
    profile_data = {
        "client_id": client_id,
        "age": 36,
        "employment_status": "employed",
        "annual_income": 130000.0,
        "risk_tolerance_score": 7.0,
        "investment_horizon_years": 10,
        "suitability_category": "Growth",
    }
    saved = await agent.save_profile(db_session, client_id, profile_data)
    assert saved.client_id == client_id
    assert saved.age == 36

    # Update existing
    profile_data["annual_income"] = 150000.0
    updated = await agent.save_profile(db_session, client_id, profile_data)
    assert updated.annual_income == 150000.0


@pytest.mark.asyncio
async def test_db_get_profile(agent, db_session):
    client_id = "test_client_fetch_456"
    profile_data = {
        "client_id": client_id,
        "age": 29,
        "employment_status": "employed",
        "annual_income": 95000.0,
        "risk_tolerance_score": 6.0,
    }
    await agent.save_profile(db_session, client_id, profile_data)

    fetched = await agent.get_profile(client_id, db=db_session)
    assert fetched is not None
    assert fetched.client_id == client_id
    assert fetched.age == 29


@pytest.mark.asyncio
async def test_legacy_process_conversation_compatibility(agent, db_session):
    history = [
        {"role": "user", "content": "I am 32, employed. Income 100k, liquid savings 50k. Horizon 10y for growth. Risk score 7 out of 10. Intermediate experience, salary source, not a PEP."}
    ]
    res = await agent.process_conversation(history, db=db_session)
    assert res["status"] in ["in_progress", "complete"]
    assert "response" in res

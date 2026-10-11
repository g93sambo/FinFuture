"""
Unit tests for backend/db/models.py
Testing all 7 ORM models, relationships, synonyms, and append-only invariant on DBAuditLog.
"""

from datetime import datetime
import pytest
from sqlalchemy import update, delete
from db.models import (
    DBUser,
    DBClientProfile,
    DBPortfolioSnapshot,
    DBTrade,
    DBAuditLog,
    DBBehavioralMemory,
    DBComplianceRule,
    AppendOnlyViolationError,
)


@pytest.mark.asyncio
async def test_create_user_and_profile_with_all_fields(db_session):
    user = DBUser(email="investor@example.com", hashed_password="hashed_pw_here")
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    profile = DBClientProfile(
        user_id=user.id,
        age=42,
        employment_status="employed",
        dependents=2,
        annual_income=150000.0,
        net_worth=500000.0,
        liquid_assets=120000.0,
        monthly_expenses=5000.0,
        existing_debts=20000.0,
        investment_experience="intermediate",
        risk_tolerance_score=6.5,
        investment_horizon_years=15,
        liquidity_needs="moderate",
        loss_capacity="medium",
        primary_goal="wealth_accumulation",
        target_return=8.0,
        specific_goals=["college_fund", "retirement"],
        suitability_category="growth",
        detected_biases=["loss_aversion"],
        emotional_risk_score=4.0,
        panic_sell_likelihood=2.5,
        kyc_verified=True,
        aml_flag=False,
        profiling_session_transcript="User expressed interest in ETFs.",
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(profile)

    assert profile.client_id is not None
    assert profile.user_id == user.id
    assert profile.dependents == 2
    assert profile.liquid_assets == 120000.0
    assert profile.monthly_expenses == 5000.0
    assert profile.existing_debts == 20000.0
    assert profile.investment_experience == "intermediate"
    assert profile.loss_capacity == "medium"
    assert profile.target_return == 8.0
    assert profile.specific_goals == ["college_fund", "retirement"]
    assert profile.emotional_risk_score == 4.0
    assert profile.panic_sell_likelihood == 2.5
    assert profile.profiling_session_transcript == "User expressed interest in ETFs."
    assert profile.user.email == "investor@example.com"


@pytest.mark.asyncio
async def test_portfolio_snapshot_model(db_session):
    client = DBClientProfile()
    db_session.add(client)
    await db_session.commit()

    snapshot = DBPortfolioSnapshot(
        client_id=client.client_id,
        total_value=250000.0,
        positions={"VTI": 0.6, "BND": 0.4},
        cash=5000.0,
    )
    db_session.add(snapshot)
    await db_session.commit()
    await db_session.refresh(snapshot)

    assert snapshot.id is not None
    assert snapshot.total_value == 250000.0
    assert snapshot.positions["VTI"] == 0.6
    assert snapshot.client.client_id == client.client_id


@pytest.mark.asyncio
async def test_trade_model_and_synonyms(db_session):
    client = DBClientProfile()
    db_session.add(client)
    await db_session.commit()

    trade = DBTrade(
        client_id=client.client_id,
        symbol="VTI",
        qty=15.0,
        side="BUY",
        order_type="MARKET",
        status="FILLED",
        filled_price=220.50,
        filled_qty=15.0,
    )
    db_session.add(trade)
    await db_session.commit()
    await db_session.refresh(trade)

    # Test synonyms
    assert trade.trade_id == trade.id
    assert trade.quantity == trade.qty == 15.0


@pytest.mark.asyncio
async def test_behavioral_memory_model(db_session):
    client = DBClientProfile()
    db_session.add(client)
    await db_session.commit()

    mem = DBBehavioralMemory(
        client_id=client.client_id,
        bias_type="recency_bias",
        severity="high",
        trigger_context={"market_drop": "-5%"},
        intervention_text="Remind user of 15y horizon.",
    )
    db_session.add(mem)
    await db_session.commit()
    await db_session.refresh(mem)

    assert mem.id is not None
    assert mem.bias_type == "recency_bias"
    assert mem.severity == "high"


@pytest.mark.asyncio
async def test_compliance_rule_model(db_session):
    rule = DBComplianceRule(
        rule_id="SUIT-001",
        name="Risk Profile Alignment",
        category="SUITABILITY",
        severity="BLOCK",
        parameters={"max_risk_delta": 1.0},
        description="Must align with risk score",
        is_active=True,
    )
    db_session.add(rule)
    await db_session.commit()
    await db_session.refresh(rule)

    assert rule.rule_id == "SUIT-001"
    assert rule.parameters["max_risk_delta"] == 1.0


@pytest.mark.asyncio
async def test_audit_log_synonyms(db_session):
    log = DBAuditLog(
        client_id="c1",
        event_type="TEST",
        actor="SYSTEM",
        details={"key": "val"},
        prev_hash="0" * 64,
        entry_hash="hash1",
        signature="sig1",
    )
    db_session.add(log)
    await db_session.commit()
    await db_session.refresh(log)

    assert log.entry_id == log.id
    assert log.previous_hash == log.prev_hash == "0" * 64
    assert log.hmac_signature == log.signature == "sig1"
    assert log.action == log.details == {"key": "val"}


@pytest.mark.asyncio
async def test_audit_log_append_only_instance_update(db_session):
    log = DBAuditLog(
        client_id="c2",
        event_type="LOGIN",
        actor="USER",
        details={"ip": "127.0.0.1"},
        prev_hash="0" * 64,
        entry_hash="hash2",
        signature="sig2",
    )
    db_session.add(log)
    await db_session.commit()

    # Attempt to modify instance
    log.actor = "ATTACKER"
    with pytest.raises(AppendOnlyViolationError) as exc_info:
        await db_session.commit()
    assert "UPDATE is strictly prohibited" in str(exc_info.value)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_audit_log_append_only_instance_delete(db_session):
    log = DBAuditLog(
        client_id="c3",
        event_type="LOGIN",
        actor="USER",
        details={},
        prev_hash="0" * 64,
        entry_hash="hash3",
        signature="sig3",
    )
    db_session.add(log)
    await db_session.commit()

    # Attempt to delete instance
    await db_session.delete(log)
    with pytest.raises(AppendOnlyViolationError) as exc_info:
        await db_session.commit()
    assert "DELETE is strictly prohibited" in str(exc_info.value)
    await db_session.rollback()


@pytest.mark.asyncio
async def test_audit_log_append_only_bulk_update(db_session):
    log = DBAuditLog(
        client_id="c4",
        event_type="TRADE",
        actor="AGENT",
        details={},
        prev_hash="0" * 64,
        entry_hash="hash4",
        signature="sig4",
    )
    db_session.add(log)
    await db_session.commit()

    with pytest.raises(AppendOnlyViolationError) as exc_info:
        await db_session.execute(
            update(DBAuditLog).where(DBAuditLog.client_id == "c4").values(actor="MODIFIED")
        )
    assert "Bulk UPDATE statement is strictly prohibited" in str(exc_info.value)


@pytest.mark.asyncio
async def test_audit_log_append_only_bulk_delete(db_session):
    log = DBAuditLog(
        client_id="c5",
        event_type="TRADE",
        actor="AGENT",
        details={},
        prev_hash="0" * 64,
        entry_hash="hash5",
        signature="sig5",
    )
    db_session.add(log)
    await db_session.commit()

    with pytest.raises(AppendOnlyViolationError) as exc_info:
        await db_session.execute(
            delete(DBAuditLog).where(DBAuditLog.client_id == "c5")
        )
    assert "Bulk DELETE statement is strictly prohibited" in str(exc_info.value)

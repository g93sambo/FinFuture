"""
backend/tests/unit/test_execution_module.py
===========================================
Unit tests covering paper trading enforcement, dual-engine Alpaca/DRY_RUN execution,
pre-trade validation gates (REG-003, REG-004, KYC, 30s lock), database persistence,
cryptographic audit logging, and order status polling.
"""

import pytest
import pytest_asyncio
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime, timezone, timedelta

from db.models import DBClientProfile, DBTrade, DBAuditLog
from services.cache import InMemoryCache, CacheService, key_trade_lock
from services.audit_logger import get_audit_logger, verify_audit_chain
from agents.execution_module import (
    ExecutionModule,
    TradeExecutionResult,
    UnapprovedTradeError,
    ExpiredApprovalError,
    KYCUnverifiedError,
    DuplicateTradeError,
)


@pytest.fixture
def cache_service():
    """Provides an isolated in-memory cache service."""
    service = CacheService()
    service.fallback = InMemoryCache()
    service._redis_available = False
    return service


@pytest.fixture
def execution_module(cache_service):
    """Provides an ExecutionModule with in-memory cache and audit logger."""
    return ExecutionModule(
        paper=True,
        cache_service=cache_service,
        audit_logger=get_audit_logger(),
    )


@pytest_asyncio.fixture
async def seeded_client(db_session):
    """Seeds a verified client in the test database."""
    client = DBClientProfile(
        client_id="client_exec_001",
        risk_tolerance_score=5.0,
        investment_horizon_years=5.0,
        kyc_verified=True,
        aml_flag=False,
    )
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    return client


# ============================================================================
# 1. Paper Trading Guard Enforcement Tests
# ============================================================================

def test_paper_trading_enforcement_raises_on_live():
    with pytest.raises(RuntimeError) as exc_info:
        ExecutionModule(paper=False)
    assert "Live trading is strictly prohibited" in str(exc_info.value)


# ============================================================================
# 2. Successful Execution in DRY_RUN Mode & DB Persistence
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_dry_run_success(db_session, execution_module, seeded_client):
    client_id = seeded_client.client_id
    now = datetime.now(timezone.utc)

    result = await execution_module.execute_trade(
        db=db_session,
        client_id=client_id,
        proposal_id="prop_test_001",
        symbol="SPY",
        side="BUY",
        qty=10.0,
        approved=True,
        approval_timestamp=now,
        dry_run=True,
    )

    assert result.success is True
    assert result.status == "FILLED"
    assert result.dry_run is True
    assert result.order_id.startswith("dry-run-")
    assert result.filled_price == 510.50
    assert result.filled_qty == 10.0
    assert result.trade_id is not None

    # Verify DB persistence in DBTrade
    db_trade = await db_session.get(DBTrade, result.trade_id)
    assert db_trade is not None
    assert db_trade.client_id == client_id
    assert db_trade.symbol == "SPY"
    assert db_trade.qty == 10.0
    assert db_trade.side == "BUY"
    assert db_trade.status == "FILLED"

    # Verify Cryptographic Audit Logging
    is_valid, tampered_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is True
    assert tampered_id is None


# ============================================================================
# 3. Pre-Trade Gate 1: Non-Discretionary Approval (REG-003)
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_unapproved_rejected(db_session, execution_module, seeded_client):
    now = datetime.now(timezone.utc)

    with pytest.raises(UnapprovedTradeError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id=seeded_client.client_id,
            proposal_id="prop_test_002",
            symbol="QQQ",
            side="BUY",
            qty=5.0,
            approved=False,  # Unapproved
            approval_timestamp=now,
            dry_run=True,
        )
    assert "REG-003" in str(exc_info.value)
    assert isinstance(exc_info.value, ValueError)


# ============================================================================
# 4. Pre-Trade Gate 2: 15-Minute Approval Freshness (REG-004)
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_expired_approval_rejected(db_session, execution_module, seeded_client):
    stale_time = datetime.now(timezone.utc) - timedelta(minutes=16)

    with pytest.raises(ExpiredApprovalError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id=seeded_client.client_id,
            proposal_id="prop_test_003",
            symbol="BND",
            side="SELL",
            qty=15.0,
            approved=True,
            approval_timestamp=stale_time,  # 16 minutes old > 15m
            dry_run=True,
        )
    assert "REG-004" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_trade_future_approval_rejected(db_session, execution_module, seeded_client):
    future_time = datetime.now(timezone.utc) + timedelta(minutes=5)

    with pytest.raises(ExpiredApprovalError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id=seeded_client.client_id,
            proposal_id="prop_test_003b",
            symbol="BND",
            side="SELL",
            qty=15.0,
            approved=True,
            approval_timestamp=future_time,
            dry_run=True,
        )
    assert "future" in str(exc_info.value).lower()


# ============================================================================
# 5. Pre-Trade Gate 3: KYC Verification Check
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_kyc_unverified_rejected(db_session, execution_module):
    # Create unverified client
    unverified_client = DBClientProfile(
        client_id="client_unverified_99",
        risk_tolerance_score=5.0,
        investment_horizon_years=5.0,
        kyc_verified=False,
    )
    db_session.add(unverified_client)
    await db_session.commit()

    now = datetime.now(timezone.utc)
    with pytest.raises(KYCUnverifiedError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id="client_unverified_99",
            proposal_id="prop_test_004",
            symbol="VTI",
            side="BUY",
            qty=2.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
    assert "KYC verification required" in str(exc_info.value)


@pytest.mark.asyncio
async def test_execute_trade_missing_profile_rejected(db_session, execution_module):
    now = datetime.now(timezone.utc)
    with pytest.raises(KYCUnverifiedError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id="non_existent_client",
            proposal_id="prop_test_005",
            symbol="SPY",
            side="BUY",
            qty=1.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
    assert "not found" in str(exc_info.value).lower()


# ============================================================================
# 6. Pre-Trade Gate 4: 30-Second Double-Submit Lock
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_30s_double_submit_rejected(db_session, execution_module, seeded_client):
    client_id = seeded_client.client_id
    now = datetime.now(timezone.utc)

    # First trade acquires lock and succeeds
    res1 = await execution_module.execute_trade(
        db=db_session,
        client_id=client_id,
        proposal_id="prop_dup_001",
        symbol="SPY",
        side="BUY",
        qty=5.0,
        approved=True,
        approval_timestamp=now,
        dry_run=True,
    )
    assert res1.success is True

    # Immediate second trade for the same client must be rejected by lock
    with pytest.raises(DuplicateTradeError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id=client_id,
            proposal_id="prop_dup_002",
            symbol="SPY",
            side="BUY",
            qty=5.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
    assert "Duplicate submit rejected" in str(exc_info.value)
    assert "30 seconds" in str(exc_info.value)


# ============================================================================
# 7. Mock Alpaca Paper Client Execution
# ============================================================================

@pytest.mark.asyncio
async def test_execute_trade_mocked_alpaca(db_session, execution_module, seeded_client):
    # Setup mock Alpaca TradingClient
    mock_order = MagicMock()
    mock_order.id = "alpaca-ord-12345"
    mock_order.status.value = "accepted"
    mock_order.filled_avg_price = 185.00
    mock_order.filled_qty = 8.0
    mock_order.submitted_at = datetime.now(timezone.utc)
    mock_order.filled_at = datetime.now(timezone.utc)

    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    execution_module.client = mock_client

    client_id = seeded_client.client_id
    now = datetime.now(timezone.utc)

    # Release any lingering lock from prior test
    await execution_module.cache_service.release_lock(key_trade_lock(client_id))

    result = await execution_module.execute_trade(
        db=db_session,
        client_id=client_id,
        proposal_id="prop_alpaca_001",
        symbol="AAPL",
        side="BUY",
        qty=8.0,
        approved=True,
        approval_timestamp=now,
        dry_run=False,  # Paper mode
    )

    assert result.success is True
    assert result.order_id == "alpaca-ord-12345"
    assert result.status == "ACCEPTED"
    assert result.dry_run is False
    assert mock_client.submit_order.called


# ============================================================================
# 8. Order Status Retrieval Helper Tests
# ============================================================================

@pytest.mark.asyncio
async def test_get_order_status_dry_run(execution_module):
    status = await execution_module.get_order_status("dry-run-uuid-123")
    assert status["status"] == "FILLED"
    assert status["dry_run"] is True


@pytest.mark.asyncio
async def test_get_order_status_alpaca(execution_module):
    mock_order = MagicMock()
    mock_order.id = "alpaca-id-789"
    mock_order.status.value = "filled"
    mock_order.symbol = "SPY"
    mock_order.qty = 10.0
    mock_order.filled_qty = 10.0
    mock_order.filled_avg_price = 510.50

    mock_client = MagicMock()
    mock_client.get_order_by_id.return_value = mock_order
    execution_module.client = mock_client

    status = await execution_module.get_order_status("alpaca-id-789")
    assert status["status"] == "FILLED"
    assert status["symbol"] == "SPY"
    assert status["filled_avg_price"] == 510.50
    assert status["dry_run"] is False


# ============================================================================
# 9. Backward-Compatible place_order Wrapper
# ============================================================================

def test_place_order_sync_dry_run(execution_module):
    execution_module.client = None
    res = execution_module.place_order(symbol="VTI", qty=5.0, side="BUY", user_approved=True)
    assert res["status"] == "mock_filled"
    assert res["symbol"] == "VTI"
    assert res["qty"] == 5.0


def test_place_order_sync_unapproved_raises(execution_module):
    with pytest.raises(ValueError) as exc_info:
        execution_module.place_order(symbol="VTI", qty=5.0, side="BUY", user_approved=False)
    assert "User has not approved" in str(exc_info.value)


@pytest.mark.asyncio
async def test_input_validation_gates(db_session, execution_module, seeded_client):
    now = datetime.now(timezone.utc)
    # Empty symbol
    with pytest.raises(ValueError) as exc1:
        await execution_module.execute_trade(
            db=db_session, client_id=seeded_client.client_id, proposal_id="p1",
            symbol="", side="BUY", qty=10.0, approved=True, approval_timestamp=now,
        )
    assert "Symbol cannot be empty" in str(exc1.value)

    # Invalid side
    with pytest.raises(ValueError) as exc2:
        await execution_module.execute_trade(
            db=db_session, client_id=seeded_client.client_id, proposal_id="p1",
            symbol="SPY", side="HOLD", qty=10.0, approved=True, approval_timestamp=now,
        )
    assert "Invalid side" in str(exc2.value)

    # Non-positive quantity
    with pytest.raises(ValueError) as exc3:
        await execution_module.execute_trade(
            db=db_session, client_id=seeded_client.client_id, proposal_id="p1",
            symbol="SPY", side="BUY", qty=0.0, approved=True, approval_timestamp=now,
        )
    assert "positive" in str(exc3.value).lower()


@pytest.mark.asyncio
async def test_get_order_status_error_handling(execution_module):
    mock_client = MagicMock()
    mock_client.get_order_by_id.side_effect = RuntimeError("Broker connection timeout")
    execution_module.client = mock_client

    status = await execution_module.get_order_status("alpaca-err-001")
    assert status["status"] == "UNKNOWN"
    assert "Broker connection timeout" in status["error"]


def test_place_order_with_live_client(execution_module):
    mock_order = MagicMock()
    mock_order.status = "new"
    mock_order.symbol = "AAPL"
    mock_order.qty = 10.0
    mock_order.side = "buy"
    mock_order.id = "ord-live-999"

    mock_client = MagicMock()
    mock_client.submit_order.return_value = mock_order
    execution_module.client = mock_client

    res = execution_module.place_order(symbol="AAPL", qty=10.0, side="BUY", user_approved=True)
    assert res["status"] == "new"
    assert res["order_id"] == "ord-live-999"


@pytest.mark.asyncio
async def test_execute_trade_broker_exception(db_session, execution_module, seeded_client):
    mock_client = MagicMock()
    mock_client.submit_order.side_effect = RuntimeError("API rate limit exceeded")
    execution_module.client = mock_client

    client_id = seeded_client.client_id
    now = datetime.now(timezone.utc)
    await execution_module.cache_service.release_lock(key_trade_lock(client_id))

    with pytest.raises(RuntimeError) as exc_info:
        await execution_module.execute_trade(
            db=db_session,
            client_id=client_id,
            proposal_id="prop_err_001",
            symbol="SPY",
            side="BUY",
            qty=5.0,
            approved=True,
            approval_timestamp=now,
            dry_run=False,
        )
    assert "API rate limit exceeded" in str(exc_info.value)


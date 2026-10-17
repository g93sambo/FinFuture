import os
import sys
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, patch, MagicMock

import pytest
import pytest_asyncio

_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "..", ".."))
_backend_root = os.path.join(_project_root, "backend")

if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from services.providers.bamboo import (
    BambooProvider,
    BambooOrderCalculation,
    BambooOrderResult,
    BAMBOO_SIMULATED_PRICES,
    DEFAULT_USD_NGN_RATE,
)
from tools.definitions.bamboo_invest import (
    BambooCalculateOrderTool,
    BambooCalculateOrderArgs,
    BambooPortfolioTool,
    BambooPortfolioArgs,
)
from agents.execution_module import (
    ExecutionModule,
    TradeExecutionResult,
)
from db.models import DBClientProfile, DBTrade
from services.cache import CacheService, InMemoryCache
from services.audit_logger import get_audit_logger


@pytest.fixture
def cache_service():
    service = CacheService()
    service.fallback = InMemoryCache()
    service._redis_available = False
    return service


@pytest.fixture
def bamboo_provider():
    return BambooProvider(live_mode=False)


@pytest.fixture
def execution_module(cache_service, bamboo_provider):
    return ExecutionModule(
        paper=True,
        cache_service=cache_service,
        audit_logger=get_audit_logger(),
        bamboo_provider=bamboo_provider,
    )


@pytest_asyncio.fixture
async def verified_client(db_session):
    client = DBClientProfile(
        client_id="client_ng_001",
        risk_tolerance_score=6.0,
        investment_horizon_years=5.0,
        kyc_verified=True,
        aml_flag=False,
    )
    db_session.add(client)
    await db_session.commit()
    await db_session.refresh(client)
    return client


# ============================================================================
# 1. Bamboo Provider Unit Tests
# ============================================================================

@pytest.mark.asyncio
async def test_bamboo_token_acquisition(bamboo_provider):
    token = await bamboo_provider.get_client_token()
    assert token is not None
    assert len(token) > 0
    # Second call should use cached token
    token2 = await bamboo_provider.get_client_token()
    assert token == token2


@pytest.mark.asyncio
async def test_bamboo_calculate_order_nigerian_stock(bamboo_provider):
    # Calculate order for Dangote Cement in NGN
    calc = await bamboo_provider.calculate_order(
        symbol="DANGCEM",
        side="buy",
        amount=500_000.0,
        currency="NGN",
    )
    assert calc.symbol == "DANGCEM"
    assert calc.currency == "NGN"
    assert calc.amount == 500_000.0
    assert calc.price_per_share == 650.0
    assert calc.fee > 0
    assert calc.quantity > 0
    # Fee is 1.5% = 7500.0
    assert calc.fee == 7500.0


@pytest.mark.asyncio
async def test_bamboo_calculate_order_us_stock_in_ngn(bamboo_provider):
    # Calculate order for Apple Inc. in NGN (converts USD to NGN)
    calc = await bamboo_provider.calculate_order(
        symbol="AAPL",
        side="buy",
        amount=155_000.0,
        currency="NGN",
    )
    assert calc.symbol == "AAPL"
    assert calc.currency == "NGN"
    assert calc.fx_rate == DEFAULT_USD_NGN_RATE
    assert calc.price_per_share == 185.0 * DEFAULT_USD_NGN_RATE
    assert calc.quantity > 0


@pytest.mark.asyncio
async def test_bamboo_place_order_sandbox(bamboo_provider):
    calc = await bamboo_provider.calculate_order(
        symbol="MTNN",
        side="buy",
        quantity=100.0,
        currency="NGN",
    )
    result = await bamboo_provider.place_order(
        calculation=calc,
        user_id="user_test_ng",
        dry_run=True,
    )
    assert result.order_id.startswith("bamboo-sim-")
    assert result.symbol == "MTNN"
    assert result.side == "BUY"
    assert result.quantity == 100.0
    assert result.status == "FILLED"
    assert result.currency == "NGN"
    assert result.dry_run is True


# ============================================================================
# 2. ExecutionModule Dual-Broker Routing Tests (Bamboo vs Alpaca)
# ============================================================================

@pytest.mark.asyncio
async def test_execution_module_routes_ngx_stock_to_bamboo(db_session, execution_module, verified_client):
    client_id = verified_client.client_id
    now = datetime.now(timezone.utc)

    # Executing Dangote Cement trade
    result = await execution_module.execute_trade(
        db=db_session,
        client_id=client_id,
        proposal_id="prop_ng_dangote_001",
        symbol="DANGCEM",
        side="BUY",
        qty=50.0,
        approved=True,
        approval_timestamp=now,
    )

    assert result.success is True
    assert result.symbol == "DANGCEM"
    assert result.broker == "bamboo"
    assert result.currency == "NGN"
    assert result.filled_price == 650.0
    assert result.order_id.startswith("bamboo-")

    # Verify database persistence
    trade_record = await db_session.get(DBTrade, result.trade_id)
    assert trade_record is not None
    assert trade_record.symbol == "DANGCEM"
    assert trade_record.broker == "bamboo"
    assert trade_record.currency == "NGN"
    assert trade_record.bamboo_order_id == result.order_id


@pytest.mark.asyncio
async def test_execution_module_routes_us_stock_to_alpaca(db_session, execution_module, verified_client):
    client_id = verified_client.client_id
    now = datetime.now(timezone.utc)

    # Executing SPY trade
    result = await execution_module.execute_trade(
        db=db_session,
        client_id=client_id,
        proposal_id="prop_us_spy_001",
        symbol="SPY",
        side="BUY",
        qty=10.0,
        approved=True,
        approval_timestamp=now,
    )

    assert result.success is True
    assert result.symbol == "SPY"
    assert result.broker == "alpaca"
    assert result.currency == "USD"
    assert result.order_id.startswith("dry-run-")


# ============================================================================
# 3. Bamboo Tools Registry Integration Tests
# ============================================================================

@pytest.mark.asyncio
async def test_bamboo_calculate_order_tool():
    tool = BambooCalculateOrderTool()
    args = BambooCalculateOrderArgs(
        symbol="GTCO",
        side="BUY",
        amount=100_000.0,
        currency="NGN",
    )
    result = await tool.execute(args)
    assert result.success is True
    assert result.data["symbol"] == "GTCO"
    assert result.data["currency"] == "NGN"
    assert result.data["price_per_share"] == 48.50
    assert result.data["quantity"] > 0


@pytest.mark.asyncio
async def test_bamboo_portfolio_tool():
    tool = BambooPortfolioTool()
    args = BambooPortfolioArgs(user_id="user_test_ng", currency="NGN")
    result = await tool.execute(args)
    assert result.success is True
    assert "positions" in result.data
    assert "DANGCEM" in result.data["positions"]

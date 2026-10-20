"""Each client sees only their own money: one shared Alpaca paper account routes the orders,
but portfolios come from each client's own trades, open orders sync to real fills, and a
client cannot spend more cash or sell more shares than they hold."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from agents.execution_module import ExecutionError, ExecutionModule
from db.models import DBClientProfile, DBTrade
from services.cache import CacheService, InMemoryCache
from services.audit_logger import get_audit_logger
from services.portfolio_service import DEFAULT_STARTING_CASH, PortfolioService


class FixedMarket:
    def __init__(self, prices):
        self.prices = prices

    async def get_quote(self, symbol):
        return SimpleNamespace(price=self.prices.get(symbol, 0.0))


@pytest_asyncio.fixture
async def two_clients(db_session):
    for cid in ("client_a", "client_b"):
        db_session.add(DBClientProfile(client_id=cid, risk_tolerance_score=5.0, investment_horizon_years=5.0, kyc_verified=True, aml_flag=False))
    await db_session.commit()


def make_execution(client=None):
    cache = CacheService()
    cache.fallback = InMemoryCache()
    cache._redis_available = False
    ex = ExecutionModule(paper=True, cache_service=cache, audit_logger=get_audit_logger())
    ex.client = client
    return ex


def trade(cid, symbol, side, qty, status, price, order_id=None, filled_qty=None):
    return DBTrade(client_id=cid, symbol=symbol, side=side, qty=qty, status=status, filled_price=price,
                   filled_qty=qty if filled_qty is None else filled_qty, alpaca_order_id=order_id)


@pytest.mark.asyncio
async def test_clients_do_not_see_each_others_trades(db_session, two_clients):
    db_session.add(trade("client_a", "SPY", "BUY", 10, "FILLED", 500.0))
    await db_session.commit()
    svc = PortfolioService(execution_module=make_execution(client=MagicMock()), market_data_agent=FixedMarket({"SPY": 520.0}))

    a = await svc.get_portfolio(db_session, "client_a")
    b = await svc.get_portfolio(db_session, "client_b")

    assert a["cash"] == DEFAULT_STARTING_CASH - 5000.0
    assert a["position_qty"] == {"SPY": 10}
    assert a["invested_value"] == 5200.0  # valued at the live price, not the fill price
    assert b["cash"] == DEFAULT_STARTING_CASH and b["positions"] == []


@pytest.mark.asyncio
async def test_open_order_syncs_to_real_fill(db_session, two_clients):
    db_session.add(trade("client_a", "AAPL", "BUY", 2, "ACCEPTED", 185.0, order_id="ord-1"))
    await db_session.commit()
    broker = MagicMock()
    broker.get_order_by_id.return_value = SimpleNamespace(status="filled", filled_qty="2", filled_avg_price="341.50", filled_at=None)
    svc = PortfolioService(execution_module=make_execution(client=broker), market_data_agent=FixedMarket({"AAPL": 342.0}))

    pf = await svc.get_portfolio(db_session, "client_a")

    assert pf["cash"] == pytest.approx(DEFAULT_STARTING_CASH - 683.0)
    assert pf["position_qty"] == {"AAPL": 2.0}
    broker.get_order_by_id.assert_called_once_with("ord-1")


@pytest.mark.asyncio
async def test_open_buy_reserves_cash(db_session, two_clients):
    db_session.add(trade("client_a", "SPY", "BUY", 10, "ACCEPTED", 500.0, order_id="ord-2", filled_qty=0))
    await db_session.commit()
    broker = MagicMock()
    broker.get_order_by_id.return_value = SimpleNamespace(status="accepted", filled_qty="0", filled_avg_price=None, filled_at=None)
    svc = PortfolioService(execution_module=make_execution(client=broker), market_data_agent=FixedMarket({}))

    pf = await svc.get_portfolio(db_session, "client_a")

    assert pf["cash"] == DEFAULT_STARTING_CASH and pf["positions"] == []
    assert pf["reserved_cash"] == 5000.0


async def _execute(ex, db, cid, symbol, side, qty):
    return await ex.execute_trade(db=db, client_id=cid, proposal_id="p1", symbol=symbol, side=side, qty=qty,
                                  approved=True, approval_timestamp=datetime.now(timezone.utc), dry_run=True)


@pytest.mark.asyncio
async def test_buy_beyond_own_cash_is_blocked(db_session, two_clients):
    ex = make_execution()
    ex.portfolio = PortfolioService(execution_module=ex, market_data_agent=FixedMarket({"SPY": 500.0}))
    with pytest.raises(ExecutionError, match="Not enough cash"):
        await _execute(ex, db_session, "client_b", "SPY", "BUY", 1000)


@pytest.mark.asyncio
async def test_selling_shares_not_held_is_blocked(db_session, two_clients):
    db_session.add(trade("client_a", "SPY", "BUY", 10, "FILLED", 500.0))
    await db_session.commit()
    ex = make_execution()
    ex.portfolio = PortfolioService(execution_module=ex, market_data_agent=FixedMarket({"SPY": 500.0}))

    with pytest.raises(ExecutionError, match="do not hold any SPY"):
        await _execute(ex, db_session, "client_b", "SPY", "SELL", 1)
    with pytest.raises(ExecutionError, match="at most 10 shares"):
        await _execute(ex, db_session, "client_a", "SPY", "SELL", 11)
    result = await _execute(ex, db_session, "client_a", "SPY", "SELL", 4)
    assert result.success


@pytest.mark.asyncio
async def test_health_plan_prices_unheld_targets_at_live_quotes(db_session, two_clients):
    """Team report: the plan valued SPY at a stale $510.50 while the Trade page charged $766.48."""
    from services.health_report import HealthReportService

    market = FixedMarket({"SPY": 766.48, "BND": 74.10})
    svc = PortfolioService(execution_module=make_execution(), market_data_agent=market)
    pf = await svc.get_portfolio(db_session, "client_b")  # all cash, nothing held yet
    report = await HealthReportService(market_data_agent=market, openai_api_key="").generate_health_report(
        db_session, "client_b",
        portfolio={"weights": pf["weights"], "positions": pf["position_qty"], "cash": pf["cash"],
                   "total_value": pf["total_value"], "prices": pf["prices"]},
    )
    plan = report.rebalancing_plan
    by_symbol = {o.symbol: o for o in plan.orders}
    assert plan.total_portfolio_value == pytest.approx(DEFAULT_STARTING_CASH)
    assert by_symbol["SPY"].estimated_price == 766.48
    assert by_symbol["BND"].estimated_price == 74.10
    assert sum(o.estimated_amount for o in plan.orders) <= DEFAULT_STARTING_CASH + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("symbol,flagged", [("BND", False), ("SPY", False), ("AAPL", True), ("GLD", True)])
async def test_single_stock_limit_skips_diversified_funds(symbol, flagged):
    """Team report: following the plan's 'Buy BND' (20%) raised a single-stock concentration warning."""
    from agents.compliance_guard import ComplianceGuard, ComplianceViolationError

    trade = {"symbol": symbol, "side": "BUY", "qty": 10, "notional_value": 900.0, "projected_weight": 0.195,
             "user_approved": True, "approval_timestamp": datetime.now(timezone.utc).isoformat()}
    try:
        violations = (await ComplianceGuard().check_trade(None, "client_a", trade, None)).violations
    except ComplianceViolationError as exc:  # other rules may block this synthetic trade; only CONC-001 matters here
        violations = exc.violations
    conc = [v for v in violations if v.rule_id == "CONC-001"]
    assert bool(conc) is flagged


@pytest.mark.asyncio
async def test_health_review_counts_cash(db_session, two_clients):
    """Team video: $1.4k of AAPL in a $100k account was reported as 'AAPL 100%' with a critical score."""
    from services.health_report import HealthReportService

    db_session.add(trade("client_a", "AAPL", "BUY", 4, "FILLED", 342.94))
    await db_session.commit()
    market = FixedMarket({"AAPL": 342.94, "SPY": 766.48, "BND": 74.10})
    pf = await PortfolioService(execution_module=make_execution(), market_data_agent=market).get_portfolio(db_session, "client_a")
    report = await HealthReportService(market_data_agent=market, openai_api_key="").generate_health_report(
        db_session, "client_a",
        portfolio={"weights": pf["weights"], "positions": pf["position_qty"], "cash": pf["cash"],
                   "total_value": pf["total_value"], "prices": pf["prices"]},
    )
    conc = report.concentration_metrics
    assert conc.max_position_symbol == "AAPL"
    assert conc.max_position_weight == pytest.approx(0.0137, abs=0.001)  # share of the whole account
    assert not conc.has_concentration_risk
    assert report.drift_analysis.asset_drifts["CASH"].current_weight > 0.98
    assert report.benchmark_comparison.portfolio_volatility < 0.02


async def _health(db, cid, market):
    from services.health_report import HealthReportService

    pf = await PortfolioService(execution_module=make_execution(), market_data_agent=market).get_portfolio(db, cid)
    return await HealthReportService(market_data_agent=market, openai_api_key="").generate_health_report(
        db, cid,
        portfolio={"weights": pf["weights"], "positions": pf["position_qty"], "cash": pf["cash"],
                   "total_value": pf["total_value"], "prices": pf["prices"]},
    )


@pytest.mark.asyncio
async def test_all_cash_account_is_not_invested_rather_than_critical(db_session, two_clients):
    report = await _health(db_session, "client_b", FixedMarket({"SPY": 766.48, "BND": 74.10}))
    assert report.not_invested is True
    assert [a.severity.value for a in report.alerts] == ["INFO"]
    assert "not invested yet" in report.narrative.executive_summary
    assert report.rebalancing_plan.orders  # the plan to invest the cash is still there


@pytest.mark.asyncio
async def test_invested_account_still_gets_a_score(db_session, two_clients):
    db_session.add(trade("client_a", "SPY", "BUY", 65, "FILLED", 766.48))
    await db_session.commit()
    report = await _health(db_session, "client_a", FixedMarket({"SPY": 766.48, "BND": 74.10}))
    assert report.not_invested is False
    assert report.health_score > 0

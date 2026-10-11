"""
backend/tests/unit/test_providers.py
====================================
Unit tests for domain data providers:
- EquitiesProvider (yfinance thread wrapping, fixture fallback, skfolio compatibility)
- TreasuryProvider (FiscalData REST API, term structure, inversion metrics)
- MacroProvider (FRED API, CalcFi, macroeconomic context)
- ETFHoldingsProvider (top holdings, sector allocations, bond metrics)
- AssetScreenerProvider (universe metadata, multi-factor filtering)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
import pandas as pd
import httpx
from skfolio.preprocessing import prices_to_returns
from skfolio.optimization import MeanRisk, ObjectiveFunction
from skfolio import RiskMeasure

from services.providers.equities import EquitiesProvider
from services.providers.treasury import TreasuryProvider
from services.providers.macro import MacroProvider
from services.providers.etf_holdings import ETFHoldingsProvider
from services.providers.screener import AssetScreenerProvider, AssetMetadata


# =====================================================================
# 1. EquitiesProvider Tests
# =====================================================================

@pytest.mark.asyncio
async def test_equities_provider_get_quote_fixture():
    provider = EquitiesProvider(offline_mode=True)
    quote = await provider.get_quote("SPY")
    assert quote["symbol"] == "SPY"
    assert quote["price"] > 0.0
    assert quote["source"] == "fixture"
    assert "timestamp" in quote


@pytest.mark.asyncio
async def test_equities_provider_get_historical_prices_fixture():
    provider = EquitiesProvider(offline_mode=True)
    symbols = ["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]
    df = await provider.get_historical_prices(symbols)
    assert isinstance(df, pd.DataFrame)
    assert isinstance(df.index, pd.DatetimeIndex)
    assert list(df.columns) == symbols
    assert len(df) == 252
    assert not df.isna().any().any()


@pytest.mark.asyncio
async def test_equities_provider_historical_prices_skfolio_cvar_solve():
    provider = EquitiesProvider(offline_mode=True)
    symbols = ["SPY", "BND", "AGG", "VTI", "VXUS", "GLD"]
    df = await provider.get_historical_prices(symbols)

    # Convert to returns
    returns = prices_to_returns(df)
    assert returns.shape[0] == 251
    assert returns.shape[1] == 6

    # Solve MeanRisk CVaR optimization
    model = MeanRisk(
        risk_measure=RiskMeasure.CVAR,
        objective_function=ObjectiveFunction.MAXIMIZE_RATIO,
        max_weights=0.30,
        min_weights=0.02
    )
    model.fit(returns)
    pred = model.predict(returns)

    assert len(pred.weights) == 6
    assert abs(sum(pred.weights) - 1.0) < 1e-4
    for w in pred.weights:
        assert 0.019 <= w <= 0.301


@pytest.mark.asyncio
async def test_equities_provider_network_error_degrades_to_fixture():
    provider = EquitiesProvider(offline_mode=False)
    with patch.object(provider, "_fetch_yfinance_quote", side_effect=Exception("Throttled")):
        quote = await provider.get_quote("GLD")
        assert quote["symbol"] == "GLD"
        assert quote["source"] == "fixture"


@pytest.mark.asyncio
async def test_equities_provider_live_quote_fast_info():
    provider = EquitiesProvider(offline_mode=False)
    mock_fast_info = MagicMock()
    mock_fast_info.last_price = 512.45
    mock_fast_info.previous_close = 510.00
    mock_fast_info.open = 511.00
    mock_fast_info.day_high = 513.00
    mock_fast_info.day_low = 509.50
    mock_fast_info.last_volume = 45000000

    mock_ticker = MagicMock()
    mock_ticker.fast_info = mock_fast_info

    with patch("yfinance.Ticker", return_value=mock_ticker):
        quote = await provider.get_quote("SPY")
        assert quote["symbol"] == "SPY"
        assert quote["price"] == 512.45
        assert quote["source"] == "yfinance"
        assert quote["change"] == round(512.45 - 510.00, 4)


@pytest.mark.asyncio
async def test_equities_provider_live_history_download():
    provider = EquitiesProvider(offline_mode=False)
    dates = pd.bdate_range(end="2026-10-09", periods=40)
    mock_df = pd.DataFrame(
        {"SPY": [500.0 + i for i in range(40)], "BND": [70.0 + (i * 0.1) for i in range(40)]},
        index=dates
    )
    with patch("yfinance.download", return_value=mock_df):
        res_df = await provider.get_historical_prices(["SPY", "BND"], period="1y")
        assert isinstance(res_df, pd.DataFrame)
        assert len(res_df) == 40
        assert "SPY" in res_df.columns
        assert "BND" in res_df.columns


# =====================================================================
# 2. TreasuryProvider Tests
# =====================================================================

@pytest.mark.asyncio
async def test_treasury_provider_get_yield_curve_fixture():
    provider = TreasuryProvider(offline_mode=True)
    curve = await provider.get_yield_curve()
    assert isinstance(curve, dict)
    assert "10Y" in curve
    assert "2Y" in curve
    assert "3M" in curve
    assert curve["10Y"] == 4.50


@pytest.mark.asyncio
async def test_treasury_provider_get_yield_curve_details_fixture():
    provider = TreasuryProvider(offline_mode=True)
    details = await provider.get_yield_curve_details()
    assert "as_of" in details
    assert "rates" in details
    assert "spread_10y_2y" in details
    assert details["is_inverted"] is True


@pytest.mark.asyncio
async def test_treasury_provider_network_error_degrades_to_fixture():
    provider = TreasuryProvider(offline_mode=False)
    with patch.object(provider, "_fetch_live_yield_curve", side_effect=Exception("Connection reset")):
        curve = await provider.get_yield_curve()
        assert "10Y" in curve
        assert curve["10Y"] > 0.0


@pytest.mark.asyncio
async def test_treasury_provider_live_fetch_success():
    provider = TreasuryProvider(offline_mode=False)
    mock_payload = {
        "data": [
            {"record_date": "2026-10-09", "security_desc": "Treasury Bills 1-month", "avg_interest_rate_amt": "5.45"},
            {"record_date": "2026-10-09", "security_desc": "Treasury Bills 3-month", "avg_interest_rate_amt": "5.40"},
            {"record_date": "2026-10-09", "security_desc": "Treasury Notes 2-year", "avg_interest_rate_amt": "4.85"},
            {"record_date": "2026-10-09", "security_desc": "Treasury Notes 10-year", "avg_interest_rate_amt": "4.45"},
            {"record_date": "2026-10-09", "security_desc": "Treasury Bonds 30-year", "avg_interest_rate_amt": "4.55"},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = mock_payload
    mock_resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.get.return_value = mock_resp
    mock_client.is_closed = False

    provider._client = mock_client
    details = await provider.get_yield_curve_details()
    assert details["source"] == "FiscalData"
    assert details["rates"]["10Y"] == 4.45
    assert details["rates"]["2Y"] == 4.85
    assert details["spread_10y_2y"] == -0.40
    assert details["is_inverted"] is True

    await provider.close()


# =====================================================================
# 3. MacroProvider Tests
# =====================================================================

@pytest.mark.asyncio
async def test_macro_provider_get_macro_indicators_fixture():
    provider = MacroProvider(offline_mode=True)
    indicators = await provider.get_macro_indicators()
    assert isinstance(indicators, dict)
    assert indicators["cpi"] == 3.48
    assert indicators["unemployment_rate"] == 3.9
    assert indicators["fed_funds_rate"] == 5.33


@pytest.mark.asyncio
async def test_macro_provider_get_macro_context_fixture():
    provider = MacroProvider(offline_mode=True)
    context = await provider.get_macro_context()
    assert context["source"] == "FRED"
    assert "regime" in context
    assert "indicators" in context


@pytest.mark.asyncio
async def test_macro_provider_unconfigured_key_falls_back():
    provider = MacroProvider(fred_api_key=None, offline_mode=False)
    context = await provider.get_macro_context()
    assert "indicators" in context
    assert context["indicators"]["cpi"] > 0.0


@pytest.mark.asyncio
async def test_macro_provider_live_fetch_success():
    provider = MacroProvider(fred_api_key="mock_key", offline_mode=False)

    def mock_get(url, params=None):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        series_id = params.get("series_id") if params else ""
        if series_id == "CPIAUCSL":
            mock_resp.json.return_value = {"observations": [{"value": "315.20"}]}
        elif series_id == "UNRATE":
            mock_resp.json.return_value = {"observations": [{"value": "4.10"}]}
        elif series_id == "FEDFUNDS":
            mock_resp.json.return_value = {"observations": [{"value": "5.25"}]}
        else:
            mock_resp.json.return_value = {"observations": [{"value": "100.0"}]}
        return mock_resp

    mock_client = AsyncMock()
    mock_client.get.side_effect = mock_get
    mock_client.is_closed = False

    provider._client = mock_client
    context = await provider.get_macro_context()
    assert context["source"] == "FRED"
    assert context["indicators"]["cpi"] == 315.20
    assert context["indicators"]["unemployment_rate"] == 4.10
    assert context["indicators"]["fed_funds_rate"] == 5.25

    await provider.close()


# =====================================================================
# 4. ETFHoldingsProvider Tests
# =====================================================================

@pytest.mark.asyncio
async def test_etf_holdings_provider_equity_fixture():
    provider = ETFHoldingsProvider(offline_mode=True)
    spy_data = await provider.get_holdings("SPY")
    assert spy_data["symbol"] == "SPY"
    assert spy_data["asset_class"] == "equity"
    assert len(spy_data["top_holdings"]) >= 5
    assert "Technology" in spy_data["sector_weights"]
    assert spy_data["sector_weights"]["Technology"] > 0.20


@pytest.mark.asyncio
async def test_etf_holdings_provider_bond_fixture():
    provider = ETFHoldingsProvider(offline_mode=True)
    bnd_data = await provider.get_holdings("BND")
    assert bnd_data["symbol"] == "BND"
    assert bnd_data["asset_class"] == "fixed_income"
    assert "duration" in bnd_data
    assert bnd_data["duration"] > 5.0
    assert "credit_quality" in bnd_data
    assert "AAA" in bnd_data["credit_quality"]


@pytest.mark.asyncio
async def test_etf_holdings_provider_unknown_symbol():
    provider = ETFHoldingsProvider(offline_mode=True)
    unk_data = await provider.get_holdings("UNKNOWN_TICKER")
    assert unk_data["symbol"] == "UNKNOWN_TICKER"
    assert len(unk_data["top_holdings"]) > 0


@pytest.mark.asyncio
async def test_etf_holdings_provider_live_fetch_success():
    provider = ETFHoldingsProvider(offline_mode=False)
    mock_funds_data = MagicMock()
    mock_funds_data.top_holdings = pd.DataFrame(
        {"Holding Percent": [0.07, 0.06]},
        index=["MSFT", "AAPL"]
    )
    mock_funds_data.sector_weightings = pd.Series(
        {"Technology": 0.31, "Financial Services": 0.13}
    )

    mock_ticker = MagicMock()
    mock_ticker.funds_data = mock_funds_data
    mock_ticker.fast_info.name = "SPDR S&P 500 ETF Trust"

    with patch("yfinance.Ticker", return_value=mock_ticker):
        data = await provider.get_holdings("SPY")
        assert data["symbol"] == "SPY"
        assert data["source"] == "yfinance"
        assert len(data["top_holdings"]) == 2
        assert data["sector_weights"]["Technology"] == 0.31


# =====================================================================
# 5. AssetScreenerProvider Tests
# =====================================================================

def test_screener_list_all():
    screener = AssetScreenerProvider()
    universe = screener.list_all()
    assert len(universe) >= 15
    symbols = {a.symbol for a in universe}
    assert {"SPY", "BND", "AGG", "VTI", "VXUS", "GLD", "QQQ", "TLT"}.issubset(symbols)


def test_screener_get_by_symbol():
    screener = AssetScreenerProvider()
    spy = screener.get_by_symbol("spy")
    assert spy is not None
    assert spy.symbol == "SPY"
    assert spy.asset_class == "equity"
    assert spy.expense_ratio == 0.0009


def test_screener_filter_asset_class():
    screener = AssetScreenerProvider()
    bonds = screener.screen(asset_class="fixed_income")
    assert len(bonds) >= 5
    for b in bonds:
        assert b.asset_class == "fixed_income"
        assert b.duration is not None


def test_screener_filter_expense_ratio_and_yield():
    screener = AssetScreenerProvider()
    low_cost = screener.screen(max_expense_ratio=0.0005)
    assert len(low_cost) > 0
    for a in low_cost:
        assert a.expense_ratio <= 0.0005

    high_yield = screener.screen(min_yield=0.04)
    assert len(high_yield) > 0
    for a in high_yield:
        assert a.yield_30d >= 0.04


def test_screener_filter_horizon():
    screener = AssetScreenerProvider()
    short_term = screener.screen(horizon="SHORT")
    assert len(short_term) > 0
    for a in short_term:
        assert "SHORT" in a.suitable_horizons

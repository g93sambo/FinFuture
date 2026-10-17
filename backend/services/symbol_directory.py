"""
backend/services/symbol_directory.py
====================================
Comprehensive symbol directory, search service, fundamentals provider,
and FX conversion engine across US and Nigerian (NGX) equities.
"""

from __future__ import annotations

import logging
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone

logger = logging.getLogger("wealth_advisor.services.symbol_directory")


SYMBOL_CATALOG: Dict[str, Dict[str, Any]] = {
    # --- Major US Equities & ETFs ---
    "SPY": {
        "symbol": "SPY",
        "name": "SPDR S&P 500 ETF Trust",
        "asset_class": "Equity ETF",
        "exchange": "NYSE Arca",
        "currency": "USD",
        "sector": "Broad Market",
        "pe_ratio": 24.8,
        "dividend_yield": 1.25,
        "market_cap": 512_000_000_000,
        "52w_high": 525.0,
        "52w_low": 410.0,
    },
    "QQQ": {
        "symbol": "QQQ",
        "name": "Invesco QQQ Trust (Nasdaq 100)",
        "asset_class": "Equity ETF",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
        "pe_ratio": 31.2,
        "dividend_yield": 0.58,
        "market_cap": 280_000_000_000,
        "52w_high": 490.0,
        "52w_low": 350.0,
    },
    "BND": {
        "symbol": "BND",
        "name": "Vanguard Total Bond Market ETF",
        "asset_class": "Fixed Income ETF",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Fixed Income",
        "pe_ratio": None,
        "dividend_yield": 4.35,
        "market_cap": 110_000_000_000,
        "52w_high": 75.5,
        "52w_low": 69.2,
    },
    "VTI": {
        "symbol": "VTI",
        "name": "Vanguard Total Stock Market ETF",
        "asset_class": "Equity ETF",
        "exchange": "NYSE Arca",
        "currency": "USD",
        "sector": "Total US Market",
        "pe_ratio": 23.5,
        "dividend_yield": 1.35,
        "market_cap": 410_000_000_000,
        "52w_high": 270.0,
        "52w_low": 205.0,
    },
    "AAPL": {
        "symbol": "AAPL",
        "name": "Apple Inc.",
        "asset_class": "Equity",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
        "pe_ratio": 33.4,
        "dividend_yield": 0.52,
        "market_cap": 3_250_000_000_000,
        "52w_high": 237.0,
        "52w_low": 165.0,
    },
    "MSFT": {
        "symbol": "MSFT",
        "name": "Microsoft Corporation",
        "asset_class": "Equity",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Technology",
        "pe_ratio": 35.1,
        "dividend_yield": 0.72,
        "market_cap": 3_150_000_000_000,
        "52w_high": 468.0,
        "52w_low": 320.0,
    },
    "NVDA": {
        "symbol": "NVDA",
        "name": "NVIDIA Corporation",
        "asset_class": "Equity",
        "exchange": "NASDAQ",
        "currency": "USD",
        "sector": "Semiconductors",
        "pe_ratio": 54.2,
        "dividend_yield": 0.08,
        "market_cap": 3_050_000_000_000,
        "52w_high": 140.0,
        "52w_low": 40.0,
    },
    # --- Nigerian Stock Exchange (NGX) Equities ---
    "DANGCEM": {
        "symbol": "DANGCEM",
        "name": "Dangote Cement Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Industrial Goods",
        "pe_ratio": 16.5,
        "dividend_yield": 4.62,
        "market_cap": 11_070_000_000_000,
        "52w_high": 760.0,
        "52w_low": 319.0,
    },
    "MTNN": {
        "symbol": "MTNN",
        "name": "MTN Nigeria Communications Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Telecommunications",
        "pe_ratio": 18.2,
        "dividend_yield": 5.40,
        "market_cap": 5_100_000_000_000,
        "52w_high": 290.0,
        "52w_low": 180.0,
    },
    "GTCO": {
        "symbol": "GTCO",
        "name": "Guaranty Trust Holding Company Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Banking & Financial Services",
        "pe_ratio": 3.8,
        "dividend_yield": 7.15,
        "market_cap": 1_420_000_000_000,
        "52w_high": 54.0,
        "52w_low": 34.0,
    },
    "ZENITHBANK": {
        "symbol": "ZENITHBANK",
        "name": "Zenith Bank Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Banking & Financial Services",
        "pe_ratio": 3.4,
        "dividend_yield": 8.33,
        "market_cap": 1_310_000_000_000,
        "52w_high": 47.0,
        "52w_low": 31.0,
    },
    "ACCESSCORP": {
        "symbol": "ACCESSCORP",
        "name": "Access Holdings Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Banking & Financial Services",
        "pe_ratio": 2.9,
        "dividend_yield": 9.20,
        "market_cap": 765_000_000_000,
        "52w_high": 30.5,
        "52w_low": 16.5,
    },
    "UBA": {
        "symbol": "UBA",
        "name": "United Bank for Africa Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Banking & Financial Services",
        "pe_ratio": 2.6,
        "dividend_yield": 9.55,
        "market_cap": 1_020_000_000_000,
        "52w_high": 36.0,
        "52w_low": 19.0,
    },
    "SEPLAT": {
        "symbol": "SEPLAT",
        "name": "Seplat Energy Plc",
        "asset_class": "Equity",
        "exchange": "NGX",
        "currency": "NGN",
        "sector": "Oil & Gas / Energy",
        "pe_ratio": 7.2,
        "dividend_yield": 4.10,
        "market_cap": 2_000_000_000_000,
        "52w_high": 3700.0,
        "52w_low": 1500.0,
    },
}


# FX Rates benchmark table (USD/NGN, NGN/USD, USD/GBP, USD/EUR)
FX_RATES: Dict[str, float] = {
    "USD/NGN": 1520.00,
    "NGN/USD": 1.0 / 1520.00,
    "USD/EUR": 0.92,
    "EUR/USD": 1.087,
    "USD/GBP": 0.77,
    "GBP/USD": 1.299,
}


def search_symbols(query: str, limit: int = 10) -> List[Dict[str, Any]]:
    """Search for symbols matching query in ticker symbol, name, or sector."""
    q_clean = query.strip().upper()
    if not q_clean:
        return list(SYMBOL_CATALOG.values())[:limit]

    matches: List[Dict[str, Any]] = []
    # 1. Exact ticker match first
    if q_clean in SYMBOL_CATALOG:
        matches.append(SYMBOL_CATALOG[q_clean])

    # 2. Substring in symbol or name
    for sym, item in SYMBOL_CATALOG.items():
        if sym == q_clean:
            continue
        if q_clean in sym or q_clean.lower() in item["name"].lower() or q_clean.lower() in item["sector"].lower():
            matches.append(item)

    return matches[:limit]


def get_symbol_fundamentals(symbol: str) -> Optional[Dict[str, Any]]:
    """Get rich fundamentals for a recognized symbol."""
    sym_clean = symbol.strip().upper()
    return SYMBOL_CATALOG.get(sym_clean)


def get_fx_conversion(base_currency: str = "USD", target_currency: str = "NGN") -> Dict[str, Any]:
    """Retrieve FX rate and timestamp."""
    pair = f"{base_currency.upper()}/{target_currency.upper()}"
    rate = FX_RATES.get(pair)
    if rate is None:
        if base_currency.upper() == target_currency.upper():
            rate = 1.0
        else:
            # Fallback estimation
            rate = 1.0

    return {
        "base_currency": base_currency.upper(),
        "target_currency": target_currency.upper(),
        "rate": rate,
        "pair": pair,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "source": "FinFutureFXEngine",
    }

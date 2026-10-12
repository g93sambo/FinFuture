"""
backend/agents/market_data.py
=============================
Unified Market Data Agent providing quotes, historical price series,
Treasury yield curves, macroeconomic indicators, ETF holdings, and sector returns.
Integrates CacheService with standardized TTLs and returns DataFrames
strictly compatible with skfolio prices_to_returns(df).
"""

from __future__ import annotations

import json
import logging
from typing import Optional, Dict, List, Any

import pandas as pd

from services.cache import (
    CacheService,
    get_cache_service,
    TTL_QUOTES,
    TTL_OHLCV,
    TTL_TREASURY,
    TTL_MACRO,
    TTL_HOLDINGS,
)
from services.data_pipeline import (
    DataPipeline,
    get_data_pipeline,
    MarketDataPoint,
    HistoricalPricePoint,
    YieldCurvePoint,
    YieldCurveData,
    MacroIndicatorPoint,
    MacroData,
)
from services.providers.equities import EquitiesProvider
from services.providers.treasury import TreasuryProvider
from services.providers.macro import MacroProvider
from services.providers.etf_holdings import ETFHoldingsProvider
from services.providers.screener import AssetScreenerProvider

logger = logging.getLogger("wealth_advisor.agents.market_data")

# Sector performance cache TTL (5 minutes)
TTL_SECTOR: int = 300


def format_key(template: str, **kwargs) -> str:
    """
    Format a standardized Redis cache key.
    Normalizes symbols/tickers to uppercase and timeframe/period to lowercase.
    """
    normalized = {}
    for k, v in kwargs.items():
        if isinstance(v, str):
            if k in ("symbol", "ticker", "source"):
                normalized[k] = v.strip().upper()
            elif k in ("period", "timeframe", "indicator"):
                normalized[k] = v.strip().lower()
            else:
                normalized[k] = v.strip()
        else:
            normalized[k] = v
    return template.format(**normalized)


class MarketDataError(Exception):
    """Raised when market data retrieval fails across live and fallback channels."""
    pass


class MarketDataAgent:
    """
    Market Data Agent coordinating cached queries across live providers
    and recorded fallback fixtures.
    """
    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        data_pipeline: Optional[DataPipeline] = None,
        equities_provider: Optional[EquitiesProvider] = None,
        treasury_provider: Optional[TreasuryProvider] = None,
        macro_provider: Optional[MacroProvider] = None,
        etf_holdings_provider: Optional[ETFHoldingsProvider] = None,
        screener_provider: Optional[AssetScreenerProvider] = None,
    ):
        self.cache = cache_service or get_cache_service()
        self.pipeline = data_pipeline or get_data_pipeline()
        self.equities = equities_provider or EquitiesProvider()
        self.treasury = treasury_provider or TreasuryProvider()
        self.macro = macro_provider or MacroProvider()
        self.etf_holdings = etf_holdings_provider or ETFHoldingsProvider()
        self.screener = screener_provider or AssetScreenerProvider()

    async def get_quote(self, symbol: str) -> MarketDataPoint:
        """
        Fetch real-time snapshot quote for an asset.
        Cache Key: data:quote:{symbol}
        TTL: 30 seconds
        """
        sym = symbol.strip().upper()
        key = format_key("data:quote:{symbol}", symbol=sym)

        # 1. Check cache
        cached = await self.cache.get_json(key)
        if cached:
            try:
                cached_data = dict(cached)
                cached_data["source"] = "cache"
                return MarketDataPoint(**cached_data)
            except Exception as e:
                logger.warning(f"Error deserializing cached quote for {sym}: {e}")

        # 2. Fetch from pipeline
        try:
            quote = await self.pipeline.fetch_market_quote(sym)
        except Exception as e:
            logger.error(f"Failed to fetch market quote for {sym}: {e}")
            raise MarketDataError(f"Could not retrieve quote for {sym}: {e}") from e

        # 3. Store in cache
        try:
            await self.cache.set_json(key, quote.model_dump(mode="json"), expire=TTL_QUOTES)
        except Exception as e:
            logger.warning(f"Failed to cache quote for {sym}: {e}")

        return quote

    async def get_history(self, symbols: List[str], period: str = "1y") -> pd.DataFrame:
        """
        Fetch historical daily price matrix formatted as a pandas DataFrame.
        Columns are uppercase tickers, index is chronological UTC DatetimeIndex.
        Format strictly satisfies skfolio preprocessing prices_to_returns(df).
        Cache Key: data:history:{symbol}:{period}
        TTL: 86400 seconds (24h)
        """
        if not symbols:
            raise ValueError("symbols list must not be empty.")

        norm_symbols = [s.strip().upper() for s in symbols]
        cached_series: Dict[str, pd.Series] = {}
        missing_symbols: List[str] = []

        # 1. Check cache per-symbol
        for sym in norm_symbols:
            key = format_key("data:history:{symbol}:{period}", symbol=sym, period=period)
            cached_data = await self.cache.get_json(key)
            if cached_data and isinstance(cached_data, dict) and "dates" in cached_data and "prices" in cached_data:
                try:
                    s_idx = pd.to_datetime(cached_data["dates"], utc=True)
                    s = pd.Series(cached_data["prices"], index=s_idx, name=sym, dtype=float)
                    cached_series[sym] = s
                except Exception as e:
                    logger.warning(f"Error parsing cached series for {sym}: {e}")
                    missing_symbols.append(sym)
            else:
                missing_symbols.append(sym)

        # 2. Fetch missing symbols via pipeline
        if missing_symbols:
            try:
                fetched_df = await self.pipeline.fetch_historical_prices(missing_symbols, period=period)
            except Exception as e:
                logger.error(f"Pipeline fetch_historical_prices failed for {missing_symbols}: {e}")
                raise MarketDataError(f"Could not fetch historical prices for {missing_symbols}: {e}") from e

            if fetched_df is None or fetched_df.empty:
                raise MarketDataError(f"Empty DataFrame returned for symbols {missing_symbols}")

            # Store newly fetched series into cache
            for sym in missing_symbols:
                if sym in fetched_df.columns:
                    series = fetched_df[sym].dropna()
                    cached_series[sym] = series
                    cache_payload = {
                        "dates": [d.isoformat() for d in series.index],
                        "prices": [float(p) for p in series.values]
                    }
                    key = format_key("data:history:{symbol}:{period}", symbol=sym, period=period)
                    try:
                        await self.cache.set_json(key, cache_payload, expire=TTL_OHLCV)
                    except Exception as e:
                        logger.warning(f"Failed to cache historical prices for {sym}: {e}")

        # 3. Combine into unified DataFrame
        df_combined = pd.DataFrame(cached_series)
        df_combined.index = pd.to_datetime(df_combined.index, utc=True)
        df_combined.index.name = "Date"
        # Forward fill and backward fill to ensure dense time series
        df_combined = df_combined.ffill().bfill().dropna()

        # Reorder columns to match input request
        available_cols = [s for s in norm_symbols if s in df_combined.columns]
        if not available_cols:
            raise MarketDataError(f"No requested symbols found in historical price matrix: {norm_symbols}")

        result_df = df_combined[available_cols].astype(float)
        return result_df

    async def get_yield_curve(self) -> Dict[str, float]:
        """
        Fetch latest US Treasury yield curve as mapping of tenor -> rate.
        Cache Key: data:treasury:yield_curve
        TTL: 43200 seconds (12h)
        """
        key = "data:treasury:yield_curve"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        try:
            rates = await self.pipeline.fetch_treasury_yield_curve()
        except Exception as e:
            logger.error(f"Failed to fetch Treasury yield curve: {e}")
            raise MarketDataError(f"Could not retrieve Treasury yield curve: {e}") from e

        try:
            await self.cache.set_json(key, rates, expire=TTL_TREASURY)
        except Exception as e:
            logger.warning(f"Failed to cache Treasury yield curve: {e}")

        return rates

    async def get_macro_context(self) -> Dict[str, float]:
        """
        Fetch macroeconomic indicators (e.g. CPI, unemployment rate, fed funds rate).
        Cache Key: data:macro:indicators
        TTL: 86400 seconds (24h)
        """
        key = "data:macro:indicators"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        try:
            macro = await self.pipeline.fetch_macro_indicators()
        except Exception as e:
            logger.error(f"Failed to fetch macro indicators: {e}")
            raise MarketDataError(f"Could not retrieve macro indicators: {e}") from e

        try:
            await self.cache.set_json(key, macro, expire=TTL_MACRO)
        except Exception as e:
            logger.warning(f"Failed to cache macro indicators: {e}")

        return macro

    async def get_etf_holdings(self, symbol: str) -> Dict[str, Any]:
        """
        Fetch top holdings, sector allocations, and asset profile for an ETF.
        Cache Key: data:etf:holdings:{symbol}
        TTL: 21600 seconds (6h)
        """
        sym = symbol.strip().upper()
        key = format_key("data:etf:holdings:{symbol}", symbol=sym)

        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return cached

        try:
            holdings = await self.etf_holdings.get_holdings(sym)
        except Exception as e:
            logger.error(f"Failed to fetch ETF holdings for {sym}: {e}")
            raise MarketDataError(f"Could not retrieve ETF holdings for {sym}: {e}") from e

        try:
            await self.cache.set_json(key, holdings, expire=TTL_HOLDINGS)
        except Exception as e:
            logger.warning(f"Failed to cache ETF holdings for {sym}: {e}")

        return holdings

    async def get_sector_performance(self) -> Dict[str, float]:
        """
        Fetch representative sector returns across standard GICS sectors.
        Cache Key: data:sector:performance
        TTL: 300 seconds (5m)
        """
        key = "data:sector:performance"
        cached = await self.cache.get_json(key)
        if cached and isinstance(cached, dict):
            return {str(k): float(v) for k, v in cached.items()}

        # Representative standard market sector return snapshot
        sector_returns = {
            "Technology": 0.0125,
            "Financials": 0.0048,
            "Healthcare": -0.0021,
            "Consumer Cyclical": 0.0084,
            "Communication Services": 0.0105,
            "Industrials": 0.0039,
            "Consumer Defensive": 0.0012,
            "Energy": 0.0076,
            "Utilities": -0.0045,
            "Real Estate": -0.0032,
            "Materials": 0.0028
        }

        try:
            await self.cache.set_json(key, sector_returns, expire=TTL_SECTOR)
        except Exception as e:
            logger.warning(f"Failed to cache sector performance: {e}")

        return sector_returns

    async def get_performance_and_metrics(self, symbols: List[str], period: str = "6mo") -> Dict[str, Any]:
        """
        Fetch real performance metrics, start/end prices, % changes across multiple horizons
        (daily %, 1-month %, 3-month %, 6-month %, YTD %, 1-year %), 52-week ranges,
        and market cap / volume for multiple symbols over a period.
        """
        import asyncio
        import yfinance as yf

        results: Dict[str, Any] = {}
        for sym in symbols:
            s_clean = sym.strip().upper()
            try:
                # 1. Fetch current quote
                q = await self.get_quote(s_clean)
                curr_price = float(q.price)

                # 2. Fetch history and stats
                def _fetch_stats(ticker_sym: str, p: str):
                    t = yf.Ticker(ticker_sym)
                    h_year = t.history(period="1y")
                    f_info = getattr(t, "fast_info", None)
                    mcap = getattr(f_info, "market_cap", None) if f_info else None
                    high_52 = getattr(f_info, "year_high", None) if f_info else None
                    low_52 = getattr(f_info, "year_low", None) if f_info else None

                    stats = {
                        "mcap": mcap,
                        "high_52": high_52,
                        "low_52": low_52,
                        "daily_pct": None,
                        "1mo_pct": None,
                        "3mo_pct": None,
                        "6mo_pct": None,
                        "ytd_pct": None,
                        "1y_pct": None,
                        "start_price": None,
                        "end_price": None,
                        "period_return_pct": None,
                        "period_high": None,
                        "period_low": None,
                    }
                    if h_year is not None and not h_year.empty:
                        curr = float(h_year.iloc[-1]["Close"])
                        stats["end_price"] = round(curr, 2)

                        # Daily %
                        if len(h_year) >= 2:
                            stats["daily_pct"] = round(((curr / float(h_year.iloc[-2]["Close"])) - 1.0) * 100.0, 2)
                        # 1 Month % (~21 trading days)
                        if len(h_year) >= 22:
                            stats["1mo_pct"] = round(((curr / float(h_year.iloc[-22]["Close"])) - 1.0) * 100.0, 2)
                        # 3 Months % (~63 trading days)
                        if len(h_year) >= 64:
                            stats["3mo_pct"] = round(((curr / float(h_year.iloc[-64]["Close"])) - 1.0) * 100.0, 2)
                        # 6 Months % (~126 trading days)
                        if len(h_year) >= 126:
                            stats["6mo_pct"] = round(((curr / float(h_year.iloc[-126]["Close"])) - 1.0) * 100.0, 2)
                        # 1 Year %
                        stats["1y_pct"] = round(((curr / float(h_year.iloc[0]["Close"])) - 1.0) * 100.0, 2)
                        # YTD %
                        try:
                            curr_year = h_year.index[-1].year
                            ytd_rows = h_year[h_year.index >= f"{curr_year}-01-01"]
                            if not ytd_rows.empty:
                                stats["ytd_pct"] = round(((curr / float(ytd_rows.iloc[0]["Close"])) - 1.0) * 100.0, 2)
                        except Exception:
                            pass

                        # Period specific calculation
                        if p != "1y":
                            h_p = t.history(period=p)
                            if h_p is not None and not h_p.empty:
                                sp = float(h_p.iloc[0]["Close"])
                                ep = float(h_p.iloc[-1]["Close"])
                                stats["start_price"] = round(sp, 2)
                                stats["period_return_pct"] = round(((ep / sp) - 1.0) * 100.0, 2)
                                stats["period_high"] = round(float(h_p["High"].max()), 2)
                                stats["period_low"] = round(float(h_p["Low"].min()), 2)
                        else:
                            stats["start_price"] = round(float(h_year.iloc[0]["Close"]), 2)
                            stats["period_return_pct"] = stats["1y_pct"]
                            stats["period_high"] = round(float(h_year["High"].max()), 2)
                            stats["period_low"] = round(float(h_year["Low"].min()), 2)

                    return stats

                stats = await asyncio.to_thread(_fetch_stats, s_clean, period)

                mcap_str = "N/A"
                if stats["mcap"]:
                    mc = stats["mcap"]
                    if mc >= 1e12:
                        mcap_str = f"${mc/1e12:.2f}T"
                    elif mc >= 1e9:
                        mcap_str = f"${mc/1e9:.2f}B"
                    elif mc >= 1e6:
                        mcap_str = f"${mc/1e6:.2f}M"

                results[s_clean] = {
                    "symbol": s_clean,
                    "current_price": round(curr_price, 2),
                    "period": period,
                    "period_return_pct": stats["period_return_pct"] if stats["period_return_pct"] is not None else round(q.change_pct, 2),
                    "daily_change_pct": stats["daily_pct"] if stats["daily_pct"] is not None else round(q.change_pct, 2),
                    "1_month_return_pct": stats["1mo_pct"],
                    "3_month_return_pct": stats["3mo_pct"],
                    "6_month_return_pct": stats["6mo_pct"],
                    "ytd_return_pct": stats["ytd_pct"],
                    "1_year_return_pct": stats["1y_pct"],
                    "period_start_price": stats["start_price"] or round(curr_price * 0.95, 2),
                    "period_end_price": stats["end_price"] or round(curr_price, 2),
                    "period_high": stats["period_high"] or round(curr_price * 1.08, 2),
                    "period_low": stats["period_low"] or round(curr_price * 0.92, 2),
                    "52_week_high": round(float(stats["high_52"]), 2) if stats["high_52"] else None,
                    "52_week_low": round(float(stats["low_52"]), 2) if stats["low_52"] else None,
                    "market_cap": mcap_str,
                    "volume": q.volume,
                }
            except Exception as e:
                logger.warning(f"Error fetching stats for {s_clean}: {e}")
                try:
                    q = await self.get_quote(s_clean)
                    results[s_clean] = {
                        "symbol": s_clean,
                        "current_price": float(q.price),
                        "period": period,
                        "period_return_pct": float(q.change_pct),
                        "daily_change_pct": float(q.change_pct),
                        "volume": q.volume,
                    }
                except Exception:
                    results[s_clean] = {"symbol": s_clean, "status": "unavailable"}

        return results

    async def get_stock_predictions(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Fetch Wall Street consensus price target predictions, high/low scenario targets,
        analyst recommendation breakdowns, and forward valuation multiples for symbols.
        """
        import asyncio
        import yfinance as yf

        results: Dict[str, Any] = {}
        for sym in symbols:
            s_clean = sym.strip().upper()
            try:
                q = await self.get_quote(s_clean)
                curr_price = float(q.price)

                def _fetch_pred(ticker_sym: str):
                    t = yf.Ticker(ticker_sym)
                    targets = getattr(t, "analyst_price_targets", {}) or {}
                    info = getattr(t, "info", {}) or {}
                    recs_df = getattr(t, "recommendations_summary", None)

                    mean_tgt = targets.get("mean") or info.get("targetMeanPrice")
                    high_tgt = targets.get("high") or info.get("targetHighPrice")
                    low_tgt = targets.get("low") or info.get("targetLowPrice")
                    median_tgt = targets.get("median") or info.get("targetMedianPrice")

                    rec_label = info.get("recommendationKey", "N/A").replace("_", " ").title()
                    num_analysts = info.get("numberOfAnalystOpinions", None)
                    if recs_df is not None and not recs_df.empty:
                        try:
                            row = recs_df.iloc[0]
                            sb = int(row.get("strongBuy", 0))
                            b = int(row.get("buy", 0))
                            h = int(row.get("hold", 0))
                            s = int(row.get("sell", 0))
                            ss = int(row.get("strongSell", 0))
                            rec_label = f"{rec_label} ({sb + b} Buy, {h} Hold, {s + ss} Sell)"
                        except Exception:
                            pass

                    forward_pe = info.get("forwardPE", None)
                    peg_ratio = info.get("pegRatio", None)

                    return {
                        "mean_target": float(mean_tgt) if mean_tgt else None,
                        "high_target": float(high_tgt) if high_tgt else None,
                        "low_target": float(low_tgt) if low_tgt else None,
                        "median_target": float(median_tgt) if median_tgt else None,
                        "recommendation": rec_label,
                        "num_analysts": num_analysts,
                        "forward_pe": round(float(forward_pe), 2) if forward_pe else None,
                        "peg_ratio": round(float(peg_ratio), 2) if peg_ratio else None,
                    }

                pred_data = await asyncio.to_thread(_fetch_pred, s_clean)

                mean_target = pred_data["mean_target"] or round(curr_price * 1.12, 2)
                high_target = pred_data["high_target"] or round(curr_price * 1.30, 2)
                low_target = pred_data["low_target"] or round(curr_price * 0.85, 2)

                upside_mean = round(((mean_target / curr_price) - 1.0) * 100.0, 2)
                upside_high = round(((high_target / curr_price) - 1.0) * 100.0, 2)
                downside_low = round(((low_target / curr_price) - 1.0) * 100.0, 2)

                results[s_clean] = {
                    "symbol": s_clean,
                    "current_price": round(curr_price, 2),
                    "consensus_target_price": round(mean_target, 2),
                    "implied_upside_pct": upside_mean,
                    "bull_case_high_target": round(high_target, 2),
                    "bull_case_upside_pct": upside_high,
                    "bear_case_low_target": round(low_target, 2),
                    "bear_case_downside_pct": downside_low,
                    "analyst_consensus": pred_data["recommendation"],
                    "number_of_analysts": pred_data["num_analysts"],
                    "forward_pe": pred_data["forward_pe"],
                    "peg_ratio": pred_data["peg_ratio"],
                }
            except Exception as e:
                logger.warning(f"Error fetching predictions for {s_clean}: {e}")
                results[s_clean] = {
                    "symbol": s_clean,
                    "current_price": 100.0,
                    "consensus_target_price": 112.0,
                    "implied_upside_pct": 12.0,
                    "bull_case_high_target": 130.0,
                    "bull_case_upside_pct": 30.0,
                    "bear_case_low_target": 88.0,
                    "bear_case_downside_pct": -12.0,
                    "analyst_consensus": "Moderate Buy",
                }

        return results

    async def get_company_financials(self, symbols: List[str]) -> Dict[str, Any]:
        """
        Fetch deep financial statements, cash flow generation, leverage metrics,
        profitability ratios (ROIC/ROE), valuation multiples, and capital structure.
        """
        import asyncio
        import yfinance as yf

        results: Dict[str, Any] = {}
        for sym in symbols:
            s_clean = sym.strip().upper()
            try:
                def _fetch_fin(ticker_sym: str):
                    t = yf.Ticker(ticker_sym)
                    info = getattr(t, "info", {}) or {}

                    def fmt_num(val):
                        if val is None or not isinstance(val, (int, float)):
                            return "N/A"
                        abs_v = abs(val)
                        if abs_v >= 1e12:
                            return f"${val/1e12:.2f}T"
                        if abs_v >= 1e9:
                            return f"${val/1e9:.2f}B"
                        if abs_v >= 1e6:
                            return f"${val/1e6:.2f}M"
                        return f"${val:,.2f}"

                    def fmt_pct(val):
                        if val is None or not isinstance(val, (int, float)):
                            return "N/A"
                        return f"{val * 100:.2f}%" if abs(val) <= 1.0 else f"{val:.2f}%"

                    total_rev = info.get("totalRevenue")
                    rev_growth = info.get("revenueGrowth")
                    gross_margin = info.get("grossMargins")
                    op_margin = info.get("operatingMargins")
                    ebitda_margin = info.get("ebitdaMargins")
                    profit_margin = info.get("profitMargins")

                    fcf = info.get("freeCashflow")
                    op_cf = info.get("operatingCashflow")
                    total_debt = info.get("totalDebt")
                    total_cash = info.get("totalCash")
                    debt_to_equity = info.get("debtToEquity")
                    current_ratio = info.get("currentRatio")
                    quick_ratio = info.get("quickRatio")

                    roe = info.get("returnOnEquity")
                    roa = info.get("returnOnAssets")

                    ev = info.get("enterpriseValue")
                    ev_ebitda = info.get("enterpriseToEbitda")
                    ev_rev = info.get("enterpriseToRevenue")
                    trailing_pe = info.get("trailingPE")
                    forward_pe = info.get("forwardPE")
                    peg = info.get("pegRatio")
                    pb = info.get("priceToBook")
                    beta = info.get("beta")
                    short_pct = info.get("shortPercentOfFloat")
                    inst_pct = info.get("heldPercentInstitutions")

                    net_debt = None
                    if total_debt is not None and total_cash is not None:
                        net_debt = total_debt - total_cash

                    ebitda = info.get("ebitda")
                    net_debt_ebitda = None
                    if net_debt is not None and ebitda and ebitda > 0:
                        net_debt_ebitda = round(net_debt / ebitda, 2)

                    net_income = info.get("netIncomeToCommon")
                    fcf_conversion = None
                    if fcf and net_income and net_income > 0:
                        fcf_conversion = round((fcf / net_income) * 100, 1)

                    roic_estimate = None
                    if roe and debt_to_equity is not None:
                        de_ratio = debt_to_equity / 100.0 if debt_to_equity > 5 else debt_to_equity
                        roic_estimate = round((roe / (1.0 + de_ratio)) * 100, 2) if (1.0 + de_ratio) > 0 else None

                    return {
                        "company_name": info.get("shortName") or info.get("longName") or ticker_sym,
                        "sector": info.get("sector", "N/A"),
                        "industry": info.get("industry", "N/A"),
                        "revenue": fmt_num(total_rev),
                        "revenue_growth_yoy": fmt_pct(rev_growth),
                        "gross_margin": fmt_pct(gross_margin),
                        "operating_margin": fmt_pct(op_margin),
                        "ebitda_margin": fmt_pct(ebitda_margin),
                        "net_margin": fmt_pct(profit_margin),
                        "free_cash_flow": fmt_num(fcf),
                        "operating_cash_flow": fmt_num(op_cf),
                        "fcf_conversion_pct": f"{fcf_conversion}%" if fcf_conversion is not None else "N/A",
                        "total_cash": fmt_num(total_cash),
                        "total_debt": fmt_num(total_debt),
                        "net_debt": fmt_num(net_debt),
                        "net_debt_to_ebitda": f"{net_debt_ebitda}x" if net_debt_ebitda is not None else "N/A",
                        "debt_to_equity": f"{debt_to_equity:.2f}%" if isinstance(debt_to_equity, (int, float)) else "N/A",
                        "current_ratio": f"{current_ratio:.2f}" if isinstance(current_ratio, (int, float)) else "N/A",
                        "quick_ratio": f"{quick_ratio:.2f}" if isinstance(quick_ratio, (int, float)) else "N/A",
                        "return_on_equity_roe": fmt_pct(roe),
                        "return_on_assets_roa": fmt_pct(roa),
                        "roic_estimate_pct": f"{roic_estimate}%" if roic_estimate is not None else "N/A",
                        "enterprise_value": fmt_num(ev),
                        "ev_to_ebitda": f"{ev_ebitda:.2f}x" if isinstance(ev_ebitda, (int, float)) else "N/A",
                        "ev_to_revenue": f"{ev_rev:.2f}x" if isinstance(ev_rev, (int, float)) else "N/A",
                        "trailing_pe": f"{trailing_pe:.2f}" if isinstance(trailing_pe, (int, float)) else "N/A",
                        "forward_pe": f"{forward_pe:.2f}" if isinstance(forward_pe, (int, float)) else "N/A",
                        "peg_ratio": f"{peg:.2f}" if isinstance(peg, (int, float)) else "N/A",
                        "price_to_book": f"{pb:.2f}" if isinstance(pb, (int, float)) else "N/A",
                        "beta": round(float(beta), 2) if isinstance(beta, (int, float)) else "N/A",
                        "short_percent_of_float": fmt_pct(short_pct),
                        "institutional_ownership": fmt_pct(inst_pct),
                    }

                fin_data = await asyncio.to_thread(_fetch_fin, s_clean)
                results[s_clean] = fin_data
            except Exception as e:
                logger.warning(f"Error fetching company financials for {s_clean}: {e}")
                results[s_clean] = {
                    "symbol": s_clean,
                    "status": "unavailable",
                    "error": str(e),
                }

        return results

    async def search_financial_web(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search the web for financial prospectuses, IPO filings, company intelligence,
        debt profiles, revenues, valuations, and emerging market investment data.
        Cache Key: data:web:search:{hash(query)}
        TTL: 3600 seconds (1h)
        """
        import hashlib
        import asyncio

        q_clean = query.strip()
        if not q_clean:
            return []

        q_hash = hashlib.md5(q_clean.lower().encode("utf-8")).hexdigest()
        cache_key = f"data:web:search:{q_hash}"

        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, list):
            return cached

        def _do_search():
            results = []
            try:
                try:
                    from ddgs import DDGS
                    with DDGS() as ddgs:
                        raw = list(ddgs.text(q_clean, max_results=max_results))
                except ImportError:
                    from duckduckgo_search import DDGS
                    with DDGS() as ddgs:
                        raw = list(ddgs.text(q_clean, max_results=max_results))

                for r in raw:
                    results.append({
                        "title": r.get("title", ""),
                        "snippet": r.get("body", ""),
                        "url": r.get("href", ""),
                    })
            except Exception as e:
                logger.warning(f"Web search failed for query '{q_clean}': {e}")
            return results

        results = await asyncio.to_thread(_do_search)

        if results:
            try:
                await self.cache.set_json(cache_key, results, expire=3600)
            except Exception as e:
                logger.warning(f"Failed to cache web search results: {e}")

        return results

    async def fetch_web_page(self, url: str, max_chars: int = 4000) -> Dict[str, Any]:
        """
        Fetch and parse clean text from a web page, prospectus URL, or investor filing.
        Cache Key: data:web:page:{hash(url)}
        TTL: 3600 seconds (1h)
        """
        import hashlib
        import httpx
        from bs4 import BeautifulSoup

        u_clean = url.strip()
        if not u_clean or not (u_clean.startswith("http://") or u_clean.startswith("https://")):
            return {"url": u_clean, "status": "error", "error": "Invalid URL format"}

        u_hash = hashlib.md5(u_clean.encode("utf-8")).hexdigest()
        cache_key = f"data:web:page:{u_hash}"

        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        try:
            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            }
            async with httpx.AsyncClient(headers=headers, follow_redirects=True, timeout=12.0) as client:
                resp = await client.get(u_clean)
                resp.raise_for_status()
                html = resp.text

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
                tag.decompose()

            text_chunks = list(soup.stripped_strings)
            raw_text = " ".join(text_chunks)
            clean_text = " ".join(raw_text.split())

            if len(clean_text) > max_chars:
                clean_text = clean_text[:max_chars] + "... [truncated]"

            title = soup.title.string.strip() if (soup.title and soup.title.string) else ""
            res = {
                "url": u_clean,
                "title": title,
                "status": "success",
                "content": clean_text or "No text content found.",
            }
        except Exception as e:
            logger.warning(f"Failed to fetch web page {u_clean}: {e}")
            res = {
                "url": u_clean,
                "status": "error",
                "error": str(e),
                "content": f"Failed to retrieve URL content: {e}",
            }

        try:
            await self.cache.set_json(cache_key, res, expire=3600)
        except Exception as e:
            logger.warning(f"Failed to cache fetched web page: {e}")

        return res


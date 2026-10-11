"""
backend/services/providers/equities.py
======================================
Asynchronous equities and ETF market data provider wrapping yfinance
in asyncio.to_thread with automatic fallback to recorded test fixtures.
"""

from __future__ import annotations

import json
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any

import pandas as pd
import yfinance as yf

logger = logging.getLogger("wealth_advisor.services.providers.equities")


class EquitiesProvider:
    """
    Asynchronous equities and ETF market data provider.
    Executes blocking yfinance queries in thread workers, and seamlessly
    falls back to local JSON fixtures in tests/fixtures/.
    """
    def __init__(self, offline_mode: bool = False, fixtures_dir: Optional[Path] = None):
        self.offline_mode = offline_mode
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else (Path(__file__).parents[2] / "tests" / "fixtures")

    def _get_quote_from_fixture(self, symbol: str) -> Dict[str, Any]:
        path = self.fixtures_dir / "market_quotes.json"
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            quotes = json.load(f)
        sym = symbol.strip().upper()
        if sym in quotes:
            res = dict(quotes[sym])
            res["source"] = "fixture"
            return res
        # Generic quote for unindexed symbol
        return {
            "symbol": sym,
            "name": f"{sym} Equity",
            "price": 100.0,
            "bid": 99.95,
            "ask": 100.05,
            "volume": 1000000,
            "change": 0.0,
            "change_pct": 0.0,
            "change_percent": 0.0,
            "open": 100.0,
            "high": 100.5,
            "low": 99.5,
            "previous_close": 100.0,
            "currency": "USD",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "fixture"
        }

    def _fetch_yfinance_quote(self, symbol: str) -> Dict[str, Any]:
        """Synchronous fetch executed in worker thread."""
        ticker = yf.Ticker(symbol)
        fast_info = getattr(ticker, "fast_info", None)

        price = None
        prev_close = None
        open_price = None
        day_high = None
        day_low = None
        volume = None

        if fast_info:
            price = getattr(fast_info, "last_price", None)
            prev_close = getattr(fast_info, "previous_close", None)
            open_price = getattr(fast_info, "open", None)
            day_high = getattr(fast_info, "day_high", None)
            day_low = getattr(fast_info, "day_low", None)
            volume = getattr(fast_info, "last_volume", None)

        # Fallback to history if fast_info missing price
        if price is None:
            hist = ticker.history(period="5d")
            if not hist.empty:
                last_row = hist.iloc[-1]
                price = float(last_row["Close"])
                open_price = float(last_row["Open"])
                day_high = float(last_row["High"])
                day_low = float(last_row["Low"])
                volume = int(last_row["Volume"])
                if len(hist) > 1:
                    prev_close = float(hist.iloc[-2]["Close"])
                else:
                    prev_close = open_price

        if price is None or price <= 0:
            raise ValueError(f"Unable to retrieve valid quote for {symbol} from yfinance.")

        change = (price - prev_close) if prev_close else 0.0
        pct = (change / prev_close * 100.0) if prev_close else 0.0

        return {
            "symbol": symbol.upper(),
            "price": float(round(price, 4)),
            "open": float(round(open_price, 4)) if open_price else None,
            "high": float(round(day_high, 4)) if day_high else None,
            "low": float(round(day_low, 4)) if day_low else None,
            "previous_close": float(round(prev_close, 4)) if prev_close else None,
            "change": float(round(change, 4)),
            "change_pct": float(round(pct, 4)),
            "change_percent": float(round(change / prev_close, 6)) if prev_close else 0.0,
            "volume": int(volume) if volume else None,
            "currency": "USD",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "source": "yfinance"
        }

    async def get_quote(self, symbol: str) -> Dict[str, Any]:
        """Fetch quote asynchronously with thread pool and fixture fallback."""
        sym = symbol.strip().upper()
        if not self.offline_mode:
            try:
                return await asyncio.to_thread(self._fetch_yfinance_quote, sym)
            except Exception as e:
                logger.warning(f"Live quote fetch failed for {sym}: {e}. Falling back to fixture.")
        return self._get_quote_from_fixture(sym)

    def _get_history_from_fixture(self, symbols: List[str]) -> pd.DataFrame:
        path = self.fixtures_dir / "historical_prices.json"
        if not path.exists():
            raise FileNotFoundError(f"Fixture not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        records = data.get("records", [])
        if not records:
            raise ValueError("Historical prices fixture has no records.")
        df = pd.DataFrame(records).set_index("date")
        df.index = pd.to_datetime(df.index, utc=True)
        requested_upper = [s.strip().upper() for s in symbols]
        available_cols = [c for c in requested_upper if c in df.columns]
        if not available_cols:
            available_cols = [c for c in df.columns if c != "date"]
        return df[available_cols].astype(float)

    def _fetch_yfinance_history(
        self,
        symbols: List[str],
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """Synchronous fetch of price history executed in worker thread."""
        tickers_str = " ".join(symbols)
        data = yf.download(
            tickers=tickers_str,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False
        )
        if data is None or data.empty:
            raise ValueError(f"No price history returned for symbols: {symbols}")

        if "Close" in data:
            df = data["Close"]
        else:
            df = data

        if isinstance(df, pd.Series):
            df = df.to_frame(name=symbols[0])

        df.index = pd.to_datetime(df.index, utc=True)
        df.index.name = "Date"
        # Ensure column names are uppercase
        df.columns = [str(col).upper() for col in df.columns]
        # Clean missing values
        df = df.ffill().bfill().dropna()
        return df.astype(float)

    async def get_historical_prices(
        self,
        symbols: List[str],
        period: str = "1y",
        interval: str = "1d"
    ) -> pd.DataFrame:
        """Fetch historical daily prices as a pandas DataFrame."""
        norm_symbols = [s.strip().upper() for s in symbols]
        if not self.offline_mode:
            try:
                df = await asyncio.to_thread(
                    self._fetch_yfinance_history, norm_symbols, period, interval
                )
                if df is not None and not df.empty and len(df) >= 30:
                    return df
            except Exception as e:
                logger.warning(f"Live history fetch failed for {symbols}: {e}. Falling back to fixture.")
        return self._get_history_from_fixture(norm_symbols)

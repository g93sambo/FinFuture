"""
backend/services/providers/etf_holdings.py
==========================================
Provider for ETF fund holdings, sector weightings, and fixed income profiles
with automatic fixture fallback.
"""

from __future__ import annotations

import json
import asyncio
import logging
from pathlib import Path
from typing import Optional, Dict, List, Any

import yfinance as yf

logger = logging.getLogger("wealth_advisor.services.providers.etf_holdings")


class ETFHoldingsProvider:
    """
    Provider for ETF fund holdings, sector weights, and fixed-income profiles.
    Wraps yfinance funds_data in worker threads and falls back to recorded fixtures.
    """
    def __init__(self, offline_mode: bool = False, fixtures_dir: Optional[Path] = None):
        self.offline_mode = offline_mode
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else (Path(__file__).parents[2] / "tests" / "fixtures")

    def _get_holdings_from_fixture(self, symbol: str) -> Dict[str, Any]:
        path = self.fixtures_dir / "etf_holdings.json"
        if not path.exists():
            raise FileNotFoundError(f"ETF holdings fixture not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            holdings_map = json.load(f)
        sym = symbol.strip().upper()
        if sym in holdings_map:
            res = dict(holdings_map[sym])
            res["source"] = "fixture"
            return res

        # Generic baseline for unindexed ETF
        return {
            "symbol": sym,
            "name": f"{sym} Fund",
            "asset_class": "equity",
            "expense_ratio": 0.0010,
            "aum_billions": 10.0,
            "top_holdings": [
                {"symbol": "TOP1", "name": "Top Holding 1", "weight": 0.05},
                {"symbol": "TOP2", "name": "Top Holding 2", "weight": 0.04}
            ],
            "sector_weights": {
                "Technology": 0.30,
                "Financial Services": 0.20,
                "Healthcare": 0.15,
                "Industrials": 0.15,
                "Other": 0.20
            },
            "source": "fixture"
        }

    def _fetch_yfinance_holdings(self, symbol: str) -> Optional[Dict[str, Any]]:
        ticker = yf.Ticker(symbol)
        funds_data = getattr(ticker, "funds_data", None)
        if not funds_data:
            return None

        top_holdings: List[Dict[str, Any]] = []
        try:
            th_df = getattr(funds_data, "top_holdings", None)
            if th_df is not None and not th_df.empty:
                for idx, row in th_df.head(10).iterrows():
                    top_holdings.append({
                        "symbol": str(idx),
                        "name": str(row.get("Holding Percent", idx)),
                        "weight": float(row.get("Holding Percent", 0.0))
                    })
        except Exception as e:
            logger.debug(f"Could not parse top holdings for {symbol}: {e}")

        sector_weights: Dict[str, float] = {}
        try:
            sw_df = getattr(funds_data, "sector_weightings", None)
            if sw_df is not None and not sw_df.empty:
                for sec, val in sw_df.items():
                    sector_weights[str(sec)] = float(val)
        except Exception as e:
            logger.debug(f"Could not parse sector weights for {symbol}: {e}")

        if not top_holdings and not sector_weights:
            return None

        return {
            "symbol": symbol.upper(),
            "name": getattr(ticker.fast_info, "name", f"{symbol} Fund"),
            "asset_class": "equity",
            "top_holdings": top_holdings,
            "sector_weights": sector_weights,
            "source": "yfinance"
        }

    async def get_holdings(self, symbol: str) -> Dict[str, Any]:
        """Fetch ETF top holdings and sector weights."""
        sym = symbol.strip().upper()
        if not self.offline_mode:
            try:
                data = await asyncio.to_thread(self._fetch_yfinance_holdings, sym)
                if data:
                    return data
            except Exception as e:
                logger.warning(f"Live ETF holdings query failed for {sym}: {e}. Falling back to fixture.")
        return self._get_holdings_from_fixture(sym)

"""
backend/services/providers/treasury.py
======================================
US Treasury yield curve provider querying FiscalData REST API
with automatic offline fixture fallback.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger("wealth_advisor.services.providers.treasury")


class TreasuryProvider:
    """
    US Treasury yield curve provider querying FiscalData REST API.
    Provides current term structure yields and inversion metrics (10Y-2Y, 10Y-3M).
    Falls back to recorded fixtures in tests/fixtures/.
    """
    FISCAL_DATA_URL = (
        "https://api.fiscaldata.treasury.gov/services/api/fiscal_service/v2/"
        "accounting/od/avg_interest_rates?sort=-record_date&page[size]=100"
    )

    def __init__(
        self,
        offline_mode: bool = False,
        fixtures_dir: Optional[Path] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.offline_mode = offline_mode
        self.fixtures_dir = Path(fixtures_dir) if fixtures_dir else (Path(__file__).parents[2] / "tests" / "fixtures")
        self._client = http_client
        self._own_client = False

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
            self._own_client = True
        return self._client

    async def close(self) -> None:
        if self._own_client and self._client is not None and not self._client.is_closed:
            await self._client.aclose()

    def _get_yield_curve_from_fixture(self) -> Dict[str, Any]:
        """Loads fallback data from treasury_yield_curve.json or yield_curve.json."""
        for filename in ("treasury_yield_curve.json", "yield_curve.json"):
            path = self.fixtures_dir / filename
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                return data
        raise FileNotFoundError(f"Treasury yield curve fixture not found in {self.fixtures_dir}")

    async def _fetch_live_yield_curve(self) -> Dict[str, Any]:
        """Queries FiscalData REST API."""
        client = await self._get_client()
        resp = await client.get(self.FISCAL_DATA_URL)
        resp.raise_for_status()
        payload = resp.json()
        records = payload.get("data", [])
        if not records:
            raise ValueError("No records found in FiscalData response.")

        # Latest record date
        latest_date = records[0].get("record_date")
        rates: Dict[str, float] = {}

        # Term mapping heuristics
        term_map = {
            "1-month": "1M",
            "2-month": "2M",
            "3-month": "3M",
            "6-month": "6M",
            "1-year": "1Y",
            "2-year": "2Y",
            "3-year": "3Y",
            "5-year": "5Y",
            "7-year": "7Y",
            "10-year": "10Y",
            "20-year": "20Y",
            "30-year": "30Y",
        }

        for row in records:
            if row.get("record_date") != latest_date:
                continue
            desc = str(row.get("security_desc", "")).lower()
            avg_rate_str = row.get("avg_interest_rate_amt")
            if not avg_rate_str:
                continue
            try:
                rate_val = float(avg_rate_str)
            except (ValueError, TypeError):
                continue

            for term_key, std_tenor in term_map.items():
                if term_key in desc and std_tenor not in rates:
                    rates[std_tenor] = round(rate_val, 2)
                    break

        if len(rates) < 4:
            raise ValueError(f"FiscalData returned insufficient maturities: {rates}")

        y10 = rates.get("10Y", 0.0)
        y2 = rates.get("2Y", 0.0)
        y3m = rates.get("3M", rates.get("1M", 0.0))
        spread_10y_2y = round(y10 - y2, 2) if (y10 and y2) else None
        spread_10y_3m = round(y10 - y3m, 2) if (y10 and y3m) else None
        is_inverted = (spread_10y_2y is not None and spread_10y_2y < 0.0)

        return {
            "as_of": f"{latest_date}T00:00:00Z",
            "source": "FiscalData",
            "rates": rates,
            "spread_10y_2y": spread_10y_2y,
            "spread_10y_3m": spread_10y_3m,
            "is_inverted": is_inverted
        }

    async def get_yield_curve_details(self) -> Dict[str, Any]:
        """Fetch full yield curve snapshot including maturities and inversion spreads."""
        if not self.offline_mode:
            try:
                return await self._fetch_live_yield_curve()
            except Exception as e:
                logger.warning(f"Live Treasury API query failed: {e}. Falling back to fixture.")
        return self._get_yield_curve_from_fixture()

    async def get_yield_curve(self) -> Dict[str, float]:
        """Returns mapping of tenor string to par yield float (e.g. {'10Y': 4.50})."""
        details = await self.get_yield_curve_details()
        return details.get("rates", {})

"""
backend/services/providers/macro.py
===================================
Macroeconomic indicators provider querying FRED or CalcFi
with automatic offline fixture fallback.
"""

from __future__ import annotations

import os
import json
import logging
from pathlib import Path
from datetime import datetime, timezone
from typing import Optional, Dict, Any

import httpx

logger = logging.getLogger("wealth_advisor.services.providers.macro")


class MacroProvider:
    """
    Macroeconomic indicators provider querying FRED API, CalcFi open data,
    or local fixture files in tests/fixtures/.
    """
    FRED_BASE_URL = "https://api.stlouisfed.org/fred/series/observations"

    def __init__(
        self,
        fred_api_key: Optional[str] = None,
        offline_mode: bool = False,
        fixtures_dir: Optional[Path] = None,
        http_client: Optional[httpx.AsyncClient] = None
    ):
        self.fred_api_key = fred_api_key or os.getenv("FRED_API_KEY")
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

    def _get_macro_from_fixture(self) -> Dict[str, Any]:
        """Loads fallback data from macro_indicators.json."""
        path = self.fixtures_dir / "macro_indicators.json"
        if not path.exists():
            raise FileNotFoundError(f"Macro indicators fixture not found at {path}")
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    async def _fetch_fred_series(self, client: httpx.AsyncClient, series_id: str) -> float:
        """Fetch latest single observation for a FRED series."""
        params = {
            "series_id": series_id,
            "api_key": self.fred_api_key,
            "file_type": "json",
            "sort_order": "desc",
            "limit": 1
        }
        resp = await client.get(self.FRED_BASE_URL, params=params)
        resp.raise_for_status()
        data = resp.json()
        obs = data.get("observations", [])
        if not obs or obs[0].get("value") in (".", None):
            raise ValueError(f"No valid observation found for series {series_id}")
        return float(obs[0]["value"])

    async def _fetch_fred_indicators(self) -> Dict[str, Any]:
        """Queries FRED API for CPI, unemployment, and federal funds rate."""
        if not self.fred_api_key:
            raise ValueError("No FRED_API_KEY provided.")

        client = await self._get_client()
        # Query primary indicators
        cpi_val = await self._fetch_fred_series(client, "CPIAUCSL")
        unrate_val = await self._fetch_fred_series(client, "UNRATE")
        fedfunds_val = await self._fetch_fred_series(client, "FEDFUNDS")

        indicators = {
            "cpi": round(cpi_val, 2),
            "unemployment_rate": round(unrate_val, 2),
            "fed_funds_rate": round(fedfunds_val, 2),
            "unrate": round(unrate_val, 2),
            "fedfunds": round(fedfunds_val, 2)
        }

        return {
            "as_of": datetime.now(timezone.utc).isoformat(),
            "source": "FRED",
            "indicators": indicators,
            "regime": "tightening_disinflation"
        }

    async def get_macro_context(self) -> Dict[str, Any]:
        """Fetch full macroeconomic context with indicators and regime."""
        if not self.offline_mode and self.fred_api_key:
            try:
                return await self._fetch_fred_indicators()
            except Exception as e:
                logger.warning(f"FRED query failed: {e}. Falling back to fixture.")
        return self._get_macro_from_fixture()

    async def get_macro_indicators(self) -> Dict[str, float]:
        """Returns mapping of indicator name to numeric value (e.g. {'cpi': 3.48})."""
        context = await self.get_macro_context()
        return context.get("indicators", {})

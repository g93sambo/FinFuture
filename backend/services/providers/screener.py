"""
backend/services/providers/screener.py
======================================
Asset universe screening provider for equities, fixed income,
and commodities supporting product comparison and suitability filtering.
"""

from __future__ import annotations

import logging
from typing import Optional, List, Dict
from pydantic import BaseModel, Field

logger = logging.getLogger("wealth_advisor.services.providers.screener")


class AssetMetadata(BaseModel):
    """Metadata and quantitative metrics for an asset in the universe."""
    symbol: str = Field(..., description="Normalized uppercase ticker symbol")
    name: str = Field(..., description="Asset or fund display name")
    asset_class: str = Field(..., description="Primary asset class: equity, fixed_income, commodity, real_estate")
    sub_category: str = Field(..., description="Sub-category: large_cap, total_market, govt_bond, etc.")
    expense_ratio: float = Field(..., ge=0.0, description="Annual net expense ratio (e.g. 0.0003 for 3bps)")
    aum_billions: float = Field(..., ge=0.0, description="Assets under management in billions USD")
    yield_30d: float = Field(..., ge=0.0, description="30-day SEC yield or dividend yield (e.g. 0.045)")
    risk_level: int = Field(..., ge=1, le=5, description="Risk tier: 1 (conservative) to 5 (aggressive)")
    duration: Optional[float] = Field(default=None, description="Effective duration in years (fixed income)")
    credit_rating: Optional[str] = Field(default=None, description="Average credit rating (e.g. AAA, A, BBB)")
    suitable_horizons: List[str] = Field(default_factory=list, description="Suitable horizons: SHORT, MEDIUM, LONG")


class AssetScreenerProvider:
    """
    Asset universe screener providing filtered queries for advisory recommendations.
    """
    def __init__(self, universe: Optional[List[AssetMetadata]] = None):
        self._universe: Dict[str, AssetMetadata] = {
            item.symbol.upper(): item for item in (universe or self._load_default_universe())
        }

    @staticmethod
    def _load_default_universe() -> List[AssetMetadata]:
        return [
            AssetMetadata(
                symbol="SPY",
                name="SPDR S&P 500 ETF Trust",
                asset_class="equity",
                sub_category="large_cap_blend",
                expense_ratio=0.0009,
                aum_billions=525.0,
                yield_30d=0.013,
                risk_level=3,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="VTI",
                name="Vanguard Total Stock Market ETF",
                asset_class="equity",
                sub_category="total_market_blend",
                expense_ratio=0.0003,
                aum_billions=410.0,
                yield_30d=0.014,
                risk_level=3,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="QQQ",
                name="Invesco QQQ Trust",
                asset_class="equity",
                sub_category="large_cap_growth",
                expense_ratio=0.0020,
                aum_billions=260.0,
                yield_30d=0.006,
                risk_level=4,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="VXUS",
                name="Vanguard Total International Stock ETF",
                asset_class="equity",
                sub_category="international_blend",
                expense_ratio=0.0008,
                aum_billions=72.0,
                yield_30d=0.031,
                risk_level=4,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="BND",
                name="Vanguard Total Bond Market ETF",
                asset_class="fixed_income",
                sub_category="total_bond_market",
                expense_ratio=0.0003,
                aum_billions=310.0,
                yield_30d=0.046,
                risk_level=2,
                duration=6.5,
                credit_rating="AAA",
                suitable_horizons=["SHORT", "MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="AGG",
                name="iShares Core U.S. Aggregate Bond ETF",
                asset_class="fixed_income",
                sub_category="total_bond_market",
                expense_ratio=0.0003,
                aum_billions=115.0,
                yield_30d=0.045,
                risk_level=2,
                duration=6.4,
                credit_rating="AAA",
                suitable_horizons=["SHORT", "MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="SHY",
                name="iShares 1-3 Year Treasury Bond ETF",
                asset_class="fixed_income",
                sub_category="short_treasury",
                expense_ratio=0.0015,
                aum_billions=28.0,
                yield_30d=0.047,
                risk_level=1,
                duration=1.9,
                credit_rating="AAA",
                suitable_horizons=["SHORT", "MEDIUM"]
            ),
            AssetMetadata(
                symbol="IEF",
                name="iShares 7-10 Year Treasury Bond ETF",
                asset_class="fixed_income",
                sub_category="intermediate_treasury",
                expense_ratio=0.0015,
                aum_billions=32.0,
                yield_30d=0.042,
                risk_level=2,
                duration=7.5,
                credit_rating="AAA",
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="TLT",
                name="iShares 20+ Year Treasury Bond ETF",
                asset_class="fixed_income",
                sub_category="long_treasury",
                expense_ratio=0.0015,
                aum_billions=51.0,
                yield_30d=0.045,
                risk_level=3,
                duration=16.8,
                credit_rating="AAA",
                suitable_horizons=["LONG"]
            ),
            AssetMetadata(
                symbol="TIP",
                name="iShares TIPS Bond ETF",
                asset_class="fixed_income",
                sub_category="inflation_protected",
                expense_ratio=0.0019,
                aum_billions=22.0,
                yield_30d=0.043,
                risk_level=2,
                duration=6.8,
                credit_rating="AAA",
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="LQD",
                name="iShares iBoxx $ Investment Grade Corporate Bond ETF",
                asset_class="fixed_income",
                sub_category="corp_investment_grade",
                expense_ratio=0.0014,
                aum_billions=35.0,
                yield_30d=0.053,
                risk_level=2,
                duration=8.2,
                credit_rating="A",
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="HYG",
                name="iShares iBoxx $ High Yield Corporate Bond ETF",
                asset_class="fixed_income",
                sub_category="corp_high_yield",
                expense_ratio=0.0049,
                aum_billions=18.0,
                yield_30d=0.072,
                risk_level=3,
                duration=3.8,
                credit_rating="BB",
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="GLD",
                name="SPDR Gold Shares",
                asset_class="commodity",
                sub_category="precious_metals",
                expense_ratio=0.0040,
                aum_billions=65.0,
                yield_30d=0.0,
                risk_level=3,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="VNQ",
                name="Vanguard Real Estate ETF",
                asset_class="real_estate",
                sub_category="us_reits",
                expense_ratio=0.0012,
                aum_billions=34.0,
                yield_30d=0.038,
                risk_level=3,
                suitable_horizons=["MEDIUM", "LONG"]
            ),
            AssetMetadata(
                symbol="VCIT",
                name="Vanguard Intermediate-Term Corporate Bond ETF",
                asset_class="fixed_income",
                sub_category="corp_intermediate",
                expense_ratio=0.0004,
                aum_billions=42.0,
                yield_30d=0.051,
                risk_level=2,
                duration=6.2,
                credit_rating="A",
                suitable_horizons=["MEDIUM", "LONG"]
            ),
        ]

    def screen(
        self,
        asset_class: Optional[str] = None,
        max_expense_ratio: Optional[float] = None,
        min_yield: Optional[float] = None,
        min_aum: Optional[float] = None,
        max_risk_level: Optional[int] = None,
        horizon: Optional[str] = None
    ) -> List[AssetMetadata]:
        """Filter universe by multi-criteria attributes."""
        results = list(self._universe.values())
        if asset_class:
            results = [a for a in results if a.asset_class.lower() == asset_class.lower()]
        if max_expense_ratio is not None:
            results = [a for a in results if a.expense_ratio <= max_expense_ratio]
        if min_yield is not None:
            results = [a for a in results if a.yield_30d >= min_yield]
        if min_aum is not None:
            results = [a for a in results if a.aum_billions >= min_aum]
        if max_risk_level is not None:
            results = [a for a in results if a.risk_level <= max_risk_level]
        if horizon:
            results = [a for a in results if horizon.strip().upper() in a.suitable_horizons]
        return results

    def get_by_symbol(self, symbol: str) -> Optional[AssetMetadata]:
        """Look up asset metadata by ticker symbol."""
        return self._universe.get(symbol.strip().upper())

    def list_all(self) -> List[AssetMetadata]:
        """Return entire vetted asset universe."""
        return list(self._universe.values())

"""
backend/tools/definitions/__init__.py
======================================
Package exports and bulk registration helper for core financial tools.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

# Relative imports work whether the app runs from backend/ (Render, Docker) or from the repository root
from .market_quote import MarketQuoteTool, MarketQuoteArgs
from .macro_indicators import MacroIndicatorsTool, MacroIndicatorsArgs
from .treasury_yield_curve import TreasuryYieldCurveTool, TreasuryYieldCurveArgs
from .asset_screener import AssetScreenerTool, AssetScreenerArgs
from .wealth_simulation import WealthSimulationTool, WealthSimulationArgs
from .portfolio_optimizer import PortfolioOptimizerTool, PortfolioOptimizerArgs
from .tax_strategy import TaxStrategyTool, TaxStrategyArgs
from .global_intelligence import CryptoMacroTool, CryptoMacroArgs, SovereignMacroTool, SovereignMacroArgs
from .web_intelligence import SearchFinancialWebTool, SearchFinancialWebArgs, FetchWebPageTool, FetchWebPageArgs
from .market_analytics import (
    StockMetricsTool,
    StockMetricsArgs,
    CompanyFinancialsTool,
    CompanyFinancialsArgs,
    StockPredictionsTool,
    StockPredictionsArgs,
    SectorPerformanceTool,
    SectorPerformanceArgs,
    AssetComparisonTool,
    AssetComparisonArgs,
)
from .portfolio_tools import GetPortfolioTool, GetPortfolioArgs, GetPortfolioHealthTool, GetPortfolioHealthArgs
from .deep_research import DeepResearchTool, DeepResearchArgs
from .legal_statutes import SearchLegalStatutesTool, LegalStatuteArgs
from .black_litterman_tool import BlackLittermanAllocationTool, BlackLittermanArgs
from .price_projection import PriceProjectionTool, PriceProjectionArgs

if TYPE_CHECKING:
    try:
        from backend.tools.registry import ToolRegistry
    except ImportError:
        from tools.registry import ToolRegistry

__all__ = [
    "MarketQuoteTool",
    "MarketQuoteArgs",
    "MacroIndicatorsTool",
    "MacroIndicatorsArgs",
    "TreasuryYieldCurveTool",
    "TreasuryYieldCurveArgs",
    "AssetScreenerTool",
    "AssetScreenerArgs",
    "WealthSimulationTool",
    "WealthSimulationArgs",
    "PortfolioOptimizerTool",
    "PortfolioOptimizerArgs",
    "TaxStrategyTool",
    "TaxStrategyArgs",
    "CryptoMacroTool",
    "CryptoMacroArgs",
    "SovereignMacroTool",
    "SovereignMacroArgs",
    "SearchFinancialWebTool",
    "SearchFinancialWebArgs",
    "FetchWebPageTool",
    "FetchWebPageArgs",
    "StockMetricsTool",
    "StockMetricsArgs",
    "CompanyFinancialsTool",
    "CompanyFinancialsArgs",
    "StockPredictionsTool",
    "StockPredictionsArgs",
    "SectorPerformanceTool",
    "SectorPerformanceArgs",
    "AssetComparisonTool",
    "AssetComparisonArgs",
    "GetPortfolioTool",
    "GetPortfolioArgs",
    "GetPortfolioHealthTool",
    "GetPortfolioHealthArgs",
    "DeepResearchTool",
    "DeepResearchArgs",
    "SearchLegalStatutesTool",
    "LegalStatuteArgs",
    "BlackLittermanAllocationTool",
    "BlackLittermanArgs",
    "PriceProjectionTool",
    "PriceProjectionArgs",
    "register_core_tools",
]


def register_core_tools(registry: Optional[ToolRegistry] = None) -> None:
    """
    Registers foundational financial tools into the given ToolRegistry instance,
    or the default global ToolRegistry singleton if none is provided.
    """
    if registry is None:
        try:
            from tools.registry import ToolRegistry
        except ImportError:
            from backend.tools.registry import ToolRegistry
        registry = ToolRegistry.get_instance()

    registry.register(MarketQuoteTool())
    registry.register(MacroIndicatorsTool())
    registry.register(MacroIndicatorsTool(name="get_macro_context"))
    registry.register(TreasuryYieldCurveTool())
    registry.register(AssetScreenerTool())
    registry.register(WealthSimulationTool())
    registry.register(PortfolioOptimizerTool())
    registry.register(TaxStrategyTool())
    registry.register(CryptoMacroTool())
    registry.register(SovereignMacroTool())
    registry.register(SearchFinancialWebTool())
    registry.register(FetchWebPageTool())
    registry.register(StockMetricsTool())
    registry.register(CompanyFinancialsTool())
    registry.register(StockPredictionsTool())
    registry.register(SectorPerformanceTool())
    registry.register(AssetComparisonTool())
    registry.register(GetPortfolioTool())
    registry.register(GetPortfolioHealthTool())
    registry.register(DeepResearchTool())
    registry.register(SearchLegalStatutesTool())
    registry.register(BlackLittermanAllocationTool())
    registry.register(PriceProjectionTool())

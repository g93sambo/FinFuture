"""
backend/tools/definitions/__init__.py
======================================
Package exports and bulk registration helper for core financial tools.
"""

from __future__ import annotations

from typing import Optional, TYPE_CHECKING

try:
    from backend.tools.definitions.market_quote import MarketQuoteTool, MarketQuoteArgs
    from backend.tools.definitions.macro_indicators import MacroIndicatorsTool, MacroIndicatorsArgs
    from backend.tools.definitions.treasury_yield_curve import TreasuryYieldCurveTool, TreasuryYieldCurveArgs
    from backend.tools.definitions.asset_screener import AssetScreenerTool, AssetScreenerArgs
    from backend.tools.definitions.wealth_simulation import WealthSimulationTool, WealthSimulationArgs
    from backend.tools.definitions.portfolio_optimizer import PortfolioOptimizerTool, PortfolioOptimizerArgs
    from backend.tools.definitions.tax_strategy import TaxStrategyTool, TaxStrategyArgs
    from backend.tools.definitions.global_intelligence import CryptoMacroTool, CryptoMacroArgs, SovereignMacroTool, SovereignMacroArgs
except ImportError:
    from .market_quote import MarketQuoteTool, MarketQuoteArgs
    from .macro_indicators import MacroIndicatorsTool, MacroIndicatorsArgs
    from .treasury_yield_curve import TreasuryYieldCurveTool, TreasuryYieldCurveArgs
    from .asset_screener import AssetScreenerTool, AssetScreenerArgs
    from .wealth_simulation import WealthSimulationTool, WealthSimulationArgs
    from .portfolio_optimizer import PortfolioOptimizerTool, PortfolioOptimizerArgs
    from .tax_strategy import TaxStrategyTool, TaxStrategyArgs
    from .global_intelligence import CryptoMacroTool, CryptoMacroArgs, SovereignMacroTool, SovereignMacroArgs

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
    "register_core_tools",
]


def register_core_tools(registry: Optional[ToolRegistry] = None) -> None:
    """
    Registers foundational financial tools into the given ToolRegistry instance,
    or the default global ToolRegistry singleton if none is provided.
    """
    if registry is None:
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

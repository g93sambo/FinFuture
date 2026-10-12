"""
backend/tools/__init__.py
=========================
Public API exports for the centralized tool registry, adapters, and definitions.
"""

from .base import (
    BaseTool,
    ToolResult,
    ExecutionContext,
    ToolCategory,
    ToolError,
    ToolNotFoundError,
    ToolAuthorizationError,
    ToolValidationError,
    ToolExecutionTimeoutError,
)
from .registry import (
    ToolRegistry,
    tool_registry,
    normalize_role,
    ROLE_NORMALIZATION_MAP,
)
from .adapters import (
    CircuitBreaker,
    CircuitState,
    CircuitBreakerOpenError,
    CircuitBreakerRegistry,
    AsyncRateLimiter,
    calculate_backoff_delay,
    execute_with_retry,
    classify_error,
    ErrorCategory,
    ExecutionProvenance,
    ExecutionStatus,
    ControlledExecutionAdapter,
    ProvenanceHistoryRecorder,
    get_provenance_recorder,
)
from .definitions import (
    MarketQuoteTool,
    MarketQuoteArgs,
    MacroIndicatorsTool,
    MacroIndicatorsArgs,
    TreasuryYieldCurveTool,
    TreasuryYieldCurveArgs,
    AssetScreenerTool,
    AssetScreenerArgs,
    WealthSimulationTool,
    WealthSimulationArgs,
    PortfolioOptimizerTool,
    PortfolioOptimizerArgs,
    register_core_tools,
)

__all__ = [
    # Base
    "BaseTool",
    "ToolResult",
    "ExecutionContext",
    "ToolCategory",
    "ToolError",
    "ToolNotFoundError",
    "ToolAuthorizationError",
    "ToolValidationError",
    "ToolExecutionTimeoutError",
    # Registry
    "ToolRegistry",
    "tool_registry",
    "normalize_role",
    "ROLE_NORMALIZATION_MAP",
    # Adapters
    "CircuitBreaker",
    "CircuitState",
    "CircuitBreakerOpenError",
    "CircuitBreakerRegistry",
    "AsyncRateLimiter",
    "calculate_backoff_delay",
    "execute_with_retry",
    "classify_error",
    "ErrorCategory",
    "ExecutionProvenance",
    "ExecutionStatus",
    "ControlledExecutionAdapter",
    "ProvenanceHistoryRecorder",
    "get_provenance_recorder",
    # Definitions
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
    "register_core_tools",
]

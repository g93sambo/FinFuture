"""
tests/unit/test_tool_registry.py
================================
Comprehensive unit tests for Milestone 1: Centralized Tool Registry & Controlled
Execution Adapters (R3). Verifies BaseTool contracts, Pydantic v2 schemas, ToolRegistry
singleton, RBAC authorization matrix, CircuitBreaker FSM, bounded retries with backoff & jitter,
execution provenance auditing, and the 6 core financial tool definitions.
"""

from __future__ import annotations

import os
import sys
import time
import json
import asyncio
import hashlib
from typing import Dict, Any, List, Optional
import pytest
from pydantic import BaseModel, Field, ValidationError

# Ensure backend and project root are on sys.path
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "..", ".."))
_backend_root = os.path.join(_project_root, "backend")

if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from tools.base import (
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
from tools.registry import (
    ToolRegistry,
    normalize_role,
    ROLE_NORMALIZATION_MAP,
)
from tools.adapters import (
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
    redact_sensitive_data,
    compute_sha256_hash,
)
from tools.definitions import (
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


# ============================================================================
# Dummy Tools for Unit Testing
# ============================================================================

class DummyQueryArgs(BaseModel):
    ticker: str = Field(..., min_length=1)
    limit: int = Field(default=10, ge=1, le=100)


class DummyQueryTool(BaseTool):
    name: str = "dummy_query"
    description: str = "Dummy query tool for registry testing"
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = DummyQueryArgs
    required_roles: List[str] = ["Financial Analyst", "Quantitative Analyst"]

    async def execute(self, *args, **kwargs) -> ToolResult:
        if args and isinstance(args[0], DummyQueryArgs):
            parsed = args[0]
        else:
            clean = {k: v for k, v in kwargs.items() if k != "context"}
            parsed = DummyQueryArgs(**clean)
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"ticker": parsed.ticker, "limit": parsed.limit, "status": "ok"},
        )


class DummyFailingTool(BaseTool):
    name: str = "dummy_failing"
    description: str = "Dummy tool that always raises an error"
    args_schema: type[BaseModel] = DummyQueryArgs
    required_roles: List[str] = ["Quantitative Analyst"]

    async def execute(self, *args, **kwargs) -> ToolResult:
        raise RuntimeError("Synthetic failure in dummy tool")


# ============================================================================
# 1. BaseTool & Pydantic Schema Validation Tests
# ============================================================================

class TestBaseToolContracts:
    def test_base_tool_instantiation_validation(self):
        """Tool without name or description or args_schema raises TypeError/ValueError."""
        with pytest.raises(ValueError, match="must specify a non-empty 'name'"):
            class NoNameTool(BaseTool):
                description = "desc"
                args_schema = DummyQueryArgs
                async def execute(self, *args, **kwargs): pass
            NoNameTool()

        with pytest.raises(ValueError, match="must specify a non-empty 'description'"):
            class NoDescTool(BaseTool):
                name = "test"
                args_schema = DummyQueryArgs
                async def execute(self, *args, **kwargs): pass
            NoDescTool()

        with pytest.raises(TypeError, match="must define an 'args_schema'"):
            class BadArgsTool(BaseTool):
                name = "test"
                description = "desc"
                args_schema = dict  # Not a BaseModel subclass
                async def execute(self, *args, **kwargs): pass
            BadArgsTool()

    def test_args_validation_success_and_failure(self):
        """Pydantic args_schema validation succeeds on valid inputs, raises ToolValidationError on invalid."""
        tool = DummyQueryTool()
        validated = tool.validate_args({"ticker": "AAPL", "limit": 25})
        assert isinstance(validated, DummyQueryArgs)
        assert validated.ticker == "AAPL"
        assert validated.limit == 25

        # Invalid args raise ToolValidationError
        with pytest.raises(ToolValidationError):
            tool.validate_args({"ticker": "", "limit": 25})  # min_length=1

        with pytest.raises(ToolValidationError):
            tool.validate_args({"ticker": "AAPL", "limit": 500})  # le=100

    def test_openai_function_schema_generation(self):
        """to_openai_schema exports valid function definition with JSON Schema parameters."""
        tool = DummyQueryTool()
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == "dummy_query"
        assert fn["description"] == "Dummy query tool for registry testing"
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
        assert "ticker" in fn["parameters"]["properties"]
        assert "limit" in fn["parameters"]["properties"]

    def test_provenance_hash_determinism(self):
        """Identical inputs and outputs produce identical SHA-256 hash; changes alter hash."""
        tool = DummyQueryTool()
        args = {"ticker": "AAPL", "limit": 10}
        data = {"ticker": "AAPL", "price": 150.0}

        h1 = tool.compute_provenance_hash(args, data)
        h2 = tool.compute_provenance_hash(args, data)
        assert h1 == h2
        assert len(h1) == 64

        h3 = tool.compute_provenance_hash(args, {"ticker": "AAPL", "price": 151.0})
        assert h1 != h3

    @pytest.mark.asyncio
    async def test_tool_call_invocation(self):
        """Tool instance can be invoked directly as an async callable."""
        tool = DummyQueryTool()
        res = await tool(ticker="MSFT", limit=5)
        assert isinstance(res, ToolResult)
        assert res.success is True
        assert res.data["ticker"] == "MSFT"


# ============================================================================
# 2. Tool Registry Singleton & RBAC Matrix Tests
# ============================================================================

class TestToolRegistryRBAC:
    @pytest.fixture(autouse=True)
    def clean_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        yield reg
        reg.reset()

    def test_singleton_identity(self, clean_registry):
        """ToolRegistry enforces strict singleton identity across calls."""
        reg1 = ToolRegistry()
        reg2 = ToolRegistry.get_instance()
        assert reg1 is reg2
        assert reg1 is clean_registry

    def test_tool_registration_and_lookup(self, clean_registry):
        """Registering, retrieving, unregistering, and listing tools."""
        tool = DummyQueryTool()
        clean_registry.register(tool)
        assert clean_registry.has_tool("dummy_query")
        assert clean_registry.has_tool("DUMMY_QUERY")  # Case-insensitive
        assert clean_registry.get_tool("dummy_query") is tool

        # Duplicate registration with override=False raises ValueError
        with pytest.raises(ValueError, match="already registered"):
            clean_registry.register(tool, override=False)

        assert "dummy_query" in clean_registry.list_tool_names()
        assert len(clean_registry.list_tools()) == 1

        unregistered = clean_registry.unregister("dummy_query")
        assert unregistered is tool
        assert not clean_registry.has_tool("dummy_query")

    def test_role_normalization(self):
        """All 8 specialist roles and supervisory roles normalize consistently."""
        assert normalize_role("Financial Analyst") == "financial_analyst"
        assert normalize_role("financial_analyst") == "financial_analyst"
        assert normalize_role("Macro & Market Analyst") == "macro_market_analyst"
        assert normalize_role("Investment Research Analyst") == "investment_research_analyst"
        assert normalize_role("Quantitative Analyst") == "quantitative_analyst"
        assert normalize_role("Intelligence/Web Analyst") == "intelligence_web_analyst"
        assert normalize_role("Risk & Devil's Advocate") == "devils_advocate"
        assert normalize_role("Personalized Advisory") == "personalized_advisory"
        assert normalize_role("Compliance Guard") == "compliance_guard"
        assert normalize_role("Orchestrator") == "orchestrator"
        assert normalize_role("admin") == "admin"

    def test_role_filtering_and_authorization(self, clean_registry):
        """get_tools_for_role filters tools strictly per authorized roles."""
        clean_registry.register(DummyQueryTool())  # Roles: Financial Analyst, Quantitative Analyst

        # Authorized roles
        fin_tools = clean_registry.get_tools_for_role("Financial Analyst")
        assert len(fin_tools) == 1
        assert fin_tools[0].name == "dummy_query"

        quant_tools = clean_registry.get_tools_for_role("quantitative_analyst")
        assert len(quant_tools) == 1

        # Unauthorized role
        web_tools = clean_registry.get_tools_for_role("Intelligence/Web Analyst")
        assert len(web_tools) == 0

        # Admin gets all
        admin_tools = clean_registry.get_tools_for_role("admin")
        assert len(admin_tools) == 1

        # Direct authorization check
        assert clean_registry.check_authorization("financial_analyst", "dummy_query") is True

        with pytest.raises(ToolAuthorizationError):
            clean_registry.check_authorization("intelligence_web_analyst", "dummy_query")

        with pytest.raises(ToolNotFoundError):
            clean_registry.check_authorization("financial_analyst", "nonexistent_tool")

    def test_export_schemas_role_filtered(self, clean_registry):
        """export_schemas exports schemas only for the given role."""
        clean_registry.register(DummyQueryTool())

        # For authorized role
        schemas = clean_registry.export_schemas(role="Financial Analyst")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "dummy_query"

        # For unauthorized role
        unauth_schemas = clean_registry.export_schemas(role="Compliance Guard")
        assert len(unauth_schemas) == 0

    @pytest.mark.asyncio
    async def test_execute_tool_pipeline_success(self, clean_registry):
        """execute_tool executes tool, validates inputs, and records timing and provenance."""
        clean_registry.register(DummyQueryTool())
        ctx = ExecutionContext(user_id="user_123", role="financial_analyst", session_id="s_99")

        res = await clean_registry.execute_tool(
            name="dummy_query",
            role="Financial Analyst",
            args={"ticker": "NVDA", "limit": 15},
            context=ctx,
        )
        assert isinstance(res, ToolResult)
        assert res.success is True
        assert res.data["ticker"] == "NVDA"
        assert res.execution_time_ms >= 0.0
        assert res.provenance_hash is not None
        assert res.metadata["caller_role"] == "Financial Analyst"
        assert res.metadata["session_id"] == "s_99"

    @pytest.mark.asyncio
    async def test_execute_tool_unauthorized_rejection(self, clean_registry):
        """execute_tool blocks unauthorized caller roles with ToolAuthorizationError."""
        clean_registry.register(DummyQueryTool())
        with pytest.raises(ToolAuthorizationError):
            await clean_registry.execute_tool(
                name="dummy_query",
                role="Compliance Guard",
                args={"ticker": "NVDA"},
            )

    @pytest.mark.asyncio
    async def test_execute_tool_validation_failure(self, clean_registry):
        """execute_tool returns failure result when arguments violate schema."""
        clean_registry.register(DummyQueryTool())
        res = await clean_registry.execute_tool(
            name="dummy_query",
            role="Financial Analyst",
            args={"ticker": "", "limit": 10},  # Invalid ticker
        )
        assert res.success is False
        assert "Invalid arguments" in res.error


# ============================================================================
# 3. Circuit Breaker FSM & Resilient Adapters Tests
# ============================================================================

class TestCircuitBreakerAndAdapters:
    @pytest.mark.asyncio
    async def test_circuit_breaker_transitions(self):
        """Circuit breaker transitions: CLOSED -> OPEN -> HALF_OPEN -> CLOSED."""
        cb = CircuitBreaker(name="test_cb", failure_threshold=3, cooldown_seconds=0.2)
        assert cb.state == CircuitState.CLOSED
        assert await cb.can_execute() is True

        # 2 failures do not trip
        await cb.record_failure(Exception("Fail 1"))
        await cb.record_failure(Exception("Fail 2"))
        assert cb.state == CircuitState.CLOSED

        # 3rd failure trips to OPEN
        await cb.record_failure(Exception("Fail 3"))
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False
        assert cb.cooldown_remaining > 0.0

        # Wait for cooldown to expire -> HALF_OPEN
        await asyncio.sleep(0.25)
        assert cb.state == CircuitState.HALF_OPEN
        assert await cb.can_execute() is True

        # Successful probe recovers to CLOSED
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

    @pytest.mark.asyncio
    async def test_circuit_breaker_half_open_failure_re_trips(self):
        """Failing probe in HALF_OPEN immediately re-trips to OPEN."""
        cb = CircuitBreaker(name="test_cb2", failure_threshold=2, cooldown_seconds=0.1)
        await cb.record_failure(Exception("F1"))
        await cb.record_failure(Exception("F2"))
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.15)
        assert cb.state == CircuitState.HALF_OPEN

        # Failed probe in HALF_OPEN
        await cb.record_failure(Exception("Probe fail"))
        assert cb.state == CircuitState.OPEN

    def test_backoff_delay_calculation(self):
        """calculate_backoff_delay respects exponential growth, max_delay cap, and jitter bounds."""
        d0 = calculate_backoff_delay(0, base_interval=1.0, max_delay=10.0, jitter=False)
        assert d0 == 1.0

        d1 = calculate_backoff_delay(1, base_interval=1.0, max_delay=10.0, jitter=False)
        assert d1 == 2.0

        d2 = calculate_backoff_delay(2, base_interval=1.0, max_delay=10.0, jitter=False)
        assert d2 == 4.0

        d_capped = calculate_backoff_delay(10, base_interval=1.0, max_delay=8.0, jitter=False)
        assert d_capped == 8.0

        # With jitter
        d_jitter = calculate_backoff_delay(0, base_interval=1.0, jitter=True, jitter_range=(0.1, 0.2))
        assert 1.1 <= d_jitter <= 1.2

    @pytest.mark.asyncio
    async def test_async_rate_limiter(self):
        """AsyncRateLimiter restricts execution rate correctly."""
        limiter = AsyncRateLimiter(rate_limit_per_sec=20.0, burst_capacity=2.0)
        t0 = time.perf_counter()
        # Consume initial burst tokens
        await limiter.acquire()
        await limiter.acquire()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1  # Fast burst

    @pytest.mark.asyncio
    async def test_execute_with_retry_transient_recovery(self):
        """execute_with_retry recovers after transient failures."""
        attempts = 0

        async def flaky_op():
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise ConnectionError("Transient network drop")
            return "success_payload"

        res = await execute_with_retry(
            flaky_op,
            max_retries=3,
            base_interval=0.01,
            max_delay=0.05,
            tool_name="test_tool",
        )
        assert res == "success_payload"
        assert attempts == 3

    @pytest.mark.asyncio
    async def test_execute_with_retry_non_retryable_fast_fail(self):
        """execute_with_retry does not retry non-retryable errors like PermissionError."""
        attempts = 0

        async def unauth_op():
            nonlocal attempts
            attempts += 1
            raise PermissionError("Access denied")

        with pytest.raises(PermissionError):
            await execute_with_retry(
                unauth_op,
                max_retries=3,
                base_interval=0.01,
                tool_name="test_tool",
            )
        assert attempts == 1  # Fast fail without retry

    def test_sensitive_data_redaction(self):
        """redact_sensitive_data recursively masks passwords, tokens, API keys."""
        raw = {
            "symbol": "SPY",
            "api_key": "super_secret_123",
            "auth_token": "bearer_abc",
            "nested": {
                "password": "pass",
                "normal": "value"
            }
        }
        cleaned = redact_sensitive_data(raw)
        assert cleaned["symbol"] == "SPY"
        assert cleaned["api_key"] == "[REDACTED]"
        assert cleaned["auth_token"] == "[REDACTED]"
        assert cleaned["nested"]["password"] == "[REDACTED]"
        assert cleaned["nested"]["normal"] == "value"


# ============================================================================
# 4. Core Tools Definition Tests (The 6 Migrated Tools)
# ============================================================================

class TestCoreToolsDefinitions:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)
        yield reg
        reg.reset()

    def test_all_core_tools_registered(self, setup_registry):
        """All 6 core tools are registered and available in the registry."""
        expected = [
            "get_stock_quote",
            "get_macro_indicators",
            "get_macro_context",
            "get_yield_curve",
            "screen_assets",
            "simulate_wealth_plan",
            "optimize_portfolio",
        ]
        registered = setup_registry.list_tool_names()
        for name in expected:
            assert setup_registry.has_tool(name), f"Missing core tool: {name}"

    @pytest.mark.asyncio
    async def test_market_quote_tool(self, setup_registry):
        """MarketQuoteTool executes quote query with uppercase symbol normalization."""
        tool = setup_registry.get_tool("get_stock_quote")
        assert isinstance(tool, MarketQuoteTool)

        res = await setup_registry.execute_tool(
            name="get_stock_quote",
            role="Financial Analyst",
            args={"symbol": "spy"},
        )
        assert res.success is True
        assert res.data["symbol"] == "SPY"
        assert "price" in res.data
        assert res.data["price"] > 0

    @pytest.mark.asyncio
    async def test_macro_indicators_tool(self, setup_registry):
        """MacroIndicatorsTool executes and filters indicator keys."""
        res = await setup_registry.execute_tool(
            name="get_macro_indicators",
            role="Macro & Market Analyst",
            args={"indicators": ["cpi", "unemployment_rate"]},
        )
        assert res.success is True
        indicators = res.data.get("indicators", {})
        assert "cpi" in indicators or "unemployment_rate" in indicators

    @pytest.mark.asyncio
    async def test_treasury_yield_curve_tool(self, setup_registry):
        """TreasuryYieldCurveTool executes and returns yield curve with spreads."""
        res = await setup_registry.execute_tool(
            name="get_yield_curve",
            role="Macro & Market Analyst",
            args={"include_spreads": True},
        )
        assert res.success is True
        assert "rates" in res.data
        assert len(res.data["rates"]) > 0

    @pytest.mark.asyncio
    async def test_asset_screener_tool(self, setup_registry):
        """AssetScreenerTool filters asset universe by criteria."""
        res = await setup_registry.execute_tool(
            name="screen_assets",
            role="Investment Research Analyst",
            args={"asset_class": "equity", "max_expense_ratio": 0.005},
        )
        assert res.success is True
        assert res.data["total_matches"] > 0
        for asset in res.data["assets"]:
            assert asset["asset_class"].lower() == "equity"
            assert asset["expense_ratio"] <= 0.005

    @pytest.mark.asyncio
    async def test_wealth_simulation_tool(self, setup_registry):
        """WealthSimulationTool runs deterministic 10k Monte Carlo and hurdle CAGR."""
        res = await setup_registry.execute_tool(
            name="simulate_wealth_plan",
            role="Quantitative Analyst",
            args={
                "starting_capital": 10_000_000.0,
                "target_capital": 100_000_000.0,
                "years": 10,
                "initial_withdrawal": 500_000.0,
                "n_simulations": 1_000,
            },
        )
        assert res.success is True
        data = res.data
        assert "required_hurdle_rate_float" in data
        assert round(data["required_hurdle_rate_float"] * 100, 2) == 34.44
        assert "ten_year_deterministic_schedule" in data
        assert "reproducible_monte_carlo_10k" in data
        assert "explicit_stress_tests" in data

    @pytest.mark.asyncio
    async def test_portfolio_optimizer_tool(self, setup_registry):
        """PortfolioOptimizerTool optimizes weights with skfolio CVaR."""
        res = await setup_registry.execute_tool(
            name="optimize_portfolio",
            role="Quantitative Analyst",
            args={
                "symbols": ["SPY", "VTI", "BND"],
                "risk_tolerance": 3,
                "include_frontier": False,
            },
        )
        assert res.success is True
        weights = res.data.get("weights", {})
        assert len(weights) > 0
        total_w = sum(weights.values())
        assert pytest.approx(total_w, abs=1e-2) == 1.0

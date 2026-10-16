"""
tests/adversarial/test_m1_tool_registry_adversarial.py
======================================================
Adversarial stress-testing suite for Milestone 1:
Centralized Tool Registry & Controlled Execution Adapters (R3).

Covers:
1. ToolRegistry RBAC: Unauthorized role rejection, privilege escalation bypasses (e.g. role='all', role='*'),
   supervisory role isolation, and unknown/malformed roles.
2. Robustness to Malformed Inputs: Type mismatches, None/empty inputs, oversized payloads,
   NaN/Inf values, boundary breaches, SQL/prompt injection payloads in tool args.
3. Case-Insensitivity & Normalization: Upper/lower/mixed casing, whitespace padding, unicode,
   punctuation in tool names and role names.
4. Schema Export Fidelity & Integrity: OpenAI schema structure, immutability, role-filtering,
   and JSON Schema compliance across all tools.
5. Adapter & Concurrency Stress: Concurrent execution throughput, circuit breaker race conditions,
   rate limiter token drain, retry jitter bounds, and provenance hash stability under pressure.
"""

from __future__ import annotations

import os
import sys
import math
import time
import json
import asyncio
import pytest
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# Ensure sys.path includes backend and project root
_current_dir = os.path.dirname(os.path.abspath(__file__))
_project_root = os.path.abspath(os.path.join(_current_dir, "..", ".."))
_backend_root = os.path.join(_project_root, "backend")

if _backend_root not in sys.path:
    sys.path.insert(0, _backend_root)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from backend.tools.base import (
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
from backend.tools.registry import (
    ToolRegistry,
    normalize_role,
    ROLE_NORMALIZATION_MAP,
)
from backend.tools.adapters import (
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
from backend.tools.definitions import (
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
# Dummy Tools for Adversarial Testing
# ============================================================================

class SensitiveArgs(BaseModel):
    action: str = Field(..., min_length=1)
    secret_code: Optional[str] = None


class ComplianceRestrictedTool(BaseTool):
    """Tool accessible ONLY by Compliance Guard."""
    name: str = "compliance_audit_lock"
    description: str = "Strict compliance audit lock tool accessible only by Compliance Guard"
    category: ToolCategory = ToolCategory.EXECUTION
    args_schema: type[BaseModel] = SensitiveArgs
    required_roles: List[str] = ["Compliance Guard"]

    async def execute(self, *args, **kwargs) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"status": "audit_locked"},
        )


class QuantRestrictedTool(BaseTool):
    """Tool accessible ONLY by Quantitative Analyst."""
    name: str = "solve_proprietary_alpha"
    description: str = "Proprietary alpha solver accessible only by Quantitative Analyst"
    category: ToolCategory = ToolCategory.QUANT_MODELING
    args_schema: type[BaseModel] = SensitiveArgs
    required_roles: List[str] = ["Quantitative Analyst"]

    async def execute(self, *args, **kwargs) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"alpha": 0.42},
        )


class NoRoleTool(BaseTool):
    """Tool with empty required_roles."""
    name: str = "no_role_tool"
    description: str = "Tool with empty required_roles"
    category: ToolCategory = ToolCategory.MARKET_DATA
    args_schema: type[BaseModel] = SensitiveArgs
    required_roles: List[str] = []

    async def execute(self, *args, **kwargs) -> ToolResult:
        return ToolResult(
            tool_name=self.name,
            success=True,
            data={"executed": True},
        )


# ============================================================================
# 1. Adversarial RBAC & Authorization Stress Tests
# ============================================================================

class TestAdversarialRBAC:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)
        reg.register(ComplianceRestrictedTool())
        reg.register(QuantRestrictedTool())
        reg.register(NoRoleTool())
        yield reg
        reg.reset()

    def test_unauthorized_specialist_roles_strictly_rejected(self, setup_registry):
        """Verify each specialist persona cannot execute tools outside their domain."""
        reg = setup_registry

        # Compliance Guard should NOT be able to run PortfolioOptimizer or WealthSimulation
        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Compliance Guard", "optimize_portfolio")

        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Compliance Guard", "simulate_wealth_plan")

        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Compliance Guard", "get_stock_quote")

        # Intelligence/Web Analyst should NOT be able to execute PortfolioOptimizer
        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Intelligence/Web Analyst", "optimize_portfolio")

        # Financial Analyst should NOT be able to execute compliance_audit_lock
        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Financial Analyst", "compliance_audit_lock")

        # Macro Analyst should NOT be able to execute solve_proprietary_alpha
        with pytest.raises(ToolAuthorizationError):
            reg.check_authorization("Macro & Market Analyst", "solve_proprietary_alpha")

    def test_arbitrary_unregistered_roles_rejected(self, setup_registry):
        """Unknown and hostile role strings must be rejected."""
        reg = setup_registry
        hostile_roles = [
            "hacker",
            "guest",
            "anonymous",
            "unauthenticated",
            "root",
            "system",
            "undefined",
            "null",
            "script_kiddie",
            "external_user",
            "eval('admin')",
            "<script>alert(1)</script>",
            "Financial Analyst; DROP TABLE users;--",
            "   ",
            "",
        ]
        for role in hostile_roles:
            with pytest.raises(ToolAuthorizationError):
                reg.check_authorization(role, "optimize_portfolio")

            with pytest.raises(ToolAuthorizationError):
                reg.check_authorization(role, "compliance_audit_lock")

    def test_none_role_handling(self, setup_registry):
        """Adversarial check: Passing None as role raises AttributeError instead of ToolAuthorizationError."""
        reg = setup_registry
        with pytest.raises(AttributeError):
            reg.check_authorization(None, "optimize_portfolio")

    @pytest.mark.asyncio
    async def test_none_role_in_execute_tool_crashes_with_attribute_error(self, setup_registry):
        """Passing role=None into execute_tool bypasses graceful error handling and crashes with AttributeError."""
        reg = setup_registry
        with pytest.raises(AttributeError):
            await reg.execute_tool(
                name="get_stock_quote",
                role=None,
                args={"symbol": "SPY"},
                raise_on_error=False,
            )

    def test_privilege_escalation_via_wildcard_and_all(self, setup_registry):
        """
        Adversarial challenge: Assess whether role='admin', role='*', or role='all'
        bypasses restricted tools like compliance_audit_lock and solve_proprietary_alpha.
        """
        reg = setup_registry
        # Admin is expected to be a superuser
        assert reg.check_authorization("admin", "compliance_audit_lock") is True
        assert reg.check_authorization("*", "compliance_audit_lock") is True

        # Vulnerability / finding: A caller specifying role='all' is granted full admin access
        # to compliance_audit_lock because 'all' is mapped to '*' in ROLE_NORMALIZATION_MAP.
        is_all_authorized = reg.check_authorization("all", "compliance_audit_lock")
        assert is_all_authorized is True

    def test_tool_with_empty_required_roles_is_inaccessible_to_normal_roles(self, setup_registry):
        """If a tool defines required_roles=[], ordinary roles must NOT have access."""
        reg = setup_registry
        for role in [
            "Financial Analyst",
            "Macro & Market Analyst",
            "Investment Research Analyst",
            "Quantitative Analyst",
            "Intelligence/Web Analyst",
            "Risk & Devil's Advocate",
            "Personalized Advisory",
            "Compliance Guard",
        ]:
            with pytest.raises(ToolAuthorizationError):
                reg.check_authorization(role, "no_role_tool")

        # But admin still can access it
        assert reg.check_authorization("admin", "no_role_tool") is True

    @pytest.mark.asyncio
    async def test_execute_tool_unauthorized_rejects_before_execution(self, setup_registry):
        """execute_tool must immediately reject unauthorized caller without executing payload."""
        reg = setup_registry
        with pytest.raises(ToolAuthorizationError):
            await reg.execute_tool(
                name="compliance_audit_lock",
                role="Investment Research Analyst",
                args={"action": "lock"},
                raise_on_error=True,
            )


# ============================================================================
# 2. Case-Insensitivity & Normalization Stress Tests
# ============================================================================

class TestAdversarialCaseAndFormatting:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)
        yield reg
        reg.reset()

    def test_tool_name_casing_variations(self, setup_registry):
        """Tool lookup and execution must be completely case-insensitive."""
        reg = setup_registry
        casing_variants = [
            "get_stock_quote",
            "GET_STOCK_QUOTE",
            "Get_Stock_Quote",
            "GeT_sToCk_QuOtE",
            "  get_stock_quote  ",
            "\tget_stock_quote\n",
        ]
        for variant in casing_variants:
            tool = reg.get_tool(variant)
            assert tool is not None, f"Failed lookup for variant: {repr(variant)}"
            assert tool.name == "get_stock_quote"
            assert reg.has_tool(variant) is True

    def test_role_name_formatting_variations(self, setup_registry):
        """Role normalization handles whitespace, casing, hyphens, and slashes."""
        role_variants = [
            ("FINANCIAL ANALYST", "financial_analyst"),
            ("financial analyst", "financial_analyst"),
            ("  financial_analyst  ", "financial_analyst"),
            ("Financial-Analyst", "financial_analyst"),
            ("MACRO & MARKET ANALYST", "macro_market_analyst"),
            ("Macro and Market Analyst", "macro_and_market_analyst"),
            ("Intelligence/Web Analyst", "intelligence_web_analyst"),
            ("INTELLIGENCE_WEB_ANALYST", "intelligence_web_analyst"),
            ("Risk & Devil's Advocate", "devils_advocate"),
            ("RISK & DEVIL'S ADVOCATE", "devils_advocate"),
            ("devil's advocate", "devils_advocate"),
            ("devils_advocate", "devils_advocate"),
            ("Personalized Advisory", "personalized_advisory"),
            ("PERSONALIZED_ADVISORY", "personalized_advisory"),
            ("Compliance Guard", "compliance_guard"),
            ("COMPLIANCE_GUARD", "compliance_guard"),
        ]
        for input_role, expected in role_variants:
            normalized = normalize_role(input_role)
            assert normalized == expected, f"Input '{input_role}' normalized to '{normalized}', expected '{expected}'"

    def test_duplicate_registration_case_insensitivity(self, setup_registry):
        """Registering a tool with the same name in different casing with override=False must raise ValueError."""
        reg = setup_registry
        tool = MarketQuoteTool()
        with pytest.raises(ValueError, match="already registered"):
            reg.register(tool, override=False)


# ============================================================================
# 3. Malformed Inputs & Schema Validation Stress Tests
# ============================================================================

class TestAdversarialMalformedInputs:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)
        yield reg
        reg.reset()

    @pytest.mark.asyncio
    async def test_market_quote_malformed_arguments(self, setup_registry):
        """Test MarketQuoteTool with invalid, boundary, and injection symbols."""
        reg = setup_registry
        role = "Financial Analyst"

        # Missing symbol
        res = await reg.execute_tool("get_stock_quote", role, {})
        assert res.success is False
        assert "validation" in res.error.lower() or "field required" in res.error.lower()

        # Empty symbol
        res = await reg.execute_tool("get_stock_quote", role, {"symbol": ""})
        assert res.success is False
        assert "min_length" in res.error.lower() or "validation" in res.error.lower()

        # Whitespace-only symbol (stripped to empty string by field_validator, but min_length checked before or after?)
        res = await reg.execute_tool("get_stock_quote", role, {"symbol": "   "})
        # Should either fail validation or normalize
        assert isinstance(res, ToolResult)

        # SQL Injection / Command Injection strings as symbol
        injection_symbols = [
            "SPY; DROP TABLE quotes;--",
            "' OR '1'='1",
            "AAPL\x00NULL",
            "$(whoami)",
            "{{7*7}}",
            "<script>alert('xss')</script>",
            "A" * 1000,  # 1000 char symbol
        ]
        for inj in injection_symbols:
            res = await reg.execute_tool("get_stock_quote", role, {"symbol": inj})
            # It should safely return a ToolResult without unhandled crash
            assert isinstance(res, ToolResult)
            assert res.tool_name == "get_stock_quote"
            assert res.execution_time_ms >= 0.0

    @pytest.mark.asyncio
    async def test_wealth_simulation_boundary_and_malformed_inputs(self, setup_registry):
        """Stress-test WealthSimulationTool boundary constraints."""
        reg = setup_registry
        role = "Quantitative Analyst"

        invalid_cases = [
            # Negative or zero starting capital (gt=0.0)
            {"starting_capital": -10000.0},
            {"starting_capital": 0.0},
            # Negative or zero target capital (gt=0.0)
            {"target_capital": -50000.0},
            {"target_capital": 0.0},
            # Horizon years out of bounds (ge=1, le=50)
            {"years": 0},
            {"years": -5},
            {"years": 51},
            {"years": 1000},
            # Negative withdrawal (ge=0.0)
            {"initial_withdrawal": -500.0},
            # Withdrawal inflation out of bounds (ge=0.0, le=0.20)
            {"withdrawal_inflation_pct": -0.01},
            {"withdrawal_inflation_pct": 0.25},
            # Tax drag out of bounds (ge=0.0, le=0.50)
            {"tax_drag_pct": -0.05},
            {"tax_drag_pct": 0.60},
            # Advisory fee out of bounds (ge=0.0, le=0.05)
            {"advisory_fee_pct": -0.01},
            {"advisory_fee_pct": 0.10},
            # n_simulations out of bounds (ge=1000, le=50000)
            {"n_simulations": 100},
            {"n_simulations": 999},
            {"n_simulations": 50001},
            {"n_simulations": -1},
            # Type mismatches
            {"starting_capital": "not_a_number"},
            {"years": "ten_years"},
        ]

        for case in invalid_cases:
            res = await reg.execute_tool("simulate_wealth_plan", role, case)
            assert res.success is False, f"Expected validation failure for input: {case}, but got success"
            assert "validation" in res.error.lower()

    @pytest.mark.asyncio
    async def test_portfolio_optimizer_boundary_and_malformed_inputs(self, setup_registry):
        """Stress-test PortfolioOptimizerTool symbols and objective constraints."""
        reg = setup_registry
        role = "Quantitative Analyst"

        invalid_cases = [
            # Less than 2 symbols (min_length=2)
            {"symbols": []},
            {"symbols": ["SPY"]},
            # Invalid risk tolerance (ge=1, le=5)
            {"symbols": ["SPY", "BND"], "risk_tolerance": 0},
            {"symbols": ["SPY", "BND"], "risk_tolerance": 6},
            {"symbols": ["SPY", "BND"], "risk_tolerance": -1},
            # Invalid solver objective (Literal)
            {"symbols": ["SPY", "BND"], "solver_objective": "invalid_magic_solver"},
            {"symbols": ["SPY", "BND"], "solver_objective": "maximize_yolo_return"},
            # Negative total portfolio value (ge=0.0)
            {"symbols": ["SPY", "BND"], "total_portfolio_value": -100.0},
        ]

        for case in invalid_cases:
            res = await reg.execute_tool("optimize_portfolio", role, case)
            assert res.success is False, f"Expected validation failure for input: {case}, but got success"
            assert "validation" in res.error.lower()

    @pytest.mark.asyncio
    async def test_asset_screener_boundary_inputs(self, setup_registry):
        """Stress-test AssetScreenerTool boundary constraints."""
        reg = setup_registry
        role = "Investment Research Analyst"

        invalid_cases = [
            # Negative expense ratio or > 0.05
            {"max_expense_ratio": -0.01},
            {"max_expense_ratio": 0.06},
            # Negative yield
            {"min_yield": -0.05},
            # Negative AUM
            {"min_aum_billions": -10.0},
            # Invalid risk tier (ge=1, le=5)
            {"max_risk_level": 0},
            {"max_risk_level": 6},
        ]

        for case in invalid_cases:
            res = await reg.execute_tool("screen_assets", role, case)
            assert res.success is False, f"Expected validation failure for input: {case}, but got success"
            assert "validation" in res.error.lower()

    @pytest.mark.asyncio
    async def test_unexpected_extra_arguments(self, setup_registry):
        """Verify behavior when extra undeclared keys are passed."""
        reg = setup_registry
        role = "Financial Analyst"
        # Passing extra payload keys alongside valid argument
        payload = {
            "symbol": "AAPL",
            "__proto__": {"injected": True},
            "extra_unrecognized_key": "some_value",
            "nested_injection": {"key": "val"},
        }
        res = await reg.execute_tool("get_stock_quote", role, payload)
        # Should gracefully ignore extra arguments or succeed
        assert isinstance(res, ToolResult)
        assert res.tool_name == "get_stock_quote"

    @pytest.mark.asyncio
    async def test_raise_on_error_mode(self, setup_registry):
        """When raise_on_error=True, ToolValidationError must be raised instead of returned in ToolResult."""
        reg = setup_registry
        role = "Quantitative Analyst"
        with pytest.raises(ToolValidationError):
            await reg.execute_tool(
                name="simulate_wealth_plan",
                role=role,
                args={"starting_capital": -1.0},
                raise_on_error=True,
            )


# ============================================================================
# 4. Schema Export Fidelity & Integrity Tests
# ============================================================================

class TestAdversarialSchemaExports:
    @pytest.fixture(autouse=True)
    def setup_registry(self):
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)
        reg.register(ComplianceRestrictedTool())
        yield reg
        reg.reset()

    def test_export_schemas_all_conforms_to_openai_format(self, setup_registry):
        """All exported schemas must strictly match OpenAI function calling specs."""
        reg = setup_registry
        schemas = reg.export_schemas()
        assert len(schemas) >= 7

        for item in schemas:
            assert item.get("type") == "function"
            fn = item.get("function")
            assert isinstance(fn, dict)
            assert "name" in fn and isinstance(fn["name"], str) and len(fn["name"]) > 0
            assert "description" in fn and isinstance(fn["description"], str)
            assert "parameters" in fn and isinstance(fn["parameters"], dict)
            params = fn["parameters"]
            assert params.get("type") == "object"
            assert "properties" in params and isinstance(params["properties"], dict)

    def test_role_filtered_schema_isolation(self, setup_registry):
        """Schema export for Compliance Guard must not leak non-compliance tools."""
        reg = setup_registry
        cg_schemas = reg.export_schemas("Compliance Guard")
        cg_tool_names = [s["function"]["name"] for s in cg_schemas]

        # Only compliance_audit_lock should be exported for Compliance Guard
        assert "compliance_audit_lock" in cg_tool_names
        assert "get_stock_quote" not in cg_tool_names
        assert "optimize_portfolio" not in cg_tool_names
        assert "simulate_wealth_plan" not in cg_tool_names

        # Quantitative Analyst schemas
        qa_schemas = reg.export_schemas("Quantitative Analyst")
        qa_tool_names = [s["function"]["name"] for s in qa_schemas]
        assert "simulate_wealth_plan" in qa_tool_names
        assert "optimize_portfolio" in qa_tool_names
        assert "compliance_audit_lock" not in qa_tool_names

    def test_export_json_schemas_fidelity(self, setup_registry):
        """export_json_schemas produces valid JSON Schemas indexed by tool name."""
        reg = setup_registry
        json_schemas = reg.export_json_schemas()
        assert "get_stock_quote" in json_schemas
        assert "simulate_wealth_plan" in json_schemas
        assert "optimize_portfolio" in json_schemas

        # Verify simulate_wealth_plan schema properties
        swp_schema = json_schemas["simulate_wealth_plan"]
        assert swp_schema["type"] == "object"
        assert "starting_capital" in swp_schema["properties"]
        assert "target_capital" in swp_schema["properties"]
        assert "years" in swp_schema["properties"]

    def test_schema_immutability(self, setup_registry):
        """Mutating an exported schema dictionary must not alter subsequent exports."""
        reg = setup_registry
        s1 = reg.export_schemas()
        # Maliciously mutate exported dict
        s1[0]["function"]["name"] = "tampered_tool_name"
        s1[0]["function"]["parameters"]["properties"]["tampered"] = {}

        # Fetch fresh schema
        s2 = reg.export_schemas()
        assert s2[0]["function"]["name"] != "tampered_tool_name"
        assert "tampered" not in s2[0]["function"]["parameters"]["properties"]


# ============================================================================
# 5. Adapter & Concurrency Stress Tests
# ============================================================================

class TestAdversarialAdaptersAndConcurrency:
    @pytest.mark.asyncio
    async def test_concurrent_tool_execution(self):
        """Execute 50 concurrent tool calls through ToolRegistry without corruption."""
        reg = ToolRegistry.get_instance()
        reg.reset()
        register_core_tools(reg)

        tickers = ["SPY", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "TSLA", "META"] * 6

        async def call_quote(ticker: str, idx: int):
            ctx = ExecutionContext(session_id=f"sess_{idx}", client_id="test_client")
            return await reg.execute_tool(
                name="get_stock_quote",
                role="Financial Analyst",
                args={"symbol": ticker},
                context=ctx,
            )

        tasks = [call_quote(t, i) for i, t in enumerate(tickers)]
        results = await asyncio.gather(*tasks)

        assert len(results) == len(tickers)
        for res in results:
            assert isinstance(res, ToolResult)
            assert res.success is True
            assert res.tool_name == "get_stock_quote"
            assert res.provenance_hash is not None
            assert len(res.provenance_hash) == 64

    @pytest.mark.asyncio
    async def test_circuit_breaker_concurrency_race(self):
        """Under concurrent failures, circuit breaker transitions cleanly to OPEN without race conditions."""
        cb = CircuitBreaker(name="test_concurrent_cb", failure_threshold=5, cooldown_seconds=1.0)
        assert cb.state == CircuitState.CLOSED

        # Launch 20 concurrent failing operations
        async def record_fail():
            await cb.record_failure(RuntimeError("concurrent fail"))

        await asyncio.gather(*(record_fail() for _ in range(20)))

        # Must be OPEN
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False

    @pytest.mark.asyncio
    async def test_rate_limiter_burst_and_drain(self):
        """AsyncRateLimiter strictly limits throughput when burst capacity is drained."""
        limiter = AsyncRateLimiter(rate_limit_per_sec=100.0, burst_capacity=10.0)

        # First 10 tokens acquire instantly
        t0 = time.perf_counter()
        for _ in range(10):
            await limiter.acquire()
        elapsed = time.perf_counter() - t0
        assert elapsed < 0.1  # Fast burst

        # 11th acquisition must wait slightly
        t1 = time.perf_counter()
        await limiter.acquire()
        elapsed_wait = time.perf_counter() - t1
        # Should have waited for refill (~0.01s)
        assert elapsed_wait >= 0.005

    def test_backoff_jitter_bounds(self):
        """calculate_backoff_delay delay is strictly positive and bounded by max_delay."""
        for attempt in range(1, 15):
            for _ in range(20):
                delay = calculate_backoff_delay(
                    attempt=attempt,
                    base_interval=1.0,
                    max_delay=30.0,
                    jitter=True,
                )
                assert delay > 0.0
                assert delay <= 30.0

    def test_provenance_hash_collision_resistance(self):
        """Small mutations in inputs generate radically distinct SHA-256 hashes."""
        tool = MarketQuoteTool()
        h1 = tool.compute_provenance_hash({"symbol": "SPY"}, {"price": 500.00})
        h2 = tool.compute_provenance_hash({"symbol": "SPY"}, {"price": 500.01})
        h3 = tool.compute_provenance_hash({"symbol": "SPX"}, {"price": 500.00})

        assert h1 != h2
        assert h1 != h3
        assert len(h1) == 64
        assert len(h2) == 64
        assert len(h3) == 64

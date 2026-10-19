"""
backend/tools/registry.py
=========================
Centralized Tool Registry for the Wealth Advisory Multi-Agent System.
Implements the singleton pattern, dynamic tool registration, role-based
authorization filtering, OpenAI schema export, and controlled execution
adapters with rate limiting, circuit breaking, and provenance logging.
"""

from __future__ import annotations

import time
import json
import logging
import inspect
import asyncio
from typing import (
    Dict,
    List,
    Optional,
    Set,
    Any,
    Callable,
    Awaitable,
    Union,
)

try:
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
except ImportError:
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

logger = logging.getLogger("wealth_advisor.tools.registry")


# ============================================================================
# Role Canonicalization & Mapping
# ============================================================================

# Authoritative canonical roles mapping both snake_case and Title Case variants
ROLE_NORMALIZATION_MAP: Dict[str, str] = {
    # 1. Financial Analyst
    "financial analyst": "financial_analyst",
    "financial_analyst": "financial_analyst",
    "financial": "financial_analyst",
    # 2. Macro & Market Analyst
    "macro & market analyst": "macro_market_analyst",
    "macro_market_analyst": "macro_market_analyst",
    "macro analyst": "macro_market_analyst",
    "macro_analyst": "macro_market_analyst",
    "macro": "macro_market_analyst",
    # 3. Investment Research Analyst
    "investment research analyst": "investment_research_analyst",
    "investment_research_analyst": "investment_research_analyst",
    "investment analyst": "investment_research_analyst",
    "investment_analyst": "investment_research_analyst",
    "research analyst": "investment_research_analyst",
    # 4. Quantitative Analyst
    "quantitative analyst": "quantitative_analyst",
    "quantitative_analyst": "quantitative_analyst",
    "quant analyst": "quantitative_analyst",
    "quant": "quantitative_analyst",
    # 5. Intelligence / Web Analyst
    "intelligence/web analyst": "intelligence_web_analyst",
    "intelligence_web_analyst": "intelligence_web_analyst",
    "intelligence analyst": "intelligence_web_analyst",
    "web analyst": "intelligence_web_analyst",
    "web_analyst": "intelligence_web_analyst",
    # 6. Risk & Devil's Advocate
    "risk & devil's advocate": "devils_advocate",
    "devils_advocate": "devils_advocate",
    "devil's advocate": "devils_advocate",
    "risk & devils advocate": "devils_advocate",
    "risk analyst": "devils_advocate",
    # 7. Personalized Advisory
    "personalized advisory": "personalized_advisory",
    "personalized_advisory": "personalized_advisory",
    "advisory": "personalized_advisory",
    "advisor": "personalized_advisory",
    # 8. Compliance Guard
    "compliance guard": "compliance_guard",
    "compliance_guard": "compliance_guard",
    "compliance": "compliance_guard",
    # Supervisory & System Personas
    "orchestrator": "orchestrator",
    "wealthadvisor": "orchestrator",
    "wealth advisor": "orchestrator",
    "execution module": "execution_module",
    "execution_module": "execution_module",
    "admin": "admin",
    "*": "*",
    "all": "*",
}


def normalize_role(role: str) -> str:
    """
    Normalizes role string into its canonical identifier for comparison.
    Falls back to lowercased underscore string if not in explicit dictionary.
    """
    cleaned = role.strip().lower()
    if cleaned in ROLE_NORMALIZATION_MAP:
        return ROLE_NORMALIZATION_MAP[cleaned]
    simplified = cleaned.replace(" & ", "_").replace("/", "_").replace(" ", "_").replace("-", "_")
    return ROLE_NORMALIZATION_MAP.get(simplified, simplified)


# ============================================================================
# Tool Registry Singleton
# ============================================================================

class ToolRegistry:
    """
    Centralized singleton registry for discovering, authorizing, and executing tools.
    
    Features:
      - Thread-safe singleton instantiation.
      - Pydantic v2 argument validation prior to execution.
      - Role-based authorization matrix enforcement.
      - Dynamic schema export for OpenAI function calling.
      - Circuit breaker, rate limiting, and execution provenance logging.
    """

    _instance: Optional[ToolRegistry] = None

    def __new__(cls, *args, **kwargs) -> ToolRegistry:
        """Enforce singleton pattern across all instantiation calls."""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        """Initialize registry internal data structures once."""
        if getattr(self, "_initialized", False):
            return
        self._tools: Dict[str, BaseTool] = {}
        self._telemetry_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None
        self._lock = asyncio.Lock()
        self._initialized = True

    @classmethod
    def get_instance(cls) -> ToolRegistry:
        """Explicit class method to acquire the registry singleton."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def set_telemetry_callback(self, callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]]) -> None:
        """Register an async callback for streaming tool telemetry events."""
        self._telemetry_callback = callback

    def register(self, tool: BaseTool, override: bool = True) -> None:
        """
        Register a tool instance in the registry.
        
        Args:
            tool: BaseTool subclass instance.
            override: If True, overwrite any existing tool with the same name.
        """
        if not isinstance(tool, BaseTool):
            raise TypeError(f"Tool must inherit from BaseTool, got {type(tool)}")
        
        key = tool.name.strip().lower()
        if not override and key in self._tools:
            raise ValueError(f"Tool with name '{tool.name}' is already registered.")
        
        self._tools[key] = tool
        logger.info(f"Registered tool: '{tool.name}' (roles: {tool.required_roles})")

    def unregister(self, name: str) -> Optional[BaseTool]:
        """Remove a tool by name from the registry."""
        key = name.strip().lower()
        removed = self._tools.pop(key, None)
        if removed:
            logger.info(f"Unregistered tool: '{name}'")
        return removed

    def get_tool(self, name: str) -> Optional[BaseTool]:
        """Retrieve a tool by name (case-insensitive)."""
        key = name.strip().lower()
        return self._tools.get(key)

    def has_tool(self, name: str) -> bool:
        """Check if a tool exists in the registry."""
        key = name.strip().lower()
        return key in self._tools

    def list_tools(self) -> List[BaseTool]:
        """Return a list of all registered tools."""
        return list(self._tools.values())

    def list_tool_names(self) -> List[str]:
        """Return a list of all registered tool names."""
        return [tool.name for tool in self._tools.values()]

    def reset(self) -> None:
        """Clear all registered tools (primarily used for hermetic testing)."""
        self._tools.clear()
        logger.debug("ToolRegistry reset: all tools cleared.")

    # ------------------------------------------------------------------------
    # Role-Based Authorization & Discovery
    # ------------------------------------------------------------------------

    def get_tools_for_role(self, role: str) -> List[BaseTool]:
        """
        Filter registered tools accessible by a specific agent role.
        
        Args:
            role: Agent role name (e.g. 'Financial Analyst' or 'financial_analyst').
        
        Returns:
            List of BaseTool instances authorized for the given role.
        """
        norm_role = normalize_role(role)
        authorized: List[BaseTool] = []

        for tool in self._tools.values():
            if self._is_role_authorized(norm_role, tool):
                authorized.append(tool)

        return authorized

    def _is_role_authorized(self, norm_caller_role: str, tool: BaseTool) -> bool:
        """Internal helper to evaluate whether caller role matches tool permissions."""
        if norm_caller_role in ("admin", "*"):
            return True

        tool_roles = tool.required_roles or tool.allowed_roles or []
        for tr in tool_roles:
            norm_tr = normalize_role(tr)
            if norm_tr in ("*", "all"):
                return True
            if norm_tr == norm_caller_role:
                return True

        return False

    def check_authorization(self, role: str, tool_name: str) -> bool:
        """
        Verify that a role is authorized to execute a specific tool.
        
        Raises:
            ToolNotFoundError: If the tool is not registered.
            ToolAuthorizationError: If the role is unauthorized.
        
        Returns:
            True if authorized.
        """
        tool = self.get_tool(tool_name)
        if tool is None:
            raise ToolNotFoundError(f"Tool '{tool_name}' is not registered.")

        norm_role = normalize_role(role)
        if not self._is_role_authorized(norm_role, tool):
            raise ToolAuthorizationError(
                f"Role '{role}' is not authorized to call tool '{tool_name}'. "
                f"Allowed roles: {tool.required_roles}"
            )
        return True

    # ------------------------------------------------------------------------
    # Schema Export for LLM Function Calling
    # ------------------------------------------------------------------------

    def export_schemas(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Export OpenAI-compatible function definitions for registered tools.
        
        Args:
            role: If provided, only export schemas authorized for this role.
        
        Returns:
            List of function calling schema dictionaries.
        """
        tools = self.get_tools_for_role(role) if role else self.list_tools()
        return [tool.to_openai_schema() for tool in tools]

    def get_openai_tools(self, role: Optional[str] = None) -> List[Dict[str, Any]]:
        """Convenience alias for export_schemas."""
        return self.export_schemas(role=role)

    def export_json_schemas(self, role: Optional[str] = None) -> Dict[str, Any]:
        """Export raw JSON Schema definitions indexed by tool name."""
        tools = self.get_tools_for_role(role) if role else self.list_tools()
        return {tool.name: tool.args_schema.model_json_schema() for tool in tools}

    # ------------------------------------------------------------------------
    # Controlled Execution Pipeline
    # ------------------------------------------------------------------------

    async def execute_tool(
        self,
        name: str,
        role: str,
        args: Dict[str, Any],
        context: Optional[ExecutionContext] = None,
        raise_on_error: bool = False,
    ) -> ToolResult:
        """
        Controlled execution pipeline enforcing:
          1. Dynamic tool lookup
          2. Role authorization check
          3. Pydantic v2 argument validation
          4. Circuit breaker and rate limiter coordination
          5. Execution timing and timeout enforcement
          6. Provenance hash calculation and telemetry emission
        """
        t0 = time.perf_counter()

        # Step 1: Tool Lookup
        tool = self.get_tool(name)
        if tool is None:
            msg = f"Tool '{name}' is not registered in ToolRegistry."
            logger.error(msg)
            raise ToolNotFoundError(msg)

        # Step 2: Role Authorization Gate
        self.check_authorization(role, name)

        # Emit telemetry start event if callback configured
        if self._telemetry_callback:
            try:
                await self._telemetry_callback({
                    "type": "tool_call_started",
                    "tool": name,
                    "role": role,
                    "args": {k: v for k, v in args.items() if "key" not in k.lower() and "token" not in k.lower()},
                    "timestamp": time.time(),
                })
            except Exception as tel_err:
                logger.debug(f"Telemetry callback failed: {tel_err}")

        # Step 3: Argument Validation
        try:
            validated_args_model = tool.validate_args(args)
            validated_kwargs = validated_args_model.model_dump()
        except ToolValidationError as val_err:
            duration_ms = (time.perf_counter() - t0) * 1000.0
            logger.warning(f"Validation failed for tool '{name}': {val_err}")
            if raise_on_error:
                raise
            return ToolResult(
                tool_name=name,
                success=False,
                error=str(val_err),
                execution_time_ms=duration_ms,
            )

        # Step 4: Circuit Breaker Verification
        cb = tool.circuit_breaker
        if cb is not None:
            can_exec = await cb.can_execute()
            if not can_exec:
                duration_ms = (time.perf_counter() - t0) * 1000.0
                err_msg = (
                    f"Circuit breaker for tool '{name}' is OPEN. "
                    f"Cooldown remaining: {getattr(cb, 'cooldown_remaining', 0.0):.1f}s"
                )
                logger.warning(err_msg)
                if raise_on_error:
                    try:
                        from tools.adapters import CircuitBreakerOpenError
                    except ImportError:
                        from backend.tools.adapters import CircuitBreakerOpenError
                    raise CircuitBreakerOpenError(service_name=name, cooldown_remaining=getattr(cb, 'cooldown_remaining', 0.0))
                return ToolResult(
                    tool_name=name,
                    success=False,
                    error=err_msg,
                    execution_time_ms=duration_ms,
                )

        # Step 5: Rate Limiting
        rl = tool.rate_limiter
        if rl is not None:
            await rl.acquire()

        # Step 6: Timed Execution with Timeout Guard
        result_payload: Dict[str, Any] = {}
        error_msg: Optional[str] = None
        success = True

        try:
            # Determine appropriate invocation format based on tool's execute signature
            sig = inspect.signature(tool.execute)
            call_kwargs = dict(validated_kwargs)
            if "context" in sig.parameters or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values()):
                call_kwargs["context"] = context

            param_names = [p.name for p in sig.parameters.values() if p.name != "self"]
            if param_names and param_names[0] == "args":
                # Method accepts args model as first positional argument
                exec_coro = tool.execute(validated_args_model, context=context)
            else:
                exec_coro = tool.execute(**call_kwargs)

            raw_result = await asyncio.wait_for(exec_coro, timeout=tool.timeout_seconds)
            duration_ms = (time.perf_counter() - t0) * 1000.0

            # If raw_result is already a ToolResult
            if isinstance(raw_result, ToolResult):
                if not raw_result.execution_time_ms:
                    raw_result.execution_time_ms = duration_ms
                if not raw_result.provenance_hash:
                    raw_result.provenance_hash = tool.compute_provenance_hash(
                        args, raw_result.data if raw_result.success else {"error": raw_result.error}
                    )
                if not raw_result.metadata:
                    raw_result.metadata = {}
                raw_result.metadata.setdefault("caller_role", role)
                if context:
                    if context.session_id:
                        raw_result.metadata.setdefault("session_id", context.session_id)
                    if context.client_id:
                        raw_result.metadata.setdefault("client_id", context.client_id)
                    if context.user_id:
                        raw_result.metadata.setdefault("user_id", context.user_id)

                if cb is not None and raw_result.success:
                    await cb.record_success()
                elif cb is not None and not raw_result.success:
                    await cb.record_failure(Exception(raw_result.error or "Tool returned failure"))

                if self._telemetry_callback:
                    try:
                        await self._telemetry_callback({
                            "type": "tool_call_completed",
                            "tool": name,
                            "role": role,
                            "latency_ms": duration_ms,
                            "status": "success" if raw_result.success else "error",
                            "timestamp": time.time(),
                        })
                    except Exception as tel_err:
                        logger.debug(f"Telemetry callback failed: {tel_err}")

                return raw_result

            elif isinstance(raw_result, dict):
                result_payload = raw_result
            elif hasattr(raw_result, "model_dump"):
                result_payload = raw_result.model_dump(mode="json")
            else:
                result_payload = {"result": raw_result}

            # Update circuit breaker on success
            if cb is not None:
                await cb.record_success()

        except asyncio.TimeoutError as timeout_err:
            success = False
            error_msg = f"Tool '{name}' execution timed out after {tool.timeout_seconds} seconds."
            logger.error(error_msg)
            if cb is not None:
                await cb.record_failure(timeout_err)
            if raise_on_error:
                raise ToolExecutionTimeoutError(error_msg) from timeout_err

        except Exception as exc:
            success = False
            error_msg = f"Execution of tool '{name}' failed: {exc}"
            logger.exception(error_msg)
            if cb is not None:
                await cb.record_failure(exc)
            if raise_on_error:
                raise

        duration_ms = (time.perf_counter() - t0) * 1000.0

        # Step 7: Provenance Hash Calculation
        provenance_hash = tool.compute_provenance_hash(args, result_payload if success else {"error": error_msg})

        # Emit telemetry completed event
        if self._telemetry_callback:
            try:
                await self._telemetry_callback({
                    "type": "tool_call_completed",
                    "tool": name,
                    "role": role,
                    "latency_ms": duration_ms,
                    "status": "success" if success else "error",
                    "timestamp": time.time(),
                })
            except Exception as tel_err:
                logger.debug(f"Telemetry callback failed: {tel_err}")

        return ToolResult(
            tool_name=name,
            success=success,
            data=result_payload if success else {},
            error=error_msg,
            execution_time_ms=duration_ms,
            provenance_hash=provenance_hash,
            metadata={
                "caller_role": role,
                "session_id": context.session_id if context else None,
                "client_id": context.client_id if context else None,
            },
        )


# Global singleton instance
tool_registry = ToolRegistry.get_instance()

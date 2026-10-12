"""
backend/tools/base.py
=====================
Abstract base classes, schemas, and execution contracts for the centralized
tool registry. Provides Pydantic v2 argument/output validation, role-based
authorization metadata, and execution telemetry integration.
"""

from __future__ import annotations

import time
import json
import hashlib
import asyncio
from abc import ABC, abstractmethod
from enum import Enum
from datetime import datetime, timezone
from typing import (
    Dict,
    Any,
    List,
    Optional,
    Type,
    Union,
    Callable,
    Awaitable,
)
from pydantic import BaseModel, Field, ValidationError


# ============================================================================
# 1. Tool Categories & Custom Exceptions
# ============================================================================

class ToolCategory(str, Enum):
    """Categorical classification of tools across the advisory platform."""
    MARKET_DATA = "MARKET_DATA"
    COMPANY_FILINGS = "COMPANY_FILINGS"
    MACRO = "MACRO"
    PORTFOLIO = "PORTFOLIO"
    WEB_INTELLIGENCE = "WEB_INTELLIGENCE"
    QUANT_MODELING = "QUANT_MODELING"
    EXECUTION = "EXECUTION"


class ToolError(Exception):
    """Base exception for all tool execution errors."""
    pass


class ToolNotFoundError(ToolError, KeyError):
    """Raised when a requested tool is not registered in ToolRegistry."""
    pass


class ToolAuthorizationError(ToolError, PermissionError):
    """Raised when an agent role is not authorized to execute a tool."""
    pass


class ToolValidationError(ToolError, ValueError):
    """Raised when tool arguments fail Pydantic schema validation."""
    pass


class ToolExecutionTimeoutError(ToolError, TimeoutError):
    """Raised when tool execution exceeds its configured timeout budget."""
    pass


# ============================================================================
# 2. Execution Context & Results Models
# ============================================================================

class ExecutionContext(BaseModel):
    """
    Runtime execution context passed to tool execution handlers.
    Captures session, tenant, and role identity for authorization and auditing.
    """
    session_id: Optional[str] = Field(default=None, description="Active session ID")
    user_id: Optional[str] = Field(default=None, description="Authenticated user ID")
    client_id: Optional[str] = Field(default=None, description="Verified client ID")
    role: Optional[str] = Field(default=None, description="Calling agent role name")
    caller: Optional[str] = Field(default=None, description="Originating agent name")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Arbitrary execution metadata")

    model_config = {"arbitrary_types_allowed": True}


class ToolResult(BaseModel):
    """
    Canonical output contract for all tool executions.
    Strictly satisfies PROJECT.md and Tier 1 test contracts.
    """
    tool_name: str = Field(..., description="Name of the executed tool")
    success: bool = Field(..., description="Whether execution completed without fatal errors")
    data: Dict[str, Any] = Field(default_factory=dict, description="Structured execution payload")
    error: Optional[str] = None
    execution_time_ms: float = Field(default=0.0, ge=0.0, description="Execution duration in milliseconds")
    provenance_hash: Optional[str] = Field(default=None, description="Cryptographic SHA-256 provenance hash")
    cached: bool = Field(default=False, description="Whether data originated from cache/fixture")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Additional provenance metadata")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize result to dictionary."""
        return self.model_dump(mode="json")


# ============================================================================
# 3. BaseTool Abstract Base Class
# ============================================================================

class BaseTool(ABC):
    """
    Abstract Base Class for all tools registered in the Wealth Advisory System.
    
    Subclasses MUST define:
      - name: Unique identifier for the tool (e.g. 'get_stock_quote')
      - description: Detailed description provided to the LLM
      - args_schema: Pydantic v2 BaseModel enforcing argument types
      - required_roles: List of agent roles authorized to invoke this tool
      - execute: Asynchronous execution coroutine
    """

    name: str = ""
    description: str = ""
    args_schema: Type[BaseModel] = BaseModel
    output_schema: Optional[Type[BaseModel]] = None
    required_roles: List[str] = []

    # Optional operational policies
    category: Optional[Union[str, ToolCategory]] = None
    timeout_seconds: float = 30.0
    idempotent: bool = True
    requires_approval: bool = False  # True for mutating operations (e.g. trade proposals)

    # Resilience primitives (optional)
    rate_limiter: Optional[Any] = None       # AsyncRateLimiter instance
    circuit_breaker: Optional[Any] = None    # CircuitBreaker instance
    cache_ttl: Optional[int] = None          # Seconds

    def __init__(self) -> None:
        if not self.name:
            raise ValueError(f"Tool class '{self.__class__.__name__}' must specify a non-empty 'name'.")
        if not self.description:
            raise ValueError(f"Tool '{self.name}' must specify a non-empty 'description'.")
        if not hasattr(self, "args_schema") or not issubclass(self.args_schema, BaseModel):
            raise TypeError(f"Tool '{self.name}' must define an 'args_schema' inheriting from pydantic.BaseModel.")

    @property
    def allowed_roles(self) -> List[str]:
        """Alias for required_roles to ensure cross-spec compatibility."""
        return self.required_roles

    def validate_args(self, raw_args: Dict[str, Any]) -> BaseModel:
        """
        Validates raw input dictionary against the tool's Pydantic v2 args_schema.
        Raises ToolValidationError if validation fails.
        """
        try:
            return self.args_schema.model_validate(raw_args)
        except ValidationError as e:
            raise ToolValidationError(f"Invalid arguments for tool '{self.name}': {e}") from e

    def to_openai_schema(self) -> Dict[str, Any]:
        """
        Exports the tool definition as an OpenAI function calling schema.
        Converts the Pydantic v2 args_schema into JSON Schema parameters.
        """
        json_schema = self.args_schema.model_json_schema()
        
        # Clean title / description from top-level schema if present
        json_schema.pop("title", None)
        
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": json_schema,
            },
        }

    def compute_provenance_hash(self, args: Dict[str, Any], result_data: Any) -> str:
        """
        Computes an auditable SHA-256 fingerprint over tool inputs and outputs.
        """
        try:
            payload = {
                "tool": self.name,
                "args": args,
                "data": result_data,
            }
            canonical_str = json.dumps(payload, sort_keys=True, default=str)
            return hashlib.sha256(canonical_str.encode("utf-8")).hexdigest()
        except Exception:
            # Fallback simple string hash
            raw = f"{self.name}:{str(args)}:{str(result_data)}"
            return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    @abstractmethod
    async def execute(self, *args, **kwargs) -> ToolResult:
        """
        Execute the tool coroutine with validated keyword arguments.
        Subclasses MUST implement this method.
        """
        raise NotImplementedError("Subclasses must implement execute().")

    async def __call__(self, *args, **kwargs) -> ToolResult:
        """Convenience invocation interface."""
        return await self.execute(*args, **kwargs)

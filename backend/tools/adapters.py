"""
backend/tools/adapters.py
=========================
Resilient execution adapters, circuit breaker finite state machines,
bounded retries with exponential backoff & jitter, structured error
classification, and execution provenance logging for the Wealth Advisory Agent.
"""

from __future__ import annotations

import os
import re
import json
import time
import uuid
import random
import asyncio
import hashlib
import logging
from enum import Enum
from datetime import datetime, timezone
from typing import Optional, Dict, List, Any, Callable, Awaitable, Tuple, Union

import httpx
from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger("wealth_advisor.tools.adapters")
provenance_logger = logging.getLogger("wealth_advisor.tools.provenance")


# =====================================================================
# 1. Structured Error Classification Taxonomy
# =====================================================================

class ErrorCategory(str, Enum):
    """Normalized domain error categories for tool execution."""
    AUTHORIZATION = "AUTHORIZATION"       # Role lacks permission to execute tool
    VALIDATION = "VALIDATION"             # Malformed arguments or schema violation
    RATE_LIMIT = "RATE_LIMIT"             # Local or upstream rate limiter exhausted
    CIRCUIT_OPEN = "CIRCUIT_OPEN"         # Circuit breaker is in OPEN state
    TIMEOUT = "TIMEOUT"                   # Execution timeout exceeded
    NETWORK = "NETWORK"                   # Socket, DNS, or transport connection drop
    UPSTREAM = "UPSTREAM"                 # 5xx HTTP response or malformed provider response
    INTERNAL = "INTERNAL"                 # Unhandled execution exception or bug


class ToolExecutionError(Exception):
    """Base domain exception for all tool execution failures."""
    def __init__(
        self,
        message: str,
        tool_name: str = "unknown",
        category: ErrorCategory = ErrorCategory.INTERNAL,
        is_retryable: bool = False,
        original_exception: Optional[Exception] = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.tool_name = tool_name
        self.category = category
        self.is_retryable = is_retryable
        self.original_exception = original_exception
        self.details = details or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "error_type": self.__class__.__name__,
            "tool_name": self.tool_name,
            "category": self.category.value,
            "message": self.message,
            "is_retryable": self.is_retryable,
            "details": self.details,
        }


class ToolAuthorizationError(ToolExecutionError):
    """Raised when the calling role is unauthorized to execute the tool."""
    def __init__(self, message: str, tool_name: str = "unknown", role: str = "unknown"):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.AUTHORIZATION,
            is_retryable=False,
            details={"caller_role": role},
        )


class ToolValidationError(ToolExecutionError):
    """Raised when input parameters fail Pydantic schema validation."""
    def __init__(self, message: str, tool_name: str = "unknown", validation_errors: Optional[Any] = None):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.VALIDATION,
            is_retryable=False,
            details={"validation_errors": validation_errors},
        )


class CircuitBreakerOpenError(ToolExecutionError):
    """
    Raised when execution is rejected because the circuit breaker is OPEN.
    Preserves exact backward compatibility with backend/services/data_pipeline.py.
    """
    def __init__(self, service_name: str, cooldown_remaining: float):
        self.service_name = service_name
        self.cooldown_remaining = cooldown_remaining
        msg = (
            f"Circuit breaker for service '{service_name}' is OPEN. "
            f"Cooldown remaining: {cooldown_remaining:.1f}s"
        )
        super().__init__(
            message=msg,
            tool_name=service_name,
            category=ErrorCategory.CIRCUIT_OPEN,
            is_retryable=False,
            details={"service_name": service_name, "cooldown_remaining": cooldown_remaining},
        )


class ToolCircuitBreakerError(CircuitBreakerOpenError):
    """Alias for CircuitBreakerOpenError under the ToolExecutionError naming convention."""
    pass


class ToolRateLimitError(ToolExecutionError):
    """Raised when rate limits (HTTP 429 or token bucket) are exceeded."""
    def __init__(self, message: str, tool_name: str = "unknown", retry_after: Optional[float] = None):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.RATE_LIMIT,
            is_retryable=True,
            details={"retry_after": retry_after},
        )


class ToolTimeoutError(ToolExecutionError):
    """Raised when tool execution exceeds allocated execution budget."""
    def __init__(self, message: str, tool_name: str = "unknown", timeout_seconds: float = 0.0):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.TIMEOUT,
            is_retryable=True,
            details={"timeout_seconds": timeout_seconds},
        )


class ToolNetworkError(ToolExecutionError):
    """Raised when network connectivity fails (connection refused, DNS error, broken pipe)."""
    def __init__(self, message: str, tool_name: str = "unknown", original_exception: Optional[Exception] = None):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.NETWORK,
            is_retryable=True,
            original_exception=original_exception,
        )


class ToolUpstreamError(ToolExecutionError):
    """Raised when upstream server returns 5xx or corrupted payloads."""
    def __init__(
        self,
        message: str,
        tool_name: str = "unknown",
        status_code: Optional[int] = None,
        original_exception: Optional[Exception] = None,
    ):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.UPSTREAM,
            is_retryable=status_code in {429, 500, 502, 503, 504} if status_code else True,
            original_exception=original_exception,
            details={"status_code": status_code},
        )


class ToolInternalError(ToolExecutionError):
    """Raised when an internal unexpected fault occurs in tool logic."""
    def __init__(self, message: str, tool_name: str = "unknown", original_exception: Optional[Exception] = None):
        super().__init__(
            message=message,
            tool_name=tool_name,
            category=ErrorCategory.INTERNAL,
            is_retryable=False,
            original_exception=original_exception,
        )


RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}
NON_RETRYABLE_STATUS_CODES = {400, 401, 403, 404, 422}


def classify_error(exc: Exception, tool_name: str = "unknown") -> Tuple[ErrorCategory, bool, str]:
    """
    Inspects an exception and classifies it into (ErrorCategory, is_retryable, sanitized_message).
    """
    if isinstance(exc, ToolExecutionError):
        return exc.category, exc.is_retryable, exc.message

    if isinstance(exc, CircuitBreakerOpenError):
        return ErrorCategory.CIRCUIT_OPEN, False, str(exc)

    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        if status == 429:
            return ErrorCategory.RATE_LIMIT, True, f"HTTP 429 Too Many Requests from {tool_name}"
        if status in {401, 403}:
            return ErrorCategory.AUTHORIZATION, False, f"HTTP {status} Forbidden/Unauthorized: {exc}"
        if status in {400, 422}:
            return ErrorCategory.VALIDATION, False, f"HTTP {status} Bad Request/Validation Error: {exc}"
        if status in RETRYABLE_STATUS_CODES:
            return ErrorCategory.UPSTREAM, True, f"HTTP {status} Server Error: {exc}"
        return ErrorCategory.UPSTREAM, False, f"HTTP {status} Error: {exc}"

    if isinstance(exc, PermissionError):
        return ErrorCategory.AUTHORIZATION, False, f"Permission denied for {tool_name}: {exc}"

    if "ValidationError" in exc.__class__.__name__:
        return ErrorCategory.VALIDATION, False, f"Parameter validation error for {tool_name}: {exc}"

    if isinstance(exc, (httpx.TimeoutException, asyncio.TimeoutError, TimeoutError)):
        return ErrorCategory.TIMEOUT, True, f"Timeout during execution of {tool_name}: {exc}"

    if isinstance(exc, (httpx.NetworkError, httpx.ConnectError, ConnectionError)):
        return ErrorCategory.NETWORK, True, f"Network transport error in {tool_name}: {exc}"

    if isinstance(exc, OSError) and not isinstance(exc, PermissionError):
        return ErrorCategory.NETWORK, True, f"OS network/socket error in {tool_name}: {exc}"

    return ErrorCategory.INTERNAL, False, f"Unexpected error in {tool_name}: {exc}"


# =====================================================================
# 2. Circuit Breaker State Machine
# =====================================================================

class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreaker:
    """
    Thread-safe and asyncio-safe Circuit Breaker finite state machine.
    Transitions:
      CLOSED -> OPEN (after failure_threshold consecutive failures)
      OPEN -> HALF_OPEN (after cooldown_seconds elapsed)
      HALF_OPEN -> CLOSED (if probe succeeds)
      HALF_OPEN -> OPEN (if probe fails)
    """
    def __init__(
        self,
        name: str = "default",
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0,
    ):
        self.name = name
        self.failure_threshold = failure_threshold
        self.cooldown_seconds = cooldown_seconds
        self._state = CircuitState.CLOSED
        self._failure_count = 0
        self._opened_at: Optional[float] = None
        self._lock = asyncio.Lock()

        # Telemetry metrics
        self._total_calls = 0
        self._total_failures = 0
        self._total_trips = 0
        self._last_state_change = time.time()
        self._last_failure_reason: Optional[str] = None

    @property
    def state(self) -> CircuitState:
        """Dynamically evaluate time-based transition from OPEN to HALF_OPEN."""
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            if time.time() - self._opened_at >= self.cooldown_seconds:
                return CircuitState.HALF_OPEN
        return self._state

    @property
    def failure_count(self) -> int:
        return self._failure_count

    @property
    def cooldown_remaining(self) -> float:
        if self._state == CircuitState.OPEN and self._opened_at is not None:
            rem = self.cooldown_seconds - (time.time() - self._opened_at)
            return max(0.0, rem)
        return 0.0

    async def can_execute(self) -> bool:
        """Returns True if a request is permitted to execute network operations."""
        async with self._lock:
            cur = self.state
            return cur in (CircuitState.CLOSED, CircuitState.HALF_OPEN)

    async def record_success(self) -> None:
        """Record successful execution; reset failure count and close circuit."""
        async with self._lock:
            self._total_calls += 1
            old_state = self.state
            self._failure_count = 0
            self._state = CircuitState.CLOSED
            self._opened_at = None
            if old_state != CircuitState.CLOSED:
                self._last_state_change = time.time()
                logger.info(f"CircuitBreaker '{self.name}': Recovered to CLOSED state.")

    async def record_failure(self, exc: Optional[Exception] = None) -> None:
        """Record failure; increment consecutive failures and trip if threshold reached."""
        async with self._lock:
            self._total_calls += 1
            self._total_failures += 1
            self._last_failure_reason = str(exc) if exc else "Unknown error"
            cur = self.state

            if cur == CircuitState.HALF_OPEN:
                self._state = CircuitState.OPEN
                self._opened_at = time.time()
                self._total_trips += 1
                self._last_state_change = time.time()
                logger.warning(
                    f"CircuitBreaker '{self.name}': Probe failed in HALF_OPEN. "
                    f"Re-tripping to OPEN for {self.cooldown_seconds}s. Reason: {self._last_failure_reason}"
                )
            elif cur == CircuitState.CLOSED:
                self._failure_count += 1
                if self._failure_count >= self.failure_threshold:
                    self._state = CircuitState.OPEN
                    self._opened_at = time.time()
                    self._total_trips += 1
                    self._last_state_change = time.time()
                    logger.error(
                        f"CircuitBreaker '{self.name}': Failure threshold {self.failure_threshold} reached. "
                        f"Circuit OPEN for {self.cooldown_seconds}s. Reason: {self._last_failure_reason}"
                    )
            elif cur == CircuitState.OPEN:
                self._opened_at = time.time()

    async def reset(self) -> None:
        """Manual reset back to CLOSED state."""
        async with self._lock:
            self._state = CircuitState.CLOSED
            self._failure_count = 0
            self._opened_at = None
            self._last_state_change = time.time()

    def get_metrics(self) -> Dict[str, Any]:
        """Returns snapshot dictionary of circuit breaker metrics."""
        return {
            "name": self.name,
            "state": self.state.value,
            "failure_count": self._failure_count,
            "failure_threshold": self.failure_threshold,
            "cooldown_seconds": self.cooldown_seconds,
            "cooldown_remaining": self.cooldown_remaining,
            "total_calls": self._total_calls,
            "total_failures": self._total_failures,
            "total_trips": self._total_trips,
            "last_failure_reason": self._last_failure_reason,
            "last_state_change": datetime.fromtimestamp(self._last_state_change, tz=timezone.utc).isoformat(),
        }


class CircuitBreakerRegistry:
    """Singleton registry managing per-tool or per-service circuit breakers."""
    _instance: Optional[CircuitBreakerRegistry] = None

    def __new__(cls) -> CircuitBreakerRegistry:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._breakers = {}
        return cls._instance

    @classmethod
    def get_instance(cls) -> CircuitBreakerRegistry:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def get_breaker(
        self,
        name: str,
        failure_threshold: int = 5,
        cooldown_seconds: float = 60.0
    ) -> CircuitBreaker:
        if name not in self._breakers:
            self._breakers[name] = CircuitBreaker(
                name=name,
                failure_threshold=failure_threshold,
                cooldown_seconds=cooldown_seconds
            )
        return self._breakers[name]

    async def reset_all(self) -> None:
        for cb in self._breakers.values():
            await cb.reset()


# =====================================================================
# 3. Asynchronous Rate Limiter (Token Bucket)
# =====================================================================

class AsyncRateLimiter:
    """
    Coroutine-safe Token Bucket rate limiter.
    Ensures requests do not exceed specified rate limits per second.
    Preserves exact backward compatibility with backend/services/data_pipeline.py.
    """
    def __init__(self, rate_limit_per_sec: float = 5.0, burst_capacity: float = 5.0):
        self.rate = float(rate_limit_per_sec)
        self.capacity = float(burst_capacity)
        self._tokens = float(burst_capacity)
        self._last_refill = time.time()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it."""
        while True:
            async with self._lock:
                now = time.time()
                elapsed = now - self._last_refill
                self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait_time = (1.0 - self._tokens) / self.rate

            # Sleep outside lock to allow concurrent coroutine evaluations
            await asyncio.sleep(max(0.001, wait_time))


# =====================================================================
# 4. Bounded Retries with Exponential Backoff and Jitter
# =====================================================================

def calculate_backoff_delay(
    attempt: int,
    base_interval: float = 1.0,
    max_delay: float = 10.0,
    jitter: bool = True,
    jitter_range: Tuple[float, float] = (0.05, 0.25),
) -> float:
    """
    Computes exponential backoff delay with additive jitter:
      delay = min(max_delay, base_interval * (2 ** attempt) + uniform(j_min, j_max))
    """
    delay = base_interval * (2.0 ** attempt)
    if jitter:
        delay += random.uniform(jitter_range[0], jitter_range[1])
    return min(max_delay, delay)


async def execute_with_retry(
    operation: Callable[[], Awaitable[Any]],
    rate_limiter: Optional[AsyncRateLimiter] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    max_retries: int = 3,
    base_interval: float = 1.0,
    max_delay: float = 10.0,
    jitter: bool = True,
    tool_name: str = "unknown",
) -> Any:
    """
    Executes an async operation with rate limiting, circuit breaker gating,
    structured error classification, and bounded exponential backoff retry.
    """
    if circuit_breaker and not await circuit_breaker.can_execute():
        raise CircuitBreakerOpenError(
            circuit_breaker.name, circuit_breaker.cooldown_remaining
        )

    last_exc: Optional[Exception] = None

    for attempt in range(max_retries + 1):
        if rate_limiter:
            await rate_limiter.acquire()

        try:
            result = await operation()
            if circuit_breaker:
                await circuit_breaker.record_success()
            return result
        except Exception as e:
            last_exc = e
            cat, is_retryable, _ = classify_error(e, tool_name=tool_name)

            # Fail fast on non-retryable errors
            if not is_retryable:
                if circuit_breaker and cat not in (ErrorCategory.VALIDATION, ErrorCategory.AUTHORIZATION):
                    await circuit_breaker.record_failure(e)
                raise

        # If we exhausted retries, break
        if attempt == max_retries:
            break

        delay = calculate_backoff_delay(
            attempt=attempt,
            base_interval=base_interval,
            max_delay=max_delay,
            jitter=jitter,
        )
        logger.warning(
            f"Tool '{tool_name}' attempt {attempt + 1} failed ({last_exc}). "
            f"Retrying in {delay:.2f}s..."
        )
        await asyncio.sleep(delay)

    # All retries exhausted
    if circuit_breaker and last_exc:
        await circuit_breaker.record_failure(last_exc)

    raise last_exc or RuntimeError(f"Operation in tool '{tool_name}' failed after maximum retries.")


# =====================================================================
# 5. Execution Provenance Logging & Telemetry
# =====================================================================

class ExecutionStatus(str, Enum):
    SUCCESS = "SUCCESS"
    RETRY_SUCCESS = "RETRY_SUCCESS"
    FAILURE = "FAILURE"
    CIRCUIT_TRIPPED = "CIRCUIT_TRIPPED"
    DEGRADED_FALLBACK = "DEGRADED_FALLBACK"


SENSITIVE_KEY_PATTERN = re.compile(
    r"(password|secret|token|api_key|auth|bearer|private_key|pin|ssn)",
    re.IGNORECASE
)


def redact_sensitive_data(val: Any) -> Any:
    """Recursively redacts passwords, tokens, API keys from dictionaries and lists."""
    if isinstance(val, dict):
        cleaned = {}
        for k, v in val.items():
            if SENSITIVE_KEY_PATTERN.search(str(k)):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = redact_sensitive_data(v)
        return cleaned
    if isinstance(val, list):
        return [redact_sensitive_data(item) for item in val]
    return val


def compute_sha256_hash(data: Any) -> str:
    """Computes deterministic SHA-256 hash of structured payload."""
    try:
        serialized = json.dumps(data, sort_keys=True, default=str)
    except Exception:
        serialized = str(data)
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


class ExecutionProvenance(BaseModel):
    """
    Immutable provenance record capturing invocation trace, analyst role,
    arguments (redacted), execution latency, and error classification.
    """
    invocation_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()),
        description="Unique execution trace UUID"
    )
    tool_name: str = Field(..., description="Target tool name")
    caller_role: str = Field(..., description="Specialist analyst role invoking the tool")
    session_id: Optional[str] = Field(default=None, description="Research or chat session ID")
    client_id: Optional[str] = Field(default=None, description="Tenant client ID")
    inquiry_id: Optional[str] = Field(default=None, description="Research DAG inquiry ID")
    arguments_redacted: Dict[str, Any] = Field(
        default_factory=dict,
        description="Invocation arguments with sensitive keys masked"
    )
    timestamp_start: datetime = Field(..., description="UTC invocation start time")
    timestamp_end: datetime = Field(..., description="UTC completion time")
    duration_ms: float = Field(..., ge=0.0, description="Latency in milliseconds")
    status: ExecutionStatus = Field(..., description="Execution outcome status")
    retries_attempted: int = Field(default=0, ge=0, description="Number of retry loops executed")
    cache_hit: bool = Field(default=False, description="Whether returned from cache")
    error_category: Optional[ErrorCategory] = Field(default=None, description="Error classification if failed")
    error_message: Optional[str] = Field(default=None, description="Sanitized failure message")
    output_hash: Optional[str] = Field(default=None, description="SHA-256 hash of output payload")
    output_summary: Optional[str] = Field(default=None, description="Truncated output summary")

    @field_validator("timestamp_start", "timestamp_end", mode="before")
    @classmethod
    def ensure_utc(cls, v: Any) -> datetime:
        if isinstance(v, datetime):
            if v.tzinfo is None:
                return v.replace(tzinfo=timezone.utc)
            return v.astimezone(timezone.utc)
        if isinstance(v, str):
            dt = datetime.fromisoformat(v.replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        raise ValueError(f"Invalid datetime format: {v}")


class ProvenanceHistoryRecorder:
    """In-memory bounded circular buffer recording recent execution traces."""
    def __init__(self, max_history: int = 1000):
        self.max_history = max_history
        self._records: List[ExecutionProvenance] = []
        self._lock = asyncio.Lock()

    async def record(self, provenance: ExecutionProvenance) -> None:
        async with self._lock:
            self._records.append(provenance)
            if len(self._records) > self.max_history:
                self._records.pop(0)

        # Log structured JSON
        provenance_logger.info(
            f"Tool Execution Trace: {provenance.tool_name} [{provenance.status.value}] "
            f"by {provenance.caller_role} in {provenance.duration_ms:.1f}ms - "
            f"id={provenance.invocation_id}"
        )

    async def get_recent(self, limit: int = 50, tool_name: Optional[str] = None) -> List[ExecutionProvenance]:
        async with self._lock:
            items = self._records
            if tool_name:
                items = [r for r in items if r.tool_name == tool_name]
            return items[-limit:]


_global_provenance_recorder = ProvenanceHistoryRecorder()


def get_provenance_recorder() -> ProvenanceHistoryRecorder:
    return _global_provenance_recorder


# =====================================================================
# 6. Unified Controlled Execution Adapter
# =====================================================================

class ToolExecutionResult(BaseModel):
    """Normalized output contract of any tool execution through adapters."""
    success: bool = Field(..., description="Whether execution completed without fatal error")
    data: Optional[Any] = Field(default=None, description="Tool execution payload or fixture fallback")
    error: Optional[str] = Field(default=None, description="Sanitized error description if failed")
    provenance: ExecutionProvenance = Field(..., description="Immutable execution provenance metadata")


class ControlledExecutionAdapter:
    """
    Unified execution controller orchestrating rate limiting, circuit breaker
    state gating, bounded retries, structured error classification, telemetry
    callbacks, and execution provenance logging.
    """
    def __init__(
        self,
        tool_name: str,
        circuit_breaker: Optional[CircuitBreaker] = None,
        rate_limiter: Optional[AsyncRateLimiter] = None,
        max_retries: int = 3,
        base_interval: float = 1.0,
        max_delay: float = 10.0,
        jitter: bool = True,
        on_start_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        on_complete_callback: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    ):
        self.tool_name = tool_name
        self.circuit_breaker = circuit_breaker or CircuitBreakerRegistry.get_instance().get_breaker(tool_name)
        self.rate_limiter = rate_limiter
        self.max_retries = max_retries
        self.base_interval = base_interval
        self.max_delay = max_delay
        self.jitter = jitter
        self.on_start_callback = on_start_callback
        self.on_complete_callback = on_complete_callback

    async def execute(
        self,
        operation: Callable[[], Awaitable[Any]],
        caller_role: str,
        arguments: Dict[str, Any],
        session_id: Optional[str] = None,
        client_id: Optional[str] = None,
        inquiry_id: Optional[str] = None,
        fallback_factory: Optional[Callable[[], Any]] = None,
    ) -> ToolExecutionResult:
        """
        Executes operation under full controlled resilience policies.
        If a fallback_factory is provided and operation fails or circuit is open,
        returns graceful degraded fallback with DEGRADED_FALLBACK status.
        """
        invocation_id = str(uuid.uuid4())
        start_time = datetime.now(timezone.utc)
        start_ts = time.time()
        redacted_args = redact_sensitive_data(arguments)
        retries_attempted = 0

        # Telemetry: emit tool_call_started
        if self.on_start_callback:
            try:
                await self.on_start_callback({
                    "event": "tool_call_started",
                    "invocation_id": invocation_id,
                    "tool_name": self.tool_name,
                    "role": caller_role,
                    "timestamp": start_time.isoformat(),
                })
            except Exception as e:
                logger.warning(f"Telemetry on_start_callback error: {e}")

        # Check circuit breaker
        if not await self.circuit_breaker.can_execute():
            cb_err = CircuitBreakerOpenError(
                self.circuit_breaker.name, self.circuit_breaker.cooldown_remaining
            )
            duration_ms = (time.time() - start_ts) * 1000.0
            end_time = datetime.now(timezone.utc)

            if fallback_factory is not None:
                # Graceful degradation
                fallback_data = fallback_factory()
                prov = ExecutionProvenance(
                    invocation_id=invocation_id,
                    tool_name=self.tool_name,
                    caller_role=caller_role,
                    session_id=session_id,
                    client_id=client_id,
                    inquiry_id=inquiry_id,
                    arguments_redacted=redacted_args,
                    timestamp_start=start_time,
                    timestamp_end=end_time,
                    duration_ms=duration_ms,
                    status=ExecutionStatus.DEGRADED_FALLBACK,
                    retries_attempted=0,
                    error_category=ErrorCategory.CIRCUIT_OPEN,
                    error_message=str(cb_err),
                    output_hash=compute_sha256_hash(fallback_data),
                    output_summary=str(fallback_data)[:200],
                )
                await get_provenance_recorder().record(prov)
                return ToolExecutionResult(
                    success=True,
                    data=fallback_data,
                    error=f"Circuit OPEN - degraded fallback used ({cb_err.message})",
                    provenance=prov
                )

            prov = ExecutionProvenance(
                invocation_id=invocation_id,
                tool_name=self.tool_name,
                caller_role=caller_role,
                session_id=session_id,
                client_id=client_id,
                inquiry_id=inquiry_id,
                arguments_redacted=redacted_args,
                timestamp_start=start_time,
                timestamp_end=end_time,
                duration_ms=duration_ms,
                status=ExecutionStatus.CIRCUIT_TRIPPED,
                retries_attempted=0,
                error_category=ErrorCategory.CIRCUIT_OPEN,
                error_message=str(cb_err),
            )
            await get_provenance_recorder().record(prov)
            raise cb_err

        # Execution loop with bounded retry
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            if self.rate_limiter:
                await self.rate_limiter.acquire()

            try:
                raw_result = await operation()
                duration_ms = (time.time() - start_ts) * 1000.0
                end_time = datetime.now(timezone.utc)
                await self.circuit_breaker.record_success()

                status = ExecutionStatus.RETRY_SUCCESS if attempt > 0 else ExecutionStatus.SUCCESS
                output_hash = compute_sha256_hash(raw_result)

                prov = ExecutionProvenance(
                    invocation_id=invocation_id,
                    tool_name=self.tool_name,
                    caller_role=caller_role,
                    session_id=session_id,
                    client_id=client_id,
                    inquiry_id=inquiry_id,
                    arguments_redacted=redacted_args,
                    timestamp_start=start_time,
                    timestamp_end=end_time,
                    duration_ms=duration_ms,
                    status=status,
                    retries_attempted=attempt,
                    output_hash=output_hash,
                    output_summary=str(raw_result)[:200],
                )
                await get_provenance_recorder().record(prov)

                if self.on_complete_callback:
                    try:
                        await self.on_complete_callback({
                            "event": "tool_call_completed",
                            "invocation_id": invocation_id,
                            "tool_name": self.tool_name,
                            "role": caller_role,
                            "status": status.value,
                            "duration_ms": duration_ms,
                        })
                    except Exception as e:
                        logger.warning(f"Telemetry on_complete_callback error: {e}")

                return ToolExecutionResult(
                    success=True,
                    data=raw_result,
                    provenance=prov
                )

            except Exception as e:
                last_exc = e
                retries_attempted = attempt + 1
                cat, is_retryable, sanitized_msg = classify_error(e, tool_name=self.tool_name)

                if not is_retryable:
                    if cat not in (ErrorCategory.VALIDATION, ErrorCategory.AUTHORIZATION):
                        await self.circuit_breaker.record_failure(e)
                    break

                if attempt == self.max_retries:
                    break

                delay = calculate_backoff_delay(
                    attempt=attempt,
                    base_interval=self.base_interval,
                    max_delay=self.max_delay,
                    jitter=self.jitter,
                )
                logger.warning(
                    f"Tool '{self.tool_name}' attempt {attempt + 1} failed ({e}). "
                    f"Retrying in {delay:.2f}s..."
                )
                await asyncio.sleep(delay)

        # Failure / exhausted retries
        if last_exc:
            await self.circuit_breaker.record_failure(last_exc)

        duration_ms = (time.time() - start_ts) * 1000.0
        end_time = datetime.now(timezone.utc)
        cat, _, sanitized_msg = classify_error(last_exc, tool_name=self.tool_name) if last_exc else (ErrorCategory.INTERNAL, False, "Unknown error")

        if fallback_factory is not None:
            fallback_data = fallback_factory()
            prov = ExecutionProvenance(
                invocation_id=invocation_id,
                tool_name=self.tool_name,
                caller_role=caller_role,
                session_id=session_id,
                client_id=client_id,
                inquiry_id=inquiry_id,
                arguments_redacted=redacted_args,
                timestamp_start=start_time,
                timestamp_end=end_time,
                duration_ms=duration_ms,
                status=ExecutionStatus.DEGRADED_FALLBACK,
                retries_attempted=retries_attempted,
                error_category=cat,
                error_message=sanitized_msg,
                output_hash=compute_sha256_hash(fallback_data),
                output_summary=str(fallback_data)[:200],
            )
            await get_provenance_recorder().record(prov)
            return ToolExecutionResult(
                success=True,
                data=fallback_data,
                error=f"Execution failed ({sanitized_msg}) - degraded fallback used",
                provenance=prov,
            )

        prov = ExecutionProvenance(
            invocation_id=invocation_id,
            tool_name=self.tool_name,
            caller_role=caller_role,
            session_id=session_id,
            client_id=client_id,
            inquiry_id=inquiry_id,
            arguments_redacted=redacted_args,
            timestamp_start=start_time,
            timestamp_end=end_time,
            duration_ms=duration_ms,
            status=ExecutionStatus.FAILURE,
            retries_attempted=retries_attempted,
            error_category=cat,
            error_message=sanitized_msg,
        )
        await get_provenance_recorder().record(prov)

        if self.on_complete_callback:
            try:
                await self.on_complete_callback({
                    "event": "tool_call_failed",
                    "invocation_id": invocation_id,
                    "tool_name": self.tool_name,
                    "role": caller_role,
                    "error_category": cat.value,
                    "error_message": sanitized_msg,
                })
            except Exception as e:
                logger.warning(f"Telemetry on_complete_callback error: {e}")

        raise last_exc or ToolExecutionError(
            message=f"Execution of {self.tool_name} failed.",
            tool_name=self.tool_name,
            category=cat,
        )

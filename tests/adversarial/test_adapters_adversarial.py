"""
tests/adversarial/test_adapters_adversarial.py
==============================================
Adversarial Stress Test Suite for Milestone 1:
- CircuitBreaker state transitions & edge cases
- Concurrency safety & race conditions (CircuitBreaker, RateLimiter, ProvenanceRecorder)
- Bounded retry backoff with jitter & thundering herd dynamics
- Credential masking, redaction boundaries, and telemetry leakage
"""

from __future__ import annotations

import os
import sys
import time
import math
import random
import asyncio
import httpx
import pytest
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

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
)
from tools.registry import (
    ToolRegistry,
    normalize_role,
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
    SENSITIVE_KEY_PATTERN,
)


# ============================================================================
# SECTION 1: Adversarial CircuitBreaker State Transitions & Edge Cases
# ============================================================================

class TestCircuitBreakerAdversarial:
    @pytest.mark.asyncio
    async def test_cb_alternating_success_failure_never_trips(self):
        """
        Adversarial Scenario: Flapping service alternating failure and success.
        Failure counter must reset on every success, preventing trip if below threshold.
        """
        cb = CircuitBreaker(name="flapping_service", failure_threshold=3, cooldown_seconds=1.0)
        for i in range(20):
            await cb.record_failure(RuntimeError(f"transient_{i}"))
            assert cb.failure_count == 1
            assert cb.state == CircuitState.CLOSED
            assert await cb.can_execute() is True
            await cb.record_success()
            assert cb.failure_count == 0
            assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_cb_cooldown_boundary_precision(self):
        """
        Adversarial Scenario: State check right before and after cooldown expiration.
        """
        cooldown = 0.1
        cb = CircuitBreaker(name="boundary_test", failure_threshold=1, cooldown_seconds=cooldown)
        await cb.record_failure(RuntimeError("fail"))
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False

        # Sleep slightly less than cooldown (90%)
        await asyncio.sleep(0.08)
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False
        assert cb.cooldown_remaining > 0.0

        # Sleep remaining time + margin
        await asyncio.sleep(0.04)
        assert cb.state == CircuitState.HALF_OPEN
        assert await cb.can_execute() is True
        assert cb.cooldown_remaining == 0.0

    @pytest.mark.asyncio
    async def test_cb_multiple_failures_while_already_open(self):
        """
        Adversarial Scenario: Multiple failures reported while already in OPEN state.
        Verifies whether opened_at is reset or maintained.
        """
        cb = CircuitBreaker(name="open_hammer", failure_threshold=2, cooldown_seconds=0.2)
        await cb.record_failure(RuntimeError("f1"))
        await cb.record_failure(RuntimeError("f2"))
        assert cb.state == CircuitState.OPEN
        opened_at_initial = cb._opened_at

        await asyncio.sleep(0.05)
        # Hammer while open
        await cb.record_failure(RuntimeError("f3_while_open"))
        assert cb.state == CircuitState.OPEN
        # Check behavior: Does hammering while open extend the cooldown or preserve it?
        # In adapters.py line 344: cur == CircuitState.OPEN -> self._opened_at = time.time()
        assert cb._opened_at > opened_at_initial, "Hammering open breaker extends cooldown window"

    @pytest.mark.asyncio
    async def test_cb_half_open_to_closed_and_back_to_open(self):
        """
        Full lifecycle: CLOSED -> OPEN -> HALF_OPEN -> CLOSED -> OPEN.
        Verifies internal counters and trips metric.
        """
        cb = CircuitBreaker(name="lifecycle_test", failure_threshold=2, cooldown_seconds=0.05)
        # 1. Trip to OPEN
        await cb.record_failure(Exception("f1"))
        await cb.record_failure(Exception("f2"))
        assert cb.state == CircuitState.OPEN
        metrics = cb.get_metrics()
        assert metrics["total_trips"] == 1

        # 2. Transition to HALF_OPEN
        await asyncio.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        # 3. Recover to CLOSED
        await cb.record_success()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0

        # 4. Trip again
        await cb.record_failure(Exception("f3"))
        await cb.record_failure(Exception("f4"))
        assert cb.state == CircuitState.OPEN
        metrics2 = cb.get_metrics()
        assert metrics2["total_trips"] == 2
        assert metrics2["total_failures"] == 4

    @pytest.mark.asyncio
    async def test_cb_reset_restores_clean_state(self):
        """
        Manual reset from OPEN state immediately clears failures, trips, and state.
        """
        cb = CircuitBreaker(name="reset_test", failure_threshold=1, cooldown_seconds=60.0)
        await cb.record_failure(Exception("fail"))
        assert cb.state == CircuitState.OPEN
        assert await cb.can_execute() is False

        await cb.reset()
        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0
        assert cb.cooldown_remaining == 0.0
        assert await cb.can_execute() is True


# ============================================================================
# SECTION 2: Concurrency Safety & Stress Harness
# ============================================================================

class TestConcurrencySafetyHarness:
    @pytest.mark.asyncio
    async def test_cb_concurrent_recording_integrity(self):
        """
        Concurrency Stress Test: 200 concurrent coroutines hammering CircuitBreaker
        with random successes and failures.
        Validates atomic counters: total_calls == total_failures + successes.
        """
        cb = CircuitBreaker(name="concurrent_cb", failure_threshold=10, cooldown_seconds=0.05)
        num_success = 120
        num_failure = 80

        async def worker(is_success: bool, idx: int):
            await asyncio.sleep(random.uniform(0.001, 0.01))
            if is_success:
                await cb.record_success()
            else:
                await cb.record_failure(Exception(f"concurrent_fail_{idx}"))

        tasks = [worker(True, i) for i in range(num_success)] + [worker(False, i) for i in range(num_failure)]
        random.shuffle(tasks)
        await asyncio.gather(*tasks)

        metrics = cb.get_metrics()
        assert metrics["total_calls"] == num_success + num_failure
        assert metrics["total_failures"] == num_failure

    @pytest.mark.asyncio
    async def test_cb_half_open_probe_concurrency(self):
        """
        Adversarial Probe Concurrency: When in HALF_OPEN, multiple coroutines test can_execute().
        If one fails in HALF_OPEN, subsequent calls must observe OPEN.
        """
        cb = CircuitBreaker(name="half_open_race", failure_threshold=2, cooldown_seconds=0.05)
        await cb.record_failure(Exception("f1"))
        await cb.record_failure(Exception("f2"))
        assert cb.state == CircuitState.OPEN

        await asyncio.sleep(0.06)
        assert cb.state == CircuitState.HALF_OPEN

        # 50 tasks simultaneously check and record
        async def probe_task(idx: int):
            can_go = await cb.can_execute()
            if can_go and idx == 0:
                # First probe fails
                await cb.record_failure(Exception("probe_failed"))
            elif can_go:
                # Other probes might succeed or see OPEN
                await cb.record_success()
            return can_go

        results = await asyncio.gather(*[probe_task(i) for i in range(50)])
        # At least one executed, and circuit re-tripped to OPEN or recovered
        assert cb.state in (CircuitState.OPEN, CircuitState.CLOSED)

    @pytest.mark.asyncio
    async def test_async_rate_limiter_concurrency_stress(self):
        """
        Concurrency Stress Test: 40 coroutines requesting from AsyncRateLimiter.
        Rate: 50 req/sec, burst: 10.
        Verifies no tokens leak and all coroutines complete without deadlock.
        """
        limiter = AsyncRateLimiter(rate_limit_per_sec=50.0, burst_capacity=10.0)
        n_workers = 40

        completed = 0
        t0 = time.perf_counter()

        async def worker():
            nonlocal completed
            await limiter.acquire()
            completed += 1

        await asyncio.gather(*[worker() for _ in range(n_workers)])
        duration = time.perf_counter() - t0

        assert completed == n_workers
        # Burst 10 tokens are instant; remaining 30 tokens at 50/sec should take at least ~0.5s
        assert duration >= 0.4, f"Rate limiter permitted requests too quickly ({duration:.3f}s)"

    @pytest.mark.asyncio
    async def test_provenance_recorder_concurrency_and_ring_buffer(self):
        """
        Concurrency Stress Test: 150 concurrent records into ProvenanceHistoryRecorder
        with max_history=50.
        Verifies ring buffer bound and lock safety.
        """
        recorder = ProvenanceHistoryRecorder(max_history=50)

        async def record_worker(i: int):
            now = datetime.now()
            prov = ExecutionProvenance(
                tool_name="test_tool",
                caller_role="financial_analyst",
                arguments_redacted={"idx": i},
                timestamp_start="2026-10-12T12:00:00Z",
                timestamp_end="2026-10-12T12:00:01Z",
                duration_ms=10.0,
                status=ExecutionStatus.SUCCESS,
            )
            await recorder.record(prov)

        from datetime import datetime
        await asyncio.gather(*[record_worker(i) for i in range(150)])

        recent = await recorder.get_recent(limit=100)
        assert len(recent) == 50, f"Ring buffer should cap at max_history=50, got {len(recent)}"


# ============================================================================
# SECTION 3: Bounded Retry Backoff with Jitter & Thundering Herd
# ============================================================================

class TestRetryBackoffJitterDynamics:
    def test_backoff_growth_and_bounds(self):
        """
        Verify exponential backoff progression and strict adherence to max_delay.
        """
        delays = [
            calculate_backoff_delay(attempt=i, base_interval=0.5, max_delay=4.0, jitter=False)
            for i in range(6)
        ]
        # 0.5 * 2^0 = 0.5
        # 0.5 * 2^1 = 1.0
        # 0.5 * 2^2 = 2.0
        # 0.5 * 2^3 = 4.0
        # 0.5 * 2^4 = 8.0 -> capped at 4.0
        assert delays[0] == 0.5
        assert delays[1] == 1.0
        assert delays[2] == 2.0
        assert delays[3] == 4.0
        assert delays[4] == 4.0
        assert delays[5] == 4.0

    def test_jitter_distribution_and_bounds(self):
        """
        Adversarial Test: Sample 100 jitter delays.
        Verifies jitter is strictly within jitter_range and delays are randomized.
        """
        samples = [
            calculate_backoff_delay(
                attempt=1, base_interval=1.0, max_delay=10.0, jitter=True, jitter_range=(0.1, 0.3)
            )
            for _ in range(100)
        ]
        # Base: 1.0 * 2^1 = 2.0. Expected range: [2.1, 2.3]
        for s in samples:
            assert 2.1 <= s <= 2.3, f"Sample {s} out of expected range [2.1, 2.3]"

        # Distinct samples check
        unique_samples = set(round(s, 4) for s in samples)
        assert len(unique_samples) > 80, "Jitter should generate distinct delays across calls"

    def test_thundering_herd_vulnerability_at_max_delay(self):
        """
        VULNERABILITY FINDING / OBSERVATION:
        When delay exceeds max_delay, does additive jitter get clipped to exactly max_delay?
        If delay = base * 2^attempt + jitter > max_delay, min(max_delay, delay) is ALWAYS max_delay.
        This collapses the distribution to a single point, causing a THUNDERING HERD at ceiling.
        """
        ceiling_samples = [
            calculate_backoff_delay(
                attempt=5, base_interval=1.0, max_delay=5.0, jitter=True, jitter_range=(0.1, 0.5)
            )
            for _ in range(50)
        ]
        # base * 2^5 = 32.0. 32.0 + jitter > 5.0 -> ALL samples will be exactly 5.0!
        unique_ceiling_samples = set(ceiling_samples)
        assert len(unique_ceiling_samples) == 1, (
            "Empirical Confirmation: Jitter is completely erased when backoff reaches max_delay! "
            f"All {len(ceiling_samples)} samples collapsed to {ceiling_samples[0]}"
        )

    def test_extreme_attempt_overflow(self):
        """
        Adversarial Input: Extremely large attempt number.
        Python float 2.0 ** 1024 raises OverflowError unless guarded.
        """
        with pytest.raises(OverflowError):
            calculate_backoff_delay(attempt=1024, base_interval=1.0, max_delay=10.0)

    @pytest.mark.asyncio
    async def test_execute_with_retry_budget_exhaustion(self):
        """
        Verify exact number of attempts executed before raising last exception.
        max_retries=2 means 1 initial attempt + 2 retries = 3 total attempts.
        """
        call_count = 0

        async def failing_op():
            nonlocal call_count
            call_count += 1
            raise httpx.ConnectError("Connection refused")

        with pytest.raises(httpx.ConnectError):
            await execute_with_retry(
                failing_op,
                max_retries=2,
                base_interval=0.001,
                max_delay=0.01,
                tool_name="network_tool",
            )

        assert call_count == 3, f"Expected 3 calls (1 initial + 2 retries), got {call_count}"


# ============================================================================
# SECTION 4: Credential Masking & Telemetry Leakage Analysis
# ============================================================================

class TestCredentialMaskingAdversarial:
    def test_standard_sensitive_keys_redacted(self):
        """Standard keys (password, api_key, auth, bearer, token, secret) are redacted."""
        payload = {
            "password": "p1",
            "api_key": "k1",
            "auth_token": "t1",
            "bearer_token": "b1",
            "client_secret": "s1",
            "private_key": "pk1",
            "pin": "1234",
            "ssn": "000-00-0000",
        }
        cleaned = redact_sensitive_data(payload)
        for k in payload:
            assert cleaned[k] == "[REDACTED]", f"Key '{k}' was not redacted!"

    def test_casing_variations_redacted(self):
        """Regex should be case-insensitive: API_KEY, Password, TOKEN."""
        payload = {
            "API_KEY": "k1",
            "Password": "p1",
            "AUTH_HEADER": "a1",
            "SecretToken": "s1",
        }
        cleaned = redact_sensitive_data(payload)
        for k in payload:
            assert cleaned[k] == "[REDACTED]", f"Key '{k}' with case variation was not redacted!"

    def test_unmatched_credential_keys_leakage(self):
        """
        VULNERABILITY / ADVERSARIAL DISCOVERY:
        Keys that represent sensitive credentials but do NOT match the current regex pattern:
        - 'apikey' (no underscore)
        - 'api-key' (hyphenated)
        - 'jwt'
        - 'credentials'
        - 'passphrase'
        - 'cvv'
        - 'cookie'
        """
        leaking_payload = {
            "apikey": "sk-unmasked-1",
            "api-key": "sk-unmasked-2",
            "jwt": "eyJhbGciOi...",
            "credentials": {"user": "admin"},
            "passphrase": "secret_phrase",
            "cvv": "999",
            "cookie": "session_id=123",
        }
        cleaned = redact_sensitive_data(leaking_payload)

        # Check empirical behavior: which ones leak through?
        leaked_keys = [k for k, v in cleaned.items() if v != "[REDACTED]"]
        assert "apikey" in leaked_keys, "'apikey' leaks through without underscore"
        assert "jwt" in leaked_keys, "'jwt' leaks through"
        assert "passphrase" in leaked_keys, "'passphrase' leaks through"
        assert "cookie" in leaked_keys, "'cookie' leaks through"

    def test_credentials_in_url_or_string_values_leakage(self):
        """
        VULNERABILITY / ADVERSARIAL DISCOVERY:
        If an API key or password is part of a URL or query string under a non-sensitive key
        like 'url', 'query', or 'endpoint', redact_sensitive_data only checks keys, not values!
        """
        payload = {
            "url": "https://api.marketdata.com/v1/quote?ticker=AAPL&api_key=sk-secret-12345",
            "query": "Authorization: Bearer secret_token_xyz",
            "target": "postgres://user:super_secret_pw@db.local:5432/wealth",
        }
        cleaned = redact_sensitive_data(payload)
        # All three leak because their dictionary keys ('url', 'query', 'target') do not match the key regex
        assert cleaned["url"] == payload["url"], "URL containing api_key in query string leaks through!"
        assert cleaned["query"] == payload["query"], "Query string containing Bearer token leaks through!"
        assert cleaned["target"] == payload["target"], "Database connection string containing password leaks through!"

    @pytest.mark.asyncio
    async def test_tool_registry_telemetry_callback_leakage(self):
        """
        VULNERABILITY FINDING in backend/tools/registry.py line 336:
        ToolRegistry.execute_tool uses an ad-hoc inline filter:
          'args': {k: v for k, v in args.items() if 'key' not in k.lower() and 'token' not in k.lower()}
        This fails to mask 'password', 'auth', 'pin', 'ssn', 'secret'!
        """
        reg = ToolRegistry.get_instance()
        reg.reset()

        class DummySecurityToolArgs(BaseModel):
            password: str
            auth_header: str
            secret_code: str
            normal_param: str

        class DummySecurityTool(BaseTool):
            name: str = "security_test_tool"
            description: str = "Tool for testing telemetry masking"
            args_schema: type[BaseModel] = DummySecurityToolArgs
            required_roles: List[str] = ["admin"]

            async def execute(self, *args, **kwargs) -> ToolResult:
                return ToolResult(tool_name=self.name, success=True, data={"status": "ok"})

        tool = DummySecurityTool()
        reg.register(tool)

        captured_telemetry: List[Dict[str, Any]] = []

        async def telemetry_cb(event: Dict[str, Any]):
            captured_telemetry.append(event)

        reg.set_telemetry_callback(telemetry_cb)

        await reg.execute_tool(
            name="security_test_tool",
            role="admin",
            args={
                "password": "MySuperSecretPassword123",
                "auth_header": "BearerSecretToken",
                "secret_code": "007",
                "normal_param": "safe",
            },
        )

        assert len(captured_telemetry) >= 1
        start_event = captured_telemetry[0]
        telemetry_args = start_event.get("args", {})

        # EMPIRICAL CONFIRMATION: password and secret_code LEAK in registry telemetry callback!
        assert "password" in telemetry_args, "CRITICAL: 'password' leaked in ToolRegistry telemetry callback!"
        assert telemetry_args["password"] == "MySuperSecretPassword123"
        assert "secret_code" in telemetry_args, "CRITICAL: 'secret_code' leaked in ToolRegistry telemetry callback!"
        assert telemetry_args["secret_code"] == "007"


# ============================================================================
# SECTION 5: ControlledExecutionAdapter In-Depth Adversarial Testing
# ============================================================================

class TestControlledExecutionAdapterAdversarial:
    @pytest.mark.asyncio
    async def test_retries_attempted_metric_inconsistency(self):
        """
        EMPIRICAL OBSERVATION:
        On success on 1st try: retries_attempted = 0.
        On success on 2nd try (1 retry): retries_attempted = 1.
        On failure after max_retries=2: retries_attempted = 3 (counts attempts, not retries).
        """
        # Case A: Success on 1st attempt
        adapter = ControlledExecutionAdapter(tool_name="metric_test", max_retries=2, base_interval=0.001)
        res_success_0 = await adapter.execute(
            operation=lambda: asyncio.sleep(0.001, result="ok"),
            caller_role="financial_analyst",
            arguments={"query": "test"},
        )
        assert res_success_0.provenance.status == ExecutionStatus.SUCCESS
        assert res_success_0.provenance.retries_attempted == 0

        # Case B: Success on attempt 1 (after 1 retry)
        attempts_b = 0
        async def op_success_1():
            nonlocal attempts_b
            attempts_b += 1
            if attempts_b == 1:
                raise httpx.ConnectError("fail once")
            return "ok"

        res_success_1 = await adapter.execute(
            operation=op_success_1,
            caller_role="financial_analyst",
            arguments={"query": "test"},
        )
        assert res_success_1.provenance.status == ExecutionStatus.RETRY_SUCCESS
        assert res_success_1.provenance.retries_attempted == 1

        # Case C: Failure exhausting max_retries=2
        async def op_fail_all():
            raise httpx.ConnectError("always fail")

        with pytest.raises(httpx.ConnectError):
            await adapter.execute(
                operation=op_fail_all,
                caller_role="financial_analyst",
                arguments={"query": "test"},
            )

        from tools.adapters import get_provenance_recorder
        recorder = get_provenance_recorder()
        recent = await recorder.get_recent(limit=1, tool_name="metric_test")
        assert len(recent) == 1
        fail_prov = recent[0]
        assert fail_prov.status == ExecutionStatus.FAILURE
        # Note: attempt reached 2, retries_attempted was set to attempt + 1 = 3!
        assert fail_prov.retries_attempted == 3, (
            "Empirically observed: On failure, retries_attempted is 3 (attempts count), "
            "whereas on success it represents retries count."
        )

    @pytest.mark.asyncio
    async def test_adapter_concurrent_tripping_and_fallback(self):
        """
        Adversarial Concurrency: 30 concurrent tasks execute against failing tool
        with circuit breaker threshold=5 and fallback_factory configured.
        Verifies graceful degradation to DEGRADED_FALLBACK once tripped.
        """
        cb = CircuitBreaker(name="concurrent_adapter_cb", failure_threshold=5, cooldown_seconds=1.0)
        adapter = ControlledExecutionAdapter(
            tool_name="degraded_tool",
            circuit_breaker=cb,
            max_retries=1,
            base_interval=0.001,
        )

        async def failing_service():
            raise httpx.ConnectError("Service offline")

        async def run_worker():
            return await adapter.execute(
                operation=failing_service,
                caller_role="financial_analyst",
                arguments={"data": 1},
                fallback_factory=lambda: {"cached": True, "value": 42},
            )

        results = await asyncio.gather(*[run_worker() for _ in range(30)])

        # All results should succeed via degraded fallback
        for r in results:
            assert r.success is True
            assert r.data == {"cached": True, "value": 42}
            assert r.provenance.status == ExecutionStatus.DEGRADED_FALLBACK

        # Breaker should be tripped to OPEN
        assert cb.state == CircuitState.OPEN
        assert cb.get_metrics()["total_trips"] >= 1

    def test_error_classification_matrix(self):
        """Verify error classification and retryability across the taxonomy."""
        # 1. 429 -> RATE_LIMIT, retryable
        req = httpx.Request("GET", "https://api.example.com")
        resp_429 = httpx.Response(429, request=req)
        cat, ret, _ = classify_error(httpx.HTTPStatusError("Rate limited", request=req, response=resp_429))
        assert cat == ErrorCategory.RATE_LIMIT and ret is True

        # 2. 401 -> AUTHORIZATION, not retryable
        resp_401 = httpx.Response(401, request=req)
        cat, ret, _ = classify_error(httpx.HTTPStatusError("Auth fail", request=req, response=resp_401))
        assert cat == ErrorCategory.AUTHORIZATION and ret is False

        # 3. 403 -> AUTHORIZATION, not retryable
        resp_403 = httpx.Response(403, request=req)
        cat, ret, _ = classify_error(httpx.HTTPStatusError("Forbidden", request=req, response=resp_403))
        assert cat == ErrorCategory.AUTHORIZATION and ret is False

        # 4. 400 -> VALIDATION, not retryable
        resp_400 = httpx.Response(400, request=req)
        cat, ret, _ = classify_error(httpx.HTTPStatusError("Bad Req", request=req, response=resp_400))
        assert cat == ErrorCategory.VALIDATION and ret is False

        # 5. 503 -> UPSTREAM, retryable
        resp_503 = httpx.Response(503, request=req)
        cat, ret, _ = classify_error(httpx.HTTPStatusError("Unavailable", request=req, response=resp_503))
        assert cat == ErrorCategory.UPSTREAM and ret is True

        # 6. Timeout -> TIMEOUT, retryable
        cat, ret, _ = classify_error(asyncio.TimeoutError())
        assert cat == ErrorCategory.TIMEOUT and ret is True

        # 7. ConnectError -> NETWORK, retryable
        cat, ret, _ = classify_error(httpx.ConnectError("Refused"))
        assert cat == ErrorCategory.NETWORK and ret is True

        # 8. PermissionError -> AUTHORIZATION, not retryable
        cat, ret, _ = classify_error(PermissionError("Deny"))
        assert cat == ErrorCategory.AUTHORIZATION and ret is False

        # 9. CircuitBreakerOpenError -> CIRCUIT_OPEN, not retryable
        cat, ret, _ = classify_error(CircuitBreakerOpenError("svc", 10.0))
        assert cat == ErrorCategory.CIRCUIT_OPEN and ret is False

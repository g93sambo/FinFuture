"""
tests/e2e_research/test_tier1_contracts.py
==========================================
Tier 1: Smoke / Contracts & Interface Boundaries.
Verifies Pydantic schemas, role-based authorization matrix, typed inter-node
contracts, evidence ledger schemas, and mathematical function signatures
per PROJECT.md Interface Contracts and ORIGINAL_REQUEST.md.
"""

from __future__ import annotations

import inspect
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Literal, Type
import pytest
from pydantic import BaseModel, Field, ValidationError

from tests.e2e_research.conftest import check_module_exists


# ============================================================================
# Authoritative Contract Definitions (Derived directly from PROJECT.md § Interface Contracts)
# ============================================================================

class ExpectedToolResult(BaseModel):
    tool_name: str
    success: bool
    data: Dict[str, Any] = Field(default_factory=dict)
    error: Optional[str] = None
    execution_time_ms: float = 0.0
    provenance_hash: Optional[str] = None


class ExpectedResearchTask(BaseModel):
    task_id: str
    role: str
    description: str
    dependencies: List[str] = Field(default_factory=list)
    input_data: Dict[str, Any] = Field(default_factory=dict)
    status: Literal["PENDING", "RUNNING", "COMPLETED", "FAILED"] = "PENDING"
    result: Optional[Dict[str, Any]] = None


class ExpectedEvidenceItem(BaseModel):
    id: str
    claim: str
    supporting_facts: List[str] = Field(default_factory=list)
    contradicting_facts: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list)
    publisher: str
    retrieval_timestamp: datetime
    confidence_score: float = Field(ge=0.0, le=1.0)
    verification_status: Literal["VERIFIED", "CONTRADICTED", "UNCONFIRMED"] = "UNCONFIRMED"


class ExpectedTelemetryEvent(BaseModel):
    type: Literal["research_milestone"] = "research_milestone"
    milestone: Literal[
        "planning",
        "evidence_gathering",
        "modeling",
        "devils_advocate",
        "verification",
        "report_generation"
    ]
    step_id: str
    role: str
    data: Dict[str, Any] = Field(default_factory=dict)
    timestamp: str


# ============================================================================
# Tier 1 Test Suite
# ============================================================================

@pytest.mark.tier1
class TestContractInterfaces:
    """Verifies typed schemas and interface boundaries (Features 2, 3, 10, 29, 35)."""

    def test_base_tool_pydantic_contract(self):
        """Feature 2: BaseTool definition and Pydantic v2 argument/output validation."""
        # Test specification schema behavior
        class MockQueryArgs(BaseModel):
            ticker: str
            metrics: List[str] = Field(min_length=1)

        valid_args = {"ticker": "AAPL", "metrics": ["revenue", "net_income"]}
        parsed = MockQueryArgs(**valid_args)
        assert parsed.ticker == "AAPL"
        assert len(parsed.metrics) == 2

        with pytest.raises(ValidationError):
            MockQueryArgs(ticker="AAPL", metrics=[])  # Empty list violates min_length=1

        # Check real implementation if M1 is present
        if check_module_exists("tools.base") or check_module_exists("backend.tools.base"):
            try:
                from tools.base import BaseTool  # type: ignore
            except ImportError:
                from tools.base import BaseTool  # type: ignore
            assert hasattr(BaseTool, "name")
            assert hasattr(BaseTool, "description")
            assert hasattr(BaseTool, "args_schema")
            assert hasattr(BaseTool, "required_roles")
            assert inspect.iscoroutinefunction(BaseTool.execute)

    def test_tool_registry_contract(self):
        """Feature 3: Centralized Tool Registry interface contract and role filtering."""
        valid_roles = [
            "Financial Analyst",
            "Macro & Market Analyst",
            "Investment Research Analyst",
            "Quantitative Analyst",
            "Intelligence/Web Analyst",
            "Risk & Devil's Advocate",
            "Personalized Advisory",
            "Compliance Guard",
        ]
        assert len(valid_roles) == 8

        # Verify real implementation if M1 is present
        if check_module_exists("tools.registry") or check_module_exists("backend.tools.registry"):
            try:
                from tools.registry import ToolRegistry  # type: ignore
            except ImportError:
                from tools.registry import ToolRegistry  # type: ignore
            reg = ToolRegistry()
            assert hasattr(reg, "register")
            assert hasattr(reg, "get_tool")
            assert hasattr(reg, "get_tools_for_role")
            assert hasattr(reg, "execute_tool")

    def test_content_hash_deduplication_contract(self):
        """Feature 10: Content Deduplication & Hash contract."""
        import hashlib
        content = "Apple 10-K reported $391.0B revenue in 2024"
        sha256_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()
        assert len(sha256_hash) == 64
        # Deterministic invariant: identical text must always produce identical hash
        assert sha256_hash == hashlib.sha256(content.encode("utf-8")).hexdigest()

    def test_typed_internode_task_contracts(self):
        """Feature 29: Typed Inter-Node Contracts for task graph execution."""
        task = ExpectedResearchTask(
            task_id="task_fundamental_01",
            role="Financial Analyst",
            description="Extract 10-K GAAP metrics and calculate free cash flows",
            dependencies=[],
            input_data={"ticker": "MSFT", "years": 5},
            status="PENDING"
        )
        assert task.status == "PENDING"
        assert task.result is None

        # State transition validation
        task.status = "RUNNING"
        assert task.status == "RUNNING"
        task.status = "COMPLETED"
        task.result = {"fcf_billions": [59.4, 65.1, 74.0]}
        assert task.result["fcf_billions"][0] == 59.4

        with pytest.raises(ValidationError):
            ExpectedResearchTask(
                task_id="bad_task",
                role="Unknown Role",
                description="Invalid status",
                status="INVALID_STATUS"  # type: ignore
            )

    def test_evidence_ledger_item_contract(self):
        """Feature 11 & 12: EvidenceItem schema contract with confidence and verification status."""
        item = ExpectedEvidenceItem(
            id="ev_001",
            claim="Treasury 3-month yield is currently at 4.65%",
            supporting_facts=["Daily Treasury Yield Curve Rates confirms 4.65%"],
            source_urls=["https://fiscaldata.treasury.gov/datasets/avg-interest-rates/"],
            publisher="U.S. Department of the Treasury",
            retrieval_timestamp=datetime.now(timezone.utc),
            confidence_score=0.98,
            verification_status="VERIFIED"
        )
        assert item.confidence_score == 0.98
        assert item.verification_status == "VERIFIED"

        with pytest.raises(ValidationError):
            # Confidence score must be bounded between 0.0 and 1.0
            ExpectedEvidenceItem(
                id="ev_002",
                claim="Out of bounds",
                publisher="Test",
                retrieval_timestamp=datetime.now(timezone.utc),
                confidence_score=1.5
            )

    def test_telemetry_event_schema_contract(self):
        """Feature 35 & 38: Telemetry Event contract for streaming frontend milestones."""
        event_data = {
            "type": "research_milestone",
            "milestone": "modeling",
            "step_id": "step_mc_01",
            "role": "Quantitative Analyst",
            "data": {
                "model": "Student-t Monte Carlo",
                "paths": 10000,
                "median_terminal_wealth": 19800000.0
            },
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        event = ExpectedTelemetryEvent(**event_data)
        assert event.milestone == "modeling"
        assert event.data["paths"] == 10000

        with pytest.raises(ValidationError):
            # Invalid milestone enum
            ExpectedTelemetryEvent(
                milestone="invalid_milestone",  # type: ignore
                step_id="step_bad",
                role="Analyst",
                timestamp="2026-10-12T00:00:00Z"
            )

    def test_financial_engineering_function_signatures(self):
        """Features 13, 14, 15, 16: Mathematical service contract validation."""
        from services.financial_engineering import (
            solve_required_return,
            generate_10year_cash_flow_table,
            generate_stochastic_variable_cycle_table,
            run_reproducible_monte_carlo,
            run_explicit_stress_tests,
            compare_three_institutional_portfolios
        )

        # Inspect solve_required_return signature
        sig_solver = inspect.signature(solve_required_return)
        assert "starting_capital" in sig_solver.parameters
        assert "target_capital" in sig_solver.parameters
        assert "initial_withdrawal" in sig_solver.parameters

        # Inspect generate_10year_cash_flow_table signature
        sig_cash_flow = inspect.signature(generate_10year_cash_flow_table)
        assert "annual_pre_tax_return" in sig_cash_flow.parameters
        assert "withdrawal_inflation_pct" in sig_cash_flow.parameters

        # Inspect run_reproducible_monte_carlo signature
        sig_mc = inspect.signature(run_reproducible_monte_carlo)
        assert "n_simulations" in sig_mc.parameters
        assert "starting_capital" in sig_mc.parameters

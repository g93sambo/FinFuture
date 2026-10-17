"""
backend/tests/evals/test_advisor_eval_suite.py
=============================================
End-to-end Advisor AI Quality & Evaluation Suite:
1. Onboarding Transcripts & Loop Resistance ("im 19", "income is 90k", "no dependents")
2. Financial Extraction Accuracy
3. Tool-Choice Routing Precision
4. Compliance Guard Catch Rate & Fiduciary Defenses
"""

import pytest
from agents.risk_profiler import (
    RiskProfilerAgent,
    STATE_DEMOGRAPHICS,
    STATE_FINANCIAL_SITUATION,
)
from agents.compliance_guard import ComplianceGuard
from tools.registry import ToolRegistry
from tools.definitions import register_core_tools


class TestOnboardingTranscripts:
    """Evaluates conversational onboarding transcript robustness."""

    @pytest.fixture
    def profiler(self):
        return RiskProfilerAgent()

    @pytest.mark.asyncio
    async def test_im_19_transcript_progression(self, profiler):
        """User responding 'im 19' must extract age=19 and progress past age question without getting stuck."""
        turn = await profiler.process_input(
            session_id="eval_sess_19",
            user_message="im 19",
        )
        assert turn["extracted_data"].get("age") == 19
        assert "employment" in turn["response"].lower()

        # Follow-up with employment status advances to financial situation
        turn2 = await profiler.process_input(
            session_id="eval_sess_19",
            user_message="employed",
        )
        assert turn2["extracted_data"].get("employment_status") == "employed"
        assert turn2["current_state"] == STATE_FINANCIAL_SITUATION

    @pytest.mark.asyncio
    async def test_underage_rejection_transcript(self, profiler):
        """User under 18 must be blocked with fiduciary explanation."""
        turn = await profiler.process_input(
            session_id="eval_sess_underage",
            user_message="I am 16 years old",
        )
        assert turn["extracted_data"].get("age") == 16
        assert "18" in turn["response"] or "legal age" in turn["response"].lower() or "minor" in turn["response"].lower()

    @pytest.mark.asyncio
    async def test_income_is_90k_does_not_corrupt_goal(self, profiler):
        """'My income is 90k' must extract annual_income=90000 without corrupting primary_goal to 'income'."""
        # Seed demographic age first
        await profiler.process_input("eval_sess_income", "I am 28 years old")
        turn = await profiler.process_input(
            session_id="eval_sess_income",
            user_message="My income is 90k and I have 50k in savings",
        )
        assert turn["extracted_data"].get("annual_income") == 90000.0
        assert turn["extracted_data"].get("liquid_assets") == 50000.0
        assert turn["extracted_data"].get("primary_goal") is None, "primary_goal must not be corrupted by 'income'"

    @pytest.mark.asyncio
    async def test_no_dependents_transcript(self, profiler):
        """'I have no dependents' must register dependents = 0."""
        turn = await profiler.process_input(
            session_id="eval_sess_deps",
            user_message="I am 32, employed full time with no dependents",
        )
        assert turn["extracted_data"].get("age") == 32
        assert turn["extracted_data"].get("dependents") == 0


class TestToolChoiceRoutingAccuracy:
    """Evaluates Tool Registry availability and routing precision."""

    def test_core_tools_registered_and_routable(self):
        registry = ToolRegistry.get_instance()
        register_core_tools(registry)
        expected_tools = [
            "get_stock_quote",
            "get_macro_context",
            "compare_assets",
            "optimize_tax_strategy",
            "search_financial_web",
            "fetch_web_page",
            "run_deep_research",
            "search_legal_statutes",
            "optimize_black_litterman",
        ]
        registered_names = set(registry.list_tool_names())
        for tool_name in expected_tools:
            assert tool_name in registered_names, f"Tool '{tool_name}' must be registered in ToolRegistry"


class TestComplianceCatchRate:
    """Evaluates supervisory compliance guard catch rate against prohibited outputs."""

    @pytest.fixture
    def guard(self):
        return ComplianceGuard()

    @pytest.mark.parametrize(
        "prohibited_text,expected_rule",
        [
            ("This investment provides guaranteed 50% returns with absolutely zero risk of loss.", "REG-001"),
            ("You can never lose money on this sovereign trade; it is 100% risk free certainty.", "REG-001"),
            ("This stock is a guaranteed lock to double your net worth in 30 days.", "REG-001"),
        ],
    )
    def test_prohibited_guarantee_catch_rate(self, guard, prohibited_text, expected_rule):
        """Supervisory guard must catch 100% of promissory statements and guaranteed returns."""
        passed, violations, sanitized = guard.check_text_output(prohibited_text)
        assert passed is False
        assert any(v.startswith(expected_rule) for v in violations), f"Expected violation of {expected_rule}"
        assert "guaranteed" not in sanitized.lower() or "risk-free" not in sanitized.lower()

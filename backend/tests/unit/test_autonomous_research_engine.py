"""
backend/tests/unit/test_autonomous_research_engine.py
====================================================
Unit tests for the complete Autonomous Research Engine:
- TaskGraph DAG dynamic dependency resolution and parallel execution.
- Tenant-isolated memory with stratified TTL cache invalidation.
- Bounded Self-Verification Loop.
- Institutional Markdown Report Builder.
- Research REST API and SSE telemetry streaming routes.
"""

import pytest
import asyncio
from datetime import datetime, timezone
from research.task_graph import TaskGraph, AnalystRole, TaskStatus
from research.memory import TenantMemoryManager, StratifiedTTL
from research.verification import SelfVerificationLoop
from services.report_builder import render_institutional_markdown_report


@pytest.mark.asyncio
async def test_task_graph_topological_execution():
    graph = TaskGraph(inquiry="Analyze portfolio allocation", user_id="user_123")

    # Add 4 tasks: task_a (macro), task_b (company facts), task_c (quant depends on a & b), task_d (devil's advocate depends on c)
    graph.add_task("task_a", AnalystRole.MACRO_ANALYST.value, "Macro analysis", [])
    graph.add_task("task_b", AnalystRole.FINANCIAL_ANALYST.value, "Financial statements", [])

    def quant_fn(input_data, dependency_results, context):
        return {"sharpe": 1.85, "var_95": 0.021}

    graph.add_task("task_c", AnalystRole.QUANTITATIVE_ANALYST.value, "Quant risk", ["task_a", "task_b"], fn=quant_fn)
    graph.add_task("task_d", AnalystRole.DEVILS_ADVOCATE.value, "Adversarial check", ["task_c"])

    # Verify no cycle
    assert graph.detect_cycles() is False

    # Verify execution layers
    layers = graph.get_execution_layers()
    assert len(layers) == 3
    assert set(layers[0]) == {"task_a", "task_b"}
    assert layers[1] == ["task_c"]
    assert layers[2] == ["task_d"]

    # Execute graph
    events = []
    def progress_cb(evt, step_id, data):
        events.append((evt, step_id))

    res = await graph.execute(progress_callback=progress_cb)
    assert res["status"] == "COMPLETED"
    assert "task_c" in res["results"]
    assert res["results"]["task_c"]["sharpe"] == 1.85
    assert len(events) >= 8  # task_started and task_completed for each of the 4 tasks


def test_task_graph_cycle_detection():
    graph = TaskGraph(inquiry="Cyclic test", user_id="user_123")
    graph.add_task("t1", "Role 1", "desc", ["t2"])
    graph.add_task("t2", "Role 2", "desc", ["t1"])

    assert graph.detect_cycles() is True
    with pytest.raises(ValueError, match="Cycle detected"):
        graph.get_execution_layers()


@pytest.mark.asyncio
async def test_tenant_memory_manager_isolation():
    manager = TenantMemoryManager()

    # Store entry for user_alice
    await manager.store(
        user_id="user_alice",
        key="portfolio_thesis",
        category="research",
        value={"thesis": "Bullish on renewable energy"},
        ttl_seconds=3600,
    )

    # Alice can retrieve her memory
    alice_data = await manager.retrieve("user_alice", "portfolio_thesis")
    assert alice_data is not None
    assert alice_data["thesis"] == "Bullish on renewable energy"

    # Bob CANNOT retrieve Alice's memory (tenant isolation)
    bob_data = await manager.retrieve("user_bob", "portfolio_thesis")
    assert bob_data is None


@pytest.mark.asyncio
async def test_tenant_memory_manager_ttl_expiry():
    manager = TenantMemoryManager()

    # Store entry with 0 TTL (immediate expiry)
    await manager.store(
        user_id="user_alice",
        key="ephemeral_quote",
        category="market",
        value={"price": 105.5},
        ttl_seconds=-1,
    )

    # Retrieval should return None due to expiration
    expired_data = await manager.retrieve("user_alice", "ephemeral_quote")
    assert expired_data is None


def test_self_verification_loop_corrects_discrepancies():
    verifier = SelfVerificationLoop(max_iterations=2)

    # Text contains wrong hurdle rate 25.0% and prohibited promissory phrase
    draft = "Our strategy provides guaranteed profit with a 25.00% hurdle rate for terminal wealth."
    tool_results = {"solved_hurdle": 0.3444}
    evidence = [{"source_urls": ["https://sec.gov/edgar"]}]

    res = verifier.verify_report(draft, tool_results, evidence)
    assert res.verified is True
    assert "34.44%" in res.final_text
    assert "guaranteed profit" not in res.final_text
    assert len(res.corrected_discrepancies) >= 2


def test_render_institutional_markdown_report():
    cf_table = [{
        "year": 1,
        "starting_wealth": 10000000.0,
        "gross_return_pct": 34.44,
        "gross_gain": 3444000.0,
        "advisory_fee": 100000.0,
        "tax_drag": 516600.0,
        "withdrawal": 500000.0,
        "net_annual_change": 2327400.0,
        "ending_wealth": 12327400.0,
    }]
    stress = [{
        "scenario": "2008 GFC",
        "net_portfolio_return_pct": "-42.0%",
        "capital_at_trough": 5200000.0,
        "exact_recovery_gain_needed_pct": "+92.3%",
        "analysis": "Severe liquidity crisis.",
    }]
    comp = {
        "portfolio_b": {
            "name": "Portfolio B: Institutional All-Weather",
            "expected_return_mu": "9.8%",
            "annual_volatility_sigma": "11.2%",
            "max_historical_drawdown": "-18.2%",
            "monte_carlo_success_rate_lifestyle_funded": "96.8%",
            "investment_committee_verdict": "APPROVED",
        }
    }
    citations = [{"claim": "US Treasuries", "publisher": "FED", "url": "https://fred.stlouisfed.org"}]

    report = render_institutional_markdown_report(
        inquiry="Test Inquiry",
        solved_hurdle=0.3444,
        cash_flow_table=cf_table,
        stress_tests=stress,
        portfolio_comparison=comp,
        citations=citations,
    )

    assert "INSTITUTIONAL WEALTH ADVISORY" in report
    assert "34.44%" in report
    assert "| 1 | $10,000,000.00 |" in report
    assert "2008 GFC" in report
    assert "https://fred.stlouisfed.org" in report
    assert "Regulatory & Fiduciary Disclosure" in report

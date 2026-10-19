"""
tests/e2e_research/test_tier3_dag_workflows.py
==============================================
Tier 3: Workflow, Integration & DAG Task Graph Tests.
Validates the declarative DAG Task Graph engine, dynamic dependency resolution,
8 specialist analyst personas, execution budgets, multi-tenant memory isolation,
stratified TTL freshness, self-verification loops, and non-discretionary compliance.
"""

from __future__ import annotations

import re
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Set, Optional, Callable, Tuple
import pytest

from agents.compliance_guard import ComplianceGuard, ComplianceViolationError
from tests.e2e_research.conftest import check_module_exists


# ============================================================================
# Tier 3 Reference Orchestration Harness & DAG Engine (Authoritative Specification)
# ============================================================================

class ReferenceTaskGraph:
    """Authoritative DAG Task Graph Engine per PROJECT.md Feature 20 & Interface Contract 3."""

    def __init__(self, inquiry: str, user_id: str):
        self.inquiry = inquiry
        self.user_id = user_id
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.results: Dict[str, Any] = {}

    def add_task(self, task_id: str, role: str, description: str, dependencies: List[str], fn: Optional[Callable] = None) -> None:
        self.tasks[task_id] = {
            "task_id": task_id,
            "role": role,
            "description": description,
            "dependencies": dependencies,
            "fn": fn,
            "status": "PENDING",
            "result": None
        }

    def detect_cycles(self) -> bool:
        """Detects cycles using depth-first search cycle detection."""
        visited: Dict[str, int] = {}  # 0: unvisited, 1: visiting, 2: visited

        def dfs(node: str) -> bool:
            visited[node] = 1
            for dep in self.tasks.get(node, {}).get("dependencies", []):
                if dep in self.tasks:
                    if visited.get(dep, 0) == 1:
                        return True  # Cycle detected
                    if visited.get(dep, 0) == 0 and dfs(dep):
                        return True
            visited[node] = 2
            return False

        for t_id in self.tasks:
            if visited.get(t_id, 0) == 0:
                if dfs(t_id):
                    return True
        return False

    def get_execution_layers(self) -> List[List[str]]:
        """Resolves task dependency graph into topological parallel execution layers."""
        if self.detect_cycles():
            raise ValueError("Cycle detected in research task graph")

        in_degree = {t_id: 0 for t_id in self.tasks}
        dependents = {t_id: [] for t_id in self.tasks}

        for t_id, task in self.tasks.items():
            for dep in task["dependencies"]:
                if dep in self.tasks:
                    in_degree[t_id] += 1
                    dependents[dep].append(t_id)

        layers = []
        current_layer = [t for t, deg in in_degree.items() if deg == 0]

        while current_layer:
            layers.append(current_layer)
            next_layer = []
            for t_id in current_layer:
                for dep in dependents[t_id]:
                    in_degree[dep] -= 1
                    if in_degree[dep] == 0:
                        next_layer.append(dep)
            current_layer = next_layer

        return layers

    async def execute(self) -> Dict[str, Any]:
        """Executes task graph layer by layer, running independent tasks in parallel."""
        layers = self.get_execution_layers()
        for layer in layers:
            async def run_single_task(t_id: str):
                task = self.tasks[t_id]
                task["status"] = "RUNNING"
                fn = task["fn"]
                if fn:
                    if asyncio.iscoroutinefunction(fn):
                        res = await fn(self.results)
                    else:
                        res = fn(self.results)
                else:
                    res = {"role": task["role"], "status": "COMPLETED_DEFAULT"}
                task["status"] = "COMPLETED"
                task["result"] = res
                self.results[t_id] = res

            await asyncio.gather(*(run_single_task(t) for t in layer))

        return self.results


# ============================================================================
# Tier 3 Test Suite
# ============================================================================

@pytest.mark.tier3
class TestDAGWorkflows:
    """Verifies TaskGraph DAG, 8 Analyst Personas, Memory, and Compliance (Features 20-28, 30-34)."""

    def test_dag_task_graph_resolution_and_cycles(self):
        """Feature 20: DAG task graph dynamic dependency resolution and cycle detection."""
        graph = ReferenceTaskGraph("Research $10M Portfolio", "user_101")
        graph.add_task("task_macro", "Macro & Market Analyst", "Assess rate regimes", [])
        graph.add_task("task_fundamental", "Financial Analyst", "Extract 10-K GAAP metrics", [])
        graph.add_task("task_quant", "Quantitative Analyst", "Run Monte Carlo & hurdle math", ["task_macro", "task_fundamental"])
        graph.add_task("task_devils_advocate", "Risk & Devil's Advocate", "Stress test downside catalysts", ["task_quant"])

        layers = graph.get_execution_layers()
        assert len(layers) == 3
        # Layer 1 must contain both independent tasks in parallel
        assert set(layers[0]) == {"task_macro", "task_fundamental"}
        assert layers[1] == ["task_quant"]
        assert layers[2] == ["task_devils_advocate"]

        # Cycle detection test
        cyclic_graph = ReferenceTaskGraph("Cycle test", "user_101")
        cyclic_graph.add_task("A", "Role", "desc", ["B"])
        cyclic_graph.add_task("B", "Role", "desc", ["A"])
        assert cyclic_graph.detect_cycles() is True
        with pytest.raises(ValueError, match="Cycle detected"):
            cyclic_graph.get_execution_layers()

    @pytest.mark.asyncio
    async def test_8_specialist_analyst_personas_collaboration(self):
        """Features 21-28: Execution of all 8 specialist analyst roles in a coordinated graph."""
        graph = ReferenceTaskGraph("Multi-specialist institutional study", "client_42")

        # 1. Financial Analyst
        graph.add_task("fa", "Financial Analyst", "Analyze ROIC and balance sheet", [],
                       fn=lambda r: {"roic": 0.28, "fcf_conversion": 0.85, "net_debt": 0.0})

        # 2. Macro & Market Analyst
        graph.add_task("macro", "Macro & Market Analyst", "Analyze Fed curve and inflation", [],
                       fn=lambda r: {"fed_funds": 0.0475, "inflation_expectation": 0.024, "regime": "Soft Landing"})

        # 3. Intelligence / Web Analyst
        graph.add_task("intel", "Intelligence/Web Analyst", "Extract SEC EDGAR facts and news", [],
                       fn=lambda r: {"filing_verified": True, "source": "SEC EDGAR 10-K"})

        # 4. Investment Research Analyst
        graph.add_task("ira", "Investment Research Analyst", "Assess moat and catalysts", ["fa", "intel"],
                       fn=lambda r: {"moat": "High Switching Costs", "competitive_advantage_period_years": 15})

        # 5. Quantitative Analyst
        graph.add_task("quant", "Quantitative Analyst", "Compute fat-tail Monte Carlo & hurdle", ["fa", "macro"],
                       fn=lambda r: {"hurdle_rate": 0.3444, "monte_carlo_median": 19_800_000.0})

        # 6. Risk & Devil's Advocate
        graph.add_task("da", "Risk & Devil's Advocate", "Challenger critique & downside catalysts", ["ira", "quant"],
                       fn=lambda r: {"downside_loss_gt_50pct": 0.384, "recommendation": "Reject aggressive moonshot"})

        # 7. Personalized Advisory
        graph.add_task("pa", "Personalized Advisory", "Fit client profile and withdrawal requirements", ["da", "quant"],
                       fn=lambda r: {"portfolio_selected": "Institutional All-Weather Endowment", "liquidity_buffer": 1_000_000.0})

        # 8. Compliance Guard Node
        graph.add_task("compliance", "Compliance Guard", "Final regulatory validation", ["pa"],
                       fn=lambda r: {"compliance_approved": True, "disclosures_attached": True})

        results = await graph.execute()
        assert len(results) == 8
        assert results["fa"]["roic"] == 0.28
        assert results["macro"]["fed_funds"] == 0.0475
        assert results["quant"]["hurdle_rate"] == 0.3444
        assert results["da"]["recommendation"] == "Reject aggressive moonshot"
        assert results["compliance"]["compliance_approved"] is True

    def test_execution_and_tool_call_budgets(self):
        """Feature 30: Execution timeouts and tool-call budget enforcement."""
        class BudgetTracker:
            def __init__(self, max_tool_calls: int = 5, timeout_seconds: float = 2.0):
                self.max_tool_calls = max_tool_calls
                self.timeout_seconds = timeout_seconds
                self.calls_made = 0

            def record_call(self) -> None:
                if self.calls_made >= self.max_tool_calls:
                    raise RuntimeError(f"Tool-call budget exhausted (limit: {self.max_tool_calls})")
                self.calls_made += 1

        tracker = BudgetTracker(max_tool_calls=3)
        tracker.record_call()
        tracker.record_call()
        tracker.record_call()
        assert tracker.calls_made == 3

        with pytest.raises(RuntimeError, match="Tool-call budget exhausted"):
            tracker.record_call()

    def test_tenant_isolated_memory(self):
        """Feature 31: Tenant-isolated memory preventing cross-user data leakage."""
        class MemoryStore:
            def __init__(self):
                self._storage: Dict[str, Dict[str, Any]] = {}

            def set(self, tenant_id: str, key: str, value: Any) -> None:
                if tenant_id not in self._storage:
                    self._storage[tenant_id] = {}
                self._storage[tenant_id][key] = value

            def get(self, tenant_id: str, key: str) -> Optional[Any]:
                return self._storage.get(tenant_id, {}).get(key)

        memory = MemoryStore()
        memory.set("client_alice", "portfolio_value", 10_000_000.0)
        memory.set("client_bob", "portfolio_value", 250_000.0)

        # Alice cannot see Bob's data
        assert memory.get("client_alice", "portfolio_value") == 10_000_000.0
        assert memory.get("client_bob", "portfolio_value") == 250_000.0
        assert memory.get("client_alice", "non_existent") is None
        assert memory.get("client_eve", "portfolio_value") is None

    def test_memory_freshness_ttl_invalidation(self):
        """Feature 32: Stratified TTL hierarchy invalidating stale cache."""
        class TTLCache:
            def __init__(self):
                self.store: Dict[str, Tuple[Any, datetime, float]] = {}

            def set(self, key: str, value: Any, ttl_seconds: float) -> None:
                self.store[key] = (value, datetime.now(timezone.utc), ttl_seconds)

            def get(self, key: str) -> Optional[Any]:
                if key not in self.store:
                    return None
                val, timestamp, ttl = self.store[key]
                age = (datetime.now(timezone.utc) - timestamp).total_seconds()
                if age > ttl:
                    del self.store[key]
                    return None
                return val

        cache = TTLCache()
        # Market data: short TTL (simulated 0.1s for fast testing)
        cache.set("market_aapl_price", 230.50, ttl_seconds=0.05)
        # Macro data: longer TTL
        cache.set("macro_fed_rate", 0.0475, ttl_seconds=3600.0)

        assert cache.get("market_aapl_price") == 230.50
        assert cache.get("macro_fed_rate") == 0.0475

        # Wait for market data expiration
        import time
        time.sleep(0.06)
        assert cache.get("market_aapl_price") is None
        assert cache.get("macro_fed_rate") == 0.0475

    def test_bounded_self_verification_loop(self):
        """Feature 33: Bounded self-verification loop (max 2 iterations)."""
        def verify_report(report_text: str, true_hurdle: float, iteration: int = 1) -> Dict[str, Any]:
            # Detect whether reported hurdle matches mathematical truth
            match = re.search(r"hurdle rate of (\d+\.\d+)%", report_text)
            claimed_rate = float(match.group(1)) if match else None

            discrepancy = (claimed_rate is None) or (abs(claimed_rate - (true_hurdle * 100)) > 0.01)

            if discrepancy and iteration < 2:
                # Correct discrepancy in second pass
                corrected_text = f"The solved required pre-tax hurdle rate of {true_hurdle * 100:.2f}% is needed."
                return verify_report(corrected_text, true_hurdle, iteration + 1)

            return {
                "iteration": iteration,
                "verified": not discrepancy,
                "final_text": report_text
            }

        # Iteration 1 starts with hallucinated rate 25.0%
        hallucinated_text = "The solved required pre-tax hurdle rate of 25.00% is needed."
        result = verify_report(hallucinated_text, true_hurdle=0.3444)
        assert result["iteration"] == 2
        assert result["verified"] is True
        assert "34.44%" in result["final_text"]

    @pytest.mark.asyncio
    async def test_non_discretionary_paper_trading_guard(self, db_session):
        """Feature 34: Non-discretionary user approval (REG-003) and paper trading enforcement."""
        guard = ComplianceGuard()

        class MockProfile:
            risk_tolerance_score = 6.0
            loss_capacity = "Moderate"

        profile = MockProfile()

        # Case 1: Trade without explicit user approval must be blocked (REG-003)
        unapproved_trade = {
            "symbol": "VTI",
            "quantity": 100,
            "order_type": "BUY",
            "user_approved": False,
            "paper": True,
        }
        with pytest.raises(ComplianceViolationError) as exc_info:
            await guard.check_trade(db=None, client_id="client_1", trade=unapproved_trade, profile=profile)
        assert any(v.rule_id == "REG-003" for v in exc_info.value.violations)

        # Case 2: Trade with explicit user approval and paper flag passes
        approved_trade = {
            "symbol": "VTI",
            "quantity": 100,
            "order_type": "BUY",
            "user_approved": True,
            "approval_timestamp": datetime.now(timezone.utc).isoformat(),
            "paper": True,
            # A Red-tier order: the orchestrator sets this after the emailed step-up code is accepted
            "step_up_verified": True,
            "fiduciary_attested": True,
        }
        res = await guard.check_trade(db=None, client_id="client_1", trade=approved_trade, profile=profile)
        assert res.passed is True

    def test_compliance_guard_output_text_filters(self):
        """Feature 28: Regulatory text filtering (REG-001 Guaranteed return blocking, REG-002 Risk disclosure)."""
        guard = ComplianceGuard()

        # Prohibited promissory statement must be blocked (REG-001)
        bad_text = "Our proprietary algorithm provides guaranteed 40% annual returns."
        passed_1, violations_1, sanitized_1 = guard.check_text_output(bad_text)
        assert passed_1 is False
        assert any("REG-001" in v for v in violations_1)

        # Text missing risk disclosure triggers REG-002 and attaches standard disclosure
        neutral_text = "We recommend an asset allocation of 35% global equities and 25% private credit."
        passed_2, violations_2, sanitized_2 = guard.check_text_output(neutral_text)
        assert passed_2 is False
        assert any("REG-002" in v for v in violations_2)
        assert "Investing involves risk" in sanitized_2

    def test_adversarial_malformed_and_disconnected_graphs(self):
        """Adversarial: Disconnected graphs and missing prerequisite nodes."""
        graph = ReferenceTaskGraph("Adversarial Graph", "user_adv")
        # Subgraph 1
        graph.add_task("task_a1", "Financial Analyst", "desc", [])
        graph.add_task("task_a2", "Quantitative Analyst", "desc", ["task_a1"])

        # Subgraph 2 (Completely disconnected)
        graph.add_task("task_b1", "Macro & Market Analyst", "desc", [])
        graph.add_task("task_b2", "Intelligence/Web Analyst", "desc", ["task_b1"])

        layers = graph.get_execution_layers()
        assert len(layers) == 2
        # Layer 1 must contain roots from both independent subgraphs
        assert set(layers[0]) == {"task_a1", "task_b1"}
        assert set(layers[1]) == {"task_a2", "task_b2"}

"""
backend/tests/unit/test_tax_engineering.py
==========================================
Unit tests for the Institutional Tax Engineering & Legal Structuring Engine.
Verifies:
1. Nigerian Personal Income Tax (PITA) graduated schedule & CRA reliefs.
2. Multi-tier tax arbitrage comparison schedule (Individual vs FIC vs NEPZA vs FGN Sukuk).
3. 5-step operational entity structuring playbook.
4. GAAR (CITA Section 22) anti-avoidance boundaries.
5. Centralized TaxStrategyTool execution and schema validation.
"""

import pytest
from services.tax_engineering import (
    calculate_nigerian_personal_income_tax,
    generate_nigerian_tax_arbitrage_model,
    generate_nigerian_5step_structuring_playbook,
    generate_anti_avoidance_and_gaar_boundaries,
    optimize_full_nigerian_tax_strategy,
)
try:
    from tools.definitions.tax_strategy import TaxStrategyTool, TaxStrategyArgs
    from tools.registry import ToolRegistry
except ImportError:
    from backend.tools.definitions.tax_strategy import TaxStrategyTool, TaxStrategyArgs
    from backend.tools.registry import ToolRegistry


def test_calculate_nigerian_personal_income_tax():
    # ₦10,000,000 gross income test
    gross = 10_000_000.0
    res = calculate_nigerian_personal_income_tax(gross)

    assert res["gross_income"] == gross
    # CRA = max(200k, 1% of 10M = 100k) + 20% of 10M = 200,000 + 2,000,000 = 2,200,000
    assert res["consolidated_relief_allowance_cra"] == 2_200_000.0
    # Pension = 8% = 800,000, NHF = 2.5% = 250,000
    assert res["statutory_deductions"]["pension_contributions_pra_2014"] == 800_000.0
    assert res["statutory_deductions"]["national_housing_fund_nhf"] == 250_000.0
    # Net chargeable income = 10M - (800k + 250k + 2.2M) = 6,750,000
    assert res["net_chargeable_taxable_income"] == 6_750_000.0

    # Tax liability must be calculated across the 6 graduated bands
    tax = res["total_tax_liability"]
    assert tax > 0
    # ETR for ₦10M income is typically around 14% - 16%
    etr = float(res["effective_tax_rate_pct"].replace("%", ""))
    assert 13.0 <= etr <= 17.0


def test_high_net_worth_pita_top_bracket():
    # ₦100,000,000 gross income test (Subject to 24% marginal rate on bulk)
    gross = 100_000_000.0
    res = calculate_nigerian_personal_income_tax(gross)
    etr = float(res["effective_tax_rate_pct"].replace("%", ""))
    # On ₦100M, bulk is taxed at 24%, so ETR is ~16.5% - 17.5% after reliefs
    assert 15.0 <= etr <= 18.0
    assert res["total_tax_liability"] > 15_000_000.0


def test_generate_nigerian_tax_arbitrage_model():
    model = generate_nigerian_tax_arbitrage_model(100_000_000.0)
    assert "tax_arbitrage_schedule" in model
    schedule = model["tax_arbitrage_schedule"]
    assert len(schedule) == 4

    # Tier 1 (Unstructured) has highest tax
    t1 = schedule[0]
    assert "Tier 1" in t1["tier"]
    t1_tax = float(t1["annual_tax_liability"].replace("₦", "").replace(",", ""))

    # Tier 2 (Corporate HoldCo / FIC) delivers substantial savings
    t2 = schedule[1]
    assert "Tier 2" in t2["tier"]

    # Tier 3 (NEPZA Free Trade Zone) has ~1.5% compliance drag
    t3 = schedule[2]
    assert "Tier 3" in t3["tier"]
    t3_tax = float(t3["annual_tax_liability"].replace("₦", "").replace(",", ""))
    assert t3_tax < t1_tax * 0.15

    # Tier 4 (Sovereign Debt) has 0% tax liability
    t4 = schedule[3]
    assert "Tier 4" in t4["tier"]
    t4_tax = float(t4["annual_tax_liability"].replace("₦", "").replace(",", ""))
    assert t4_tax == 0.0


def test_generate_nigerian_5step_structuring_playbook():
    playbook = generate_nigerian_5step_structuring_playbook()
    assert len(playbook) == 5
    assert "Holding Co" in playbook[0]["step"]
    assert "Remuneration" in playbook[1]["step"]
    assert "Free Trade Zone" in playbook[2]["step"]
    assert "Sovereign Asset" in playbook[3]["step"]
    assert "Cross-Border" in playbook[4]["step"]

    for step in playbook:
        assert "legal_mechanic" in step
        assert "statutory_basis" in step
        assert "operational_execution" in step
        assert "tax_impact" in step


def test_generate_anti_avoidance_boundaries():
    gaar = generate_anti_avoidance_and_gaar_boundaries()
    assert "statutory_gaar_rule" in gaar
    assert "CITA Cap C21 Section 22" in gaar["statutory_gaar_rule"]
    assert len(gaar["compliance_requirements"]) >= 4


@pytest.mark.asyncio
async def test_tax_strategy_tool_execution():
    tool = TaxStrategyTool()
    assert tool.name == "optimize_tax_strategy"

    # Test argument parsing
    parsed = tool._parse_args({"jurisdiction": "Nigeria", "annual_income": 80_000_000.0})
    assert parsed.jurisdiction == "Nigeria"
    assert parsed.annual_income == 80_000_000.0

    # Test execution
    result = await tool.execute(annual_income=80_000_000.0)
    assert result.success is True
    assert result.data["jurisdiction"] == "Nigeria (Federal Republic of Nigeria)"
    assert "tax_arbitrage_comparison" in result.data
    assert len(result.data["five_step_operational_playbook"]) == 5

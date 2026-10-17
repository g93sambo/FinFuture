"""
backend/tests/unit/test_legal_retrieval.py
==========================================
Retrieval evaluation test set for the statutory legal knowledge base.
Validates that legal queries retrieve the exact target statutes and sections.
"""

import pytest
from services.legal_knowledge import retrieve_statutes, STATUTE_DATABASE


def test_statute_database_completeness():
    """Verify all 5 required statutory regimes are present."""
    statute_codes = {a.statute_code for a in STATUTE_DATABASE}
    assert any("PITA" in code for code in statute_codes), "PITA missing from statute DB"
    assert any("CITA" in code for code in statute_codes), "CITA missing from statute DB"
    assert any("CGTA" in code for code in statute_codes), "CGTA missing from statute DB"
    assert any("NEPZA" in code for code in statute_codes), "NEPZA missing from statute DB"
    assert any("PRA" in code for code in statute_codes), "PRA missing from statute DB"


@pytest.mark.parametrize(
    "query,expected_code_substring",
    [
        ("Consolidated relief allowance and tax brackets", "PITA-SEC-33"),
        ("Are FGN bonds and treasury bills tax exempt?", "PITA-SCH-3"),
        ("Corporate income tax rate for small vs large companies", "CITA-SEC-23-40"),
        ("Holding company franked investment income dividend exemption", "CITA-SEC-80-3"),
        ("Capital gains tax rate on sovereign securities disposal", "CGTA-SEC-2-30"),
        ("Free trade zone 100% tax holiday and profit repatriation", "NEPZA-SEC-8-10"),
        ("Pre-tax deduction for pension contributions", "PRA-2014-SEC-10"),
    ],
)
def test_legal_retrieval_precision(query: str, expected_code_substring: str):
    """Ensure search queries retrieve the exact target statute as the #1 ranked result."""
    results = retrieve_statutes(query=query, jurisdiction="Nigeria", top_k=3)
    assert len(results) > 0, f"No statutes retrieved for query: {query}"
    top_result = results[0]
    assert expected_code_substring in top_result.statute_code, (
        f"Query '{query}' expected top result containing '{expected_code_substring}', but got '{top_result.statute_code}'"
    )

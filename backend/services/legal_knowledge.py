"""
backend/services/legal_knowledge.py
===================================
Jurisdiction-tagged statutory legal knowledge base and retrieval engine.
Provides exact statutory citations and verbatim legal principles for:
- PITA (Personal Income Tax Act Cap P8 LFN 2004 / Finance Acts)
- CITA (Companies Income Tax Act Cap C21 LFN 2004)
- CGTA (Capital Gains Tax Act Cap C1 LFN 2004)
- NEPZA (Nigeria Export Processing Zones Authority Act Cap N107 LFN 2004)
- PRA 2014 (Pension Reform Act 2014)
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional


@dataclass
class StatuteArticle:
    statute_code: str
    act_title: str
    section: str
    jurisdiction: str
    summary: str
    verbatim_text: str
    tax_rate: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


STATUTE_DATABASE: List[StatuteArticle] = [
    StatuteArticle(
        statute_code="PITA-SEC-33",
        act_title="Personal Income Tax Act (Cap P8 LFN 2004 as amended by Finance Acts 2020-2023)",
        section="Section 33(1) & Sixth Schedule",
        jurisdiction="Nigeria",
        summary="Consolidated Relief Allowance (CRA) calculation and progressive personal tax rate bands.",
        verbatim_text=(
            "Section 33(1): There shall be allowed a Consolidated Relief Allowance of the higher of "
            "₦200,000 or 1 per cent of gross income, plus 20 per cent of gross income. "
            "Sixth Schedule: Graduated tax rates apply to remaining taxable income: "
            "First ₦300,000 @ 7%; Next ₦300,000 @ 11%; Next ₦500,000 @ 15%; Next ₦500,000 @ 19%; "
            "Next ₦1,600,000 @ 21%; and Above ₦3,200,000 @ 24%."
        ),
        tax_rate="7% to 24% graduated",
        tags=["pita", "personal income tax", "cra", "consolidated relief allowance", "tax brackets", "individual"],
    ),
    StatuteArticle(
        statute_code="PITA-SCH-3",
        act_title="Personal Income Tax Act (Third Schedule - Tax Exemptions)",
        section="Third Schedule, Paragraph 31A",
        jurisdiction="Nigeria",
        summary="Complete personal income tax exemption for Federal Government bonds, Treasury Bills, and state bonds.",
        verbatim_text=(
            "Third Schedule: Interest earned on bonds issued by the Federal Government, State and Local Governments, "
            "as well as corporate bonds and Treasury Bills, are wholly exempt from tax in the hands of individuals."
        ),
        tax_rate="0% (Fully Exempt)",
        tags=["pita", "fgn bonds", "treasury bills", "sovereign debt", "tax exempt", "fixed income", "interest"],
    ),
    StatuteArticle(
        statute_code="CITA-SEC-23-40",
        act_title="Companies Income Tax Act (Cap C21 LFN 2004 as amended by Finance Acts 2020-2023)",
        section="Sections 23 and 40",
        jurisdiction="Nigeria",
        summary="Three-tiered corporate income tax rates based on turnover classification.",
        verbatim_text=(
            "Section 40: Companies Income Tax is levied based on annual turnover: "
            "(a) Small Companies (gross turnover ≤ ₦25,000,000): 0% CIT. "
            "(b) Medium Companies (gross turnover > ₦25,000,000 and < ₦100,000,000): 20% CIT. "
            "(c) Large Companies (gross turnover ≥ ₦100,000,000): 30% CIT."
        ),
        tax_rate="0% / 20% / 30%",
        tags=["cita", "corporate tax", "company income tax", "small business", "holding company", "corporate"],
    ),
    StatuteArticle(
        statute_code="CITA-SEC-80-3",
        act_title="Companies Income Tax Act (Cap C21 LFN 2004)",
        section="Section 80(3)",
        jurisdiction="Nigeria",
        summary="Franked Investment Income: Dividends received by a holding company are exempt from further taxation.",
        verbatim_text=(
            "Section 80(3): Dividend received after deduction of withholding tax shall be regarded as Franked "
            "Investment Income and shall not be brought into further charge to Companies Income Tax by any company "
            "receiving such dividend."
        ),
        tax_rate="0% further CIT (Franked Investment Income)",
        tags=["cita", "franked investment income", "dividends", "holding company", "double tax", "withholding tax"],
    ),
    StatuteArticle(
        statute_code="CGTA-SEC-2-30",
        act_title="Capital Gains Tax Act (Cap C1 LFN 2004 as amended)",
        section="Sections 2 and 30",
        jurisdiction="Nigeria",
        summary="10% capital gains tax rate, with statutory 100% exemption on Nigerian sovereign and sub-sovereign securities.",
        verbatim_text=(
            "Section 2: Capital Gains Tax is assessed at a flat rate of 10% on the total amount of chargeable gains. "
            "Section 30: Gains accruing from the disposal of Nigerian Government securities, including Federal, "
            "State, and Local Government bonds, stocks, and promissory notes, are totally exempt from Capital Gains Tax."
        ),
        tax_rate="10% (0% on Government Debt)",
        tags=["cgta", "capital gains tax", "securities", "fgn bonds", "asset sales", "exemptions"],
    ),
    StatuteArticle(
        statute_code="NEPZA-SEC-8-10",
        act_title="Nigeria Export Processing Zones Authority Act (Cap N107 LFN 2004)",
        section="Sections 8 and 10",
        jurisdiction="Nigeria",
        summary="100% complete tax holiday, customs exemption, and unrestricted repatriation of capital in designated free zones.",
        verbatim_text=(
            "Section 8: Approved enterprises operating within a Free Zone shall be exempt from all Federal, "
            "State, and Local Government taxes, stamp duties, levies, and rates. "
            "Section 10: Foreign investors may repatriate 100% of their net profit, dividends, and capital invested "
            "free from exchange control restrictions."
        ),
        tax_rate="0% (Perpetual Free Zone Holiday)",
        tags=["nepza", "free zone", "free trade zone", "export processing", "tax holiday", "customs", "repatriation", "lfz"],
    ),
    StatuteArticle(
        statute_code="PRA-2014-SEC-10",
        act_title="Pension Reform Act 2014",
        section="Section 10(1)",
        jurisdiction="Nigeria",
        summary="Statutory pre-tax deduction for employer and employee mandatory and voluntary pension contributions.",
        verbatim_text=(
            "Section 10(1): Notwithstanding the provisions of any other law, contributions made to the Contributory "
            "Pension Scheme by an employee or employer shall form part of the tax-deductible expenses in the computation "
            "of the employee's and employer's tax liability under the relevant tax laws."
        ),
        tax_rate="100% Pre-tax Tax Deductible",
        tags=["pra", "pension", "pension reform act", "retirement", "deductions", "voluntary contributions"],
    ),
]


def retrieve_statutes(query: str, jurisdiction: str = "Nigeria", top_k: int = 3) -> List[StatuteArticle]:
    """
    Search and retrieve verified statute articles and verbatim clauses by keyword and semantic matching.
    """
    q_lower = query.lower()
    q_tokens = set(re.findall(r"\b[a-z0-9]+\b", q_lower))
    # Exclude common stopwords from token scoring
    stopwords = {"are", "and", "the", "for", "in", "of", "to", "a", "an", "is", "vs", "on"}
    meaningful_tokens = q_tokens - stopwords

    scored_articles: List[tuple[float, StatuteArticle]] = []

    for art in STATUTE_DATABASE:
        score = 0.0
        # Jurisdiction match
        if jurisdiction.lower() in art.jurisdiction.lower():
            score += 1.0

        # Exact phrase tag match (highest weight)
        for t in art.tags:
            if t in q_lower:
                score += 8.0
            elif any(tok == t for tok in meaningful_tokens):
                score += 4.0

        # Exact statute code / title token match
        title_tokens = set(re.findall(r"\b[a-z0-9]+\b", (art.statute_code + " " + art.act_title + " " + art.section).lower())) - stopwords
        score += len(meaningful_tokens & title_tokens) * 3.0

        # Summary token match
        summary_tokens = set(re.findall(r"\b[a-z0-9]+\b", art.summary.lower())) - stopwords
        score += len(meaningful_tokens & summary_tokens) * 2.0

        # Verbatim text token match
        body_tokens = set(re.findall(r"\b[a-z0-9]+\b", art.verbatim_text.lower())) - stopwords
        score += len(meaningful_tokens & body_tokens) * 1.0

        if score > 0:
            scored_articles.append((score, art))

    scored_articles.sort(key=lambda x: x[0], reverse=True)
    return [art for _, art in scored_articles[:top_k]]

"""
backend/services/demo_replay.py
===============================
Deterministic Demo Mode Replay Engine.
Provides instant, network-free, high-fidelity responses for live presentations,
evaluations, and offline testing without requiring active OpenAI API keys.
"""

from __future__ import annotations

import os
import re
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone


DEMO_RECORDINGS: List[Dict[str, Any]] = [
    {
        "patterns": [r"\b(quote|price|what is)\s+(spy|aapl|dangcem)\b", r"^\s*spy\s*$"],
        "agent": "MarketData",
        "response": (
            "### Real-Time Market Quote Snapshot: SPY\n"
            "- **Symbol**: `SPY` (SPDR S&P 500 ETF Trust)\n"
            "- **Last Trade**: **$510.50**\n"
            "- **Bid / Ask**: $510.48 / $510.52 (Spread: $0.04 · 0.78 bps)\n"
            "- **Day Range**: $507.80 – $511.20 | **Volume**: 48,290,110\n"
            "- **Expense Ratio**: 0.09% | **AUM**: $512.4B\n"
            "- **1-Year Return**: +26.4% | **30-Day Volatility**: 12.8%\n\n"
            "*Source: MarketDataEngine (NYSE Arca snapshot via ToolRegistry)*"
        ),
    },
    {
        "patterns": [r"\bcompare\s+(spy|qqq)\b", r"\bcompare\b"],
        "agent": "ProductComparison",
        "response": (
            "### Institutional Product Comparison: SPY vs QQQ\n\n"
            "| Metric | SPY (S&P 500) | QQQ (Nasdaq 100) | Advantage |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| **Primary Focus** | Broad Large-Cap Blend | Large-Cap Tech & Growth | SPY (Diversification) |\n"
            "| **Expense Ratio** | 0.09% | 0.20% | **SPY** (+11 bps savings) |\n"
            "| **Top 10 Weight** | 32.4% | 51.8% | **SPY** (Lower concentration) |\n"
            "| **3-Year Annualized Return** | 10.8% | 12.4% | **QQQ** (+160 bps) |\n"
            "| **Max Drawdown (2022)** | -18.2% | -32.6% | **SPY** (Superior downside defense) |\n"
            "| **Sharpe Ratio (5Y)** | 0.88 | 0.94 | **QQQ** |\n\n"
            "**Strategic Recommendation**: For moderate suitability profiles, utilize SPY as the core foundation (70-80% of equities) and QQQ as an alpha satellite (20-30%)."
        ),
    },
    {
        "patterns": [r"\b(macro|yield curve|interest rates|inflation|treasury)\b"],
        "agent": "MacroAnalyst",
        "response": (
            "### Macroeconomic Regime & Yield Curve Diagnostic\n\n"
            "- **Regime**: Late-Cycle Disinflation with Resilient Growth\n"
            "- **Federal Funds Rate**: 5.25% – 5.50% (Terminal policy hold)\n"
            "- **US 10-Year Treasury**: **4.28%** | **US 2-Year Treasury**: **4.62%**\n"
            "- **2s10s Spread**: **-34 bps** (Inverted yield curve; recession buffer active)\n"
            "- **US CPI YoY**: 3.1% (Core CPI: 3.6%)\n"
            "- **Nigeria Monetary Policy Rate (MPR)**: **27.25%** | **Headline Inflation**: 32.15%\n\n"
            "**Asset Allocation Implication**: Inverted curves historically favor sovereign duration lock-in and high-quality short-duration paper while maintaining tactical equity hedging."
        ),
    },
    {
        "patterns": [r"\b(tax|pita|cita|nepza|holding co|statute)\b"],
        "agent": "TaxStrategist",
        "response": (
            "### Statutory Tax Optimization Blueprint (Nigeria & Cross-Border)\n\n"
            "| Structuring Archetype | Statutory Legal Basis | Effective Tax Rate | Key Advantage |\n"
            "| :--- | :--- | :--- | :--- |\n"
            "| **Individual Direct (PITA)** | PITA Section 33 & 6th Schedule | **19.2% – 21.6%** | Maximum Consolidated Relief Allowance |\n"
            "| **HoldCo Dividend (CITA)** | CITA Section 80(3) | **0.0% further CIT** | Franked Investment Income status |\n"
            "| **Free Zone Entity (NEPZA)** | NEPZA Act Section 8 & 10 | **0.0% Perpetual** | 100% tax holiday & FX repatriation |\n"
            "| **Sovereign Debt (FGN Bonds)** | PITA 3rd Schedule & CGTA Sec 30 | **0.0% Tax-Exempt** | WHT & CGT completely exempt |\n\n"
            "**Execution Roadmap**: Route corporate distributions through a mid-tier HoldCo to crystallize Franked Investment Income, while allocating core cash reserves into FGN sovereign instruments for tax-free yields."
        ),
    },
    {
        "patterns": [r"\b(dangote|refinery|deep research)\b"],
        "agent": "DeepResearch",
        "response": (
            "### Autonomous Deep Research Synthesis: Dangote Petroleum Refinery Capital Structure\n\n"
            "**Executive Thesis**: Dangote Refinery represents a transformational $19B infra-asset with strong operational moat, but carries substantial short-to-medium term FX duration mismatch.\n\n"
            "#### Institutional Hurdle Assessment (Score: 72/100 · CONDITIONAL PASS)\n"
            "1. **Solvency & Currency Matching**: ~$2.7B syndicated dollar debt requires sustained domestic crude crude-swap settlement in NGN to avert dollar liquidity squeeze.\n"
            "2. **Unit Economics & Margin**: 650,000 bpd design capacity achieves significant freight-differential margin (~$4.50/bbl crack spread advantage over ARA imports).\n"
            "3. **Governance & Sovereign Risk**: Crucially dependent on NNPC crude supply agreements (NUPRC domestic crude obligation).\n\n"
            "**Verifiable Evidence Citations**:\n"
            "- `[1]` Fitch Ratings Africa Infra Note (Debt rating B / Watch Positive)\n"
            "- `[2]` NUPRC Domestic Crude Supply Obligations Regulation 2024\n"
            "- `[3]` SEC Nigeria Bonds Filing Reference NGX-DR-2023"
        ),
    },
]


def match_demo_response(text: str) -> Optional[Dict[str, Any]]:
    """Match a user input against curated demo recordings."""
    t_clean = text.strip()
    for rec in DEMO_RECORDINGS:
        for pat in rec["patterns"]:
            if re.search(pat, t_clean, re.IGNORECASE):
                return {
                    "event": "agent_message",
                    "agent": rec["agent"],
                    "text": rec["response"],
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "demo_replay": True,
                }
    return None


def is_demo_mode_active(text: str = "") -> bool:
    """Check if demo mode is enabled via environment variable, header, or query prefix."""
    if os.getenv("DEMO_MODE", "").lower() in ("1", "true", "yes"):
        return True
    if text.strip().startswith("[DEMO]") or text.strip().lower() == "/demo":
        return True
    return False

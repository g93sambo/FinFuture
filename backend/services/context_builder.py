"""
backend/services/context_builder.py
===================================
Financial Context Builder: Unifies client profile, goals, portfolio state,
currency, behavioral tendencies, and regulatory constraints into a single,
canonical ClientFinancialContext handed to every agent and tool execution path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from sqlalchemy.ext.asyncio import AsyncSession

from services.portfolio_service import PortfolioService

logger = logging.getLogger("wealth_advisor.services.context_builder")


@dataclass
class ClientFinancialContext:
    client_id: str
    name: str = "Valued Client"
    age: Optional[int] = None
    annual_income: Optional[float] = None
    liquid_net_worth: Optional[float] = None
    risk_tolerance_score: Optional[float] = None
    suitability_category: str = "MODERATE"
    primary_goal: Optional[str] = None
    time_horizon_years: Optional[int] = None
    currency: str = "USD"
    kyc_verified: bool = False
    portfolio: Dict[str, Any] = field(default_factory=dict)
    constraints: List[str] = field(default_factory=list)
    behavioral_biases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_system_prompt_snippet(self) -> str:
        """
        Compact, privacy-preserving suitability context block injected into the LLM system prompt.
        Direct PII (full_name, email, raw client_id, user_id, national IDs, account numbers)
        is stripped and replaced with a one-way SHA-256 pseudonym (ANON-XXXXXXXX).
        """
        import hashlib

        anon_ref = "ANON-" + hashlib.sha256(str(self.client_id).encode("utf-8")).hexdigest()[:8].upper()
        pv = self.portfolio.get("total_value", 0.0)
        cash = self.portfolio.get("cash", 0.0)
        positions = self.portfolio.get("positions", [])
        holdings_str = ", ".join(f"{p['symbol']} ({p['weight']*100:.1f}%)" for p in positions) if positions else "All cash / no active equity positions"

        constraints_str = "; ".join(self.constraints) if self.constraints else "Standard fiduciary diversification"
        biases_str = ", ".join(self.behavioral_biases) if self.behavioral_biases else "None detected"

        return (
            "\n[ANONYMIZED CLIENT SUITABILITY CONTEXT — DIRECT PII REDACTED]\n"
            f"- Pseudonym Reference: {anon_ref}\n"
            f"- Age: {self.age or 'Unspecified'} | Primary Goal: {self.primary_goal or 'Wealth Accumulation'}\n"
            f"- Base Currency: {self.currency} | KYC Status: {'Verified' if self.kyc_verified else 'Pending'}\n"
            f"- Suitability Category: {self.suitability_category} (Risk Tolerance Score: {self.risk_tolerance_score or 5.0}/10)\n"
            + (
                f"- Annual Income: ${self.annual_income:,.2f} | Liquid Net Worth: ${self.liquid_net_worth:,.2f}\n"
                if self.annual_income and self.liquid_net_worth
                else f"- Suitability: {self.suitability_category} (Score: {self.risk_tolerance_score or 5.0}/10)\n"
            )
            + f"- Time Horizon: {self.time_horizon_years or 10} years\n"
            f"- Portfolio Total Value: ${pv:,.2f} (Cash: ${cash:,.2f})\n"
            f"- Active Holdings: {holdings_str}\n"
            f"- Governing Constraints: {constraints_str}\n"
            f"- Known Behavioral Tendencies: {biases_str}\n"
            "Tailor all recommendations, risk warnings, and asset allocations strictly to this individual's horizon, suitability, and liquidity.\n"
        )


class FinancialContextBuilder:
    def __init__(
        self,
        risk_profiler: Optional[Any] = None,
        portfolio_service: Optional[PortfolioService] = None,
    ):
        if risk_profiler is None:
            try:
                from agents.risk_profiler import RiskProfilerAgent
                self.risk_profiler = RiskProfilerAgent()
            except ImportError:
                self.risk_profiler = None
        else:
            self.risk_profiler = risk_profiler
        self.portfolio_service = portfolio_service or PortfolioService()

    async def build_context(self, db: AsyncSession, client_id: str) -> ClientFinancialContext:
        """Fetch profile and portfolio, derive suitability constraints, and return unified context."""
        try:
            profile = await self.risk_profiler.get_profile(db, client_id)
        except Exception as exc:
            logger.warning("Failed to load profile for %s: %s", client_id, exc)
            profile = None

        try:
            portfolio = await self.portfolio_service.get_portfolio(db, client_id)
        except Exception as exc:
            logger.warning("Failed to load portfolio for %s: %s", client_id, exc)
            portfolio = {"total_value": 100000.0, "cash": 100000.0, "positions": [], "weights": {}}

        # Derive constraints
        constraints: List[str] = []
        age = getattr(profile, "age", None) if profile else None
        risk_score = float(getattr(profile, "risk_tolerance_score", 50.0) or 50.0) if profile else 50.0
        suitability = getattr(profile, "suitability_category", "MODERATE") if profile else "MODERATE"

        if age and age >= 60:
            constraints.append("Capital preservation priority: Max equity allocation 40%, min 40% fixed income")
        elif age and age < 25:
            constraints.append("Long horizon growth: Limit speculative/penny stocks to < 5%")

        if suitability in ("CONSERVATIVE", "VERY_CONSERVATIVE"):
            constraints.append("Max equity exposure 30%; max single-asset concentration 10%")
        elif suitability == "MODERATE":
            constraints.append("Max equity exposure 70%; max single-asset concentration 15%")
        elif suitability in ("AGGRESSIVE", "VERY_AGGRESSIVE"):
            constraints.append("Max single-asset concentration 25%")

        # Default biases or from notes
        biases: List[str] = []
        if getattr(profile, "panic_sell_likelihood", 0.0) and float(profile.panic_sell_likelihood) > 0.6:
            biases.append("Loss Aversion / Panic Selling Susceptibility")

        return ClientFinancialContext(
            client_id=str(client_id),
            name=f"Client {client_id}",
            age=age,
            annual_income=getattr(profile, "annual_income", None) if profile else None,
            liquid_net_worth=getattr(profile, "liquid_net_worth", None) if profile else None,
            risk_tolerance_score=risk_score,
            suitability_category=suitability,
            primary_goal=getattr(profile, "primary_goal", None) if profile else None,
            time_horizon_years=getattr(profile, "time_horizon_years", None) if profile else None,
            currency="USD",
            kyc_verified=bool(getattr(profile, "kyc_verified", False) if profile else False),
            portfolio=portfolio,
            constraints=constraints,
            behavioral_biases=biases,
        )

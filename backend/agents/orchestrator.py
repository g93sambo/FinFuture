"""
backend/agents/orchestrator.py
==============================
Central Orchestrator Agent.

Responsibilities (spec section 2.2):
* 5-state session state machine (PROFILING, ADVICE_GENERATION, PROPOSAL_REVIEW, EXECUTION, HEALTH_MONITORING)
* routing user intent to specialised domain agents
* universal compliance gate on every outgoing text (REG-001 / REG-002)
* non-discretionary approval gate for trades (REG-003 / REG-004)
* cryptographic audit logging of every material decision

All public coroutines return a list of *events* (plain dicts) so that the REST
chat endpoint and the WebSocket endpoint share exactly the same behaviour.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from agents.allocation_engine import AllocationEngine
from agents.behavioral_bias import BehavioralBiasAgent
from agents.compliance_guard import ComplianceGuard, ComplianceViolationError
from agents.execution_module import (
    DuplicateTradeError,
    ExecutionError,
    ExecutionModule,
    ExpiredApprovalError,
    KYCUnverifiedError,
    UnapprovedTradeError,
)
from agents.market_data import MarketDataAgent
from agents.product_comparison import ProductComparisonAgent
from agents.risk_profiler import STATE_DEMOGRAPHICS, STATE_PROMPTS, RiskProfilerAgent
from db.models import DBClientProfile
from services.audit_logger import AuditLogger, get_audit_logger
from services.cache import CacheService, get_cache_service, key_session
from services.health_report import HealthReportService
from services.portfolio_service import PortfolioService

logger = logging.getLogger("wealth_advisor.agents.orchestrator")

SESSION_TTL_SECONDS = 24 * 3600
PROPOSAL_TTL_SECONDS = 15 * 60

EQUITY_SYMBOLS = {"SPY", "VTI", "QQQ", "VXUS", "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "VOO", "IVV"}
BOND_SYMBOLS = {"BND", "AGG", "SHY", "TLT", "IEF", "TIP", "LQD"}

# ---------------------------------------------------------------------- #
# 5-State Session State Machine Definition
# ---------------------------------------------------------------------- #
class SessionStage(str, Enum):
    PROFILING = "PROFILING"
    ADVICE_GENERATION = "ADVICE_GENERATION"
    PROPOSAL_REVIEW = "PROPOSAL_REVIEW"
    EXECUTION = "EXECUTION"
    HEALTH_MONITORING = "HEALTH_MONITORING"


def _normalize_stage(stage: Optional[str]) -> SessionStage:
    if not stage:
        return SessionStage.PROFILING
    s = str(stage).upper()
    if s in ("ADVISING", "ADVICE_GENERATION"):
        return SessionStage.ADVICE_GENERATION
    if s in ("PROFILING",):
        return SessionStage.PROFILING
    if s in ("PROPOSAL_REVIEW",):
        return SessionStage.PROPOSAL_REVIEW
    if s in ("EXECUTION",):
        return SessionStage.EXECUTION
    if s in ("HEALTH_MONITORING",):
        return SessionStage.HEALTH_MONITORING
    return SessionStage.ADVICE_GENERATION


# ---------------------------------------------------------------------- #
# Intent Regexes
# ---------------------------------------------------------------------- #
TRADE_RE = re.compile(
    r"\b(buy|sell)\s+(\d+(?:\.\d+)?)\s+(?:shares?\s+of\s+|units?\s+of\s+)?([A-Za-z]{1,5})\b",
    re.IGNORECASE,
)
APPROVE_RE = re.compile(
    r"^\s*(approve|approved|confirm|yes|execute|go ahead|proceed)\b",
    re.IGNORECASE,
)
REJECT_RE = re.compile(
    r"^\s*(reject|cancel|no|decline|stop|abort|don't|dont)\b",
    re.IGNORECASE,
)
COMPARE_RE = re.compile(r"\b(compare|versus|vs|better than|difference between)\b", re.IGNORECASE)
REBALANCE_RE = re.compile(r"\b(rebalance|rebalancing|realign|fix drift|adjust allocation)\b", re.IGNORECASE)
HEALTH_RE = re.compile(
    r"\b(health|drift|how is my portfolio|portfolio review|performance|portfolio status)\b",
    re.IGNORECASE,
)
ALLOCATION_RE = re.compile(
    r"\b(allocat|recommend|what should i invest|build (?:me )?a portfolio|suggest a portfolio)\b",
    re.IGNORECASE,
)
QUOTE_RE = re.compile(r"\b(?:quote|price of|how much is)\s+([A-Za-z]{1,5})\b", re.IGNORECASE)
MACRO_RE = re.compile(
    r"\b(macro|yield curve|treasury rates|interest rates|inflation|gdp|unemployment)\b",
    re.IGNORECASE,
)
TICKER_RE = re.compile(r"\b[A-Z]{2,5}\b")
STOPWORDS_TICKER = {"ETF", "ETFS", "AND", "VS", "THE", "BOND", "BONDS", "FOR", "BUY", "SELL"}

SAFE_REPLACEMENT = (
    "I cannot promise returns or describe any investment as free of risk. Every investment "
    "can lose value, and I will only give you balanced, evidence-based information. "
    "Investing involves risk, including possible loss of principal. "
    "Past performance is no guarantee of future results."
)


class ProposalError(HTTPException):
    pass


@dataclass
class AgentContainer:
    """Holds the singleton agent instances shared by REST + WebSocket layers."""

    cache: CacheService
    audit: AuditLogger
    market: MarketDataAgent
    profiler: RiskProfilerAgent
    bias: BehavioralBiasAgent
    compliance: ComplianceGuard
    allocation: AllocationEngine
    comparison: ProductComparisonAgent
    execution: ExecutionModule
    health: HealthReportService
    portfolio: PortfolioService
    orchestrator: "OrchestratorAgent"


def build_container() -> AgentContainer:
    cache = get_cache_service()
    audit = get_audit_logger()
    market = MarketDataAgent()
    execution = ExecutionModule(cache_service=cache, audit_logger=audit)
    container = AgentContainer(
        cache=cache,
        audit=audit,
        market=market,
        profiler=RiskProfilerAgent(),
        bias=BehavioralBiasAgent(cache_service=cache),
        compliance=ComplianceGuard(audit_logger=audit),
        allocation=AllocationEngine(market_data_agent=market),
        comparison=ProductComparisonAgent(market_data_agent=market),
        execution=execution,
        health=HealthReportService(market_data_agent=market),
        portfolio=PortfolioService(execution_module=execution, market_data_agent=market),
        orchestrator=None,  # type: ignore[arg-type]
    )
    container.orchestrator = OrchestratorAgent(container)
    return container


def _event(kind: str, agent: str, text: str = "", **extra: Any) -> Dict[str, Any]:
    return {"event": kind, "agent": agent, "text": text, "timestamp": datetime.now(timezone.utc).isoformat(), **extra}


class OrchestratorAgent:
    def __init__(self, c: AgentContainer) -> None:
        self.c = c

    # ------------------------------------------------------------------ #
    # Session state
    # ------------------------------------------------------------------ #
    async def start_session(self, user_id: str, client_id: Optional[str] = None) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        stage = SessionStage.ADVICE_GENERATION.value if client_id else SessionStage.PROFILING.value
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "client_id": client_id,
            "stage": stage,
        }
        await self.c.cache.set_json(key_session(session_id), session, expire=SESSION_TTL_SECONDS)
        greeting = (
            "Welcome back! Ask me for an allocation, compare ETFs, or request a portfolio health report."
            if client_id
            else STATE_PROMPTS[STATE_DEMOGRAPHICS]
        )
        return {"session": session, "message": greeting}

    async def load_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        session = await self.c.cache.get_json(key_session(session_id))
        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        if session.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session belongs to another user")
        return session

    async def _save_session(self, session: Dict[str, Any]) -> None:
        await self.c.cache.set_json(key_session(session["session_id"]), session, expire=SESSION_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Compliance gate for outgoing text
    # ------------------------------------------------------------------ #
    async def gate_text(self, text: str, db: Optional[AsyncSession], client_id: Optional[str]) -> str:
        passed, violations, sanitized = self.c.compliance.check_text_output(text)
        if violations:
            if any(v.startswith("REG-001") for v in violations):
                _, _, sanitized = self.c.compliance.check_text_output(SAFE_REPLACEMENT)
            if db is not None and client_id:
                try:
                    await self.c.audit.log_audit_entry(
                        db=db,
                        client_id=client_id,
                        event_type="OUTPUT_FILTERED",
                        actor="AGENT:orchestrator",
                        details={"violations": violations},
                        status="WARN",
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error("Failed to audit filtered output: %s", exc)
        return sanitized

    async def _say(
        self, text: str, db: AsyncSession, cid: Optional[str], agent: str = "Orchestrator", kind: str = "agent_response", **extra: Any
    ) -> Dict[str, Any]:
        return _event(kind, agent, await self.gate_text(text, db, cid), **extra)

    # ------------------------------------------------------------------ #
    # Milestone 5 Canonical Message Processing
    # ------------------------------------------------------------------ #
    async def process_user_message(
        self,
        session_id: str,
        user_id: str,
        client_id: Optional[str],
        message: str,
        db: AsyncSession,
    ) -> List[Dict[str, Any]]:
        session = await self.load_session(session_id, user_id)
        if client_id and not session.get("client_id"):
            session["client_id"] = client_id

        events: List[Dict[str, Any]] = [_event("user_message", "User", message)]
        stage = _normalize_stage(session.get("stage"))

        if stage == SessionStage.PROFILING:
            events += await self._profiling_turn(db, session, message)
        elif stage == SessionStage.PROPOSAL_REVIEW:
            events += await self._proposal_review_turn(db, session, message)
        else:
            events += await self._advising_turn(db, session, message)

        await self._save_session(session)
        return events

    # Backward-compatible facade for handle_message
    async def handle_message(self, db: AsyncSession, user_id: str, session_id: str, text: str) -> List[Dict[str, Any]]:
        return await self.process_user_message(
            session_id=session_id, user_id=user_id, client_id=None, message=text, db=db
        )

    # -- profiling ---------------------------------------------------- #
    async def _profiling_turn(self, db: AsyncSession, session: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        provisional_id = session.get("client_id") or f"pending-{session['session_id']}"

        for b in await self.c.bias.detect_bias(client_id=provisional_id, user_message=text):
            events.append(
                _event(
                    "bias_alert",
                    "BehavioralBias",
                    b.intervention,
                    bias_type=b.bias_type,
                    severity=b.severity,
                    confidence=b.confidence,
                    cool_off_recommended=b.cool_off_recommended,
                )
            )

        result = await self.c.profiler.process_input(session["session_id"], text, db=db)

        if result.get("status") == "complete":
            client_id = result["client_id"]
            profile = await self.c.profiler.get_profile(client_id, db=db)
            if profile is not None:
                profile.user_id = session["user_id"]
                await db.commit()
            session.update({"client_id": client_id, "stage": SessionStage.ADVICE_GENERATION.value})
            await self._save_session(session)
            await self.c.audit.log_audit_entry(
                db=db,
                client_id=client_id,
                event_type="PROFILE_COMPLETED",
                actor="AGENT:risk_profiler",
                details={
                    "suitability_category": getattr(profile, "suitability_category", None),
                    "risk_tolerance_score": getattr(profile, "risk_tolerance_score", None),
                    "kyc_verified": getattr(profile, "kyc_verified", None),
                },
                session_id=session["session_id"],
            )
            events.append(
                await self._say(result["response"], db, client_id, agent="RiskProfiler", client_id=client_id, profile_complete=True)
            )
        else:
            events.append(await self._say(result["response"], db, None, agent="RiskProfiler"))
        return events

    # -- proposal review turn ------------------------------------------ #
    async def _proposal_review_turn(self, db: AsyncSession, session: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
        client_id = session.get("client_id")
        user_id = session["user_id"]
        pending = session.get("pending_proposal_id")
        events: List[Dict[str, Any]] = []

        if pending and APPROVE_RE.match(text):
            events += await self.handle_trade_approval(db, user_id, pending, approved=True, session_id=session["session_id"])
            session.pop("pending_proposal_id", None)
            session["stage"] = SessionStage.ADVICE_GENERATION.value
            return events

        if pending and REJECT_RE.match(text):
            await self.c.cache.delete(f"proposal:{pending}")
            session.pop("pending_proposal_id", None)
            session["stage"] = SessionStage.ADVICE_GENERATION.value
            if client_id:
                await self.c.audit.log_audit_entry(
                    db=db, client_id=client_id, event_type="TRADE_REJECTED_BY_USER",
                    actor="USER", details={"proposal_id": pending}, session_id=session["session_id"],
                )
            events.append(await self._say("Understood — the trade proposal was cancelled and nothing was sent to the broker.", db, client_id))
            return events

        # If user asks another query while proposal is pending, answer it but keep proposal active
        return await self._advising_turn(db, session, text)

    # -- advising ----------------------------------------------------- #
    async def _advising_turn(self, db: AsyncSession, session: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
        client_id = session.get("client_id")
        user_id = session["user_id"]
        events: List[Dict[str, Any]] = []
        lowered = text.lower()

        if client_id:
            for b in await self.c.bias.detect_bias(client_id=client_id, user_message=text, db=db):
                events.append(
                    _event(
                        "bias_alert", "BehavioralBias", b.intervention,
                        bias_type=b.bias_type, severity=b.severity, confidence=b.confidence,
                        cool_off_recommended=b.cool_off_recommended,
                    )
                )

        pending = session.get("pending_proposal_id")

        if pending and APPROVE_RE.match(text):
            events += await self.handle_trade_approval(db, user_id, pending, approved=True, session_id=session["session_id"])
            session.pop("pending_proposal_id", None)
            session["stage"] = SessionStage.ADVICE_GENERATION.value
        elif pending and REJECT_RE.match(text):
            await self.c.cache.delete(f"proposal:{pending}")
            session.pop("pending_proposal_id", None)
            session["stage"] = SessionStage.ADVICE_GENERATION.value
            if client_id:
                await self.c.audit.log_audit_entry(
                    db=db, client_id=client_id, event_type="TRADE_REJECTED_BY_USER",
                    actor="USER", details={"proposal_id": pending}, session_id=session["session_id"],
                )
            events.append(await self._say("Understood — the trade proposal was cancelled and nothing was sent to the broker.", db, client_id))
        elif (m := TRADE_RE.search(text)):
            side, qty, symbol = m.group(1).upper(), float(m.group(2)), m.group(3).upper()
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting trades.", db, None))
            else:
                events += await self.propose_trade(db, user_id, client_id, symbol, side, qty, session=session)
        elif REBALANCE_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting rebalancing.", db, None))
            else:
                events += await self._rebalance(db, client_id, session)
        elif COMPARE_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling before comparing products.", db, None))
            else:
                symbols = [t for t in TICKER_RE.findall(text) if t not in STOPWORDS_TICKER]
                events += await self._compare(db, client_id, symbols, bonds="bond" in lowered)
        elif HEALTH_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling to review your portfolio health.", db, None))
            else:
                session["stage"] = SessionStage.HEALTH_MONITORING.value
                events += await self._health(db, client_id)
                session["stage"] = SessionStage.ADVICE_GENERATION.value
        elif ALLOCATION_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting an allocation recommendation.", db, None))
            else:
                events += await self.recommend_allocation(db, client_id)
        elif (m_quote := QUOTE_RE.search(text)):
            symbol = m_quote.group(1).upper()
            events += await self._quote(db, client_id, symbol)
        elif MACRO_RE.search(text):
            events += await self._macro(db, client_id)
        else:
            events.append(await self._say(await self._general_reply(db, client_id, text), db, client_id))

        return events

    # ------------------------------------------------------------------ #
    # Market Data Dispatchers
    # ------------------------------------------------------------------ #
    async def _quote(self, db: AsyncSession, client_id: Optional[str], symbol: str) -> List[Dict[str, Any]]:
        try:
            q = await self.c.market.get_quote(symbol)
            txt = (
                f"Quote for {q.symbol}: Price ${q.price:.2f} (Bid: ${q.bid:.2f}, Ask: ${q.ask:.2f}, "
                f"Volume: {q.volume:,}). Data as of {q.as_of}."
            )
            return [await self._say(txt, db, client_id, agent="MarketData", quote=q.model_dump(mode="json"))]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Market quote lookup failed: %s", exc)
            return [await self._say(f"Market quote for {symbol} is currently unavailable.", db, client_id, agent="MarketData")]

    async def _macro(self, db: AsyncSession, client_id: Optional[str]) -> List[Dict[str, Any]]:
        try:
            macro = await self.c.market.get_macro_context()
            curve = await self.c.market.get_yield_curve()
            curve_10y = curve.get("10Y", "N/A")
            gdp = macro.get("gdp_growth", "N/A")
            cpi = macro.get("cpi", "N/A")
            txt = (
                f"Macroeconomic Context: GDP Growth: {gdp}%, CPI: {cpi}%, "
                f"10-Year Treasury Yield: {curve_10y}%. Monetary and economic indicators remain balanced."
            )
            return [await self._say(txt, db, client_id, agent="MarketData", macro=macro, yield_curve=curve)]
        except Exception as exc:  # noqa: BLE001
            logger.warning("Macro data lookup failed: %s", exc)
            return [await self._say("Macroeconomic and Treasury data is currently unavailable.", db, client_id, agent="MarketData")]

    # ------------------------------------------------------------------ #
    # Rebalance Flow
    # ------------------------------------------------------------------ #
    async def _rebalance(self, db: AsyncSession, client_id: str, session: Dict[str, Any]) -> List[Dict[str, Any]]:
        profile = await self.c.profiler.get_profile(client_id, db=db)
        if profile is None:
            raise HTTPException(status_code=404, detail="Client profile not found")
        portfolio = await self.c.portfolio.get_portfolio(db, client_id)
        result = await self.c.allocation.generate_allocation(
            profile, include_frontier=True, current_positions=portfolio["position_qty"] or None, db=db
        )

        events: List[Dict[str, Any]] = []
        if result.rebalance_plan and result.rebalance_plan.trades:
            first_trade = result.rebalance_plan.trades[0]
            proposal = await self.create_trade_proposal(
                db=db,
                client_id=client_id,
                symbol=first_trade.symbol,
                side=first_trade.side,
                qty=first_trade.qty,
                session_id=session.get("session_id"),
            )
            session["pending_proposal_id"] = proposal["proposal_id"]
            session["stage"] = SessionStage.PROPOSAL_REVIEW.value
            txt = (
                f"Portfolio drift detected. Recommended rebalancing step: {first_trade.side} "
                f"{first_trade.qty:g} {first_trade.symbol} to align with target allocation. "
                f"Reply 'approve' to execute within 15 minutes, or 'cancel'."
            )
            events.append(await self._say(txt, db, client_id, agent="AllocationEngine", kind="trade_proposal", proposal=proposal))
        else:
            txt = "Your portfolio allocation is currently well-balanced within allowable tolerance bands. No rebalance is needed at this time."
            events.append(await self._say(txt, db, client_id, agent="AllocationEngine"))
        return events

    # ------------------------------------------------------------------ #
    # Specialised flows
    # ------------------------------------------------------------------ #
    @staticmethod
    def _equity_weight(weights: Dict[str, float]) -> float:
        return sum(w for s, w in weights.items() if s.upper() in EQUITY_SYMBOLS)

    async def recommend_allocation(self, db: AsyncSession, client_id: str) -> List[Dict[str, Any]]:
        profile = await self.c.profiler.get_profile(client_id, db=db)
        if profile is None:
            raise HTTPException(status_code=404, detail="Client profile not found")
        portfolio = await self.c.portfolio.get_portfolio(db, client_id)
        result = await self.c.allocation.generate_allocation(
            profile, include_frontier=True, current_positions=portfolio["position_qty"] or None, db=db
        )

        # Gate explanation text through compliance output filter before recommendation validation
        gated_explanation = await self.gate_text(result.explanation, db, client_id)

        equity_weight = self._equity_weight(result.weights)
        rec = {
            "risk_level": round(1 + 9 * equity_weight, 2),
            "equity_weight": equity_weight,
            "weights": result.weights,
            "text": gated_explanation,
        }
        events: List[Dict[str, Any]] = []
        try:
            check = await self.c.compliance.check_recommendation(db, client_id, rec, profile)
            events.append(_event("compliance_check", "ComplianceGuard", passed=check.passed, details=check.to_dict()))
        except ComplianceViolationError as exc:
            events.append(
                _event(
                    "compliance_check", "ComplianceGuard",
                    "Recommendation blocked by compliance rules.",
                    passed=False, violations=[v.to_dict() for v in exc.violations],
                )
            )
            return events

        weights_txt = ", ".join(f"{s} {w:.1%}" for s, w in sorted(result.weights.items(), key=lambda kv: -kv[1]) if w > 0.001)
        text = f"Recommended allocation ({result.solver_method}): {weights_txt}.\n\n{gated_explanation}"
        events.append(
            await self._say(
                text, db, client_id, agent="AllocationEngine",
                weights=result.weights, metrics=result.metrics,
                feature_attributions=result.feature_attributions,
                frontier=[p.model_dump() for p in (result.frontier or [])],
                rebalance_plan=result.rebalance_plan.model_dump() if result.rebalance_plan else None,
            )
        )
        await self.c.audit.log_audit_entry(
            db=db, client_id=client_id, event_type="RECOMMENDATION_GENERATED",
            actor="AGENT:allocation_engine", details={"weights": result.weights, "solver": result.solver_method},
        )
        return events

    async def _compare(self, db: AsyncSession, client_id: str, symbols: List[str], bonds: bool = False) -> List[Dict[str, Any]]:
        if len(symbols) < 2:
            return [await self._say("Tell me at least two tickers to compare, e.g. 'compare SPY VTI QQQ'.", db, client_id)]
        profile = await self.c.profiler.get_profile(client_id, db=db)
        fn = self.c.comparison.compare_bonds if bonds else self.c.comparison.compare_etfs
        report = await fn(symbols, profile=profile, client_id=client_id)
        ranked = "; ".join(f"#{p.rank} {p.symbol} ({p.composite_score:.1f}/10)" for p in report.ranked_products) or "none suitable"
        text = f"Ranking for you: {ranked}. Best fit: {report.winner_symbol}.\n\n{report.summary_rationale}"
        return [await self._say(text, db, client_id, agent="ProductComparison", report=report.model_dump())]

    async def _health(self, db: AsyncSession, client_id: str) -> List[Dict[str, Any]]:
        await self.c.bias.record_portfolio_check(client_id, db=db)
        report = await self.c.health.generate_health_report(db, client_id)
        n = report.narrative
        text = "\n".join([n.executive_summary, n.drift_diagnosis, *n.actionable_recommendations])
        return [
            await self._say(str(text), db, client_id, agent="HealthReport", kind="portfolio_update",
                            report=report.model_dump(mode="json"))
        ]

    async def _general_reply(self, db: AsyncSession, client_id: Optional[str], text: str) -> str:
        key = os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_api_key_here":
            try:
                from openai import AsyncOpenAI

                resp = await AsyncOpenAI(api_key=key).chat.completions.create(
                    model=os.getenv("OPENAI_MODEL", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": (
                            "You are a cautious, non-discretionary wealth advisor. Never promise returns, "
                            "never say guaranteed or risk-free, never execute trades. Be concise."
                        )},
                        {"role": "user", "content": text},
                    ],
                    temperature=0.3,
                )
                return resp.choices[0].message.content.strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("General reply LLM failed: %s", exc)
        return (
            "I can build an allocation ('recommend a portfolio'), compare funds ('compare SPY VTI QQQ'), "
            "review portfolio health ('how is my portfolio?'), or propose a trade ('buy 10 BND')."
        )

    # ------------------------------------------------------------------ #
    # Milestone 5 Canonical Trade Proposal & Approval
    # ------------------------------------------------------------------ #
    async def create_trade_proposal(
        self,
        db: AsyncSession,
        client_id: str,
        symbol: str,
        side: str,
        qty: float,
        session_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        symbol, side = symbol.strip().upper(), side.strip().upper()
        if side not in ("BUY", "SELL") or qty <= 0 or not symbol:
            raise HTTPException(status_code=422, detail="Invalid trade: need BUY/SELL, positive qty and a symbol")
        proj = await self.c.portfolio.projected_weight(db, client_id, symbol, side, qty)
        proposal = {
            "proposal_id": str(uuid.uuid4()),
            "client_id": client_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": proj["price"],
            "notional_value": proj["notional_value"],
            "projected_weight": proj["projected_weight"],
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_in_seconds": PROPOSAL_TTL_SECONDS,
        }
        await self.c.cache.set_json(f"proposal:{proposal['proposal_id']}", proposal, expire=PROPOSAL_TTL_SECONDS)
        await self.c.audit.log_audit_entry(
            db=db, client_id=client_id, event_type="TRADE_PROPOSED",
            actor="AGENT:orchestrator", details=proposal,
        )
        if session_id:
            try:
                session = await self.c.cache.get_json(key_session(session_id))
                if session:
                    session["pending_proposal_id"] = proposal["proposal_id"]
                    session["stage"] = SessionStage.PROPOSAL_REVIEW.value
                    await self._save_session(session)
            except Exception as exc:
                logger.warning("Failed to link proposal to session %s: %s", session_id, exc)
        return proposal

    # Backward-compatible facade for create_proposal
    async def create_proposal(
        self, db: AsyncSession, client_id: str, symbol: str, side: str, qty: float
    ) -> Dict[str, Any]:
        return await self.create_trade_proposal(db, client_id, symbol, side, qty)

    async def propose_trade(
        self, db: AsyncSession, user_id: str, client_id: str, symbol: str, side: str, qty: float,
        session: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        sid = session.get("session_id") if session else None
        proposal = await self.create_trade_proposal(db, client_id, symbol, side, qty, session_id=sid)
        if session is not None:
            session["pending_proposal_id"] = proposal["proposal_id"]
            session["stage"] = SessionStage.PROPOSAL_REVIEW.value
        text = (
            f"Proposed order: {proposal['side']} {proposal['qty']:g} {proposal['symbol']} at about "
            f"${proposal['price']:.2f} (~${proposal['notional_value']:,.2f}). Reply 'approve' to execute it in the "
            f"paper-trading account within 15 minutes, or 'cancel'. Nothing is sent until you approve."
        )
        return [await self._say(text, db, client_id, kind="trade_proposal", proposal=proposal)]

    async def handle_trade_approval(
        self,
        db: AsyncSession,
        user_id: str,
        proposal_id: str,
        approved: bool,
        session_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        proposal = await self.c.cache.get_json(f"proposal:{proposal_id}")
        if not proposal:
            raise HTTPException(status_code=404, detail="Trade proposal not found or expired (15 minute window)")
        client_id = proposal["client_id"]

        profile = await self.c.profiler.get_profile(client_id, db=db)
        if profile is None or str(profile.user_id or "") != str(user_id):
            raise HTTPException(status_code=403, detail="Proposal does not belong to this user")

        approval_ts = datetime.now(timezone.utc)
        events: List[Dict[str, Any]] = []
        if approved:
            events.append(_event("trade_approved", "User", f"Approved {proposal['side']} {proposal['qty']:g} {proposal['symbol']}", proposal=proposal))

        trade = {
            "user_approved": approved,
            "user_approved_at": approval_ts.isoformat(),
            "symbol": proposal["symbol"],
            "side": proposal["side"],
            "qty": proposal["qty"],
            "price": proposal["price"],
            "notional_value": proposal["notional_value"],
            "projected_weight": proposal["projected_weight"],
        }
        try:
            check = await self.c.compliance.check_trade(db, client_id, trade, profile)
            events.append(_event("compliance_check", "ComplianceGuard", passed=check.passed, details=check.to_dict()))
        except ComplianceViolationError as exc:
            events.append(
                _event("compliance_check", "ComplianceGuard", "Trade blocked by compliance rules.",
                       passed=False, violations=[v.to_dict() for v in exc.violations])
            )
            raise TradeBlocked(exc.violations, events) from exc

        try:
            result = await self.c.execution.execute_trade(
                db=db, client_id=client_id, proposal_id=proposal_id,
                symbol=proposal["symbol"], side=proposal["side"], qty=proposal["qty"],
                approved=approved, approval_timestamp=approval_ts,
            )
        except (UnapprovedTradeError, ExpiredApprovalError, KYCUnverifiedError, DuplicateTradeError, ExecutionError) as exc:
            raise TradeBlocked([], events, reason=str(exc), error_type=type(exc).__name__) from exc

        await self.c.cache.delete(f"proposal:{proposal_id}")
        if session_id:
            try:
                session = await self.c.cache.get_json(key_session(session_id))
                if session:
                    session.pop("pending_proposal_id", None)
                    session["stage"] = SessionStage.ADVICE_GENERATION.value
                    await self._save_session(session)
            except Exception:
                pass

        events.append(
            await self._say(
                f"Order {result.status}: {result.side} {result.qty:g} {result.symbol}"
                + (f" at ${result.filled_price:.2f}" if result.filled_price else "")
                + (" (simulated paper fill)." if result.dry_run else " via Alpaca paper trading."),
                db, client_id, agent="ExecutionModule", kind="trade_filled", execution=result.model_dump(mode="json"),
            )
        )
        pf = await self.c.portfolio.get_portfolio(db, client_id, persist_snapshot=True)
        events.append(_event("portfolio_update", "PortfolioService", portfolio={k: v for k, v in pf.items() if k not in ("prices", "position_qty")}))
        return events

    # Backward-compatible facade for execute_proposal
    async def execute_proposal(
        self, db: AsyncSession, user_id: str, proposal_id: str, approved: bool
    ) -> List[Dict[str, Any]]:
        return await self.handle_trade_approval(db, user_id, proposal_id, approved)


class TradeBlocked(Exception):
    """Raised when compliance or execution gates reject a trade."""

    def __init__(self, violations: list, events: list, reason: str = "", error_type: str = "ComplianceViolationError") -> None:
        self.violations = violations
        self.events = events
        self.reason = reason or "Trade blocked by compliance rules"
        self.error_type = error_type
        super().__init__(self.reason)

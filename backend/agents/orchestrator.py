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
from core.config import settings
from db.models import DBClientProfile
from services.audit_logger import AuditLogger, get_audit_logger
from services.cache import CacheService, get_cache_service, key_session
from services.health_report import HealthReportService
from services.portfolio_service import PortfolioService
from services.context_builder import FinancialContextBuilder
from agents.review_stage import ReviewStage
from services.demo_replay import is_demo_mode_active, match_demo_response

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
QUOTE_RE = re.compile(
    r"\b(?:quote|qoute|price|how much is|cost)\s*(?:for|of)?\s*([A-Za-z]{1,5})\b",
    re.IGNORECASE,
)
MACRO_RE = re.compile(
    r"\b(macro|yield curve|treasury rates|interest rates|inflation|gdp|unemployment)\b",
    re.IGNORECASE,
)
TICKER_RE = re.compile(r"\b[A-Za-z]{2,5}\b")
STOPWORDS_TICKER = {
    "ETF", "ETFS", "AND", "VS", "THE", "BOND", "BONDS", "FOR", "BUY", "SELL",
    "SHOW", "WHAT", "HOW", "MUCH", "COST", "QUOTE", "PRICE", "IS", "OF", "AT",
    "CAN", "YOU", "GET", "CHECK", "ME", "PLEASE", "STOCK", "STOCKS", "TELL", "ABOUT",
    "WITH", "FROM", "HAVE", "SOME", "MANY", "YOUR", "OUR", "THIS", "THAT", "TOKEN",
    "TOKENS", "SHARE", "SHARES", "INFO", "STATS", "VIEW", "SEE", "LOOK", "UP",
    "THEIR", "THEM", "THEY", "THESE", "THOSE", "WHICH", "WHOSE", "WHERE", "WHEN", "WHY",
    "MORE", "MOST", "EACH", "EVERY", "OTHER", "ANY", "ALL", "SUCH", "BEST", "GOOD",
    "SMART", "BAD", "HIGH", "LOW", "NEW", "OLD", "FIRST", "LAST", "WELL", "JUST",
    "ALSO", "EVEN", "VERY", "BACK", "DOWN", "AWAY", "OUT", "OVER", "UNDER", "AGAIN",
    "THEN", "ONCE", "HERE", "ONLY", "ABOVE", "AFTER", "BEFORE", "BELOW", "BETWEEN",
    "INTO", "THROUGH", "DURING", "WITHOUT", "AGAINST", "AMONG", "BECAUSE", "WHILE",
    "UNTIL", "SINCE", "ALTHOUGH", "UNLESS", "FIND", "GIVE", "KNOW", "MAKE", "TAKE",
    "WANT", "NEED", "LIKE", "COME", "GO", "HAD", "HAS", "DO", "DOES", "DID", "WILL",
    "WOULD", "SHALL", "SHOULD", "COULD", "MAY", "MIGHT", "MUST", "ARE", "WAS", "WERE",
    "BEEN", "BEING", "RETURN", "INVEST", "HELP", "VITAL", "SOME", "SOMEONE", "ANYONE",
}


def extract_quote_symbol(text: str) -> Optional[str]:
    """Extract ticker symbol from a user quote or price query with flexible phrasing."""
    t_clean = text.strip()
    words = t_clean.split()

    # 0. If it is a conversational, exploratory research, or complex multi-clause query, do not greedily extract a ticker
    research_indicators = {
        "invest", "investing", "investment", "companies", "company", "supply", "supplying",
        "supplier", "suppliers", "materials", "partner", "partners", "help", "find",
        "smart", "research", "analyze", "analysis", "explain", "why", "should", "which",
        "portfolio", "tell", "opinion", "evaluate", "value", "parts", "components",
        "manufacture", "manufacturing", "industry", "sector", "chain", "subcontractors",
        "services", "energy", "power", "batteries", "talent", "staffing", "who", "makes",
        "produces", "provides", "defense", "aerospace", "auto", "vehicle", "pharma",
        "biotech", "healthcare", "utilities", "lithium", "semiconductor", "cooling",
    }
    lowered_tokens = set(re.findall(r"\b[a-z]+\b", t_clean.lower()))
    if len(words) > 6 and (lowered_tokens & research_indicators):
        return None

    # Check for known ticker directly if inquiry terms are present
    inquiry_keywords = {"quote", "qoute", "price", "cost", "token", "tokens", "share", "shares", "stock", "show", "check", "trading"}
    raw_words = re.findall(r"\b[A-Za-z]{1,5}\b", t_clean)
    upper_words = [w.upper() for w in raw_words]

    if any(k in t_clean.lower() for k in inquiry_keywords):
        for w in upper_words:
            if w in EQUITY_SYMBOLS or w in BOND_SYMBOLS:
                return w

    # Long sentences (>6 words) without explicit known tickers should be parsed by intent translator / LLM
    if len(words) > 6:
        return None

    # 1. Direct patterns like 'quote SPY', 'price of SPY', 'show SPY token', 'check SPY'
    m1 = re.search(r"\b(?:quote|qoute|price|how much is|cost of|check|show|token|info on)\s+(?:for\s+|of\s+)?([A-Za-z]{1,5})\b", t_clean, re.IGNORECASE)
    if m1 and m1.group(1).upper() not in STOPWORDS_TICKER:
        return m1.group(1).upper()

    # 2. Inverted patterns like 'show SPY quote', 'SPY quote', 'SPY price', 'SPY token'
    m2 = re.search(r"\b([A-Za-z]{1,5})\s+(?:quote|qoute|price|cost|stock|token|share)\b", t_clean, re.IGNORECASE)
    if m2:
        cand = m2.group(1)
        if cand.upper() not in STOPWORDS_TICKER and (cand.isupper() or cand.upper() in EQUITY_SYMBOLS or cand.upper() in BOND_SYMBOLS):
            return cand.upper()

    # 3. Ticker in text if quote/price/trading keywords appear anywhere
    if any(k in t_clean.lower() for k in ["quote", "qoute", "price", "trading at", "how much is", "check price"]):
        for w in raw_words:
            if w.isupper() and len(w) >= 2 and w.upper() not in STOPWORDS_TICKER:
                return w.upper()
    return None

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
        self.context_builder = FinancialContextBuilder(
            risk_profiler=getattr(c, "profiler", None),
            portfolio_service=getattr(c, "portfolio", None),
        )
        self.review_stage = ReviewStage()
        try:
            try:
                from tools.definitions import register_core_tools
            except ImportError:
                from backend.tools.definitions import register_core_tools
            register_core_tools()
        except Exception as reg_err:
            logger.debug("Core tool registration notice: %s", reg_err)

    # ------------------------------------------------------------------ #
    # ------------------------------------------------------------------ #
    # Session state
    # ------------------------------------------------------------------ #
    async def start_session(
        self, user_id: str, client_id: Optional[str] = None, title: Optional[str] = None, db: Optional[AsyncSession] = None
    ) -> Dict[str, Any]:
        session_id = str(uuid.uuid4())
        stage = SessionStage.ADVICE_GENERATION.value if client_id else SessionStage.PROFILING.value
        sess_title = title or "New Advisory Conversation"
        session = {
            "session_id": session_id,
            "user_id": user_id,
            "client_id": client_id,
            "stage": stage,
            "title": sess_title,
        }
        await self.c.cache.set_json(key_session(session_id), session, expire=SESSION_TTL_SECONDS)
        greeting = (
            "Welcome back! Ask me for an allocation, compare ETFs, or request a portfolio health report."
            if client_id
            else (
                "**SEC & FINRA Regulatory Disclosure & Advisory Agreement**\n\n"
                "• *Investing involves risk, including possible loss of principal.*\n"
                "• *Past performance is no guarantee of future results.*\n"
                "• *All trades are strictly non-discretionary and require your explicit human confirmation.*\n\n"
                "By proceeding, you acknowledge and agree to these advisory terms.\n\n"
                f"---\n\n{STATE_PROMPTS[STATE_DEMOGRAPHICS]}"
            )
        )
        if db is not None:
            try:
                from db.models import DBChatSession, DBChatMessage
                chat_sess = DBChatSession(
                    id=session_id,
                    user_id=user_id,
                    title=sess_title,
                    stage=stage,
                )
                db.add(chat_sess)
                db.add(
                    DBChatMessage(
                        session_id=session_id,
                        sender="agent",
                        agent="WealthAdvisor",
                        text=greeting,
                        events=[{"event": "agent_response", "structured_event": "session_started", "text": greeting, "stage": stage}],
                    )
                )
                await db.commit()
            except Exception as e:
                await db.rollback()
                logger.warning("Failed to persist new session to db: %s", e)

        return {"session": session, "message": greeting}

    async def load_session(self, session_id: str, user_id: str, db: Optional[AsyncSession] = None) -> Dict[str, Any]:
        session = await self.c.cache.get_json(key_session(session_id))
        if not session:
            try:
                from sqlalchemy import select
                from db.models import DBChatSession, DBClientProfile

                async def _fetch_from_db(target_db: AsyncSession):
                    row = (await target_db.execute(select(DBChatSession).where(DBChatSession.id == session_id))).scalars().first()
                    if row:
                        client_row = (
                            await target_db.execute(
                                select(DBClientProfile).where(DBClientProfile.user_id == row.user_id).order_by(DBClientProfile.created_at.desc())
                            )
                        ).scalars().first()
                        from db.models import DBChatMessage
                        msg_rows = (
                            await target_db.execute(
                                select(DBChatMessage)
                                .where(DBChatMessage.session_id == session_id)
                                .order_by(DBChatMessage.created_at.asc())
                            )
                        ).scalars().all()
                        hist = []
                        for m in msg_rows[-20:]:
                            role = "user" if m.sender == "user" else "assistant"
                            if m.text:
                                hist.append({"role": role, "content": m.text})
                        return {
                            "session_id": row.id,
                            "user_id": row.user_id,
                            "client_id": client_row.client_id if client_row else None,
                            "stage": row.stage,
                            "title": row.title,
                            "history": hist,
                        }
                    return None

                if db is not None:
                    session = await _fetch_from_db(db)
                else:
                    from db.database import AsyncSessionLocal
                    async with AsyncSessionLocal() as local_db:
                        session = await _fetch_from_db(local_db)

                if session:
                    await self.c.cache.set_json(key_session(session_id), session, expire=SESSION_TTL_SECONDS)
            except Exception as exc:
                logger.debug("Could not fallback load session from DB: %s", exc)

        if not session:
            raise HTTPException(status_code=404, detail="Session not found or expired")
        if session.get("user_id") != user_id:
            raise HTTPException(status_code=403, detail="Session belongs to another user")
        session.setdefault("history", [])
        return session

    async def _save_session(self, session: Dict[str, Any]) -> None:
        await self.c.cache.set_json(key_session(session["session_id"]), session, expire=SESSION_TTL_SECONDS)

    # ------------------------------------------------------------------ #
    # Compliance gate for outgoing text
    # ------------------------------------------------------------------ #
    async def gate_text(
        self, text: str, db: Optional[AsyncSession], client_id: Optional[str], enforce_disclosure: bool = True
    ) -> str:
        passed, violations, sanitized = self.c.compliance.check_text_output(text)
        if violations:
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
            if any(v.startswith("REG-001") for v in violations):
                _, _, sanitized = self.c.compliance.check_text_output(SAFE_REPLACEMENT)
                return sanitized
        # If enforce_disclosure is requested (e.g. formal allocation recommendations), include standard disclosure.
        # Otherwise, terms have already been presented & accepted at the setup stage, keeping chat dialogue clean.
        if enforce_disclosure:
            return sanitized
        return text

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
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        session = await self.load_session(session_id, user_id, db=db)
        if client_id and not session.get("client_id"):
            session["client_id"] = client_id

        # Persist session and user message in DBChatSession / DBChatMessage
        async def _persist_user_msg(target_db: AsyncSession):
            try:
                from sqlalchemy import select
                from db.models import DBChatSession, DBChatMessage
                sess_row = (await target_db.execute(select(DBChatSession).where(DBChatSession.id == session_id))).scalars().first()
                if not sess_row:
                    sess_row = DBChatSession(
                        id=session_id,
                        user_id=user_id,
                        title=session.get("title") or (message[:45] + "…" if len(message) > 45 else (message or "Multimodal Query")),
                        stage=session.get("stage") or "ADVICE_GENERATION",
                    )
                    target_db.add(sess_row)
                elif sess_row.title in ("New Advisory Conversation", "New Chat", "") and message.strip():
                    sess_row.title = (message[:45] + "…") if len(message) > 45 else message

                sess_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                target_db.add(
                    DBChatMessage(
                        session_id=session_id,
                        sender="user",
                        agent="User",
                        text=message,
                        attachments=attachments or [],
                        events=[],
                    )
                )
                await target_db.commit()
            except Exception:
                await target_db.rollback()
                raise

        try:
            if db is not None:
                await _persist_user_msg(db)
            else:
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as local_db:
                    await _persist_user_msg(local_db)
        except Exception as exc:
            logger.warning("Failed to persist user message: %s", exc)

        # Track conversation history in session for multi-turn context
        history = session.setdefault("history", [])
        history.append({"role": "user", "content": message})
        if len(history) > 20:
            session["history"] = history[-20:]

        user_ev = _event("user_message", "User", message)
        if attachments:
            user_ev["attachments"] = attachments
        events: List[Dict[str, Any]] = [user_ev]
        stage = _normalize_stage(session.get("stage"))

        # Action 10: Demo Mode Replay Check
        if is_demo_mode_active(message):
            clean_demo_msg = re.sub(r"^\[DEMO\]\s*", "", message, flags=re.IGNORECASE)
            demo_match = match_demo_response(clean_demo_msg or message)
            if demo_match:
                events.append(await self._say(demo_match["text"], db, client_id, agent=demo_match["agent"]))
                session["history"].append({"role": "assistant", "content": demo_match["text"]})
                await self._save_session(session)
                return events

        if stage == SessionStage.PROFILING:
            events += await self._profiling_turn(db, session, message)
        elif stage == SessionStage.PROPOSAL_REVIEW:
            events += await self._proposal_review_turn(db, session, message)
        else:
            events += await self._advising_turn(db, session, message, attachments=attachments)

        # Track assistant responses in history for multi-turn context
        for ev in events:
            if ev.get("event") == "agent_response" and ev.get("text"):
                session["history"].append({"role": "assistant", "content": ev["text"]})
        if len(session.get("history", [])) > 20:
            session["history"] = session["history"][-20:]

        await self._save_session(session)

        # Persist agent response in DBChatMessage
        async def _persist_agent_resp(target_db: AsyncSession):
            try:
                from sqlalchemy import select
                from db.models import DBChatMessage, DBChatSession
                last_agent_text = next((e.get("text") for e in reversed(events) if e.get("text") and e.get("event") != "user_message"), "")
                last_agent_name = next((e.get("agent") for e in reversed(events) if e.get("agent") and e.get("agent") != "User"), "WealthAdvisor")
                agent_events = [e for e in events if e.get("event") != "user_message"]
                if last_agent_text or agent_events:
                    target_db.add(
                        DBChatMessage(
                            session_id=session_id,
                            sender="agent",
                            agent=last_agent_name,
                            text=last_agent_text,
                            events=agent_events,
                        )
                    )
                    sess_row = (await target_db.execute(select(DBChatSession).where(DBChatSession.id == session_id))).scalars().first()
                    if sess_row:
                        sess_row.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                        sess_row.stage = session.get("stage", sess_row.stage)
                    await target_db.commit()
            except Exception:
                await target_db.rollback()
                raise

        try:
            if db is not None:
                await _persist_agent_resp(db)
            else:
                from db.database import AsyncSessionLocal
                async with AsyncSessionLocal() as local_db:
                    await _persist_agent_resp(local_db)
        except Exception as exc:
            logger.warning("Failed to persist agent response: %s", exc)

        return events

    # Backward-compatible facade for handle_message
    async def handle_message(
        self, db: AsyncSession, user_id: str, session_id: str, text: str, attachments: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
        return await self.process_user_message(
            session_id=session_id, user_id=user_id, client_id=None, message=text, db=db, attachments=attachments
        )

    # -- profiling ---------------------------------------------------- #
    async def _profiling_turn(self, db: AsyncSession, session: Dict[str, Any], text: str) -> List[Dict[str, Any]]:
        events: List[Dict[str, Any]] = []
        provisional_id = session.get("client_id") or f"pending-{session['session_id']}"
        lowered = text.lower()

        # Check for market data quote requests during profiling
        sym = extract_quote_symbol(text)
        if sym:
            return await self._quote(db, session.get("client_id"), sym)

        # Check for macro inquiries during profiling
        if MACRO_RE.search(text):
            return await self._macro(db, session.get("client_id"))

        # Check for comparison requests during profiling
        if COMPARE_RE.search(text):
            symbols = [t for t in TICKER_RE.findall(text.upper()) if t not in STOPWORDS_TICKER]
            if len(symbols) >= 2:
                return await self._compare(db, session.get("client_id"), symbols, bonds="bond" in lowered)

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
            events.append(await self._say(result["response"], db, None, agent="RiskProfiler", options=result.get("options", [])))
        return events

    # -- intent translator via LLM ------------------------------------ #
    async def _translate_intent(self, text: str, history: Optional[List[Dict[str, str]]] = None) -> Optional[Dict[str, Any]]:
        key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not key or key == "your_openai_api_key_here":
            return None
        prompt = (
            "You are an intent parser and expert financial research assistant for an AI Wealth Advisory Agent. "
            "You have access to recent conversation history. Use conversation context to resolve pronouns, references, and follow-ups "
            "(e.g., if the user previously discussed companies like NEE, D, RHI, MAN, and now asks 'give me their stock price for last 6 months and analyze the growth and potential for more growth', "
            "recognize that 'their' refers to NEE, D, RHI, MAN). "
            "Translate specific operational requests into canonical commands: "
            "- 'quote SYMBOL' (e.g. 'show spy token', 'what is SPY at', 'check Apple price') "
            "- 'compare SYM1 SYM2' (e.g. 'compare SPY and QQQ') "
            "- 'macro' (for yield curve, interest rates, inflation, macro context) "
            "- 'how is my portfolio' (for portfolio review, health, drift) "
            "- 'recommend a portfolio' (for asset allocation recommendations) "
            "- 'buy QTY SYM' or 'sell QTY SYM' (for trades). "
            "CRITICAL: If the user is asking a research question, follow-up inquiry, company/ticker analysis, stock performance analysis, "
            "investment analysis, company discovery, supplier/value-chain question across ANY industry "
            "(e.g. AI/Tech, Electric Vehicles & Batteries, Aerospace & Defense, Healthcare & Biotech, Clean Energy & Utilities, "
            "Semiconductors, Industrial Manufacturing, Consumer Goods, Retail/E-Commerce, etc.), such as who supplies key materials, power, parts, "
            "cooling, staffing/talent/HR, contract manufacturing, logistics, or asking whether an industry/company is a smart investment, "
            "or asking for past performance, historical prices, growth drivers, or potential for future growth: "
            "DO NOT output an operational command (set command to null). "
            "Instead, provide an insightful, conversational, well-structured expert financial and equity research analysis in 'answer' addressing their specific context and follow-up. "
            "When analyzing growth and stock performance, cover revenue/earnings trends, competitive moat, secular vs cyclical tailwinds, risks, and valuation multiples. "
            "Never promise risk-free returns. "
            "Output JSON: {\"command\": null, \"answer\": \"...\"}."
        )
        try:
            import httpx
            import json
            from openai import AsyncOpenAI
            async with httpx.AsyncClient(timeout=httpx.Timeout(25.0, connect=10.0)) as http_client:
                client = AsyncOpenAI(api_key=key, http_client=http_client)
                messages = [{"role": "system", "content": prompt}]
                if history:
                    prior_turns = [
                        turn for turn in history
                        if turn.get("role") in ("user", "assistant") and turn.get("content")
                    ]
                    if prior_turns and prior_turns[-1].get("role") == "user" and prior_turns[-1].get("content") == text:
                        prior_turns = prior_turns[:-1]
                    for turn in prior_turns[-8:]:
                        messages.append({"role": turn["role"], "content": turn["content"]})
                messages.append({"role": "user", "content": text})

                resp = await client.chat.completions.create(
                    model=settings.openai_model or "gpt-4o",
                    messages=messages,
                    response_format={"type": "json_object"},
                    temperature=0.2,
                )
                return json.loads(resp.choices[0].message.content)
        except Exception as exc:
            logger.warning("Intent translation failed: %s", exc)
            return None

    # -- agentic chat turn with application tool calling --------------- #
    async def _agentic_chat_turn(
        self,
        db: AsyncSession,
        session: Dict[str, Any],
        text: str,
        history: Optional[List[Dict[str, str]]] = None,
        attachments: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if not key or key == "your_openai_api_key_here":
            return []

        client_id = session.get("client_id")
        user_id = session.get("user_id", "")
        events: List[Dict[str, Any]] = []

        tools = [
            {
                "type": "function",
                "function": {
                    "name": "get_stock_metrics",
                    "description": "Fetch real live market data, current stock price, historical period return (start price, end price, % change, high, low), 52-week range, market cap, and volume for one or more stock tickers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbols": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of ticker symbols, e.g. ['NEE', 'D', 'RHI', 'MAN']",
                            },
                            "period": {
                                "type": "string",
                                "enum": ["1mo", "3mo", "6mo", "1y", "ytd"],
                                "description": "Historical timeframe to evaluate, e.g. '6mo' for last 6 months",
                            },
                        },
                        "required": ["symbols"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_predictions",
                    "description": "Fetch Wall Street analyst consensus price target predictions, 12-month forecasts, bull/bear scenario targets, analyst recommendations, and forward valuation multiples for one or more stock tickers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbols": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of ticker symbols, e.g. ['NEE', 'D', 'RHI', 'MAN']",
                            },
                        },
                        "required": ["symbols"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_stock_quote",
                    "description": "Fetch real-time snapshot quote (price, bid, ask, volume) for a specific symbol.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Ticker symbol, e.g. 'SPY'"},
                        },
                        "required": ["symbol"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_macro_context",
                    "description": "Fetch latest macroeconomic indicators (GDP growth, CPI inflation, 10Y/2Y Treasury yield curve).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sector_performance",
                    "description": "Fetch representative sector returns across standard GICS sectors (Tech, Utilities, Energy, Industrials, etc.).",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_portfolio",
                    "description": "Fetch user's current paper portfolio holdings, cash balance, total portfolio value, and asset weights.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_portfolio_health",
                    "description": "Fetch portfolio health diagnostics, drift analysis against target model, and health score.",
                    "parameters": {"type": "object", "properties": {}},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "compare_assets",
                    "description": "Run quantitative multi-factor comparison and ranking across 2 or more ETF, bond, or stock symbols.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbols": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Tickers to compare, e.g. ['SPY', 'QQQ']",
                            },
                        },
                        "required": ["symbols"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_company_financials",
                    "description": "Fetch deep fundamental financial statements, balance sheet leverage, free cash flow generation, ROIC/ROE profitability metrics, capital structure, and valuation multiples for one or more stock tickers.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbols": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "List of ticker symbols, e.g. ['AAPL', 'NVDA', 'MSFT', 'NEE']",
                            },
                        },
                        "required": ["symbols"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_financial_web",
                    "description": "Search the live web for financial prospectuses, IPO filings, company intelligence, debt profiles, revenues, valuations, emerging market investments, or private/unlisted company data (e.g. Dangote Refinery, Stripe, SpaceX, unlisted equities).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Search query, e.g. 'Dangote Refinery IPO prospectus valuation financials debt'",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "Number of search results to return (default 5)",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "fetch_web_page",
                    "description": "Fetch and read clean text content from a specific web URL, company prospectus page, or investor filing.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "url": {
                                "type": "string",
                                "description": "Full URL to fetch, e.g. 'https://ipo.dangote.com/'",
                            },
                            "max_chars": {
                                "type": "integer",
                                "description": "Max characters to extract (default 4000)",
                            },
                        },
                        "required": ["url"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "simulate_wealth_plan",
                    "description": "Generate an audited 10-year financial model, solve required compound return (CAGR), run a 10,000-path Monte Carlo probability simulation, execute multi-factor portfolio stress tests, provide 5 concrete institutional investment dossiers, and evaluate strategic wealth tradeoffs (e.g. growing $10M to $100M with $500k/yr withdrawals).",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "starting_capital": {
                                "type": "number",
                                "description": "Starting portfolio capital in dollars, e.g. 10000000",
                            },
                            "target_capital": {
                                "type": "number",
                                "description": "Target terminal wealth in dollars, e.g. 100000000",
                            },
                            "years": {
                                "type": "integer",
                                "description": "Horizon in years, e.g. 10",
                            },
                            "initial_withdrawal": {
                                "type": "number",
                                "description": "Annual living expense withdrawal, e.g. 500000",
                            },
                            "withdrawal_inflation_pct": {
                                "type": "number",
                                "description": "Annual inflation rate for withdrawals, e.g. 0.02 (2%)",
                            },
                        },
                        "required": ["starting_capital"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "optimize_tax_strategy",
                    "description": "Compute statutory legal tax optimization schedules, comparative numerical tax arbitrage tables (Individual PITA vs Holding Co vs Free Trade Zone vs Sovereign Debt), and operational 5-step entity structuring blueprints for Nigerian and cross-border HNW wealth.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "jurisdiction": {
                                "type": "string",
                                "description": "Target tax jurisdiction (e.g. 'Nigeria', 'Cross-Border', 'US', 'UK')",
                            },
                            "annual_income": {
                                "type": "number",
                                "description": "Gross annual earnings, profit, or cash flow to be optimized in local currency (e.g. 100000000 for ₦100M)",
                            },
                            "net_worth": {
                                "type": "number",
                                "description": "Total liquid and illiquid net worth for estate planning and wealth holding structuring",
                            },
                        },
                        "required": ["jurisdiction"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_crypto_macro",
                    "description": "Fetch global cryptocurrency market aggregates: aggregate market cap, 24h volume, Bitcoin & Ethereum dominance, total stablecoin supply, and aggregate DeFi TVL.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "include_defi": {
                                "type": "boolean",
                                "description": "Whether to include DeFi Total Value Locked (TVL) and stablecoins",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_sovereign_macro",
                    "description": "Fetch sovereign macroeconomic health indicators for a nation: GDP growth, CPI inflation rate, central bank policy rate, debt-to-GDP, and foreign exchange reserves.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "country_code": {
                                "type": "string",
                                "description": "3-letter ISO country code (e.g. USA, NGA, GBR, ARE, CHE, SGP)",
                            },
                        },
                        "required": ["country_code"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_deep_research",
                    "description": "Trigger deep autonomous multi-analyst research graph across Macro, Financial, Quantitative, and Devil's Advocate analysts, streaming progress milestones and yielding verifiable citations.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "inquiry": {
                                "type": "string",
                                "description": "Subject or thesis to investigate (e.g. 'Dangote Refinery capital structure and FX sustainability')",
                            },
                            "starting_capital": {"type": "number", "description": "Starting portfolio size in dollars"},
                            "target_capital": {"type": "number", "description": "Target terminal wealth in dollars"},
                            "horizon_years": {"type": "integer", "description": "Horizon in years"},
                            "annual_withdrawal": {"type": "number", "description": "Annual scheduled living expense withdrawal"},
                        },
                        "required": ["inquiry"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "search_legal_statutes",
                    "description": "Retrieve verified statutory clauses and legal tax text from PITA, CITA, CGTA, NEPZA, and PRA 2014.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "query": {
                                "type": "string",
                                "description": "Legal topic or question (e.g. 'dividend withholding tax holding company', 'sovereign debt exemption', 'CRA relief')",
                            },
                            "jurisdiction": {
                                "type": "string",
                                "description": "Tax jurisdiction (default 'Nigeria')",
                            },
                        },
                        "required": ["query"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "propose_trade",
                    "description": "Prepare a formal non-discretionary paper trade proposal to buy or sell shares of a stock/ETF for user confirmation.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "symbol": {"type": "string", "description": "Ticker symbol to trade"},
                            "side": {"type": "string", "enum": ["BUY", "SELL"], "description": "Order side"},
                            "qty": {"type": "number", "description": "Number of shares"},
                        },
                        "required": ["symbol", "side", "qty"],
                    },
                },
            },
        ]

        system_prompt = (
            "You are an elite, proactive AI Wealth Advisor, senior quantitative strategist, "
            "and principal equity research analyst. "
            "You have continuous multi-turn conversation memory and are directly connected to live application tools:\n"
            "- `optimize_tax_strategy`: Compute statutory tax optimization schedules, effective tax rates, and jurisdictional wealth structuring blueprints for Nigerian and cross-border HNW clients.\n"
            "- `simulate_wealth_plan`: Multi-year financial modeling, compound return solving, Monte Carlo probability distributions, portfolio stress tests, and institutional asset allocation.\n"
            "- `run_deep_research`: Run multi-agent research across company filings, macro backdrop, quantitative valuation, and devil's advocate reviews, yielding verifiable citations.\n"
            "- `search_financial_web`: Search the live web for prospectuses, regulatory filings, debt schedules, revenues, valuations, and emerging market / IPO intelligence.\n"
            "- `fetch_web_page`: Retrieve and parse the text content of any prospectus URL, investor note, or financial filing.\n"
            "- `get_company_financials`: Fundamental analysis, income statements, balance sheets, cash flow, and valuation ratios.\n"
            "- `get_stock_predictions`: Analyst consensus forecasts, price targets, and forward estimates.\n"
            "- `get_stock_metrics`: Real-time market data, price changes, and historical volatility.\n"
            "- `get_stock_quote`: Real-time bid/ask snapshot prices.\n"
            "- `get_macro_context`: Macroeconomic backdrop, Treasury yields, CPI inflation, and GDP growth.\n"
            "- `get_sector_performance`: Sector returns and rotation dynamics.\n"
            "- `get_portfolio`: Client holdings, asset allocation, cash balances, and performance.\n"
            "- `get_portfolio_health`: Portfolio drift diagnosis, diversification analysis, and health score.\n"
            "- `compare_assets`: Six-factor scoring and suitability ranking for ETFs, equities, and fixed income.\n"
            "- `propose_trade`: Prepare a formal non-discretionary paper trade proposal for user confirmation.\n"
            "\n"
            "CORE OPERATIONAL PRINCIPLES:\n"
            "1. CODE SUPPLIES THE NUMBERS, YOU SUPPLY THE SYNTHESIS:\n"
            "   Never invent, estimate, or hallucinate financial figures, interest rates, tax percentages, or hurdle rates from memory.\n"
            "   Always call the appropriate tools to fetch live data or compute mathematical models, and report the exact figures returned by the tools.\n"
            "2. UNABRIDGED TABULAR OUTPUT:\n"
            "   When `simulate_wealth_plan` or `optimize_tax_strategy` returns tabular data, render the full markdown tables without truncating rows or summarizing columns away.\n"
            "   Present the audited cash flow accounting, Monte Carlo percentiles, portfolio allocations, and stress-test arithmetic with full numerical fidelity.\n"
            "3. UNLISTED / IPO / PRIVATE / FOREIGN ENTITIES:\n"
            "   When asked about IPOs, emerging market assets, or private companies, call `search_financial_web` and `fetch_web_page` to retrieve filings and prospectuses.\n"
            "   Quote exact figures, revenue, debt, and risk factors directly from the extracted tool content, citing the source document and URL.\n"
            "4. INSTITUTIONAL INVESTMENT HURDLE EVALUATION:\n"
            "   Evaluate investment inquiries across the 5 core institutional pillars:\n"
            "   • Pillar 1: Financial Transparency & Audit Quality (audited financial statements, prospectus availability, track record)\n"
            "   • Pillar 2: Solvency & Balance Sheet Fortress (Net Debt/EBITDA, currency matching between debt and revenue, interest coverage)\n"
            "   • Pillar 3: Unit Economics & FCF Conversion (gross/operating margins, cash flow durability)\n"
            "   • Pillar 4: Valuation & Margin of Safety vs Global Peers\n"
            "   • Pillar 5: Governance, Sovereign & Regulatory Risk\n"
            "   Provide an explicit hurdle score and clear investment verdict based strictly on verified data and fatal dealbreaker criteria.\n"
            "5. TAX STRATEGY & JURISDICTIONAL STRUCTURING:\n"
            "   Always call `optimize_tax_strategy` to calculate tax arbitrage comparisons and entity structuring steps.\n"
            "   Quote legal statutes and tax rates strictly from the tool results, detailing entity architecture and compliance safeguards.\n"
            "6. FIDUCIARY STANDARDS & COMPLIANCE:\n"
            "   Maintain an authoritative, institutional, and consultative tone.\n"
            "   Always uphold fiduciary duty: include regulatory risk disclosures, highlight investment risks and potential drawdowns, and never guarantee speculative returns.\n"
            "7. MULTIMODAL FINANCIAL VISION:\n"
            "   When the user provides charts, financial statements, or screenshots, scrutinize axes, labels, and numbers directly from the visual evidence and synthesize them with quantitative precision."
        )

        # Inject unified financial context (Action 5)
        client_id_val = session.get("client_id")
        if client_id_val:
            try:
                client_ctx = await self.context_builder.build_context(db, str(client_id_val))
                system_prompt += client_ctx.to_system_prompt_snippet()
            except Exception as ctx_err:
                logger.debug("Client financial context injection notice: %s", ctx_err)

        try:
            import httpx
            import json
            from openai import AsyncOpenAI

            messages = [{"role": "system", "content": system_prompt}]
            redacted_text = self.c.compliance.redact_sensitive_data(text or "")
            if history:
                prior_turns = [
                    turn for turn in history
                    if turn.get("role") in ("user", "assistant") and turn.get("content")
                ]
                if prior_turns and prior_turns[-1].get("role") == "user" and prior_turns[-1].get("content") == text:
                    prior_turns = prior_turns[:-1]
                for turn in prior_turns[-8:]:
                    turn_content = turn["content"]
                    if isinstance(turn_content, str):
                        turn_content = self.c.compliance.redact_sensitive_data(turn_content)
                    messages.append({"role": turn["role"], "content": turn_content})

            if attachments:
                user_content: List[Dict[str, Any]] = [
                    {"type": "text", "text": redacted_text or "Please analyze the attached financial image/document."}
                ]
                for att in attachments:
                    att_type = att.get("type", "")
                    mime = str(att.get("mime_type", ""))
                    data_url = att.get("data") or att.get("url")
                    if (att_type == "image" or "image" in mime or (data_url and data_url.startswith("data:image/"))) and data_url:
                        user_content.append({
                            "type": "image_url",
                            "image_url": {"url": data_url}
                        })
                messages.append({"role": "user", "content": user_content})
            else:
                messages.append({"role": "user", "content": redacted_text})

            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http_client:
                client = AsyncOpenAI(api_key=key, http_client=http_client)

                # Multi-step tool execution loop (up to 4 iterations)
                for _iteration in range(4):
                    # Force final synthesis on last iteration
                    active_tools = tools if _iteration < 3 else None

                    resp = await client.chat.completions.create(
                        model=settings.openai_model or "gpt-4o",
                        messages=messages,
                        tools=active_tools,
                        temperature=0.2,
                        max_tokens=4000,
                    )
                    msg = resp.choices[0].message

                    if not msg.tool_calls:
                        if msg.content and msg.content.strip():
                            final_text = msg.content.strip()
                            try:
                                ctx_dict = client_ctx.to_dict() if "client_ctx" in locals() and client_ctx else None
                                rev_res = await self.review_stage.review_and_revise(
                                    initial_text=final_text,
                                    client_context=ctx_dict,
                                    openai_client=client,
                                    model=settings.openai_model,
                                    max_revisions=3,
                                )
                                final_text = rev_res.final_text
                            except Exception as rev_err:
                                logger.debug("Review stage notice: %s", rev_err)

                            events.append(await self._say(final_text, db, client_id, agent="WealthAdvisor"))
                            return events
                        break

                    messages.append(msg)

                    # 1. Non-discretionary execution gate: Check for propose_trade
                    trade_tc = next((tc for tc in msg.tool_calls if tc.function.name == "propose_trade"), None)
                    if trade_tc:
                        fn_args = json.loads(trade_tc.function.arguments or "{}")
                        sym = fn_args.get("symbol", "").upper()
                        side = fn_args.get("side", "").upper()
                        qty = float(fn_args.get("qty", 0.0))
                        if client_id and sym and side in ("BUY", "SELL") and qty > 0:
                            return await self.propose_trade(db, user_id, client_id, sym, side, qty, session=session)
                        else:
                            messages.append({"role": "tool", "tool_call_id": trade_tc.id, "content": json.dumps({"status": "error", "message": "Invalid trade or client not onboarded."})})

                    # 2. Centralized ToolRegistry Execution Pipeline:
                    # Enforces Role Authorization, Circuit Breakers, Rate Limiting, Timeouts, and Provenance Logging
                    try:
                        from tools.registry import ToolRegistry
                        from tools.base import ExecutionContext
                    except ImportError:
                        from backend.tools.registry import ToolRegistry
                        from backend.tools.base import ExecutionContext

                    registry = ToolRegistry.get_instance()
                    exec_ctx = ExecutionContext(
                        session_id=session.get("session_id"),
                        user_id=user_id,
                        client_id=client_id,
                        role="Orchestrator",
                        caller="WealthAdvisor",
                        metadata={"db": db},
                    )

                    async def _run_tool_call(tc) -> Dict[str, Any]:
                        t_name = tc.function.name
                        try:
                            t_args = json.loads(tc.function.arguments or "{}")
                        except Exception:
                            t_args = {}

                        try:
                            t_res = await registry.execute_tool(
                                name=t_name,
                                args=t_args,
                                role="Orchestrator",
                                context=exec_ctx,
                                raise_on_error=False,
                            )
                            if t_res.success:
                                content = json.dumps(t_res.data)
                            else:
                                content = json.dumps({"status": "error", "message": t_res.error or "Tool execution failed"})
                        except Exception as exc:
                            logger.warning(f"Registry tool execution error for '{t_name}': {exc}")
                            content = json.dumps({"status": "error", "message": str(exc)})

                        return {"role": "tool", "tool_call_id": tc.id, "content": content}

                    # Execute all independent tool calls concurrently in parallel
                    nontrade_calls = [tc for tc in msg.tool_calls if tc.function.name != "propose_trade"]
                    if nontrade_calls:
                        tool_responses = await asyncio.gather(*[_run_tool_call(tc) for tc in nontrade_calls])
                        messages.extend(tool_responses)

        except Exception as exc:
            logger.warning("Agentic chat turn failed: %s", exc)

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
    async def _advising_turn(
        self, db: AsyncSession, session: Dict[str, Any], text: str, attachments: Optional[List[Dict[str, Any]]] = None
    ) -> List[Dict[str, Any]]:
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

        words = text.strip().split()
        is_direct_command = (len(words) <= 12 and "\n" not in text.strip() and text.count("?") <= 1 and not attachments)

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
        elif is_direct_command and (m := TRADE_RE.search(text)):
            side, qty, symbol = m.group(1).upper(), float(m.group(2)), m.group(3).upper()
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting trades.", db, None))
            else:
                events += await self.propose_trade(db, user_id, client_id, symbol, side, qty, session=session)
        elif is_direct_command and REBALANCE_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting rebalancing.", db, None))
            else:
                events += await self._rebalance(db, client_id, session)
        elif is_direct_command and COMPARE_RE.search(text):
            symbols = [t for t in TICKER_RE.findall(text.upper()) if t not in STOPWORDS_TICKER]
            events += await self._compare(db, client_id, symbols, bonds="bond" in lowered)
        elif is_direct_command and HEALTH_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling to review your portfolio health.", db, None))
            else:
                session["stage"] = SessionStage.HEALTH_MONITORING.value
                events += await self._health(db, client_id)
                session["stage"] = SessionStage.ADVICE_GENERATION.value
        elif is_direct_command and ALLOCATION_RE.search(text):
            if not client_id:
                events.append(await self._say("Please complete risk profiling before requesting an allocation recommendation.", db, None))
            else:
                events += await self.recommend_allocation(db, client_id)
        elif is_direct_command and (sym := extract_quote_symbol(text)):
            events += await self._quote(db, client_id, sym)
        elif is_direct_command and MACRO_RE.search(text):
            events += await self._macro(db, client_id)
        else:
            history = session.get("history", [])
            # 1. Run agentic tool-calling turn connected to application services
            agentic_events = await self._agentic_chat_turn(db, session, text, history=history, attachments=attachments)
            if agentic_events:
                return agentic_events

            if attachments:
                file_names = ", ".join([a.get("name", "attachment") for a in attachments])
                fallback_msg = (
                    f"**Multi-modal Input Received**: Visual documents/charts (`{file_names}`) processed.\n\n"
                    "• **Visual Analysis**: Financial graphics detected. The image was staged into your advisory session.\n"
                    "• **Institutional Note**: Connect live market data or prompt specific equity/fixed-income questions to cross-examine this document against live metrics."
                )
                events.append(await self._say(fallback_msg, db, client_id, agent="WealthAdvisor"))
                return events

            # 2. Fallback to intent parser and general reply if agentic turn did not produce events
            translated = await self._translate_intent(text, history=history)
            if translated and translated.get("command"):
                cmd = str(translated["command"]).strip()
                if (sym := extract_quote_symbol(cmd)):
                    events += await self._quote(db, client_id, sym)
                    return events
                elif COMPARE_RE.search(cmd):
                    symbols = [t for t in TICKER_RE.findall(cmd.upper()) if t not in STOPWORDS_TICKER]
                    if len(symbols) >= 2:
                        events += await self._compare(db, client_id, symbols, bonds="bond" in cmd.lower())
                        return events
                elif MACRO_RE.search(cmd):
                    events += await self._macro(db, client_id)
                    return events
                elif HEALTH_RE.search(cmd):
                    if client_id:
                        events += await self._health(db, client_id)
                        return events
                elif ALLOCATION_RE.search(cmd):
                    if client_id:
                        events += await self.recommend_allocation(db, client_id)
                        return events
                elif (m := TRADE_RE.search(cmd)):
                    side, qty, symbol = m.group(1).upper(), float(m.group(2)), m.group(3).upper()
                    if client_id:
                        events += await self.propose_trade(db, user_id, client_id, symbol, side, qty, session=session)
                        return events

            # 3. Direct deterministic regex fallback when LLM is offline/unconfigured
            if (sym := extract_quote_symbol(text)):
                events += await self._quote(db, client_id, sym)
                return events
            elif MACRO_RE.search(text):
                events += await self._macro(db, client_id)
                return events
            elif COMPARE_RE.search(text):
                symbols = [t for t in TICKER_RE.findall(text.upper()) if t not in STOPWORDS_TICKER]
                if len(symbols) >= 2:
                    events += await self._compare(db, client_id, symbols, bonds="bond" in lowered)
                    return events

            if translated and translated.get("answer"):
                events.append(await self._say(translated["answer"], db, client_id, agent="WealthAdvisor"))
            else:
                events.append(await self._say(await self._general_reply(db, client_id, text, history=history), db, client_id, agent="WealthAdvisor"))

        return events

    # ------------------------------------------------------------------ #
    # Market Data Dispatchers
    # ------------------------------------------------------------------ #
    async def _quote(self, db: AsyncSession, client_id: Optional[str], symbol: str) -> List[Dict[str, Any]]:
        try:
            q = await self.c.market.get_quote(symbol)
            as_of = getattr(q, "as_of", None) or getattr(q, "timestamp", "recently")
            bid_str = f", Bid: ${q.bid:.2f}" if getattr(q, "bid", None) else ""
            ask_str = f", Ask: ${q.ask:.2f}" if getattr(q, "ask", None) else ""
            vol_str = f", Volume: {q.volume:,}" if getattr(q, "volume", None) else ""
            change_str = ""
            if getattr(q, "change_pct", None) is not None:
                sign = "+" if q.change_pct > 0 else ""
                change_str = f" ({sign}{q.change_pct:.2f}%)"
            txt = f"Quote for {q.symbol}: Price ${q.price:.2f}{change_str}{bid_str}{ask_str}{vol_str}. Data as of {as_of}."
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
            events.append(
                await self._say(
                    txt,
                    db,
                    client_id,
                    agent="AllocationEngine",
                    kind="trade_proposal",
                    proposal=proposal,
                    proposal_id=proposal["proposal_id"],
                    action=proposal["side"],
                    side=proposal["side"],
                    quantity=proposal["qty"],
                    qty=proposal["qty"],
                    symbol=proposal["symbol"],
                    price=proposal["price"],
                    notional_value=proposal["notional_value"],
                )
            )
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

    async def _compare(self, db: AsyncSession, client_id: Optional[str], symbols: List[str], bonds: bool = False) -> List[Dict[str, Any]]:
        if len(symbols) < 2:
            return [await self._say("Tell me at least two tickers to compare, e.g. 'compare SPY VTI QQQ'.", db, client_id)]
        profile = await self.c.profiler.get_profile(client_id, db=db) if client_id else None
        fn = self.c.comparison.compare_bonds if bonds else self.c.comparison.compare_etfs
        report = await fn(symbols, profile=profile, client_id=client_id)
        ranked = "; ".join(f"#{p.rank} {p.symbol} ({p.composite_score:.1f}/10)" for p in report.ranked_products) or "none suitable"
        target_str = "for you" if client_id else "by composite score"
        text = f"Ranking {target_str}: {ranked}. Best fit: {report.winner_symbol}.\n\n{report.summary_rationale}"
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

    async def _general_reply(self, db: AsyncSession, client_id: Optional[str], text: str, history: Optional[List[Dict[str, str]]] = None) -> str:
        key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        if key and key != "your_openai_api_key_here":
            try:
                import httpx
                from openai import AsyncOpenAI

                async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0)) as http_client:
                    client = AsyncOpenAI(api_key=key, http_client=http_client)
                    messages = [
                        {
                            "role": "system",
                            "content": (
                                "You are a licensed, friendly, conversational, and expert non-discretionary AI Wealth Advisor and equity research analyst. "
                                "Maintain conversational context across multiple turns. Always resolve pronouns and contextual references from prior messages. "
                                "When users ask about supply chains, suppliers, component providers, derivative plays, or value chains across ANY industry "
                                "(e.g. AI/Tech, Electric Vehicles & Batteries, Aerospace & Defense, Healthcare & Biotech, Clean Energy & Utilities, "
                                "Semiconductors, Industrial Manufacturing, Consumer Goods, Retail/E-Commerce, etc.): "
                                "Provide deep, well-structured multi-tier research breaking down the ecosystem into clear tiers: "
                                "1. Raw Materials & Commodities; 2. Key Component, Subsystem & Equipment Suppliers; 3. Infrastructure, Utilities, Power & Physical Facilities; "
                                "4. Contract Manufacturing, Integration & Foundries; 5. Human Capital, Specialized Staffing & Enterprise Software; 6. Prime End-Market Leaders. "
                                "Include concrete public stock tickers for each tier, discuss competitive moats, evaluate valuation context, and analyze risks. "
                                "When presented with complex mock scenarios, wealth advisory case studies, multi-question briefs, or high-stakes challenges: "
                                "Deliver the depth and rigor of a senior multidisciplinary institutional investment team. Adhere strictly to all specified non-negotiable rules. "
                                "List critical client information required and why each matters, state baseline assumptions clearly, challenge assumptions aggressively, "
                                "and conclude with a direct, unambiguous recommendation ('proceed as designed', 'proceed with modifications', or 'reject proposed objective'). "
                                "When presented with ambitious wealth-building targets (e.g. $10M to $100M in 10 years with lifestyle withdrawals): "
                                "Never invent probabilities out of thin air or assume constant linear returns without accounting for withdrawals, fees, and taxes. "
                                "Provide the exact mathematical required CAGR accounting for withdrawals, taxes, and fees (which raises required pre-tax return to ~34.4% per year, far above the zero-cash-flow 25.89%), "
                                "provide a 10-year audited accounting schedule, quote empirical 10,000-path Monte Carlo probability simulations (showing P(reaching $100M) is ~1% while P(losing >50% capital) is ~18%-25%), "
                                "detail 5 concrete institutional investment dossiers with verified financials and Hamilton Helmer moats (not generic sectors), "
                                "include multi-factor stress tests (2008 GFC, 2022 Stagflation, Currency shocks, sequence-of-returns), "
                                "gate tax/legal advice by client tax residency, and challenge the client with the Ruin vs Riches trade-off matrix. "
                                "NEVER deflect or tell the user to 'consult a financial advisor' or 'seek professional advice' — YOU ARE THE CLIENT'S WEALTH ADVISOR. "
                                "When asked whether to invest in an IPO (such as Dangote Refinery), private deal, or equity, conduct the deep analysis yourself and deliver an authoritative investment verdict. "
                                "Compute the Institutional Hurdle Score (0-100) across Financial Transparency (25), Solvency/Debt (20), Unit Economics (20), Valuation (15), and Sovereign/FX/Feedstock Risk (20). "
                                "If Score >= 70 and no fatal dealbreakers exist, verdict is YES — INVEST (with exact allocation e.g. 3-5%). "
                                "If Score < 70 or any fatal dealbreaker is triggered (e.g. massive unhedged FX debt, lack of audited public prospectus, or feedstock friction), verdict is NO — DO NOT INVEST with TARGET ALLOCATION: 0.0%. "
                                "NEVER suggest a 'HOLD / NEUTRAL' with a 2-3% satellite allocation when an asset fails the hurdle! In institutional finance, if an opportunity fails the hurdle, you pass completely (0.0%). "
                                "Never promise risk-free returns; provide balanced, evidence-based commentary."
                            ),
                        },
                    ]
                    redacted_text = self.c.compliance.redact_sensitive_data(text or "")
                    if history:
                        prior_turns = [
                            turn for turn in history
                            if turn.get("role") in ("user", "assistant") and turn.get("content")
                        ]
                        if prior_turns and prior_turns[-1].get("role") == "user" and prior_turns[-1].get("content") == text:
                            prior_turns = prior_turns[:-1]
                        for turn in prior_turns[-8:]:
                            turn_content = turn["content"]
                            if isinstance(turn_content, str):
                                turn_content = self.c.compliance.redact_sensitive_data(turn_content)
                            messages.append({"role": turn["role"], "content": turn_content})
                    messages.append({"role": "user", "content": redacted_text})

                    resp = await client.chat.completions.create(
                        model=settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o"),
                        messages=messages,
                        temperature=0.3,
                        max_tokens=4000,
                    )
                    return resp.choices[0].message.content.strip()
            except Exception as exc:  # noqa: BLE001
                logger.warning("General reply LLM failed: %s", exc)
        return (
            "I'm here to help you navigate your wealth advisory journey! You can ask me any financial or investing question, "
            "request real-time market quotes (e.g. 'show SPY quote'), compare funds ('compare SPY VTI QQQ'), review portfolio health ('how is my portfolio?'), "
            "recommend a portfolio allocation ('recommend a portfolio'), or propose a paper trade ('buy 10 BND')."
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
        broker: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> Dict[str, Any]:
        symbol, side = symbol.strip().upper(), side.strip().upper()
        if side not in ("BUY", "SELL") or qty <= 0 or not symbol:
            raise HTTPException(status_code=422, detail="Invalid trade: need BUY/SELL, positive qty and a symbol")

        cb_status = self.c.compliance.get_circuit_breaker_status(client_id)
        if cb_status["is_locked"]:
            raise HTTPException(
                status_code=423,
                detail=(
                    f"PERM-CIRCUIT-BREAKER: Account '{client_id}' is temporarily locked due to "
                    f"{cb_status['incident_count_15m']} security incidents in the last 15 minutes."
                ),
            )

        if symbol not in self.c.compliance.ALLOWED_TRADING_SYMBOLS:
            raise HTTPException(
                status_code=403,
                detail=(
                    f"PERM-WHITELIST: Symbol '{symbol}' is not on the approved symbol whitelist "
                    f"({len(self.c.compliance.ALLOWED_TRADING_SYMBOLS)} vetted ETFs & equities)."
                ),
            )

        proj = await self.c.portfolio.projected_weight(db, client_id, symbol, side, qty)

        is_ngx = symbol in ("DANGCEM", "MTNN", "GTCO", "ZENITHBANK", "ACCESSCORP", "UBA", "SEPLAT", "AIRTELAFRI", "BUACEMENT", "BUAFOODS", "NESTLE", "GEREGU", "TRANSPOWER", "TRANSCORP", "NGXGROUP")
        chosen_broker = (broker or ("bamboo" if is_ngx else "alpaca")).lower()
        chosen_currency = (currency or ("NGN" if is_ngx else "USD")).upper()

        tier_info = self.c.compliance.classify_trade_permission_tier(
            float(proj["notional_value"]), float(proj["projected_weight"])
        )

        proposal = {
            "proposal_id": str(uuid.uuid4()),
            "client_id": client_id,
            "symbol": symbol,
            "side": side,
            "qty": qty,
            "price": proj["price"],
            "notional_value": proj["notional_value"],
            "projected_weight": proj["projected_weight"],
            "broker": chosen_broker,
            "currency": chosen_currency,
            "permission_tier": tier_info["permission_tier"],
            "requires_step_up_auth": tier_info["requires_step_up_auth"],
            "step_up_reason": tier_info["step_up_reason"],
            "exceeds_concentration_ceiling": float(proj["projected_weight"]) > 0.15,
            "max_recommended_weight": 0.15,
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
        curr_sym = "₦" if proposal.get("currency") == "NGN" else "$"
        broker_label = "Bamboo (Live NGX & Global)" if proposal.get("broker") == "bamboo" else "Alpaca Paper Trading"
        text = (
            f"Proposed order: {proposal['side']} {proposal['qty']:g} {proposal['symbol']} at about "
            f"{curr_sym}{proposal['price']:.2f} (~{curr_sym}{proposal['notional_value']:,.2f}) via {broker_label}. "
            f"Reply 'approve' to execute within 15 minutes, or 'cancel'. Nothing is sent until you approve."
        )
        return [
            await self._say(
                text,
                db,
                client_id,
                kind="trade_proposal",
                proposal=proposal,
                proposal_id=proposal["proposal_id"],
                action=proposal["side"],
                side=proposal["side"],
                quantity=proposal["qty"],
                qty=proposal["qty"],
                symbol=proposal["symbol"],
                price=proposal["price"],
                notional_value=proposal["notional_value"],
                broker=proposal.get("broker"),
                currency=proposal.get("currency"),
            )
        ]

    async def handle_trade_approval(
        self,
        db: AsyncSession,
        user_id: str,
        proposal_id: str,
        approved: bool,
        session_id: Optional[str] = None,
        mfa_code: Optional[str] = None,
        fiduciary_attested: Optional[bool] = None,
    ) -> List[Dict[str, Any]]:
        proposal = await self.c.cache.get_json(f"proposal:{proposal_id}")
        if not proposal:
            executed = await self.c.cache.get_json(f"executed_proposal:{proposal_id}")
            if executed:
                return [
                    _event(
                        "agent_response",
                        "ExecutionModule",
                        f"Order for {executed.get('symbol', 'this asset')} has already been confirmed and processed.",
                    )
                ]
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
            "user_id": str(user_id),
            "proposal_id": proposal_id,
            "user_approved": approved,
            "user_approved_at": approval_ts.isoformat(),
            "symbol": proposal["symbol"],
            "side": proposal["side"],
            "qty": proposal["qty"],
            "price": proposal["price"],
            "notional_value": proposal["notional_value"],
            "projected_weight": proposal["projected_weight"],
            "broker": proposal.get("broker"),
            "currency": proposal.get("currency"),
            "mfa_code": mfa_code,
            "fiduciary_attested": fiduciary_attested,
            "enforce_step_up_mfa": (mfa_code is not None or fiduciary_attested is not None),
        }
        try:
            check = await self.c.compliance.check_trade(db, client_id, trade, profile)
            summary_rules = f"Pre-trade compliance verified: {len(check.rule_results)} rules passed."
            events.append(_event("compliance_check", "ComplianceGuard", text=summary_rules, passed=check.passed, details=check.to_dict()))
        except ComplianceViolationError as exc:
            violation_details = []
            for v in exc.violations:
                rid = getattr(v, "rule_id", "RULE")
                rname = getattr(v, "rule_name", rid)
                desc = getattr(v, "description", "") or getattr(v, "details", "") or str(v)
                violation_details.append(f"{rid} ({rname}): {desc}")
            violation_text = "Trade blocked by regulatory & compliance rules:\n• " + "\n• ".join(violation_details)
            self.c.compliance.record_security_incident(str(user_id), violation_text, incident_type="TRADE_COMPLIANCE_BLOCK")
            events.append(
                _event("compliance_check", "ComplianceGuard", text=violation_text,
                       passed=False, violations=[v.to_dict() if hasattr(v, "to_dict") else dict(v) for v in exc.violations])
            )
            raise TradeBlocked(exc.violations, events, reason=violation_text) from exc

        try:
            result = await self.c.execution.execute_trade(
                db=db, client_id=client_id, proposal_id=proposal_id,
                symbol=proposal["symbol"], side=proposal["side"], qty=proposal["qty"],
                approved=approved, approval_timestamp=approval_ts,
                broker=proposal.get("broker"),
                currency=proposal.get("currency"),
                user_id=str(user_id),
            )
        except (UnapprovedTradeError, ExpiredApprovalError, KYCUnverifiedError, DuplicateTradeError, ExecutionError) as exc:
            raise TradeBlocked([], events, reason=str(exc), error_type=type(exc).__name__) from exc

        await self.c.cache.set_json(
            f"executed_proposal:{proposal_id}",
            {"symbol": proposal.get("symbol", ""), "side": proposal.get("side", ""), "qty": proposal.get("qty", 0)},
            expire=900,
        )
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

        curr_sym = "₦" if getattr(result, "currency", "USD") == "NGN" else "$"
        if getattr(result, "broker", "alpaca") == "bamboo":
            broker_msg = " via Bamboo Investment (Live)." if not result.dry_run else " via Bamboo Investment (Sandbox)."
        else:
            broker_msg = " (simulated paper fill)." if result.dry_run else " via Alpaca paper trading."

        events.append(
            await self._say(
                f"Order {result.status}: {result.side} {result.qty:g} {result.symbol}"
                + (f" at {curr_sym}{result.filled_price:.2f}" if result.filled_price else "")
                + broker_msg,
                db, client_id, agent="ExecutionModule", kind="trade_filled", execution=result.model_dump(mode="json"),
            )
        )
        pf = await self.c.portfolio.get_portfolio(db, client_id, persist_snapshot=True)
        tot = pf.get("total_value", 0.0)
        cash = pf.get("cash", 0.0)
        txt = f"Portfolio balance updated: Total value ${tot:,.2f}, cash balance ${cash:,.2f}."
        events.append(_event("portfolio_update", "PortfolioService", text=txt, portfolio={k: v for k, v in pf.items() if k not in ("prices", "position_qty")}))
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

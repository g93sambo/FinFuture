"""
backend/db/models.py
====================
SQLAlchemy ORM models with append-only tamper-resistance invariants.
"""

import uuid
from datetime import datetime, timezone
from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    JSON,
    Text,
    ForeignKey,
    event,
)
from sqlalchemy.orm import relationship, synonym, Session
from .database import Base


def generate_uuid() -> str:
    """Generate a standard UUID4 string."""
    return str(uuid.uuid4())


class AppendOnlyViolationError(RuntimeError):
    """Raised when an attempt is made to UPDATE or DELETE an append-only audit record."""
    pass


class DBUser(Base):
    """User account entity for authentication and ownership security."""
    __tablename__ = "users"

    id = Column(String, primary_key=True, default=generate_uuid)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Relationships
    client_profiles = relationship(
        "DBClientProfile",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    chat_sessions = relationship(
        "DBChatSession",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DBChatSession.updated_at.desc()",
    )


class DBChatSession(Base):
    """Chat session entity for persisting multi-turn conversations and history."""
    __tablename__ = "chat_sessions"

    id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    title = Column(String, nullable=False, default="New Advisory Conversation")
    stage = Column(String, nullable=False, default="ADVICE_GENERATION")
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False, index=True)

    # Relationships
    user = relationship("DBUser", back_populates="chat_sessions")
    messages = relationship(
        "DBChatMessage",
        back_populates="session",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="DBChatMessage.created_at.asc()",
    )


class DBChatMessage(Base):
    """Individual chat message within a session, supporting multimodal attachments and structured events."""
    __tablename__ = "chat_messages"

    id = Column(String, primary_key=True, default=generate_uuid)
    session_id = Column(String, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    sender = Column(String, nullable=False)  # "user" | "agent"
    agent = Column(String, nullable=True, default="Orchestrator")
    text = Column(Text, nullable=True)
    attachments = Column(JSON, nullable=True, default=list)  # list of {"type": "image", "url": "...", "name": "..."}
    events = Column(JSON, nullable=True, default=list)        # list of event dicts
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    session = relationship("DBChatSession", back_populates="messages")


class DBClientProfile(Base):
    """Comprehensive client financial, psychological, and suitability profile."""
    __tablename__ = "client_profiles"

    client_id = Column(String, primary_key=True, default=generate_uuid)
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)

    # Demographics & Financial Situation
    age = Column(Integer, nullable=True)
    employment_status = Column(String, nullable=True)
    dependents = Column(Integer, nullable=True, default=0)
    annual_income = Column(Float, nullable=True)
    net_worth = Column(Float, nullable=True)
    liquid_assets = Column(Float, nullable=True, default=0.0)
    monthly_expenses = Column(Float, nullable=True, default=0.0)
    existing_debts = Column(Float, nullable=True, default=0.0)
    source_of_funds = Column(String, nullable=True, default="salary")

    # Investment Parameters & Preferences
    investment_experience = Column(String, nullable=True)
    risk_tolerance_score = Column(Float, nullable=True)
    investment_horizon_years = Column(Integer, nullable=True)
    liquidity_needs = Column(String, nullable=True)
    loss_capacity = Column(String, nullable=True)
    primary_goal = Column(String, nullable=True)
    target_return = Column(Float, nullable=True)
    specific_goals = Column(JSON, default=list)
    drawdown_reaction = Column(String, nullable=True, default="hold")
    monitoring_frequency = Column(String, nullable=True, default="monthly")

    # Synthesis & Psychology
    suitability_category = Column(String, nullable=True)
    detected_biases = Column(JSON, default=list)
    emotional_risk_score = Column(Float, nullable=True, default=0.0)
    panic_sell_likelihood = Column(Float, nullable=True, default=0.0)
    profiling_session_transcript = Column(Text, nullable=True, default="")

    # Compliance & Status
    kyc_verified = Column(Boolean, default=False)
    aml_flag = Column(Boolean, default=False)
    pep_status = Column(Boolean, default=False)
    high_risk_jurisdiction = Column(Boolean, default=False)

    # Timestamps
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)

    # Pydantic schema compatibility synonyms
    profile_created_at = synonym("created_at")
    profile_updated_at = synonym("updated_at")

    # Relationships
    user = relationship("DBUser", back_populates="client_profiles")
    portfolio_snapshots = relationship(
        "DBPortfolioSnapshot",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    trades = relationship("DBTrade", back_populates="client")
    audit_logs = relationship("DBAuditLog", back_populates="client")
    behavioral_memories = relationship(
        "DBBehavioralMemory",
        back_populates="client",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class DBPortfolioSnapshot(Base):
    """Periodic or event-driven portfolio snapshot for health monitoring and drift detection."""
    __tablename__ = "portfolio_snapshots"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False, index=True)
    total_value = Column(Float, nullable=False)
    positions = Column(JSON, nullable=False, default=dict)
    cash = Column(Float, nullable=False, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationship
    client = relationship("DBClientProfile", back_populates="portfolio_snapshots")


class DBTrade(Base):
    """Trade execution entity recording orders placed with broker (Alpaca)."""
    __tablename__ = "trades"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("client_profiles.client_id"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)
    qty = Column(Float, nullable=False)
    side = Column(String, nullable=False)  # BUY / SELL
    order_type = Column(String, nullable=False, default="MARKET")
    status = Column(String, nullable=False, default="PENDING")  # PENDING / FILLED / REJECTED / CANCELLED

    filled_price = Column(Float, nullable=True)
    filled_qty = Column(Float, nullable=True, default=0.0)
    broker = Column(String, nullable=False, default="alpaca")  # alpaca / bamboo
    currency = Column(String, nullable=False, default="USD")   # USD / NGN
    alpaca_order_id = Column(String, nullable=True, index=True)
    bamboo_order_id = Column(String, nullable=True, index=True)

    compliance_report = Column(JSON, nullable=True, default=dict)
    user_approved_at = Column(DateTime, nullable=True)
    filled_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Synonyms for backwards compatibility
    trade_id = synonym("id")
    quantity = synonym("qty")

    # Relationship
    client = relationship("DBClientProfile", back_populates="trades")


class DBAuditLog(Base):
    """Cryptographically chained append-only audit trail."""
    __tablename__ = "audit_log"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("client_profiles.client_id"), nullable=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    actor = Column(String, nullable=False)  # USER / SYSTEM / AGENT:xxx
    details = Column(JSON, nullable=False, default=dict)
    timestamp = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), nullable=False, index=True)

    prev_hash = Column(String, nullable=True)
    entry_hash = Column(String, nullable=False)
    signature = Column(String, nullable=False)

    # Operational context fields
    session_id = Column(String, nullable=True)
    agent_id = Column(String, nullable=True)
    status = Column(String, nullable=True, default="PASS")

    # Synonyms for backwards compatibility
    entry_id = synonym("id")
    previous_hash = synonym("prev_hash")
    hmac_signature = synonym("signature")
    action = synonym("details")

    # Relationship
    client = relationship("DBClientProfile", back_populates="audit_logs")


class DBBehavioralMemory(Base):
    """Persistent storage for detected client behavioral biases and debiasing interventions."""
    __tablename__ = "behavioral_memory"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False, index=True)
    bias_type = Column(String, nullable=False, index=True)  # loss_aversion, recency_bias, overconfidence, etc.
    severity = Column(String, nullable=False, default="medium")  # low, medium, high
    trigger_context = Column(JSON, nullable=True)
    intervention_text = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

    # Relationship
    client = relationship("DBClientProfile", back_populates="behavioral_memories")


class DBComplianceRule(Base):
    """Dynamically configurable compliance and regulatory rules."""
    __tablename__ = "compliance_rules"

    rule_id = Column(String, primary_key=True)  # e.g. SUIT-001, CONC-001, REG-001, AML-001
    name = Column(String, nullable=False)
    category = Column(String, nullable=False, index=True)  # SUITABILITY, CONCENTRATION, REGULATORY, AML
    severity = Column(String, nullable=False, default="BLOCK")  # BLOCK / WARN
    parameters = Column(JSON, nullable=False, default=dict)
    description = Column(Text, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False)


# ============================================================================
# Append-Only Invariant Enforcement on DBAuditLog
# ============================================================================

@event.listens_for(DBAuditLog, "before_update")
def prevent_audit_log_instance_update(mapper, connection, target):
    """Enforce append-only invariant: block instance UPDATE."""
    raise AppendOnlyViolationError(
        f"Append-only violation: UPDATE is strictly prohibited on DBAuditLog (entry_id={target.id})"
    )


@event.listens_for(DBAuditLog, "before_delete")
def prevent_audit_log_instance_delete(mapper, connection, target):
    """Enforce append-only invariant: block instance DELETE."""
    raise AppendOnlyViolationError(
        f"Append-only violation: DELETE is strictly prohibited on DBAuditLog (entry_id={target.id})"
    )


@event.listens_for(Session, "do_orm_execute")
def prevent_audit_log_bulk_mutation(orm_execute_state):
    """Enforce append-only invariant: block bulk UPDATE and DELETE statements."""
    if orm_execute_state.is_delete or orm_execute_state.is_update:
        if orm_execute_state.bind_mapper and issubclass(orm_execute_state.bind_mapper.class_, DBAuditLog):
            action = "DELETE" if orm_execute_state.is_delete else "UPDATE"
            raise AppendOnlyViolationError(
                f"Append-only violation: Bulk {action} statement is strictly prohibited on DBAuditLog"
            )

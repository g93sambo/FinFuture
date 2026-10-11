"""
Unit tests for backend/services/audit_logger.py
Testing hash-chaining, HMAC signature verification, 100-entry chain verification, and tamper detection.
"""

import asyncio
import pytest
from sqlalchemy import text, select
from services.audit_logger import (
    log_audit_entry,
    verify_audit_chain,
    GENESIS_HASH,
    AuditLogger,
)
from db.models import DBClientProfile, DBAuditLog


@pytest.mark.asyncio
async def test_log_audit_entry_genesis(db_session):
    client_id = "test-client-genesis"
    entry = await log_audit_entry(
        db=db_session,
        client_id=client_id,
        event_type="LOGIN",
        actor="USER",
        details={"ip": "192.168.1.1"},
    )

    assert entry.id is not None
    assert entry.prev_hash == GENESIS_HASH
    assert len(entry.entry_hash) == 64
    assert len(entry.signature) == 64

    is_valid, corrupted_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is True
    assert corrupted_id is None


@pytest.mark.asyncio
async def test_sequential_chaining(db_session):
    client_id = "test-client-chain"

    e1 = await log_audit_entry(
        db=db_session,
        client_id=client_id,
        event_type="KYC_VERIFIED",
        actor="COMPLIANCE_GUARD",
        details={"status": "APPROVED"},
    )
    e2 = await log_audit_entry(
        db=db_session,
        client_id=client_id,
        event_type="PROPOSAL_CREATED",
        actor="ORCHESTRATOR",
        details={"proposal_id": "prop-123"},
    )

    assert e1.prev_hash == GENESIS_HASH
    assert e2.prev_hash == e1.entry_hash

    is_valid, corrupted_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is True
    assert corrupted_id is None


@pytest.mark.asyncio
async def test_100_entries_verification_and_tamper_detection(db_session):
    client_id = "test-client-100-entries"

    # 1. Generate 100 sequential audit log entries
    entries = []
    for i in range(100):
        entry = await log_audit_entry(
            db=db_session,
            client_id=client_id,
            event_type=f"EVENT_{i}",
            actor=f"ACTOR_{i % 3}",
            details={"step": i, "data": f"payload_{i}"},
        )
        entries.append(entry)

    assert len(entries) == 100

    # 2. Verify all 100 entries pass verification cleanly
    is_valid, corrupted_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is True
    assert corrupted_id is None

    # 3. Tamper with entry #50 via raw SQL statement (bypassing ORM model listener)
    tampered_entry = entries[50]
    tampered_id = tampered_entry.id

    await db_session.execute(
        text("UPDATE audit_log SET details = :new_details WHERE id = :target_id"),
        {"new_details": '{"step": 50, "tampered": true}', "target_id": tampered_id}
    )
    await db_session.commit()
    db_session.expire_all()

    # 4. Re-run verification: MUST fail and identify entry #50 as corrupted
    is_valid, detected_corrupted_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is False
    assert detected_corrupted_id == tampered_id


@pytest.mark.asyncio
async def test_tamper_signature_detected(db_session):
    client_id = "test-client-sig-tamper"

    e1 = await log_audit_entry(
        db=db_session,
        client_id=client_id,
        event_type="TRADE_EXECUTED",
        actor="EXECUTION",
        details={"symbol": "SPY", "qty": 10},
    )

    # Tamper with signature
    await db_session.execute(
        text("UPDATE audit_log SET signature = :fake_sig WHERE id = :target_id"),
        {"fake_sig": "0" * 64, "target_id": e1.id}
    )
    await db_session.commit()
    db_session.expire_all()

    is_valid, corrupted_id = await verify_audit_chain(db_session, client_id)
    assert is_valid is False
    assert corrupted_id == e1.id


@pytest.mark.asyncio
async def test_wrong_hmac_key_fails_verification(db_session):
    client_id = "test-client-wrong-key"

    await log_audit_entry(
        db=db_session,
        client_id=client_id,
        event_type="AUTH",
        actor="SYSTEM",
        details={"action": "token_refresh"},
        hmac_key="correct-key-32-chars-long-12345678",
    )

    # Verification with wrong key fails
    is_valid, corrupted_id = await verify_audit_chain(
        db_session, client_id, hmac_key="wrong-key-32-chars-long-87654321"
    )
    assert is_valid is False
    assert corrupted_id is not None

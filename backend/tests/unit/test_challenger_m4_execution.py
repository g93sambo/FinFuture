"""
backend/tests/unit/test_challenger_m4_execution.py
===================================================
Challenger 1 Adversarial Test Suite for Milestone 4:
Execution Module, Locking Mechanics, KYC Gates, Freshness Windows,
DB Persistence, and Cryptographic Audit Log Integrity.
"""

import asyncio
import time
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
import pytest
import pytest_asyncio

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy import select

from db.database import Base
from db.models import DBClientProfile, DBTrade, DBAuditLog
from services.cache import CacheService, InMemoryCache, key_trade_lock
from services.audit_logger import get_audit_logger, verify_audit_chain
from agents.execution_module import (
    ExecutionModule,
    TradeExecutionResult,
    UnapprovedTradeError,
    ExpiredApprovalError,
    KYCUnverifiedError,
    DuplicateTradeError,
    ExecutionError,
)


@pytest_asyncio.fixture
async def challenger_db_engine(tmp_path):
    """Isolated file-backed SQLite engine for challenger stress tests.

    A file (not :memory:) is used so concurrent sessions get their own connections
    instead of interleaving transactions on one shared in-memory connection.
    """
    engine = create_async_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'challenger.db'}",
        echo=False,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def session_factory(challenger_db_engine):
    """Factory creating distinct AsyncSessions bound to the challenger engine."""
    return async_sessionmaker(
        challenger_db_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@pytest.fixture
def cache_service():
    """Isolated in-memory CacheService with transparent fallback."""
    service = CacheService()
    service.fallback = InMemoryCache()
    service._redis_available = False
    return service


@pytest.fixture
def execution_module(cache_service):
    """Isolated ExecutionModule configured for paper/dry-run trading."""
    return ExecutionModule(
        paper=True,
        cache_service=cache_service,
        audit_logger=get_audit_logger(),
    )


async def _expire_durable_trade_lock(session_factory, client_id: str) -> None:
    """Backdates the client's trades past the 30s window so the durable DB duplicate check clears."""
    async with session_factory() as s:
        trades = (await s.execute(select(DBTrade).where(DBTrade.client_id == client_id))).scalars().all()
        for t in trades:
            t.created_at = t.created_at - timedelta(seconds=31)
        await s.commit()


@pytest_asyncio.fixture
async def verified_client(session_factory):
    """Seeds a verified KYC client in the challenger database."""
    async with session_factory() as s:
        client = DBClientProfile(
            client_id="challenger_client_001",
            risk_tolerance_score=6.5,
            investment_horizon_years=7.0,
            kyc_verified=True,
            aml_flag=False,
        )
        s.add(client)
        await s.commit()
    return "challenger_client_001"


# ============================================================================
# 1. Stress-Test 30s Double-Submit Lock: Rapid Concurrent Requests
# ============================================================================

@pytest.mark.asyncio
async def test_stress_concurrent_double_submit_single_winner(
    session_factory, execution_module, verified_client
):
    """
    Stress-test rapid concurrent trade submissions for the SAME client_id.
    Fires 10 simultaneous coroutines via asyncio.gather.
    VERIFIES:
    - Exactly 1 submission succeeds.
    - Exactly 9 submissions raise DuplicateTradeError.
    - All 9 rejected submissions log a TRADE_BLOCKED entry with gate DOUBLE_SUBMIT_LOCK.
    - Exactly 1 DBTrade record is written to the database.
    - The client's audit log chain verifies with 0 tamper defects.
    """
    client_id = verified_client
    now = datetime.now(timezone.utc)
    concurrency_count = 10

    async def submit_trade(idx: int):
        async with session_factory() as s:
            try:
                res = await execution_module.execute_trade(
                    db=s,
                    client_id=client_id,
                    proposal_id=f"prop_concurrent_{idx}",
                    symbol="SPY",
                    side="BUY",
                    qty=1.0,
                    approved=True,
                    approval_timestamp=now,
                    dry_run=True,
                )
                return ("SUCCESS", idx, res)
            except DuplicateTradeError as exc:
                return ("DUPLICATE", idx, str(exc))
            except Exception as exc:
                return ("ERROR", idx, type(exc).__name__, str(exc))

    results = await asyncio.gather(*[submit_trade(i) for i in range(concurrency_count)])

    successes = [r for r in results if r[0] == "SUCCESS"]
    duplicates = [r for r in results if r[0] == "DUPLICATE"]
    errors = [r for r in results if r[0] == "ERROR"]

    # Invariants
    assert len(errors) == 0, f"Unexpected errors during concurrent execution: {errors}"
    assert len(successes) == 1, f"Expected exactly 1 success, got {len(successes)}"
    assert len(duplicates) == concurrency_count - 1, f"Expected {concurrency_count - 1} duplicates, got {len(duplicates)}"

    # Verify DB persistence: exactly 1 DBTrade
    async with session_factory() as s:
        stmt = select(DBTrade).where(DBTrade.client_id == client_id)
        trades = (await s.execute(stmt)).scalars().all()
        assert len(trades) == 1
        assert trades[0].symbol == "SPY"
        assert trades[0].qty == 1.0

        # Verify Audit Log: 1 TRADE_EXECUTED + 9 TRADE_BLOCKED = 10 entries
        stmt_audit = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        audit_entries = (await s.execute(stmt_audit)).scalars().all()
        assert len(audit_entries) == concurrency_count

        executed_entries = [e for e in audit_entries if e.event_type == "TRADE_EXECUTED"]
        blocked_entries = [e for e in audit_entries if e.event_type == "TRADE_BLOCKED"]
        assert len(executed_entries) == 1
        assert len(blocked_entries) == concurrency_count - 1

        # Check gate in blocked details
        for b in blocked_entries:
            assert b.details.get("gate") == "DOUBLE_SUBMIT_LOCK"
            assert b.status == "BLOCK"

        # Verify cryptographic hash chain integrity
        is_valid, tampered_id = await verify_audit_chain(s, client_id)
        assert is_valid is True
        assert tampered_id is None


@pytest.mark.asyncio
async def test_stress_concurrent_different_clients_no_crosstalk(
    session_factory, execution_module
):
    """
    Stress-test concurrent submissions for DIFFERENT clients.
    Verifies lock isolation: 5 distinct clients submitting concurrently must ALL succeed.
    """
    client_ids = [f"client_isolated_{i}" for i in range(5)]
    now = datetime.now(timezone.utc)

    # Seed all 5 clients
    async with session_factory() as s:
        for cid in client_ids:
            s.add(DBClientProfile(client_id=cid, kyc_verified=True, aml_flag=False))
        await s.commit()

    async def submit_for_client(cid: str):
        async with session_factory() as s:
            return await execution_module.execute_trade(
                db=s,
                client_id=cid,
                proposal_id=f"prop_{cid}",
                symbol="QQQ",
                side="BUY",
                qty=2.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )

    results = await asyncio.gather(*[submit_for_client(cid) for cid in client_ids])

    # All 5 should succeed
    assert len(results) == 5
    for r in results:
        assert r.success is True
        assert r.status == "FILLED"

    # Verify all 5 DBTrade records and audit chains
    async with session_factory() as s:
        for cid in client_ids:
            stmt = select(DBTrade).where(DBTrade.client_id == cid)
            trade = (await s.execute(stmt)).scalars().first()
            assert trade is not None
            assert trade.symbol == "QQQ"

            valid, tampered = await verify_audit_chain(s, cid)
            assert valid is True
            assert tampered is None


# ============================================================================
# 2. Stress-Test Lock Release After TTL Expiration
# ============================================================================

@pytest.mark.asyncio
async def test_stress_lock_release_after_ttl_expiration(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Stress-test lock lifecycle:
    1. First submission acquires lock and succeeds.
    2. Immediate second submission is rejected by the 30s lock.
    3. Fast-forwarding time past the 30s TTL allows the next submission to succeed.
    4. Manual release_lock also allows immediate submission.
    """
    client_id = verified_client
    now = datetime.now(timezone.utc)

    # Step 1: Initial trade succeeds
    async with session_factory() as s:
        r1 = await execution_module.execute_trade(
            db=s,
            client_id=client_id,
            proposal_id="prop_ttl_1",
            symbol="SPY",
            side="BUY",
            qty=5.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
        assert r1.success is True

    # Step 2: Immediate re-submit is blocked
    with pytest.raises(DuplicateTradeError) as exc_info:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s,
                client_id=client_id,
                proposal_id="prop_ttl_2",
                symbol="SPY",
                side="BUY",
                qty=5.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )
    assert "30 seconds" in str(exc_info.value)

    # Step 3: Fast-forward lock expiration in cache
    lock_key = key_trade_lock(client_id)
    val, exp = cache_service.fallback._data[lock_key]
    # Set expire_at to 1 second in the past
    cache_service.fallback._data[lock_key] = (val, time.time() - 1.0)
    await _expire_durable_trade_lock(session_factory, client_id)

    # Step 4: Submission after TTL expiration must succeed
    async with session_factory() as s:
        r2 = await execution_module.execute_trade(
            db=s,
            client_id=client_id,
            proposal_id="prop_ttl_3",
            symbol="SPY",
            side="BUY",
            qty=5.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
        assert r2.success is True

    # Step 5: Test explicit lock release
    await cache_service.release_lock(lock_key)
    async with session_factory() as s:
        r3 = await execution_module.execute_trade(
            db=s,
            client_id=client_id,
            proposal_id="prop_ttl_4",
            symbol="SPY",
            side="SELL",
            qty=2.0,
            approved=True,
            approval_timestamp=now,
            dry_run=True,
        )
        assert r3.success is True

    # Verify all 3 trades persisted
    async with session_factory() as s:
        stmt = select(DBTrade).where(DBTrade.client_id == client_id)
        trades = (await s.execute(stmt)).scalars().all()
        assert len(trades) == 3


# ============================================================================
# 3. Stress-Test REG-004 Approval Freshness Window Boundary Analysis
# ============================================================================

@pytest.mark.asyncio
async def test_stress_reg_004_approval_freshness_boundary_exact_cases(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Sub-second and boundary analysis for REG-004:
    - 14 minutes ago (840s): PASS
    - 14m 59s ago (899s): PASS
    - Exactly 15 minutes (900.0s boundary): PASS
    - 15 minutes 1 second ago (901.0s): FAIL (ExpiredApprovalError)
    - 15 minutes + 1 millisecond (900.001s): FAIL (ExpiredApprovalError)
    - 16 minutes ago (960s): FAIL (ExpiredApprovalError)
    - Future timestamps:
      * +30s in future (within 60s skew tolerance): PASS
      * +65s in future (beyond 60s skew tolerance): FAIL (ExpiredApprovalError)
    """
    client_id = verified_client
    T0 = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    lock_key = key_trade_lock(client_id)

    async def attempt_at_offset(delta: timedelta) -> TradeExecutionResult:
        await cache_service.release_lock(lock_key)
        await _expire_durable_trade_lock(session_factory, client_id)
        with patch("agents.execution_module.datetime") as mock_dt:
            mock_dt.now.return_value = T0
            mock_dt.side_effect = lambda *args, **kw: datetime(*args, **kw)
            async with session_factory() as s:
                return await execution_module.execute_trade(
                    db=s,
                    client_id=client_id,
                    proposal_id=f"prop_fresh_{delta.total_seconds()}",
                    symbol="VTI",
                    side="BUY",
                    qty=1.0,
                    approved=True,
                    approval_timestamp=T0 - delta,
                    dry_run=True,
                )

    # 1. 14 minutes (840s): PASS
    res_14m = await attempt_at_offset(timedelta(minutes=14))
    assert res_14m.success is True

    # 2. 14m 59s (899s): PASS
    res_14m59s = await attempt_at_offset(timedelta(seconds=899))
    assert res_14m59s.success is True

    # 3. Exactly 15 minutes (900.0s boundary): PASS
    res_15m = await attempt_at_offset(timedelta(seconds=900.0))
    assert res_15m.success is True

    # 4. 15 minutes 1 second (901.0s): FAIL
    with pytest.raises(ExpiredApprovalError) as exc_901:
        await attempt_at_offset(timedelta(seconds=901.0))
    assert "REG-004" in str(exc_901.value)
    assert "901.0s" in str(exc_901.value)

    # 5. 15 minutes + 1 ms (900.001s): FAIL
    with pytest.raises(ExpiredApprovalError) as exc_sub_ms:
        await attempt_at_offset(timedelta(seconds=900.001))
    assert "REG-004" in str(exc_sub_ms.value)

    # 6. 16 minutes (960s): FAIL
    with pytest.raises(ExpiredApprovalError) as exc_16m:
        await attempt_at_offset(timedelta(minutes=16))
    assert "REG-004" in str(exc_16m.value)

    # 7. Future timestamp within 60s clock skew (+30s): PASS
    res_skew_ok = await attempt_at_offset(timedelta(seconds=-30.0))
    assert res_skew_ok.success is True

    # 8. Future timestamp beyond 60s clock skew (+65s): FAIL
    with pytest.raises(ExpiredApprovalError) as exc_future:
        await attempt_at_offset(timedelta(seconds=-65.0))
    assert "future" in str(exc_future.value).lower()


@pytest.mark.asyncio
async def test_stress_reg_004_timezone_awareness_and_naive(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Stress-test approval timestamp timezone handling:
    - Timezone-aware UTC.
    - Timezone-aware non-UTC (e.g. UTC-5 EST).
    - Naive datetime (assumed UTC).
    All must normalize correctly without type errors.
    """
    client_id = verified_client
    lock_key = key_trade_lock(client_id)
    now_utc = datetime.now(timezone.utc)

    # 1. Non-UTC timezone (UTC-5) 5 minutes ago
    tz_est = timezone(timedelta(hours=-5))
    ts_est = now_utc.astimezone(tz_est) - timedelta(minutes=5)
    await cache_service.release_lock(lock_key)

    async with session_factory() as s:
        r1 = await execution_module.execute_trade(
            db=s,
            client_id=client_id,
            proposal_id="prop_tz_est",
            symbol="BND",
            side="BUY",
            qty=2.0,
            approved=True,
            approval_timestamp=ts_est,
            dry_run=True,
        )
        assert r1.success is True

    # 2. Naive datetime 5 minutes ago
    ts_naive = datetime.utcnow() - timedelta(minutes=5)
    await cache_service.release_lock(lock_key)

    async with session_factory() as s:
        r2 = await execution_module.execute_trade(
            db=s,
            client_id=client_id,
            proposal_id="prop_tz_naive",
            symbol="BND",
            side="SELL",
            qty=1.0,
            approved=True,
            approval_timestamp=ts_naive,
            dry_run=True,
        )
        assert r2.success is True


# ============================================================================
# 4. Stress-Test Unverified KYC Client Blocked
# ============================================================================

@pytest.mark.asyncio
async def test_stress_unverified_kyc_client_scenarios(
    session_factory, execution_module, cache_service
):
    """
    Stress-test KYC gate:
    1. Client with kyc_verified=False is rejected.
    2. Client with kyc_verified=None/missing is rejected.
    3. Non-existent client is rejected.
    4. Verify no DBTrade is written.
    5. Verify audit log records TRADE_BLOCKED with gate KYC_VERIFICATION.
    6. Verify double-submit lock was NOT locked by rejected attempts.
    """
    now = datetime.now(timezone.utc)

    # Seed client with kyc_verified = False
    async with session_factory() as s:
        s.add(DBClientProfile(client_id="kyc_false_client", kyc_verified=False))
        await s.commit()

    # Scenario 1: kyc_verified = False
    with pytest.raises(KYCUnverifiedError) as exc1:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s,
                client_id="kyc_false_client",
                proposal_id="p_kyc_1",
                symbol="AAPL",
                side="BUY",
                qty=3.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )
    assert "not KYC verified" in str(exc1.value)

    # Scenario 2: Non-existent client
    with pytest.raises(KYCUnverifiedError) as exc2:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s,
                client_id="ghost_client_404",
                proposal_id="p_kyc_2",
                symbol="AAPL",
                side="BUY",
                qty=3.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )
    assert "not found" in str(exc2.value).lower()

    # Invariant: No trade written to DBTrade
    async with session_factory() as s:
        stmt = select(DBTrade).where(DBTrade.client_id == "kyc_false_client")
        trades = (await s.execute(stmt)).scalars().all()
        assert len(trades) == 0

        # Invariant: Audit log recorded TRADE_BLOCKED
        stmt_audit = select(DBAuditLog).where(DBAuditLog.client_id == "kyc_false_client")
        audits = (await s.execute(stmt_audit)).scalars().all()
        assert len(audits) == 1
        assert audits[0].event_type == "TRADE_BLOCKED"
        assert audits[0].details.get("gate") == "KYC_VERIFICATION"
        assert audits[0].status == "BLOCK"

    # Invariant: Lock was NOT acquired by rejected KYC attempt
    lock_key = key_trade_lock("kyc_false_client")
    is_locked = await cache_service.fallback.exists(lock_key)
    assert is_locked is False, "Double-submit lock should NOT be held after KYC failure."


# ============================================================================
# 5. Stress-Test Trade Execution Without Approval (REG-003)
# ============================================================================

@pytest.mark.asyncio
async def test_stress_trade_without_approval_blocked_reg_003(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Stress-test REG-003 gate:
    1. approved=False raises UnapprovedTradeError.
    2. UnapprovedTradeError is an instance of ExecutionError and ValueError.
    3. Trade is NOT recorded in DBTrade.
    4. Audit log records TRADE_BLOCKED with gate REG-003.
    5. Double-submit lock is NOT held.
    """
    client_id = verified_client
    now = datetime.now(timezone.utc)

    with pytest.raises(UnapprovedTradeError) as exc_info:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s,
                client_id=client_id,
                proposal_id="prop_unapproved",
                symbol="MSFT",
                side="BUY",
                qty=4.0,
                approved=False,  # Unapproved
                approval_timestamp=now,
                dry_run=True,
            )

    # Invariant: inherits from ValueError and ExecutionError
    assert isinstance(exc_info.value, ValueError)
    assert isinstance(exc_info.value, ExecutionError)
    assert "REG-003" in str(exc_info.value)

    # Invariant: DBTrade is clean
    async with session_factory() as s:
        stmt = select(DBTrade).where(DBTrade.client_id == client_id)
        trades = (await s.execute(stmt)).scalars().all()
        assert len(trades) == 0

        # Invariant: Audit log recorded TRADE_BLOCKED
        stmt_audit = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        audits = (await s.execute(stmt_audit)).scalars().all()
        assert len(audits) == 1
        assert audits[0].event_type == "TRADE_BLOCKED"
        assert audits[0].details.get("gate") == "REG-003"
        assert audits[0].status == "BLOCK"

    # Invariant: Lock was NOT acquired
    lock_key = key_trade_lock(client_id)
    is_locked = await cache_service.fallback.exists(lock_key)
    assert is_locked is False, "Double-submit lock should NOT be held after REG-003 failure."


# ============================================================================
# 6. Stress-Test Dry-Run Execution and Database Persistence to DBTrade
# ============================================================================

@pytest.mark.asyncio
async def test_stress_dry_run_execution_and_persistence(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Stress-test dry-run execution and database persistence:
    1. Executes trades across multiple standard and unknown tickers.
    2. Verifies simulation pricing logic.
    3. Verifies every required column of DBTrade is persisted accurately.
    4. Verifies cryptographic audit chain integrity across consecutive trades.
    """
    client_id = verified_client
    test_symbols = [
        ("SPY", 510.50),
        ("QQQ", 440.25),
        ("NVDA", 125.00),
        ("UNKNOWN_CO", 100.00),  # Falls back to default price 100.00
    ]

    lock_key = key_trade_lock(client_id)

    for sym, expected_price in test_symbols:
        await cache_service.release_lock(lock_key)
        now = datetime.now(timezone.utc)

        async with session_factory() as s:
            result = await execution_module.execute_trade(
                db=s,
                client_id=client_id,
                proposal_id=f"prop_persist_{sym}",
                symbol=sym,
                side="BUY",
                qty=10.0,
                approved=True,
                approval_timestamp=now,
                dry_run=True,
            )

            # Check result schema
            assert result.success is True
            assert result.status == "FILLED"
            assert result.dry_run is True
            assert result.order_id.startswith("dry-run-")
            assert result.filled_price == expected_price
            assert result.filled_qty == 10.0
            assert result.trade_id is not None

            # Check DBTrade row
            db_trade = await s.get(DBTrade, result.trade_id)
            assert db_trade is not None
            assert db_trade.client_id == client_id
            assert db_trade.symbol == sym
            assert db_trade.qty == 10.0
            assert db_trade.side == "BUY"
            assert db_trade.order_type == "MARKET"
            assert db_trade.status == "FILLED"
            assert db_trade.filled_price == expected_price
            assert db_trade.filled_qty == 10.0
            assert db_trade.alpaca_order_id == result.order_id
            assert db_trade.compliance_report is not None
            assert "validation_gates" in db_trade.compliance_report
            assert db_trade.user_approved_at is not None
            assert db_trade.filled_at is not None
            assert db_trade.created_at is not None

    # Verify cumulative DBTrade and audit log chain
    async with session_factory() as s:
        stmt = select(DBTrade).where(DBTrade.client_id == client_id)
        trades = (await s.execute(stmt)).scalars().all()
        assert len(trades) == len(test_symbols)

        valid, tampered_id = await verify_audit_chain(s, client_id)
        assert valid is True
        assert tampered_id is None


# ============================================================================
# 7. Stress-Test Input Validation & Live Trading Security Guards
# ============================================================================

@pytest.mark.asyncio
async def test_stress_input_validation_and_tamper_detection(
    session_factory, execution_module, verified_client, cache_service
):
    """
    Stress-test boundary edge inputs and tamper detection:
    - Empty and whitespace symbol.
    - Invalid trade side.
    - Non-positive qty.
    - Tampered audit log entry fails verification.
    """
    client_id = verified_client
    now = datetime.now(timezone.utc)

    # 1. Whitespace symbol
    with pytest.raises(ValueError) as exc1:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s, client_id=client_id, proposal_id="p", symbol="   ",
                side="BUY", qty=1.0, approved=True, approval_timestamp=now,
            )
    assert "Symbol cannot be empty" in str(exc1.value)

    # 2. Invalid side
    with pytest.raises(ValueError) as exc2:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s, client_id=client_id, proposal_id="p", symbol="SPY",
                side="HODL", qty=1.0, approved=True, approval_timestamp=now,
            )
    assert "Invalid side" in str(exc2.value)

    # 3. Negative quantity
    with pytest.raises(ValueError) as exc3:
        async with session_factory() as s:
            await execution_module.execute_trade(
                db=s, client_id=client_id, proposal_id="p", symbol="SPY",
                side="BUY", qty=-5.0, approved=True, approval_timestamp=now,
            )
    assert "positive" in str(exc3.value).lower()

    # 4. Successful trade followed by intentional tamper detection
    lock_key = key_trade_lock(client_id)
    await cache_service.release_lock(lock_key)

    async with session_factory() as s:
        res = await execution_module.execute_trade(
            db=s, client_id=client_id, proposal_id="p_tamper", symbol="SPY",
            side="BUY", qty=1.0, approved=True, approval_timestamp=now, dry_run=True,
        )
        assert res.success is True

        # Verify initial valid chain
        valid, _ = await verify_audit_chain(s, client_id)
        assert valid is True

        # Tamper with the audit log entry's hash in database
        stmt = select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        entry = (await s.execute(stmt)).scalars().first()
        assert entry is not None

        # Directly tamper with raw entry hash via connection update bypassing ORM listener
        conn = await s.connection()
        await conn.exec_driver_sql(
            "UPDATE audit_log SET entry_hash = 'tampered_bad_hash_value' WHERE id = ?",
            (entry.id,)
        )
        await s.commit()

        # Chain verification must now fail
        valid_after, tampered_id = await verify_audit_chain(s, client_id)
        assert valid_after is False
        assert tampered_id == entry.id

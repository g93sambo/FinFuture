"""
Unit tests for backend/services/otp_service.py and the step-up approval path (PERM-STEP-UP-MFA).

Covers: random single-use codes stored only as digests, attempt limits, resend throttling,
per-user binding, expiry, fail-closed delivery in production, and the orchestrator gate.
"""

import json
import re
import uuid

import pytest
import pytest_asyncio
from pydantic import ValidationError

from agents.orchestrator import TradeBlocked, build_container
from core.config import Settings
from core.security import get_password_hash
from db.models import DBClientProfile, DBUser
from services.cache import CacheService
from services.otp_service import (
    EmailSender,
    OTPDeliveryError,
    OTPRateLimitedError,
    StepUpOTPService,
    key_step_up_otp,
    mask_email,
)


class CapturingSender(EmailSender):
    """Records outgoing mail instead of delivering it."""

    def __init__(self, cfg: Settings) -> None:
        super().__init__(cfg)
        self.outbox = []

    @property
    def channel(self) -> str:
        return "smtp"

    async def send(self, to: str, subject: str, text: str) -> None:
        self.outbox.append({"to": to, "subject": subject, "text": text})

    def last_code(self) -> str:
        return re.search(r"code is: (\d{6})", self.outbox[-1]["text"]).group(1)


def make_service(**overrides):
    cfg = Settings(_env_file=None, otp_resend_cooldown_seconds=0, **overrides)
    sender = CapturingSender(cfg)
    return StepUpOTPService(CacheService(redis_url="redis://127.0.0.1:1/0"), cfg=cfg, sender=sender), sender


def proposal(pid=None):
    return {
        "proposal_id": pid or str(uuid.uuid4()),
        "symbol": "SPY",
        "side": "BUY",
        "qty": 10,
        "notional_value": 5000.0,
        "currency": "USD",
    }


@pytest.mark.asyncio
async def test_code_is_random_emailed_and_stored_only_as_digest():
    svc, sender = make_service()
    p = proposal("98765432-aaaa-bbbb-cccc-111122223333")
    info = await svc.issue("user-1", "jane.doe@gmail.com", p)
    code = sender.last_code()

    assert sender.outbox[-1]["to"] == "jane.doe@gmail.com"
    assert info["destination"] == "j******e@gmail.com"
    assert "dev_code" not in info
    # Not derivable from the proposal id (the old scheme returned "987654")
    assert code != "987654" or (await svc.issue("user-1", "jane.doe@gmail.com", p) and sender.last_code() != "987654")
    stored = json.dumps(await svc.cache.get_json(key_step_up_otp(p["proposal_id"])))
    assert sender.last_code() not in stored


@pytest.mark.asyncio
async def test_codes_differ_across_issues():
    svc, sender = make_service()
    codes = set()
    for _ in range(5):
        p = proposal()
        await svc.issue("user-1", "a@b.com", p)
        codes.add(sender.last_code())
    assert len(codes) > 1


@pytest.mark.asyncio
async def test_valid_code_is_single_use():
    svc, sender = make_service()
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    code = sender.last_code()

    assert (await svc.verify("user-1", p["proposal_id"], code)).ok is True
    replay = await svc.verify("user-1", p["proposal_id"], code)
    assert replay.ok is False
    assert "No active verification code" in replay.reason


@pytest.mark.asyncio
async def test_code_is_bound_to_user():
    svc, sender = make_service()
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    assert (await svc.verify("attacker", p["proposal_id"], sender.last_code())).ok is False
    # The legitimate user's code is still valid afterwards
    assert (await svc.verify("user-1", p["proposal_id"], sender.last_code())).ok is True


@pytest.mark.asyncio
async def test_attempt_limit_burns_the_code():
    svc, sender = make_service(otp_max_attempts=3)
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    code = sender.last_code()
    wrong = "000000" if code != "000000" else "111111"

    first = await svc.verify("user-1", p["proposal_id"], wrong)
    assert (first.ok, first.attempts_remaining) == (False, 2)
    await svc.verify("user-1", p["proposal_id"], "abc")  # malformed input also counts
    last = await svc.verify("user-1", p["proposal_id"], wrong)
    assert last.locked is True
    assert (await svc.verify("user-1", p["proposal_id"], code)).ok is False


@pytest.mark.asyncio
async def test_resend_replaces_previous_code():
    svc, sender = make_service()
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    old = sender.last_code()
    await svc.issue("user-1", "a@b.com", p)
    new = sender.last_code()
    if old != new:
        assert (await svc.verify("user-1", p["proposal_id"], old)).ok is False
    assert (await svc.verify("user-1", p["proposal_id"], new)).ok is True


@pytest.mark.asyncio
async def test_resend_cooldown_and_send_cap():
    svc, _ = make_service()
    svc.cfg = Settings(_env_file=None, otp_resend_cooldown_seconds=60)
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    with pytest.raises(OTPRateLimitedError) as exc:
        await svc.issue("user-1", "a@b.com", p)
    assert exc.value.retry_after and exc.value.retry_after > 0

    svc2, _ = make_service(otp_max_sends=2)
    p2 = proposal()
    await svc2.issue("user-1", "a@b.com", p2)
    await svc2.issue("user-1", "a@b.com", p2)
    with pytest.raises(OTPRateLimitedError):
        await svc2.issue("user-1", "a@b.com", p2)


@pytest.mark.asyncio
async def test_expired_code_is_rejected():
    svc, sender = make_service()
    p = proposal()
    await svc.issue("user-1", "a@b.com", p)
    key = key_step_up_otp(p["proposal_id"])
    challenge = await svc.cache.get_json(key)
    challenge["expires_at"] = 0
    await svc.cache.set_json(key, challenge, expire=60)
    assert (await svc.verify("user-1", p["proposal_id"], sender.last_code())).ok is False


@pytest.mark.asyncio
async def test_console_delivery_fails_closed_in_production():
    cfg = Settings(_env_file=None, environment="production", secret_key="a" * 40, audit_secret_key="b" * 40)
    sender = EmailSender(cfg)
    assert sender.channel == "console"
    with pytest.raises(OTPDeliveryError):
        await sender.send("a@b.com", "s", "t")

    svc = StepUpOTPService(CacheService(redis_url="redis://127.0.0.1:1/0"), cfg=cfg, sender=sender)
    p = proposal()
    with pytest.raises(OTPDeliveryError):
        await svc.issue("user-1", "a@b.com", p)
    # A failed send leaves no usable challenge behind
    assert await svc.cache.get_json(key_step_up_otp(p["proposal_id"])) is None


def test_email_mode_without_provider_is_unconfigured():
    assert EmailSender(Settings(_env_file=None, otp_delivery="email")).channel == "unconfigured"
    assert EmailSender(Settings(_env_file=None, smtp_host="smtp.gmail.com")).channel == "smtp"
    assert EmailSender(Settings(_env_file=None, resend_api_key="re_x", smtp_host="smtp.gmail.com")).channel == "resend"
    assert EmailSender(Settings(_env_file=None, brevo_api_key="xkeysib", resend_api_key="re_x")).channel == "brevo"


@pytest.mark.asyncio
async def test_dev_echo_is_opt_in_and_refused_in_production():
    cfg = Settings(_env_file=None, otp_dev_echo=True)
    svc = StepUpOTPService(CacheService(redis_url="redis://127.0.0.1:1/0"), cfg=cfg)
    info = await svc.issue("user-1", "a@b.com", proposal())
    assert info["delivery"] == "console" and re.fullmatch(r"\d{6}", info["dev_code"])

    with pytest.raises(ValidationError):
        Settings(_env_file=None, environment="production", secret_key="a" * 40, audit_secret_key="b" * 40, otp_dev_echo=True)


def test_mask_email():
    assert mask_email("ab@x.io") == "a*@x.io"
    assert mask_email("not-an-email") == "your registered email"


# ---------------------------------------------------------------------------
# Orchestrator gate
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def red_tier_setup(db_session):
    user = DBUser(
        id=str(uuid.uuid4()),
        email=f"otp_{uuid.uuid4().hex[:6]}@example.com",
        hashed_password=get_password_hash("test-pass-otp!"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    profile = DBClientProfile(
        client_id=str(uuid.uuid4()),
        user_id=user.id,
        age=35,
        annual_income=150000.0,
        liquid_assets=100000.0,
        investment_horizon_years=15,
        risk_tolerance_score=7.5,
        suitability_category="Growth",
        kyc_verified=True,
    )
    db_session.add(profile)
    await db_session.commit()

    container = build_container()
    sender = CapturingSender(container.otp.cfg)
    container.otp.sender = sender
    container.otp.cfg = Settings(_env_file=None, otp_resend_cooldown_seconds=0)
    p = await container.orchestrator.create_trade_proposal(db_session, profile.client_id, "SPY", "BUY", 5)
    assert p["requires_step_up_auth"] is True
    return container, user, p, sender


@pytest.mark.asyncio
async def test_orchestrator_rejects_wrong_code_and_accepts_emailed_code(db_session, red_tier_setup):
    container, user, p, sender = red_tier_setup
    orch = container.orchestrator
    info = await orch.request_step_up_code(db_session, user.id, user.email, p["proposal_id"])
    assert info["destination"].endswith("@example.com")
    code = sender.last_code()
    wrong = "000000" if code != "000000" else "111111"

    with pytest.raises(TradeBlocked) as bad:
        await orch.handle_trade_approval(db_session, user.id, p["proposal_id"], True, mfa_code=wrong, fiduciary_attested=True)
    assert bad.value.error_type == "InvalidStepUpCodeError"
    assert "attempts left" in bad.value.reason

    events = await orch.handle_trade_approval(
        db_session, user.id, p["proposal_id"], True, mfa_code=code, fiduciary_attested=True
    )
    assert any(e.get("event") == "trade_filled" for e in events)


@pytest.mark.asyncio
async def test_missing_attestation_does_not_consume_code(db_session, red_tier_setup):
    container, user, p, sender = red_tier_setup
    orch = container.orchestrator
    await orch.request_step_up_code(db_session, user.id, user.email, p["proposal_id"])
    code = sender.last_code()

    with pytest.raises(TradeBlocked) as no_attest:
        await orch.handle_trade_approval(db_session, user.id, p["proposal_id"], True, mfa_code=code, fiduciary_attested=False)
    assert no_attest.value.error_type == "AttestationRequiredError"

    events = await orch.handle_trade_approval(
        db_session, user.id, p["proposal_id"], True, mfa_code=code, fiduciary_attested=True
    )
    assert any(e.get("event") == "trade_filled" for e in events)


@pytest.mark.asyncio
async def test_code_cannot_be_requested_for_another_users_proposal(db_session, red_tier_setup):
    container, _, p, _ = red_tier_setup
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc:
        await container.orchestrator.request_step_up_code(db_session, "someone-else", "x@y.com", p["proposal_id"])
    assert exc.value.status_code == 403

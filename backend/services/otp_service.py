"""
backend/services/otp_service.py
===============================
Step-up one-time passcodes (OTP) for Red-tier trade approvals (PERM-STEP-UP-MFA).

A code is issued per (user, proposal) on request, delivered out-of-band by email, and
stored only as an HMAC digest keyed with SECRET_KEY. Codes are random (``secrets``),
expire after ``otp_ttl_seconds``, allow ``otp_max_attempts`` guesses, and are consumed
on first successful use. Resends are rate limited per proposal.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import secrets
import smtplib
import ssl
import time
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any, Dict, Optional

import httpx

from core.config import Settings, settings as default_settings
from services.cache import CacheService

logger = logging.getLogger("wealth_advisor.services.otp")

OTP_DIGITS = 6


def key_step_up_otp(proposal_id: str) -> str:
    return f"stepup:otp:{proposal_id}"


def mask_email(email: str) -> str:
    """'jane.doe@gmail.com' -> 'j******e@gmail.com'."""
    local, _, domain = (email or "").partition("@")
    if not domain:
        return "your registered email"
    if len(local) <= 2:
        masked = local[:1] + "*"
    else:
        masked = local[0] + "*" * (len(local) - 2) + local[-1]
    return f"{masked}@{domain}"


class OTPError(Exception):
    """Base class for step-up OTP failures surfaced to the API layer."""

    status_code = 400
    error_type = "StepUpOTPError"

    def __init__(self, reason: str, retry_after: Optional[int] = None) -> None:
        super().__init__(reason)
        self.reason = reason
        self.retry_after = retry_after


class OTPRateLimitedError(OTPError):
    status_code = 429
    error_type = "StepUpRateLimitedError"


class OTPDeliveryError(OTPError):
    status_code = 503
    error_type = "StepUpDeliveryError"


@dataclass
class OTPVerification:
    ok: bool
    reason: str = ""
    attempts_remaining: int = 0
    locked: bool = False


class EmailSender:
    """Delivers transactional email via Brevo or Resend (HTTPS) or SMTP, or logs it in console mode."""

    def __init__(self, cfg: Settings) -> None:
        self.cfg = cfg

    @property
    def channel(self) -> str:
        mode = (self.cfg.otp_delivery or "auto").strip().lower()
        if mode == "console":
            return "console"
        if self.cfg.brevo_api_key:
            return "brevo"
        if self.cfg.resend_api_key:
            return "resend"
        if self.cfg.smtp_host:
            return "smtp"
        return "console" if mode == "auto" else "unconfigured"

    async def send(self, to: str, subject: str, text: str) -> None:
        channel = self.channel
        if channel == "brevo":
            await self._send_brevo(to, subject, text)
        elif channel == "resend":
            await self._send_resend(to, subject, text)
        elif channel == "smtp":
            await asyncio.to_thread(self._send_smtp, to, subject, text)
        elif channel == "console":
            if self.cfg.environment.strip().lower() == "production":
                raise OTPDeliveryError(
                    "Verification codes cannot be delivered: no email provider is configured on this server."
                )
            logger.warning("[OTP console delivery] to=%s subject=%s\n%s", to, subject, text)
        else:
            raise OTPDeliveryError(
                "Verification codes cannot be delivered: no email provider is configured on this server."
            )

    async def _post_json(self, provider: str, url: str, headers: Dict[str, str], body: Dict[str, Any]) -> None:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, headers=headers, json=body)
        except httpx.HTTPError as exc:
            logger.error("%s OTP delivery failed: %s", provider, exc)
            raise OTPDeliveryError("We could not send your verification code. Please try again shortly.") from exc
        if resp.status_code >= 300:
            logger.error("%s rejected OTP email (%s): %s", provider, resp.status_code, resp.text[:300])
            raise OTPDeliveryError("We could not send your verification code. Please try again shortly.")

    async def _send_brevo(self, to: str, subject: str, text: str) -> None:
        name, address = parseaddr(self.cfg.email_from)
        await self._post_json(
            "Brevo",
            "https://api.brevo.com/v3/smtp/email",
            {"api-key": self.cfg.brevo_api_key or "", "accept": "application/json"},
            {"sender": {"name": name or self.cfg.app_name, "email": address},
             "to": [{"email": to}], "subject": subject, "textContent": text},
        )

    async def _send_resend(self, to: str, subject: str, text: str) -> None:
        await self._post_json(
            "Resend",
            "https://api.resend.com/emails",
            {"Authorization": f"Bearer {self.cfg.resend_api_key}"},
            {"from": self.cfg.email_from, "to": [to], "subject": subject, "text": text},
        )

    def _send_smtp(self, to: str, subject: str, text: str) -> None:
        msg = EmailMessage()
        msg["From"] = self.cfg.email_from
        msg["To"] = to
        msg["Subject"] = subject
        msg.set_content(text)
        context = ssl.create_default_context()
        try:
            if self.cfg.smtp_use_ssl:
                with smtplib.SMTP_SSL(self.cfg.smtp_host, self.cfg.smtp_port, context=context, timeout=15) as server:
                    self._smtp_login_and_send(server, msg)
            else:
                with smtplib.SMTP(self.cfg.smtp_host, self.cfg.smtp_port, timeout=15) as server:
                    server.starttls(context=context)
                    self._smtp_login_and_send(server, msg)
        except (smtplib.SMTPException, OSError) as exc:
            logger.error("SMTP OTP delivery failed: %s", exc)
            raise OTPDeliveryError("We could not send your verification code. Please try again shortly.") from exc

    def _smtp_login_and_send(self, server: smtplib.SMTP, msg: EmailMessage) -> None:
        if self.cfg.smtp_username:
            server.login(self.cfg.smtp_username, self.cfg.smtp_password or "")
        server.send_message(msg)


class StepUpOTPService:
    """Issues and verifies single-use step-up codes bound to one user and one trade proposal."""

    def __init__(
        self,
        cache: CacheService,
        cfg: Optional[Settings] = None,
        sender: Optional[EmailSender] = None,
    ) -> None:
        self.cache = cache
        self.cfg = cfg or default_settings
        self.sender = sender or EmailSender(self.cfg)

    def _digest(self, user_id: str, proposal_id: str, code: str) -> str:
        msg = f"{proposal_id}:{user_id}:{code}".encode("utf-8")
        return hmac.new(self.cfg.secret_key.encode("utf-8"), msg, hashlib.sha256).hexdigest()

    async def _load(self, proposal_id: str) -> Optional[Dict[str, Any]]:
        challenge = await self.cache.get_json(key_step_up_otp(proposal_id))
        if not challenge or float(challenge.get("expires_at", 0)) <= time.time():
            return None
        return challenge

    async def _store(self, proposal_id: str, challenge: Dict[str, Any]) -> None:
        ttl = max(1, int(float(challenge["expires_at"]) - time.time()))
        await self.cache.set_json(key_step_up_otp(proposal_id), challenge, expire=ttl)

    async def issue(self, user_id: str, email: str, proposal: Dict[str, Any]) -> Dict[str, Any]:
        """Generates a fresh code for the proposal, replacing any earlier one, and emails it."""
        proposal_id = str(proposal["proposal_id"])
        now = time.time()
        existing = await self._load(proposal_id)
        sends = 0
        if existing and existing.get("user_id") == str(user_id):
            sends = int(existing.get("sends", 0))
            wait = int(self.cfg.otp_resend_cooldown_seconds - (now - float(existing.get("last_sent_at", 0))))
            if wait > 0:
                raise OTPRateLimitedError(f"Please wait {wait}s before requesting another code.", retry_after=wait)
            if sends >= self.cfg.otp_max_sends:
                raise OTPRateLimitedError(
                    "Too many codes requested for this order. Cancel it and create a new proposal.",
                    retry_after=int(float(existing["expires_at"]) - now),
                )

        code = f"{secrets.randbelow(10 ** OTP_DIGITS):0{OTP_DIGITS}d}"
        challenge = {
            "user_id": str(user_id),
            "digest": self._digest(str(user_id), proposal_id, code),
            "attempts": 0,
            "sends": sends + 1,
            "last_sent_at": now,
            "expires_at": now + self.cfg.otp_ttl_seconds,
        }
        await self._store(proposal_id, challenge)

        minutes = max(1, self.cfg.otp_ttl_seconds // 60)
        curr = "₦" if proposal.get("currency") == "NGN" else "$"
        subject = f"{code} is your {self.cfg.app_name} trade verification code"
        text = (
            f"Your verification code is: {code}\n\n"
            f"It approves this order only: {proposal.get('side')} {float(proposal.get('qty', 0)):g} "
            f"{proposal.get('symbol')} (~{curr}{float(proposal.get('notional_value', 0)):,.2f}).\n"
            f"The code expires in {minutes} minutes and can be used once.\n\n"
            "If you did not request this, do not share the code with anyone, and change your password."
        )
        try:
            await self.sender.send(email, subject, text)
        except OTPDeliveryError:
            await self.cache.delete(key_step_up_otp(proposal_id))
            raise

        result = {
            "proposal_id": proposal_id,
            "delivery": self.sender.channel,
            "destination": mask_email(email),
            "expires_in_seconds": self.cfg.otp_ttl_seconds,
            "resend_after_seconds": self.cfg.otp_resend_cooldown_seconds,
            "max_attempts": self.cfg.otp_max_attempts,
        }
        if self.sender.channel == "console" and self.cfg.otp_dev_echo:
            # Opt-in local-demo aid only; Settings refuses OTP_DEV_ECHO in production.
            result["dev_code"] = code
        return result

    async def verify(self, user_id: str, proposal_id: str, code: str) -> OTPVerification:
        """Checks a submitted code. Success consumes it; too many failures burn the challenge."""
        lock_key = f"lock:stepup:{proposal_id}"
        if not await self.cache.acquire_lock(lock_key, timeout_seconds=5):
            return OTPVerification(ok=False, reason="Another verification for this order is in progress. Try again.")
        try:
            challenge = await self._load(proposal_id)
            if not challenge or challenge.get("user_id") != str(user_id):
                return OTPVerification(
                    ok=False, reason="No active verification code for this order. Request a new code."
                )
            supplied = (code or "").strip()
            expected = challenge["digest"]
            if supplied.isdigit() and len(supplied) == OTP_DIGITS and hmac.compare_digest(
                self._digest(str(user_id), proposal_id, supplied), expected
            ):
                await self.cache.delete(key_step_up_otp(proposal_id))
                return OTPVerification(ok=True)

            challenge["attempts"] = int(challenge.get("attempts", 0)) + 1
            remaining = self.cfg.otp_max_attempts - challenge["attempts"]
            if remaining <= 0:
                await self.cache.delete(key_step_up_otp(proposal_id))
                return OTPVerification(
                    ok=False,
                    locked=True,
                    reason="Too many incorrect codes. This code has been invalidated; request a new one.",
                )
            await self._store(proposal_id, challenge)
            return OTPVerification(
                ok=False,
                attempts_remaining=remaining,
                reason=f"Incorrect verification code. {remaining} attempt{'s' if remaining != 1 else ''} left.",
            )
        finally:
            await self.cache.release_lock(lock_key)

"""Authentication routes: register, login (OAuth2 password flow), me."""

from __future__ import annotations

import logging
import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from core.security import create_access_token, get_current_user, get_password_hash, verify_password
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])
logger = logging.getLogger("wealth_advisor.api.auth")

# Per-account failed-login throttle (in-process; resets on restart and is not shared across instances)
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
REGISTER_WINDOW_SECONDS = 60 * 60
_failed_logins: Dict[str, List[float]] = {}
# Per-IP throttles: failed logins across many accounts (credential spraying) and account creation
_ip_login_failures: Dict[str, List[float]] = {}
_ip_registrations: Dict[str, List[float]] = {}


def _prune(store: Dict[str, List[float]], key: str, now: float, window: float) -> List[float]:
    events = [t for t in store.get(key, []) if now - t < window]
    if events:
        store[key] = events
    else:
        store.pop(key, None)
    return events


def _recent_failures(email: str, now: float) -> List[float]:
    return _prune(_failed_logins, email, now, LOGIN_FAILURE_WINDOW_SECONDS)


def _client_ip(request: Request) -> str:
    # Behind Render's proxy the last X-Forwarded-For hop is the address the proxy saw
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def _too_many(detail: str, retry_after: float) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        detail=detail,
        headers={"Retry-After": str(int(retry_after) + 1)},
    )


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserResponse(BaseModel):
    id: str
    email: str


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(req: RegisterRequest, request: Request, db: AsyncSession = Depends(get_db)):
    if settings.auth_rate_limit_enabled:
        ip, now = _client_ip(request), time.time()
        recent = _prune(_ip_registrations, ip, now, REGISTER_WINDOW_SECONDS)
        if len(recent) >= settings.register_max_per_ip_per_hour:
            raise _too_many("Too many accounts created from this network. Try again later.", REGISTER_WINDOW_SECONDS - (now - recent[0]))
        _ip_registrations.setdefault(ip, []).append(now)
    email = req.email.lower()
    existing = await db.execute(select(DBUser).where(DBUser.email == email))
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Email already registered")
    try:
        user = DBUser(email=email, hashed_password=get_password_hash(req.password))
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return UserResponse(id=user.id, email=user.email)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    except Exception as exc:
        await db.rollback()
        logger.exception("Registration failed unexpectedly: %s", exc)
        raise HTTPException(status_code=500, detail="Registration failed. Please try again.")


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/login", response_model=TokenResponse)
async def login(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    email: Optional[str] = None
    password: Optional[str] = None

    # Detect Content-Type to support both application/json and application/x-www-form-urlencoded
    content_type = request.headers.get("content-type", "")
    if "application/json" in content_type:
        try:
            body = await request.json()
            email = body.get("email") or body.get("username")
            password = body.get("password")
        except Exception:
            pass
    else:
        try:
            form = await request.form()
            email = form.get("username") or form.get("email")
            password = form.get("password")
        except Exception:
            pass

    if not email or not password:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Missing username/email or password in request",
        )

    email_key = email.lower()
    now = time.time()
    ip = _client_ip(request)
    if settings.auth_rate_limit_enabled:
        ip_failures = _prune(_ip_login_failures, ip, now, LOGIN_FAILURE_WINDOW_SECONDS)
        if len(ip_failures) >= settings.login_failures_max_per_ip:
            raise _too_many("Too many failed login attempts from this network. Try again later.", LOGIN_FAILURE_WINDOW_SECONDS - (now - ip_failures[0]))
    failures = _recent_failures(email_key, now)
    if len(failures) >= LOGIN_MAX_FAILURES:
        raise _too_many("Too many failed login attempts for this account. Try again later.", LOGIN_FAILURE_WINDOW_SECONDS - (now - failures[0]))

    result = await db.execute(select(DBUser).where(DBUser.email == email_key))
    user = result.scalars().first()
    if user is None or not verify_password(password, user.hashed_password):
        _failed_logins.setdefault(email_key, []).append(now)
        if settings.auth_rate_limit_enabled:
            _ip_login_failures.setdefault(ip, []).append(now)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user account")
    _failed_logins.pop(email_key, None)
    return TokenResponse(access_token=create_access_token({"sub": user.id}))


@router.get("/me", response_model=UserResponse)
async def me(user: DBUser = Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email)

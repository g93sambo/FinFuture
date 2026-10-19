"""Authentication routes: register, login (OAuth2 password flow), me."""

from __future__ import annotations

import time
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_access_token, get_current_user, get_password_hash, verify_password
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Per-account failed-login throttle (in-process; resets on restart and is not shared across instances)
LOGIN_MAX_FAILURES = 5
LOGIN_FAILURE_WINDOW_SECONDS = 15 * 60
_failed_logins: Dict[str, List[float]] = {}


def _recent_failures(email: str, now: float) -> List[float]:
    failures = [t for t in _failed_logins.get(email, []) if now - t < LOGIN_FAILURE_WINDOW_SECONDS]
    if failures:
        _failed_logins[email] = failures
    else:
        _failed_logins.pop(email, None)
    return failures


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
async def register(req: RegisterRequest, db: AsyncSession = Depends(get_db)):
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
        import logging
        logging.getLogger("wealth_advisor.api.auth").exception("Registration failed unexpectedly: %s", exc)
        raise HTTPException(status_code=500, detail=f"Registration error: {str(exc)}")


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
    failures = _recent_failures(email_key, now)
    if len(failures) >= LOGIN_MAX_FAILURES:
        retry_after = int(LOGIN_FAILURE_WINDOW_SECONDS - (now - failures[0])) + 1
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many failed login attempts for this account. Try again later.",
            headers={"Retry-After": str(retry_after)},
        )

    result = await db.execute(select(DBUser).where(DBUser.email == email_key))
    user = result.scalars().first()
    if user is None or not verify_password(password, user.hashed_password):
        _failed_logins.setdefault(email_key, []).append(now)
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

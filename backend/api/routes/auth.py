"""Authentication routes: register, login (OAuth2 password flow), me."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from core.security import create_access_token, get_current_user, get_password_hash, verify_password
from db.database import get_db
from db.models import DBUser

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


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
    user = DBUser(email=email, hashed_password=get_password_hash(req.password))
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status_code=409, detail="Email already registered")
    await db.refresh(user)
    return UserResponse(id=user.id, email=user.email)


@router.post("/login", response_model=TokenResponse)
async def login(form: OAuth2PasswordRequestForm = Depends(), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DBUser).where(DBUser.email == form.username.lower()))
    user = result.scalars().first()
    if user is None or not verify_password(form.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Inactive user account")
    return TokenResponse(access_token=create_access_token({"sub": user.id}))


@router.get("/me", response_model=UserResponse)
async def me(user: DBUser = Depends(get_current_user)):
    return UserResponse(id=user.id, email=user.email)

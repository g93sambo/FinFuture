"""
backend/core/security.py
========================
Cryptographic utilities, password hashing, JWT lifecycle, and authentication dependencies.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Dict, Any

from fastapi import Depends, HTTPException, Query, WebSocket, status
from fastapi.exceptions import WebSocketException
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from passlib.context import CryptContext
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.database import get_db
from db.models import DBUser, DBClientProfile

logger = logging.getLogger("wealth_advisor.core.security")

import bcrypt

# --- OAuth2 Scheme for Swagger & REST Endpoints ---
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    description="JWT Bearer token authentication"
)


# =============================================================================
# 1. Password Hashing & Verification (Native Bcrypt)
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password against an existing bcrypt hash using native bcrypt.
    Safely truncates to 72 bytes to conform with bcrypt limitations.
    """
    if not plain_password or not hashed_password:
        return False
    try:
        pw_bytes = plain_password.encode("utf-8")[:72]
        hash_bytes = hashed_password.encode("utf-8")
        return bcrypt.checkpw(pw_bytes, hash_bytes)
    except Exception as e:
        logger.warning("verify_password failed: %s", e)
        return False


def get_password_hash(password: str) -> str:
    """
    Generates a salted bcrypt hash for a plaintext password using native bcrypt.
    Safely truncates to 72 bytes to satisfy bcrypt specifications.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    pw_bytes = password.encode("utf-8")[:72]
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(pw_bytes, salt).decode("utf-8")


# =============================================================================
# 2. JWT Token Lifecycle
# =============================================================================

def create_access_token(
    data: Dict[str, Any],
    expires_delta: Optional[timedelta] = None
) -> str:
    """
    Creates an RFC 7519 compliant JSON Web Token (JWT).
    
    Args:
        data: Payload dictionary (must contain 'sub' claim representing user ID).
        expires_delta: Optional custom lifetime duration. Defaults to settings.access_token_expire_minutes.
        
    Returns:
        str: Encoded JWT string.
    """
    to_encode = data.copy()
    now_utc = datetime.now(timezone.utc)

    if expires_delta:
        expire = now_utc + expires_delta
    else:
        expire = now_utc + timedelta(minutes=settings.access_token_expire_minutes)

    to_encode.update({
        "exp": expire,
        "iat": now_utc,
    })

    encoded_jwt = jwt.encode(
        to_encode,
        settings.secret_key,
        algorithm=settings.jwt_algorithm
    )
    return encoded_jwt


def decode_access_token(token: str) -> Dict[str, Any]:
    """
    Decodes and cryptographically validates a JWT token.
    
    Args:
        token: The raw JWT string.
        
    Returns:
        Dict[str, Any]: The decoded token payload.
        
    Raises:
        HTTPException(401): If token signature is invalid, malformed, or expired.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        return payload
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except (JWTError, Exception) as exc:
        logger.warning(f"JWT decode failure: {exc}")
        raise credentials_exception


# =============================================================================
# 3. REST API Authentication Dependency
# =============================================================================

async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db)
) -> DBUser:
    """
    FastAPI dependency to extract and authenticate the current user from the Authorization header.
    
    Args:
        token: Bearer token extracted from header.
        db: Active database session.
        
    Returns:
        DBUser: Authenticated active user database entity.
        
    Raises:
        HTTPException(401): If token is missing, invalid, expired, or user not found.
        HTTPException(403): If the user account is disabled / inactive.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    payload = decode_access_token(token)
    user_id: Optional[str] = payload.get("sub")
    if user_id is None:
        raise credentials_exception

    result = await db.execute(select(DBUser).where(DBUser.id == str(user_id)))
    user = result.scalars().first()

    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if hasattr(user, "is_active") and not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account"
        )

    return user


# =============================================================================
# 4. WebSocket Authentication Dependency & Helper
# =============================================================================

async def get_current_user_ws(
    websocket: WebSocket,
    token: Optional[str] = Query(None, description="JWT token query parameter"),
    db: AsyncSession = Depends(get_db)
) -> DBUser:
    """
    FastAPI dependency for authenticating WebSocket connections via query parameter:
    ws://.../ws/chat?token=<jwt_token>
    
    If authentication fails, raises WebSocketException with code 1008 (Policy Violation).
    """
    if not token:
        logger.warning("WebSocket connection rejected: missing ?token= query parameter")
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing authentication token"
        )

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token missing 'sub' subject claim")

        result = await db.execute(select(DBUser).where(DBUser.id == str(user_id)))
        user = result.scalars().first()

        if user is None or (hasattr(user, "is_active") and not user.is_active):
            raise ValueError("User not found or account is inactive")

        return user

    except Exception as exc:
        logger.warning(f"WebSocket authentication rejected: {exc}")
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid authentication token"
        ) from exc


async def authenticate_websocket(
    websocket: WebSocket,
    token: Optional[str],
    db: AsyncSession
) -> DBUser:
    """
    Explicit helper for WebSocket route handlers that manually accept and authenticate connections.
    Closes the WebSocket with code 1008 if token is missing or invalid.
    
    Args:
        websocket: The active WebSocket connection.
        token: Query string token extracted from connection URL.
        db: Active database session.
        
    Returns:
        DBUser: The authenticated active user.
        
    Raises:
        WebSocketException: Upon failure after closing socket.
    """
    if not token:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing authentication token"
        )
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Missing authentication token"
        )

    try:
        payload = jwt.decode(
            token,
            settings.secret_key,
            algorithms=[settings.jwt_algorithm]
        )
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Missing subject")

        result = await db.execute(select(DBUser).where(DBUser.id == str(user_id)))
        user = result.scalars().first()
        if user is None or (hasattr(user, "is_active") and not user.is_active):
            raise ValueError("Inactive or missing user")

        return user

    except Exception as exc:
        await websocket.close(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token"
        )
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason="Invalid or expired token"
        ) from exc


# =============================================================================
# 5. Per-User Client Profile Ownership Guard
# =============================================================================

async def verify_client_ownership(
    user: DBUser,
    client_id: str,
    db: AsyncSession
) -> DBClientProfile:
    """
    Guarantees tenant isolation: verifies that the client_id belongs to the authenticated user.
    
    Enforces the rule: user.id == client_profile.user_id
    
    Args:
        user: The authenticated DBUser obtained via get_current_user.
        client_id: The client identifier requested in route path or body.
        db: Active database session.
        
    Returns:
        DBClientProfile: The verified client profile record.
        
    Raises:
        HTTPException(404): If the client_id does not exist in the database.
        HTTPException(403): If the client profile belongs to another user.
    """
    result = await db.execute(
        select(DBClientProfile).where(DBClientProfile.client_id == str(client_id))
    )
    profile = result.scalars().first()

    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Client profile '{client_id}' not found"
        )

    # Convert to string to guarantee robust UUID / str equality comparison
    profile_owner_id = str(getattr(profile, "user_id", "") or "")
    current_user_id = str(getattr(user, "id", "") or "")

    if profile_owner_id != current_user_id:
        logger.warning(
            f"Unauthorized profile access attempt: user '{current_user_id}' "
            f"attempted to access profile '{client_id}' owned by '{profile_owner_id}'"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Forbidden: You do not have permission to access this client profile"
        )

    return profile

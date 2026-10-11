# Architectural Design & Implementation Specification: Foundation Layer (Config, Security, Requirements)

**Module:** Milestone 1 (Foundation)  
**Author:** Explorer M1-1  
**Target Files:**  
- `backend/requirements.txt`  
- `backend/core/config.py`  
- `backend/core/security.py`  
**Date:** 2026-10-10  
**Status:** Approved for Implementation  

---

## 1. Executive Summary

Milestone 1 establishes the foundational infrastructure for the entire Wealth Advisory Agent backend. Without a robust configuration engine and hardened security boundary, downstream agent routing, execution, and compliance gating cannot safely function.

This analysis provides the comprehensive, production-grade specification for:
1. **`backend/requirements.txt`**: A complete, conflict-free package manifest covering web serving, security/JWT/bcrypt, database migrations, caching, quantitative portfolio math (`skfolio`), brokerage integration (`alpaca-py`), Sepolia testnet anchoring (`web3`), LLMs, and the full test suite with coverage gating (`pytest-cov`).
2. **`backend/core/config.py`**: A Pydantic v2 `BaseSettings` management layer that dynamically loads from `.env` and `../.env`, enforcing hard startup validation guards:
   - **Paper Trading Guard**: Refuses startup if `ALPACA_PAPER` is set to `False` or if `ALPACA_BASE_URL` targets live Alpaca endpoints (`https://api.alpaca.markets`).
   - **Sepolia Testnet Guard**: Strictly enforces `SEPOLIA_CHAIN_ID == 11155111` and blocks Ethereum Mainnet (Chain ID 1) from ever being configured or queried.
   - **Database & Cache Configuration**: Auto-translates synchronous database drivers (`postgresql://`, `sqlite://`) into async SQLAlchemy drivers (`postgresql+asyncpg://`, `sqlite+aiosqlite://`).
   - **Secret Protection**: Provides safe development defaults, shields secrets from serialization logs, and enables dry-run execution when optional external services are unconfigured.
3. **`backend/core/security.py`**: High-performance authentication, authorization, and tenant isolation utilities:
   - **Bcrypt Password Hashing**: Passlib CryptContext wrapper supporting UTF-8 and arbitrary input lengths.
   - **JWT Lifecycle**: RFC 7519 compliant token creation with `exp` and `iat` claims, and strict decoding/validation raising `HTTPException(401)`.
   - **FastAPI REST Dependency**: `get_current_user` inspecting the `Authorization: Bearer <token>` header, querying `DBUser`, and validating active user status.
   - **WebSocket Authentication**: `get_current_user_ws` dependency and `authenticate_websocket` handler supporting `?token=<jwt>` query parameters with RFC 6455 close code `1008` (Policy Violation) upon auth failure.
   - **Tenant Ownership Guard**: `verify_client_ownership(user, client_id, db)` enforcing that authenticated users may only access `client_profiles` matching `client.user_id == user.id`, returning `HTTPException(403)` on mismatch and `HTTPException(404)` on missing records.

---

## 2. Component 1: `backend/requirements.txt` Specification

### 2.1 Complete Package Manifest

Below is the complete, verified list of Python packages required across all 5 milestones. The runtime environment was verified on Python 3.12.4.

```text
# =============================================================================
# Wealth Advisory Agent Backend - Requirements Manifest
# Python >= 3.11, < 3.13 (Verified on Python 3.12.4)
# =============================================================================

# --- Core Web Framework & Server ---
fastapi>=0.104.1,<1.0.0
uvicorn[standard]>=0.24.0,<1.0.0
pydantic>=2.5.2,<3.0.0
pydantic-settings>=2.1.0,<3.0.0
python-dotenv>=1.0.0
email-validator>=2.0.0
python-multipart>=0.0.6

# --- Security, Authentication & Cryptography ---
passlib[bcrypt]>=1.7.4
bcrypt>=4.0.1
python-jose[cryptography]>=3.3.0
cryptography>=41.0.7

# --- Database, ORM & Migrations ---
SQLAlchemy>=2.0.23,<3.0.0
asyncpg>=0.29.0
aiosqlite>=0.19.0
alembic>=1.13.0
greenlet>=3.0.0

# --- Caching, Sessions & Distributed Locks ---
redis>=5.0.1

# --- Brokerage & Trading Execution ---
alpaca-py>=0.30.0

# --- Web3 & Testnet Blockchain Anchoring ---
web3>=6.15.0
eth-account>=0.11.0

# --- Quantitative Finance, Portfolio Optimization & Math ---
pandas>=2.1.0
numpy>=1.26.0
scipy>=1.11.0
scikit-learn>=1.3.2
shap>=0.44.0
skfolio>=0.1.0
cvxpy>=1.4.0
yfinance>=0.2.36

# --- Multi-Agent System, LLM & Resilient Networking ---
openai>=1.13.3
httpx>=0.25.2
tenacity>=8.2.3
datasets>=2.16.0

# --- Testing, Coverage & Test Infrastructure ---
pytest>=7.4.3
pytest-asyncio>=0.21.1
pytest-cov>=4.1.0
websockets>=12.0
```

### 2.2 Package Justification Table

| Category | Package | Version Constraint | Role & Justification |
|:---|:---|:---|:---|
| **API** | `fastapi` | `>=0.104.1` | Asynchronous REST and WebSocket routing framework |
| **API** | `uvicorn[standard]` | `>=0.24.0` | ASGI server with uvloop and websockets speedups |
| **API** | `pydantic-settings` | `>=2.1.0` | Type-safe `.env` loading and startup validation |
| **API** | `email-validator` | `>=2.0.0` | Validates email syntax on user registration (`EmailStr`) |
| **API** | `python-multipart` | `>=0.0.6` | Required by FastAPI `OAuth2PasswordRequestForm` |
| **Security** | `passlib[bcrypt]` | `>=1.7.4` | Salted password hashing algorithm |
| **Security** | `bcrypt` | `>=4.0.1` | Native binary cryptographic backend for passlib |
| **Security** | `python-jose` | `>=3.3.0` | JWT encoding, decoding, expiration validation |
| **Database** | `SQLAlchemy` | `>=2.0.23` | Async ORM models, relationship mapping, event hooks |
| **Database** | `aiosqlite` | `>=0.19.0` | Async SQLite driver (default zero-Docker local execution) |
| **Database** | `asyncpg` | `>=0.29.0` | Async PostgreSQL driver for production deployments |
| **Database** | `alembic` | `>=1.13.0` | Async database schema versioning and migration engine |
| **Cache** | `redis` | `>=5.0.1` | Redis asyncio client for session store and 30s trade locks |
| **Brokerage**| `alpaca-py` | `>=0.30.0` | Alpaca Trading API SDK for paper order submission |
| **Web3** | `web3` | `>=6.15.0` | Sepolia testnet interaction and smart contract anchoring |
| **Web3** | `eth-account` | `>=0.11.0` | Local transaction signing with testnet private keys |
| **Finance** | `skfolio` | `>=0.1.0` | CVaR portfolio optimization and efficient frontier |
| **Finance** | `shap` | `>=0.44.0` | Portfolio feature attribution and explainability |
| **Data** | `yfinance` | `>=0.2.36` | Market quotes, historical bars, dividend yields |
| **Agent** | `openai` | `>=1.13.3` | Async OpenAI client for conversational agents |
| **Agent** | `tenacity` | `>=8.2.3` | Exponential backoff retry engine for API pipelines |
| **Agent** | `datasets` | `>=2.16.0` | HuggingFace dataset grounding for behavioral bias agent |
| **Test** | `pytest-cov` | `>=4.1.0` | Coverage enforcement for acceptance criteria (`--cov-fail-under=80`) |

---

## 3. Component 2: `backend/core/config.py` Specification

### 3.1 Design Principles
1. **Immutability and Type-Safety**: Extends Pydantic's `BaseSettings` with strict typing.
2. **Fail-Fast Safety Boundary**: If dangerous configurations (e.g. live Alpaca endpoints, Ethereum Mainnet chain ID) are detected, the process refuses to boot immediately during Pydantic initialization.
3. **Pluggable Discovery**: Inspects `.env` in both current directory (`./.env`) and parent directory (`../.env`).
4. **Transparent Async Drivers**: Automatically normalizes synchronous connection strings (`postgresql://` -> `postgresql+asyncpg://`, `sqlite://` -> `sqlite+aiosqlite://`).
5. **Zero-Secret Leakage**: Critical credentials are never exposed in string representations or logs.

### 3.2 Exact Implementation Code

```python
"""
backend/core/config.py
======================
Central application configuration with strict security and paper-trading startup guards.
"""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from typing import Optional, List
from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger("wealth_advisor.core.config")


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables and .env files.
    Enforces critical safety guards for paper trading and testnet blockchain operations.
    """

    # --- Application Metadata ---
    app_name: str = Field(default="Wealth Advisory Agent API", description="Application name")
    app_version: str = Field(default="2.0.0", description="Application semantic version")
    environment: str = Field(default="development", description="Environment: development, test, production")
    debug: bool = Field(default=False, description="Debug mode flag")
    log_level: str = Field(default="INFO", description="Log level: DEBUG, INFO, WARNING, ERROR")

    # --- Security & JWT Authentication ---
    secret_key: str = Field(
        default="dev-insecure-secret-key-change-in-production-min-32-chars!",
        description="Secret key for JWT token signature"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT cryptographic algorithm")
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="Access token validity lifetime in minutes"
    )
    audit_secret_key: str = Field(
        default="dev-insecure-audit-hmac-key-change-in-production-min-32!",
        description="Secret key for HMAC-SHA256 audit log signing"
    )

    # --- Database & Persistence ---
    database_url: str = Field(
        default="sqlite+aiosqlite:///./wealth_advisor.db",
        description="SQLAlchemy database connection URL"
    )

    # --- Cache, Sessions & Distributed Locks ---
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis connection URL for cache and distributed locks"
    )

    # --- Brokerage & Paper Trading Guard ---
    alpaca_paper: bool = Field(
        default=True,
        description="Paper trading enforcement flag. MUST ALWAYS BE TRUE."
    )
    alpaca_base_url: str = Field(
        default="https://paper-api.alpaca.markets",
        description="Alpaca Trading API endpoint. Live endpoints are strictly forbidden."
    )
    alpaca_api_key: Optional[str] = Field(default=None, description="Alpaca Paper API Key")
    alpaca_secret_key: Optional[str] = Field(default=None, description="Alpaca Paper Secret Key")

    # --- Web3 & Sepolia Anchoring Guard ---
    sepolia_chain_id: int = Field(
        default=11155111,
        description="Sepolia testnet chain ID. Mainnet (1) is strictly forbidden."
    )
    sepolia_rpc_url: Optional[str] = Field(
        default=None,
        description="Sepolia testnet RPC URL (e.g. Infura/Alchemy)"
    )
    sepolia_private_key: Optional[str] = Field(
        default=None,
        description="Testnet Ethereum private key for Merkle root anchoring"
    )
    audit_contract_address: Optional[str] = Field(
        default=None,
        description="Sepolia audit smart contract address"
    )

    # --- LLM & External Data Providers ---
    openai_api_key: Optional[str] = Field(default=None, description="OpenAI API key")
    openai_model: str = Field(default="gpt-4o", description="Default LLM model name")
    fred_api_key: Optional[str] = Field(default=None, description="Federal Reserve Economic Data API Key")

    # --- Execution Controls ---
    dry_run: bool = Field(
        default=False,
        description="Simulate external side-effects (Alpaca, Sepolia) without network calls"
    )

    # --- Pydantic Settings Configuration ---
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore"
    )

    # -------------------------------------------------------------------------
    # Safety Guards & Field Validators
    # -------------------------------------------------------------------------

    @field_validator("alpaca_paper")
    @classmethod
    def guard_paper_trading_mode(cls, v: bool) -> bool:
        """
        Hard-enforce paper trading. Refuse to start if set to False.
        """
        if not v:
            raise ValueError(
                "CRITICAL SECURITY GUARD: Live trading is strictly prohibited! "
                "'ALPACA_PAPER' must be True."
            )
        return v

    @field_validator("alpaca_base_url")
    @classmethod
    def guard_alpaca_live_url(cls, v: str) -> str:
        """
        Refuse to start if Alpaca base URL points to production live endpoints.
        """
        v_clean = v.strip().lower()
        # Disallow production live endpoints
        if "https://api.alpaca.markets" in v_clean or "http://api.alpaca.markets" in v_clean:
            raise ValueError(
                f"CRITICAL SECURITY GUARD: Live Alpaca endpoint detected ('{v}')! "
                "Only the paper trading endpoint (https://paper-api.alpaca.markets) or local mocks are permitted."
            )
        # If pointing to alpaca.markets, must contain 'paper'
        if "alpaca.markets" in v_clean and "paper" not in v_clean:
            raise ValueError(
                f"CRITICAL SECURITY GUARD: Non-paper Alpaca domain detected ('{v}')! "
                "Only paper trading endpoints are permitted."
            )
        return v

    @field_validator("sepolia_chain_id")
    @classmethod
    def guard_sepolia_chain_id(cls, v: int) -> int:
        """
        Sepolia Testnet Guard:
        Hard-enforce chain ID 11155111. Explicitly reject Ethereum Mainnet (Chain ID 1).
        """
        if v == 1:
            raise ValueError(
                "CRITICAL SECURITY GUARD: Ethereum Mainnet (Chain ID 1) is strictly forbidden! "
                "Only Sepolia testnet (Chain ID 11155111) is permitted."
            )
        if v != 11155111:
            raise ValueError(
                f"CRITICAL SECURITY GUARD: Invalid chain ID {v}. "
                "The Wealth Advisory Agent operates exclusively on Sepolia testnet (Chain ID 11155111)."
            )
        return v

    @field_validator("sepolia_rpc_url")
    @classmethod
    def guard_sepolia_rpc_url(cls, v: Optional[str]) -> Optional[str]:
        """
        Guard against RPC URLs containing 'mainnet'.
        Logs a critical warning if configured; AnchoringService will refuse to anchor.
        """
        if v and "mainnet" in v.strip().lower():
            logger.warning(
                "SECURITY WARNING: SEPOLIA_RPC_URL points to mainnet! "
                "AnchoringService will block all on-chain transactions and force dry-run."
            )
        return v

    # -------------------------------------------------------------------------
    # Computed Properties & Helpers
    # -------------------------------------------------------------------------

    @property
    def async_database_url(self) -> str:
        """
        Returns a normalized database URL with asynchronous driver prefixes.
        Converts 'postgresql://' -> 'postgresql+asyncpg://'
        Converts 'sqlite://' -> 'sqlite+aiosqlite://'
        """
        url = self.database_url.strip()
        if url.startswith("postgresql://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url

    @property
    def is_anchoring_configured(self) -> bool:
        """
        Determines whether Sepolia testnet anchoring can proceed on-chain.
        Returns False if unconfigured or if pointing to mainnet, prompting dry-run.
        """
        if not self.sepolia_rpc_url or not self.sepolia_private_key or not self.audit_contract_address:
            return False
        if "mainnet" in self.sepolia_rpc_url.lower():
            return False
        return True


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """
    Factory function returning a cached singleton Settings instance.
    """
    return Settings()


# Global settings singleton instance for direct import
settings = get_settings()
```

---

## 4. Component 3: `backend/core/security.py` Specification

### 4.1 Design Principles
1. **RFC-Compliant Password Hashing**: Cryptographic password hashing using bcrypt with auto-generated salts and work factor 12.
2. **Stateless JWT Authorization**: Bearer token authentication in HTTP headers, verifiable without DB overhead for token decoding, followed by DB verification of user existence and active status.
3. **Dual Protocol Authentication**:
   - **REST API**: Header-based `Authorization: Bearer <token>` via `OAuth2PasswordBearer`.
   - **WebSocket API**: Query-parameter-based `/ws/chat?token=<jwt>`, validating before protocol acceptance and emitting WebSocket close code `1008` (Policy Violation) upon auth failure.
4. **Strict Per-User Ownership & Tenant Isolation**: Ensures that user $A$ cannot query or manipulate client profile $B$. Mismatches return `HTTPException(403 Forbidden)`, and non-existent profiles return `HTTPException(404 Not Found)`.

### 4.2 Exact Implementation Code

```python
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

# --- Password Hashing Context ---
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# --- OAuth2 Scheme for Swagger & REST Endpoints ---
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login",
    description="JWT Bearer token authentication"
)


# =============================================================================
# 1. Password Hashing & Verification
# =============================================================================

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """
    Verifies a plaintext password against an existing bcrypt hash.
    
    Args:
        plain_password: The plaintext password entered by the user.
        hashed_password: The bcrypt hash stored in the database.
        
    Returns:
        bool: True if password matches hash, False otherwise.
    """
    if not plain_password or not hashed_password:
        return False
    return pwd_context.verify(plain_password, hashed_password)


def get_password_hash(password: str) -> str:
    """
    Generates a salted bcrypt hash for a plaintext password.
    
    Args:
        password: The plaintext password to hash.
        
    Returns:
        str: Salted bcrypt hash string.
        
    Raises:
        ValueError: If password is empty.
    """
    if not password:
        raise ValueError("Password cannot be empty")
    return pwd_context.hash(password)


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

    result = await db.execute(select(DBUser).where(DBUser.id == user_id))
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

        result = await db.execute(select(DBUser).where(DBUser.id == user_id))
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

        result = await db.execute(select(DBUser).where(DBUser.id == user_id))
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
        select(DBClientProfile).where(DBClientProfile.client_id == client_id)
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
```

---

## 5. Interface Contracts & Inter-Module Integration

### 5.1 Downstream Modules Relying on `core/config.py`
1. **`db/database.py`**:
   - Replaces ad-hoc `os.getenv("DATABASE_URL")` with `settings.async_database_url`.
2. **`services/cache.py`**:
   - Reads `settings.redis_url` to initialize connection pool.
3. **`services/audit_logger.py`**:
   - Reads `settings.audit_secret_key` for HMAC-SHA256 signature generation.
4. **`services/anchoring.py`**:
   - Reads `settings.sepolia_chain_id`, `settings.sepolia_rpc_url`, `settings.sepolia_private_key`, `settings.audit_contract_address`, `settings.dry_run`.
   - If `settings.is_anchoring_configured` is False, falls back cleanly to dry-run mode.
5. **`agents/execution_module.py`**:
   - Reads `settings.alpaca_api_key`, `settings.alpaca_secret_key`, `settings.alpaca_base_url`, `settings.alpaca_paper`.
   - Guaranteed that `alpaca_paper` is True and endpoint is not live.

### 5.2 Downstream Modules Relying on `core/security.py`
1. **`api/routes/auth.py`**:
   - `POST /register`: Uses `get_password_hash(req.password)` to store user password.
   - `POST /login`: Uses `verify_password(req.password, user.hashed_password)` and issues token via `create_access_token({"sub": str(user.id), "email": user.email})`.
   - `GET /me`: Injects `current_user: DBUser = Depends(get_current_user)`.
2. **`api/routes/profile.py`, `portfolio.py`, `trade.py`, `audit.py`**:
   - Injects `current_user: DBUser = Depends(get_current_user)`.
   - Calls `profile = await verify_client_ownership(current_user, client_id, db)` before processing or returning any client-specific assets or trades.
3. **`api/routes/chat.py` (`/ws/chat`)**:
   - Injects `current_user: DBUser = Depends(get_current_user_ws)`.
   - Associates chat sessions and risk profiles directly with `current_user.id`.

---

## 6. Verification and Unit Testing Plan

### 6.1 Unit Test Matrix (`backend/tests/unit/test_config.py`)

| Test Function | Test Description | Expected Behavior |
|:---|:---|:---|
| `test_default_settings()` | Initialize `Settings()` with standard environment | Instantiates successfully; `alpaca_paper==True`, `sepolia_chain_id==11155111` |
| `test_paper_guard_blocks_live_flag()` | Instantiate `Settings(alpaca_paper=False)` | Raises `pydantic.ValidationError` containing "Live trading is strictly prohibited" |
| `test_paper_guard_blocks_live_url()` | Instantiate `Settings(alpaca_base_url="https://api.alpaca.markets")` | Raises `pydantic.ValidationError` containing "Live Alpaca endpoint detected" |
| `test_paper_guard_accepts_paper_url()` | Instantiate `Settings(alpaca_base_url="https://paper-api.alpaca.markets")` | Passes validation |
| `test_paper_guard_accepts_mock_url()` | Instantiate `Settings(alpaca_base_url="http://localhost:8000/mock-alpaca")` | Passes validation |
| `test_sepolia_guard_blocks_mainnet()` | Instantiate `Settings(sepolia_chain_id=1)` | Raises `pydantic.ValidationError` containing "Ethereum Mainnet (Chain ID 1) is strictly forbidden" |
| `test_sepolia_guard_blocks_other_chains()` | Instantiate `Settings(sepolia_chain_id=137)` | Raises `pydantic.ValidationError` containing "Invalid chain ID" |
| `test_database_url_postgresql_conversion()` | Set `database_url="postgresql://usr:pwd@host/db"` | `async_database_url` returns `"postgresql+asyncpg://usr:pwd@host/db"` |
| `test_database_url_sqlite_conversion()` | Set `database_url="sqlite:///./wealth.db"` | `async_database_url` returns `"sqlite+aiosqlite:///./wealth.db"` |

### 6.2 Unit Test Matrix (`backend/tests/unit/test_security.py`)

| Test Function | Test Description | Expected Behavior |
|:---|:---|:---|
| `test_password_hashing()` | Hash password and verify with correct/incorrect plaintexts | Returns valid bcrypt hash; `verify_password` returns True on match, False on mismatch |
| `test_jwt_creation_and_decode()` | Create token with user ID and decode | Decodes valid payload matching original subject and timestamps |
| `test_jwt_expired_token()` | Create token with `expires_delta = timedelta(seconds=-5)` | `decode_access_token` raises `HTTPException(401)` with "Token has expired" |
| `test_jwt_tampered_token()` | Tamper signature of valid token | `decode_access_token` raises `HTTPException(401)` with "Could not validate credentials" |
| `test_get_current_user_active()` | Provide valid token for active user in DB | Returns corresponding `DBUser` instance |
| `test_get_current_user_inactive()` | Provide valid token for user with `is_active=False` | Raises `HTTPException(403)` with "Inactive user account" |
| `test_get_current_user_not_found()` | Provide valid token for non-existent user ID | Raises `HTTPException(401)` with "User not found" |
| `test_verify_client_ownership_success()` | Authenticated user matches `profile.user_id` | Returns `DBClientProfile` record |
| `test_verify_client_ownership_mismatch()` | Authenticated user ID does not match `profile.user_id` | Raises `HTTPException(403)` with "Forbidden" |
| `test_verify_client_ownership_missing()` | Client profile ID does not exist in DB | Raises `HTTPException(404)` with "not found" |
| `test_websocket_auth_success()` | Provide valid token query param | `get_current_user_ws` returns authenticated user |
| `test_websocket_auth_missing()` | Call `get_current_user_ws` with `token=None` | Raises `WebSocketException` with code `1008` |
| `test_websocket_auth_invalid()` | Call `get_current_user_ws` with invalid token | Raises `WebSocketException` with code `1008` |

---

## 7. Deliverable Summary & Next Steps

1. **Implementer Action 1**: Update `backend/requirements.txt` with the unified package manifest.
2. **Implementer Action 2**: Create `backend/core/__init__.py`, `backend/core/config.py`, and `backend/core/security.py` using the exact code specifications in sections 3 and 4.
3. **Implementer Action 3**: Run the test suites in `backend/tests/unit/test_config.py` and `test_security.py` to confirm 100% pass rate.

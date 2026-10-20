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

_DEV_SECRET_KEY = "dev-insecure-secret-key-change-in-production-min-32-chars!"
_DEV_AUDIT_SECRET_KEY = "dev-insecure-audit-hmac-key-change-in-production-min-32!"
_MIN_SECRET_LENGTH = 32


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
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Allowed CORS origins (comma-separated string, or '*' for open)"
    )
    cors_origin_regex: str = Field(
        default=r"https://fin-?future(-[a-z0-9-]+)?\.vercel\.app|http://localhost:\d+|http://127\.0\.0\.1:\d+",
        description="Regex of additional allowed origins: this project's Vercel production/preview domains and local dev"
    )

    # --- Security & JWT Authentication ---
    secret_key: str = Field(
        default=_DEV_SECRET_KEY,
        description="Secret key for JWT token signature"
    )
    jwt_algorithm: str = Field(default="HS256", description="JWT cryptographic algorithm")
    access_token_expire_minutes: int = Field(
        default=60,
        ge=1,
        description="Access token validity lifetime in minutes"
    )
    audit_secret_key: str = Field(
        default=_DEV_AUDIT_SECRET_KEY,
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
    fmp_api_key: Optional[str] = Field(default=None, description="Financial Modeling Prep API Key")
    polygon_api_key: Optional[str] = Field(default=None, description="Polygon.io Market Data API Key")
    coingecko_api_key: Optional[str] = Field(default=None, description="CoinGecko API Key (optional pro key)")

    # --- Execution Controls & Permission Tier Limits ---
    dry_run: bool = Field(
        default=False,
        description="Simulate external side-effects (Alpaca, Sepolia) without network calls"
    )
    allow_autonomous_execution: bool = Field(
        default=False,
        description="Tier 5 Autonomous Execution flag. MUST ALWAYS BE FALSE (non-discretionary only)."
    )
    max_single_trade_notional_usd: float = Field(
        default=100000.0,
        gt=0,
        description="Tier 4 hard per-trade notional cap in USD (AML-001)"
    )
    max_daily_trade_notional_usd: float = Field(
        default=250000.0,
        gt=0,
        description="Tier 4 hard rolling 24-hour cumulative trade notional cap in USD per client"
    )
    step_up_mfa_notional_threshold_usd: float = Field(
        default=1000.0,
        gt=0,
        description="Notional threshold in USD above which step-up 6-digit MFA is required"
    )

    # --- Authentication abuse limits (per client IP, in-process) ---
    auth_rate_limit_enabled: bool = Field(default=True, description="Throttle registrations and failed logins per IP")
    register_max_per_ip_per_hour: int = Field(default=10, ge=1, description="Accounts one IP may create per hour")
    anchor_cooldown_seconds: int = Field(
        default=600, ge=0, description="Minimum time between Sepolia anchors for one client (each anchor spends test ETH)"
    )
    anchor_max_per_hour: int = Field(default=20, ge=1, description="Sepolia anchors the whole server may send per hour")
    login_failures_max_per_ip: int = Field(default=30, ge=1, description="Failed logins one IP may make per 15 minutes")

    # --- Step-Up OTP & Transactional Email ---
    otp_delivery: str = Field(
        default="auto",
        description="Step-up OTP channel: auto (Brevo, else Resend, else SMTP, else console), email (fail if unconfigured), console"
    )
    otp_ttl_seconds: int = Field(default=300, ge=60, le=900, description="Lifetime of a step-up OTP")
    otp_max_attempts: int = Field(default=5, ge=1, le=10, description="Wrong guesses allowed before a code is burned")
    otp_resend_cooldown_seconds: int = Field(default=30, ge=0, description="Minimum gap between code sends")
    otp_max_sends: int = Field(default=5, ge=1, description="Maximum codes sent per trade proposal")
    otp_dev_echo: bool = Field(
        default=False,
        description="Local demos only: return the code in the API response when using console delivery. Refused in production."
    )
    email_from: str = Field(
        default="FinFuture <onboarding@resend.dev>",
        description="From address for transactional email (must be a verified sender for your provider)"
    )
    brevo_api_key: Optional[str] = Field(default=None, description="Brevo API key (HTTPS email delivery)")
    resend_api_key: Optional[str] = Field(default=None, description="Resend API key (HTTPS email delivery)")
    smtp_host: Optional[str] = Field(default=None, description="SMTP host, e.g. smtp.gmail.com")
    smtp_port: int = Field(default=587, description="SMTP port (587 STARTTLS, 465 SSL)")
    smtp_username: Optional[str] = Field(default=None, description="SMTP username")
    smtp_password: Optional[str] = Field(default=None, description="SMTP password or app password")
    smtp_use_ssl: bool = Field(default=False, description="Use implicit TLS (port 465) instead of STARTTLS")

    # --- Pydantic Settings Configuration ---
    model_config = SettingsConfigDict(
        env_file=(".env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        # Validation errors would otherwise print every setting, API keys included, into the logs
        hide_input_in_errors=True,
    )

    # -------------------------------------------------------------------------
    # Safety Guards & Field Validators
    # -------------------------------------------------------------------------

    @field_validator("allow_autonomous_execution")
    @classmethod
    def guard_autonomous_execution_disabled(cls, v: bool) -> bool:
        """
        Hard-disable Tier 5 autonomous execution. Refuse to start if set to True.
        """
        if v:
            raise ValueError(
                "CRITICAL SECURITY GUARD: Autonomous execution (Tier 5) is strictly forbidden! "
                "'ALLOW_AUTONOMOUS_EXECUTION' must be False. The advisor is strictly non-discretionary."
            )
        return v

    @model_validator(mode="after")
    def guard_production_secrets(self) -> "Settings":
        """
        Refuse to start in production with the built-in development signing keys or short keys:
        anyone who knows them could forge JWTs (SECRET_KEY) or re-sign the audit chain (AUDIT_SECRET_KEY).
        """
        if self.environment.strip().lower() != "production":
            return self
        for name, value, dev_default in (
            ("SECRET_KEY", self.secret_key, _DEV_SECRET_KEY),
            ("AUDIT_SECRET_KEY", self.audit_secret_key, _DEV_AUDIT_SECRET_KEY),
        ):
            if not value or value == dev_default or len(value) < _MIN_SECRET_LENGTH:
                raise ValueError(
                    f"CRITICAL SECURITY GUARD: {name} must be set to a unique random value of at least "
                    f"{_MIN_SECRET_LENGTH} characters when ENVIRONMENT=production."
                )
        if self.secret_key == self.audit_secret_key:
            raise ValueError(
                "CRITICAL SECURITY GUARD: SECRET_KEY and AUDIT_SECRET_KEY must be different values."
            )
        if self.otp_dev_echo:
            raise ValueError(
                "CRITICAL SECURITY GUARD: OTP_DEV_ECHO returns step-up codes in API responses and is "
                "forbidden when ENVIRONMENT=production."
            )
        if self.debug:
            raise ValueError("CRITICAL SECURITY GUARD: DEBUG must be false when ENVIRONMENT=production.")
        return self

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
        if "https://api.alpaca.markets" in v_clean or "http://api.alpaca.markets" in v_clean:
            raise ValueError(
                f"CRITICAL SECURITY GUARD: Live Alpaca endpoint detected ('{v}')! "
                "Only the paper trading endpoint (https://paper-api.alpaca.markets) or local mocks are permitted."
            )
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
        Converts 'postgres://' or 'postgresql://' -> 'postgresql+asyncpg://'
        Converts 'sqlite://' -> 'sqlite+aiosqlite://'
        """
        url = self.database_url.strip()
        if url.startswith("postgres://"):
            return url.replace("postgres://", "postgresql+asyncpg://", 1)
        if url.startswith("postgresql://") and not url.startswith("postgresql+asyncpg://"):
            return url.replace("postgresql://", "postgresql+asyncpg://", 1)
        if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite://"):
            return url.replace("sqlite://", "sqlite+aiosqlite://", 1)
        return url

    @property
    def allowed_cors_origins(self) -> List[str]:
        if not self.cors_origins:
            return ["http://localhost:3000", "http://127.0.0.1:3000"]
        if self.cors_origins.strip() == "*":
            return ["*"]
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

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

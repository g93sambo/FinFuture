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
from pydantic import Field, field_validator
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
    cors_origins: str = Field(
        default="http://localhost:3000,http://127.0.0.1:3000",
        description="Allowed CORS origins (comma-separated string, or '*' for open)"
    )

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

    # --- Bamboo Investment Brokerage (Nigeria & Global) ---
    bamboo_live_mode: bool = Field(
        default=False,
        description="Bamboo live investment execution flag for Nigerian and global assets."
    )
    bamboo_base_url: str = Field(
        default="https://powered-by-bamboo-sandbox.investbamboo.com",
        description="Bamboo API base URL (sandbox or production powered-by-bamboo endpoint)."
    )
    bamboo_app_key: Optional[str] = Field(default=None, description="Bamboo App Key identifying tenant")
    bamboo_username: Optional[str] = Field(default=None, description="Bamboo Tenant Username")
    bamboo_password: Optional[str] = Field(default=None, description="Bamboo Tenant Password")


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

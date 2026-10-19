"""
Unit tests for backend/core/config.py
Testing Pydantic settings, startup validation guards, and URL conversions.
"""

import pytest
from pydantic import ValidationError
from core.config import Settings


def test_default_settings():
    s = Settings()
    assert s.alpaca_paper is True
    assert s.sepolia_chain_id == 11155111
    assert "paper" in s.alpaca_base_url


def test_production_refuses_default_secrets():
    with pytest.raises(ValidationError) as exc_info:
        # Ignore any local .env so the built-in development secrets are what get validated
        Settings(_env_file=None, environment="production")
    assert any("SECRET_KEY must be set" in str(e["msg"]) for e in exc_info.value.errors())


def test_production_refuses_short_or_shared_secrets():
    with pytest.raises(ValidationError):
        Settings(environment="production", secret_key="short", audit_secret_key="b" * 40)
    with pytest.raises(ValidationError) as exc_info:
        Settings(environment="production", secret_key="a" * 40, audit_secret_key="a" * 40)
    assert any("must be different" in str(e["msg"]) for e in exc_info.value.errors())


def test_production_accepts_unique_secrets():
    s = Settings(environment="production", secret_key="a" * 40, audit_secret_key="b" * 40)
    assert s.environment == "production"


def test_paper_guard_blocks_live_flag():
    with pytest.raises(ValidationError) as exc_info:
        Settings(alpaca_paper=False)
    errors = exc_info.value.errors()
    assert any("Live trading is strictly prohibited" in str(e["msg"]) for e in errors)


def test_paper_guard_blocks_live_url():
    with pytest.raises(ValidationError) as exc_info:
        Settings(alpaca_base_url="https://api.alpaca.markets")
    errors = exc_info.value.errors()
    assert any("Live Alpaca endpoint detected" in str(e["msg"]) for e in errors)


def test_paper_guard_blocks_non_paper_alpaca_domain():
    with pytest.raises(ValidationError) as exc_info:
        Settings(alpaca_base_url="https://live.alpaca.markets")
    errors = exc_info.value.errors()
    assert any("Non-paper Alpaca domain detected" in str(e["msg"]) for e in errors)


def test_paper_guard_accepts_paper_url():
    s = Settings(alpaca_base_url="https://paper-api.alpaca.markets")
    assert s.alpaca_base_url == "https://paper-api.alpaca.markets"


def test_paper_guard_accepts_mock_url():
    s = Settings(alpaca_base_url="http://localhost:8000/mock-alpaca")
    assert s.alpaca_base_url == "http://localhost:8000/mock-alpaca"


def test_sepolia_guard_blocks_mainnet():
    with pytest.raises(ValidationError) as exc_info:
        Settings(sepolia_chain_id=1)
    errors = exc_info.value.errors()
    assert any("Ethereum Mainnet (Chain ID 1) is strictly forbidden" in str(e["msg"]) for e in errors)


def test_sepolia_guard_blocks_invalid_chain():
    with pytest.raises(ValidationError) as exc_info:
        Settings(sepolia_chain_id=137)
    errors = exc_info.value.errors()
    assert any("Invalid chain ID 137" in str(e["msg"]) for e in errors)


def test_sepolia_guard_accepts_sepolia():
    s = Settings(sepolia_chain_id=11155111)
    assert s.sepolia_chain_id == 11155111


def test_database_url_postgresql_conversion():
    s = Settings(database_url="postgresql://user:pass@localhost:5432/wealth")
    assert s.async_database_url == "postgresql+asyncpg://user:pass@localhost:5432/wealth"


def test_database_url_sqlite_conversion():
    s = Settings(database_url="sqlite:///./wealth_advisor.db")
    assert s.async_database_url == "sqlite+aiosqlite:///./wealth_advisor.db"


def test_database_url_preserves_async():
    s = Settings(database_url="sqlite+aiosqlite:///./wealth_advisor.db")
    assert s.async_database_url == "sqlite+aiosqlite:///./wealth_advisor.db"


def test_is_anchoring_configured():
    # Unconfigured
    s1 = Settings(sepolia_rpc_url=None, sepolia_private_key=None, audit_contract_address=None)
    assert s1.is_anchoring_configured is False

    # Mainnet in URL
    s2 = Settings(
        sepolia_rpc_url="https://mainnet.infura.io/v3/test",
        sepolia_private_key="0x" + "1" * 64,
        audit_contract_address="0x" + "2" * 40
    )
    assert s2.is_anchoring_configured is False

    # Valid Sepolia
    s3 = Settings(
        sepolia_rpc_url="https://sepolia.infura.io/v3/test",
        sepolia_private_key="0x" + "1" * 64,
        audit_contract_address="0x" + "2" * 40
    )
    assert s3.is_anchoring_configured is True

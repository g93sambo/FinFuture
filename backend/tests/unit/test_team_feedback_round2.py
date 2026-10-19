"""Second round of team-testing fixes: price projections, compliance false positives,
tool registration when run from backend/, and password strength."""

import math
import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from agents.compliance_guard import ComplianceGuard
from api.routes.auth import password_problem
from main import app
from tools.definitions.price_projection import compute_projection, resolve_symbol

BACKEND_DIR = Path(__file__).resolve().parents[2]


# --- price projection -----------------------------------------------------------------------------

def test_projection_bands_follow_volatility():
    # Alternating +1% / -1% daily moves: daily log-vol ~1%, so a 5-day 1-sd band is ~sqrt(5)%
    closes = [100.0]
    for i in range(120):
        closes.append(closes[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    p = compute_projection(closes, 5)
    assert p["last_price"] == pytest.approx(closes[-1], rel=1e-6)
    assert p["range_68pct"]["low"] < p["last_price"] < p["range_68pct"]["high"]
    assert p["range_95pct"]["low"] < p["range_68pct"]["low"] and p["range_95pct"]["high"] > p["range_68pct"]["high"]
    assert p["expected_move_1sd_pct"] == pytest.approx((math.exp(0.01 * 1.0 * math.sqrt(5) * 1.0) - 1) * 100, rel=0.05)
    assert p["historical_same_horizon_moves_pct"]["observations"] == len(closes) - 5


def test_projection_needs_enough_history():
    with pytest.raises(ValueError):
        compute_projection([100.0] * 10, 5)


@pytest.mark.parametrize("raw,ticker", [("XAUUSD", "GC=F"), ("xau/usd", "GC=F"), ("gold", "GC=F"), ("EURUSD", "EURUSD=X"), ("BTC", "BTC-USD"), ("AAPL", "AAPL")])
def test_symbol_aliases(raw, ticker):
    assert resolve_symbol(raw)[0] == ticker


def test_all_tools_register_when_run_from_backend_dir():
    """Render and Docker start the app from backend/ without the repo root on sys.path."""
    code = (
        "import sys, os; sys.path.insert(0, os.getcwd());"
        "from tools.registry import ToolRegistry; from tools.definitions import register_core_tools;"
        "register_core_tools(); names = {t.name for t in ToolRegistry.get_instance().list_tools()};"
        "assert {'project_price_range', 'get_stock_quote', 'get_stock_metrics', 'simulate_wealth_plan'} <= names, names;"
        "assert not [m for m in sys.modules if m.startswith('backend.')], 'duplicate backend.* modules loaded'"
    )
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    res = subprocess.run([sys.executable, "-c", code], cwd=BACKEND_DIR, env=env, capture_output=True, text=True, timeout=120)
    assert res.returncode == 0, res.stderr[-2000:]


# --- compliance output filter ---------------------------------------------------------------------

@pytest.mark.parametrize("text", [
    "This is a statistical range, not a guaranteed prediction.",
    "Returns are never guaranteed.",
    "The Sharpe ratio subtracts the risk-free rate from the return.",
])
def test_disclaimers_and_finance_terms_are_not_flagged(text):
    _, violations, _ = ComplianceGuard().check_text_output(text)
    assert not any(v.startswith("REG-001") for v in violations), violations


@pytest.mark.parametrize("text", ["This fund offers guaranteed returns.", "A risk-free way to double your money.", "There is no risk here."])
def test_promissory_language_is_still_flagged(text):
    _, violations, _ = ComplianceGuard().check_text_output(text)
    assert any(v.startswith("REG-001") for v in violations)


# --- KYC message ----------------------------------------------------------------------------------

def test_kyc_message_explains_the_fix_without_internal_ids():
    from types import SimpleNamespace

    from agents.execution_module import describe_kyc_gap

    other = describe_kyc_gap(SimpleNamespace(source_of_funds="other", pep_status=False, high_risk_jurisdiction=False, aml_flag=False))
    assert "source of funds" in other and "Risk profile" in other
    pep = describe_kyc_gap(SimpleNamespace(source_of_funds="salary", pep_status=True, high_risk_jurisdiction=False, aml_flag=True))
    assert "manual compliance review" in pep


# --- password strength ----------------------------------------------------------------------------

@pytest.mark.parametrize("pw", ["short1", "abcdefghijk", "1234567890", "aaaaaaaaa1", "Password123", "jane.doe2024x"])
def test_weak_passwords_are_rejected(pw):
    assert password_problem(pw, "jane.doe@example.com") is not None


def test_reasonable_password_is_accepted():
    assert password_problem("Blue-Harbor-73", "jane.doe@example.com") is None


@pytest.mark.asyncio
async def test_register_endpoint_rejects_weak_password():
    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            r = await client.post("/api/v1/auth/register", json={"email": f"w{uuid.uuid4().hex[:6]}@example.com", "password": "password123"})
            assert r.status_code == 422
            assert "common" in str(r.json()["detail"]).lower()

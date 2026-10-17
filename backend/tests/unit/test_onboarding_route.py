import uuid
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from main import app
from db.models import DBUser, DBClientProfile, DBAuditLog
from core.security import create_access_token, get_password_hash
from sqlalchemy import select


@pytest_asyncio.fixture
async def auth_user_and_token(db_session):
    user_id = str(uuid.uuid4())
    email = f"onboarding_{uuid.uuid4().hex[:6]}@example.com"
    user = DBUser(
        id=user_id,
        email=email,
        hashed_password=get_password_hash("password123"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)

    token = create_access_token({"sub": user.id})
    return user, token


from db.database import get_db
from agents.orchestrator import build_container

@pytest.mark.asyncio
async def test_onboarding_profile_creation_and_get(auth_user_and_token, db_session):
    user, token = auth_user_and_token
    if not hasattr(app.state, "container") or app.state.container is None:
        app.state.container = build_container()
    app.dependency_overrides[get_db] = lambda: db_session
    transport = ASGITransport(app=app)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # 1. Initially user has no profile
        res_get_initial = await client.get(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_get_initial.status_code == 404

        # 2. Submit onboarding profile
        payload = {
            "age": 32,
            "employment_status": "employed",
            "dependents": 1,
            "annual_income": 125000.0,
            "liquid_assets": 60000.0,
            "monthly_expenses": 4500.0,
            "existing_debts": 15000.0,
            "investment_experience": "intermediate",
            "risk_tolerance_score": 7.5,
            "investment_horizon_years": 12,
            "liquidity_needs": "low",
            "loss_capacity": "high",
            "primary_goal": "growth",
            "target_return": 8.0,
            "specific_goals": ["wealth_accumulation", "retirement"],
            "drawdown_reaction": "buy_more",
            "monitoring_frequency": "monthly",
            "source_of_funds": "salary",
            "pep_status": False,
            "high_risk_jurisdiction": False,
        }

        res_post = await client.post(
            "/api/v1/profile/onboarding",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_post.status_code == 200, res_post.text
        data = res_post.json()
        assert data["user_id"] == user.id
        assert data["age"] == 32
        assert data["annual_income"] == 125000.0
        assert data["suitability_category"] in ("Growth", "Aggressive Growth", "Moderate")
        assert data["kyc_verified"] is True
        assert data["aml_flag"] is False
        assert data["risk_tolerance_score"] == 7.5
        assert data["panic_sell_likelihood"] is not None
        assert data["emotional_risk_score"] is not None
        assert data["source_of_funds"] == "salary"
        assert data["drawdown_reaction"] == "buy_more"
        assert data["monitoring_frequency"] == "monthly"
        assert data["pep_status"] is False
        assert data["high_risk_jurisdiction"] is False
        client_id = data["client_id"]

        # 3. Fetch profile via /api/v1/profile
        res_get = await client.get(
            "/api/v1/profile",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_get.status_code == 200
        get_data = res_get.json()
        assert get_data["client_id"] == client_id
        assert get_data["user_id"] == user.id
        assert get_data["source_of_funds"] == "salary"
        assert get_data["drawdown_reaction"] == "buy_more"
        assert get_data["monitoring_frequency"] == "monthly"
        assert get_data["pep_status"] is False
        assert get_data["high_risk_jurisdiction"] is False

        # 4. Verify audit log was recorded
        audit_res = await db_session.execute(
            select(DBAuditLog).where(DBAuditLog.client_id == client_id)
        )
        logs = audit_res.scalars().all()
        assert len(logs) >= 1
        assert any(l.event_type == "PROFILE_COMPLETED" for l in logs)

        # 5. Test direct profile edit via PUT /api/v1/profile
        put_payload = {
            "annual_income": 150000.0,
            "source_of_funds": "business",
            "drawdown_reaction": "hold",
            "monitoring_frequency": "quarterly",
            "pep_status": True,
            "high_risk_jurisdiction": False,
        }
        res_put = await client.put(
            "/api/v1/profile",
            json=put_payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_put.status_code == 200
        put_data = res_put.json()
        assert put_data["annual_income"] == 150000.0
        assert put_data["source_of_funds"] == "business"
        assert put_data["drawdown_reaction"] == "hold"
        assert put_data["monitoring_frequency"] == "quarterly"
        assert put_data["pep_status"] is True

        # 6. Re-submitting updates the existing profile
        payload["risk_tolerance_score"] = 2.0
        payload["primary_goal"] = "capital_preservation"
        payload["loss_capacity"] = "low"
        payload["investment_horizon_years"] = 1
        res_update = await client.post(
            "/api/v1/profile/onboarding",
            json=payload,
            headers={"Authorization": f"Bearer {token}"},
        )
        assert res_update.status_code == 200
        updated_data = res_update.json()
        assert updated_data["client_id"] == client_id
        assert updated_data["suitability_category"] in ("Conservative", "Moderate Conservative")


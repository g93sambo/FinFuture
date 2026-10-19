"""Profile routes: client risk profile and suitability metrics."""

from __future__ import annotations

import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.deps import get_container
from agents.orchestrator import AgentContainer, SESSION_TTL_SECONDS
from core.security import get_current_user, verify_client_ownership
from db.database import get_db
from db.models import DBClientProfile, DBUser

router = APIRouter(prefix="/api/v1", tags=["profile"])


def _profile_dict(p: DBClientProfile) -> Dict[str, Any]:
    return {c.name: getattr(p, c.name) for c in p.__table__.columns if c.name != "profiling_session_transcript"}


class OnboardingProfileRequest(BaseModel):
    age: int = Field(..., ge=18, le=120, description="Client age (must be at least 18)")
    employment_status: str = Field(..., description="e.g. employed, self-employed, retired, student, unemployed")
    dependents: int = Field(default=0, ge=0, le=20)

    annual_income: float = Field(..., ge=0.0)
    net_worth: Optional[float] = None
    liquid_assets: float = Field(..., ge=0.0)
    monthly_expenses: float = Field(..., ge=0.0)
    existing_debts: float = Field(default=0.0, ge=0.0)

    investment_experience: str = Field(default="intermediate")
    risk_tolerance_score: float = Field(..., ge=1.0, le=10.0)
    investment_horizon_years: int = Field(..., ge=1, le=50)
    liquidity_needs: str = Field(default="medium")
    loss_capacity: str = Field(default="medium")

    primary_goal: str = Field(default="growth")
    target_return: Optional[float] = Field(default=7.0, ge=0.0, le=50.0)
    specific_goals: List[str] = Field(default_factory=list)

    drawdown_reaction: str = Field(default="hold")
    monitoring_frequency: str = Field(default="monthly")

    source_of_funds: str = Field(default="salary")
    pep_status: bool = Field(default=False)
    high_risk_jurisdiction: bool = Field(default=False)

    session_id: Optional[str] = None


@router.get("/profile")
async def get_my_profile(
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Retrieve the current authenticated user's risk profile."""
    stmt = (
        select(DBClientProfile)
        .where(DBClientProfile.user_id == user.id)
        .order_by(DBClientProfile.created_at.desc())
    )
    result = await db.execute(stmt)
    profile = result.scalars().first()
    if not profile:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile found for this account")
    return _profile_dict(profile)


@router.post("/profile/onboarding", status_code=status.HTTP_200_OK)
async def submit_onboarding_profile(
    req: OnboardingProfileRequest,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """
    Direct structured onboarding: computes suitability tier, emotional risk score,
    panic sell likelihood, and KYC/AML checks without conversational chat.
    Creates or updates DBClientProfile and updates the user's active session.
    """
    try:
        existing_stmt = (
            select(DBClientProfile)
            .where(DBClientProfile.user_id == user.id)
            .order_by(DBClientProfile.created_at.desc())
        )
        existing_res = await db.execute(existing_stmt)
        existing_profile = existing_res.scalars().first()

        client_id = existing_profile.client_id if existing_profile else str(uuid.uuid4())
        ext = req.model_dump()

        # Net worth calculation fallback
        if ext.get("net_worth") is None:
            ext["net_worth"] = max(
                0.0,
                ext["liquid_assets"] + (ext["annual_income"] * 0.5) - ext["existing_debts"]
            )

        # Detect behavioral biases from structured answers
        biases: List[str] = []
        if ext.get("drawdown_reaction") in ("sell_all", "sell_some") and ext.get("loss_capacity") == "low":
            biases.append("loss_aversion")
        if ext.get("risk_tolerance_score", 5.0) >= 8.0 and ext.get("investment_experience") in ("none", "novice"):
            biases.append("overconfidence")
        if ext.get("monitoring_frequency") == "daily":
            biases.append("myopic_loss_aversion")
        ext["detected_biases"] = biases

        # Quantitative scoring engines from RiskProfilerAgent
        composite_score, suitability_cat = c.profiler.calculate_suitability_score(ext)
        emotional_score = c.profiler.calculate_emotional_risk_score(ext)
        panic_prob = c.profiler.calculate_panic_sell_likelihood(ext, emotional_score, composite_score)
        kyc_ok, aml_flag = c.profiler.evaluate_compliance_kyc_aml(ext)

        profile_data = {
            "client_id": client_id,
            "user_id": user.id,
            "age": ext["age"],
            "employment_status": ext["employment_status"],
            "dependents": ext["dependents"],
            "annual_income": ext["annual_income"],
            "net_worth": ext["net_worth"],
            "liquid_assets": ext["liquid_assets"],
            "monthly_expenses": ext["monthly_expenses"],
            "existing_debts": ext["existing_debts"],
            "investment_experience": ext["investment_experience"],
            "risk_tolerance_score": ext["risk_tolerance_score"],
            "investment_horizon_years": ext["investment_horizon_years"],
            "liquidity_needs": ext["liquidity_needs"],
            "loss_capacity": ext["loss_capacity"],
            "primary_goal": ext["primary_goal"],
            "target_return": ext["target_return"],
            "specific_goals": ext["specific_goals"],
            "suitability_category": suitability_cat,
            "detected_biases": biases,
            "emotional_risk_score": emotional_score,
            "panic_sell_likelihood": panic_prob,
            "kyc_verified": kyc_ok,
            "aml_flag": aml_flag,
            "source_of_funds": ext.get("source_of_funds", "salary"),
            "drawdown_reaction": ext.get("drawdown_reaction", "hold"),
            "monitoring_frequency": ext.get("monitoring_frequency", "monthly"),
            "pep_status": bool(ext.get("pep_status", False)),
            "high_risk_jurisdiction": bool(ext.get("high_risk_jurisdiction", False)),
            "profiling_session_transcript": "Completed via structured onboarding questionnaire",
        }

        saved_profile = await c.profiler.save_profile(db, client_id, profile_data)

        # Log immutable audit entry
        try:
            await c.audit.log_audit_entry(
                db=db,
                client_id=client_id,
                event_type="PROFILE_COMPLETED" if not existing_profile else "PROFILE_UPDATED",
                actor="USER:onboarding_form",
                details={
                    "suitability_category": suitability_cat,
                    "risk_tolerance_score": ext["risk_tolerance_score"],
                    "kyc_verified": kyc_ok,
                    "aml_flag": aml_flag,
                    "method": "structured_onboarding",
                },
                session_id=req.session_id,
            )
        except Exception as audit_err:
            import logging
            logging.getLogger("wealth_advisor.api.profile").warning("Audit entry warning: %s", audit_err)

        # Update active session in redis if session_id is provided
        if req.session_id:
            try:
                session = await c.cache.get_json(f"session:{req.session_id}")
                if session and session.get("user_id") == user.id:
                    session["client_id"] = client_id
                    session["stage"] = "ADVICE_GENERATION"
                    await c.cache.set_json(f"session:{req.session_id}", session, expire=SESSION_TTL_SECONDS)
            except Exception:
                pass

        return _profile_dict(saved_profile)
    except Exception as exc:
        await db.rollback()
        import logging
        logging.getLogger("wealth_advisor.api.profile").exception("Onboarding submission failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="We could not save your profile. Please try again.",
        )


class UpdateProfileRequest(BaseModel):
    client_id: Optional[str] = None
    age: Optional[int] = Field(default=None, ge=18, le=120)
    employment_status: Optional[str] = None
    dependents: Optional[int] = Field(default=None, ge=0, le=20)

    annual_income: Optional[float] = Field(default=None, ge=0.0)
    net_worth: Optional[float] = None
    liquid_assets: Optional[float] = Field(default=None, ge=0.0)
    monthly_expenses: Optional[float] = Field(default=None, ge=0.0)
    existing_debts: Optional[float] = Field(default=None, ge=0.0)
    source_of_funds: Optional[str] = None

    investment_experience: Optional[str] = None
    risk_tolerance_score: Optional[float] = Field(default=None, ge=1.0, le=10.0)
    investment_horizon_years: Optional[int] = Field(default=None, ge=1, le=50)
    liquidity_needs: Optional[str] = None
    loss_capacity: Optional[str] = None

    primary_goal: Optional[str] = None
    target_return: Optional[float] = Field(default=None, ge=0.0, le=50.0)
    specific_goals: Optional[List[str]] = None

    drawdown_reaction: Optional[str] = None
    monitoring_frequency: Optional[str] = None

    pep_status: Optional[bool] = None
    high_risk_jurisdiction: Optional[bool] = None


@router.put("/profile")
@router.put("/profile/{client_id}")
async def update_client_profile(
    req: UpdateProfileRequest,
    client_id: Optional[str] = None,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    c: AgentContainer = Depends(get_container),
):
    """
    Update client profile parameters, recompute suitability and behavioral risk metrics,
    and persist the updated profile with immutable audit logging.
    """
    target_cid = client_id or req.client_id
    if target_cid:
        profile = await verify_client_ownership(user, target_cid, db)
    else:
        stmt = (
            select(DBClientProfile)
            .where(DBClientProfile.user_id == user.id)
            .order_by(DBClientProfile.created_at.desc())
        )
        res = await db.execute(stmt)
        profile = res.scalars().first()
        if not profile:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No profile found to update")
        target_cid = profile.client_id

    # Merge incoming updates over existing profile
    curr = _profile_dict(profile)
    incoming = {k: v for k, v in req.model_dump().items() if v is not None and k != "client_id"}
    merged = {**curr, **incoming}

    # Recalculate net worth if financial inputs changed
    if "liquid_assets" in incoming or "annual_income" in incoming or "existing_debts" in incoming:
        if req.net_worth is None:
            merged["net_worth"] = max(
                0.0,
                merged.get("liquid_assets", 0.0) + (merged.get("annual_income", 0.0) * 0.5) - merged.get("existing_debts", 0.0)
            )

    # Re-evaluate behavioral biases
    biases: List[str] = list(profile.detected_biases or [])
    if merged.get("drawdown_reaction") in ("sell_all", "sell_some") and merged.get("loss_capacity") == "low":
        if "loss_aversion" not in biases:
            biases.append("loss_aversion")
    if (merged.get("risk_tolerance_score") or 5.0) >= 8.0 and merged.get("investment_experience") in ("none", "novice"):
        if "overconfidence" not in biases:
            biases.append("overconfidence")
    if merged.get("monitoring_frequency") == "daily":
        if "myopic_loss_aversion" not in biases:
            biases.append("myopic_loss_aversion")
    merged["detected_biases"] = biases

    # Recompute quantitative risk and suitability scores
    composite_score, suitability_cat = c.profiler.calculate_suitability_score(merged)
    emotional_score = c.profiler.calculate_emotional_risk_score(merged)
    panic_prob = c.profiler.calculate_panic_sell_likelihood(merged, emotional_score, composite_score)
    kyc_ok, aml_flag = c.profiler.evaluate_compliance_kyc_aml(merged)

    merged["suitability_category"] = suitability_cat
    merged["emotional_risk_score"] = emotional_score
    merged["panic_sell_likelihood"] = panic_prob
    merged["kyc_verified"] = kyc_ok
    merged["aml_flag"] = aml_flag

    saved = await c.profiler.save_profile(db, target_cid, merged)

    await c.audit.log_audit_entry(
        db=db,
        client_id=target_cid,
        event_type="PROFILE_UPDATED",
        actor="USER:profile_editor",
        details={
            "updated_fields": list(incoming.keys()),
            "suitability_category": suitability_cat,
            "risk_tolerance_score": merged.get("risk_tolerance_score"),
        },
    )

    return _profile_dict(saved)


@router.get("/profile/{client_id}")
async def get_profile(
    client_id: str,
    user: DBUser = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    profile = await verify_client_ownership(user, client_id, db)
    return _profile_dict(profile)


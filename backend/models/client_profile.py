from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class ClientProfile(BaseModel):
    client_id: str
    age: int
    employment_status: str
    dependents: int = 0
    
    annual_income: float
    net_worth: Optional[float] = None
    liquid_assets: float = 0.0
    monthly_expenses: float = 0.0
    existing_debts: float = 0.0
    
    investment_experience: str = "intermediate"
    risk_tolerance_score: float = Field(..., ge=1.0, le=10.0)
    investment_horizon_years: int
    liquidity_needs: str = "medium"
    loss_capacity: str = "medium"
    
    primary_goal: str = "growth"
    target_return: Optional[float] = 7.0
    specific_goals: List[str] = Field(default_factory=list)
    
    detected_biases: List[str] = Field(default_factory=list)
    emotional_risk_score: float = 0.0
    panic_sell_likelihood: float = 0.0
    
    kyc_verified: bool = False
    aml_flag: bool = False
    suitability_category: str = "Moderate"
    
    profile_created_at: datetime = Field(default_factory=datetime.utcnow)
    profile_updated_at: datetime = Field(default_factory=datetime.utcnow)
    profiling_session_transcript: str = ""

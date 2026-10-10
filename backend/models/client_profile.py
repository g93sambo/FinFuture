from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime
from pydantic import Field

class ClientProfile(BaseModel):
    client_id: str
    age: int
    employment_status: str
    dependents: int
    
    annual_income: float
    net_worth: float
    liquid_assets: float
    monthly_expenses: float
    existing_debts: float
    
    investment_experience: str
    risk_tolerance_score: float = Field(..., ge=1.0, le=10.0)
    investment_horizon_years: int
    liquidity_needs: str
    loss_capacity: str
    
    primary_goal: str
    target_return: float
    specific_goals: List[str]
    
    detected_biases: List[str] = []
    emotional_risk_score: float = 0.0
    panic_sell_likelihood: float = 0.0
    
    kyc_verified: bool = False
    aml_flag: bool = False
    suitability_category: str
    
    profile_created_at: datetime = Field(default_factory=datetime.utcnow)
    profile_updated_at: datetime = Field(default_factory=datetime.utcnow)
    profiling_session_transcript: str = ""

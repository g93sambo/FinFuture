"""
backend/agents/risk_profiler.py
===============================
State-machine driven conversational risk profiler agent with quantitative scoring,
KYC/AML validation, draft session caching, and database persistence.
"""

from __future__ import annotations

import re
import math
import uuid
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.database import AsyncSessionLocal
from db.models import DBClientProfile
from services.cache import (
    CacheService,
    get_cache_service,
    key_profile_draft,
    TTL_PROFILE_DRAFT,
)

logger = logging.getLogger("wealth_advisor.agents.risk_profiler")

# --- FSM States ---
STATE_DEMOGRAPHICS = "DEMOGRAPHICS"
STATE_FINANCIAL_SITUATION = "FINANCIAL_SITUATION"
STATE_TIME_HORIZON = "TIME_HORIZON"
STATE_RISK_TOLERANCE = "RISK_TOLERANCE"
STATE_EXPERIENCE = "EXPERIENCE"
STATE_PROFILE_SYNTHESIS = "PROFILE_SYNTHESIS"
STATE_COMPLETE = "COMPLETE"

FSM_STATES = [
    STATE_DEMOGRAPHICS,
    STATE_FINANCIAL_SITUATION,
    STATE_TIME_HORIZON,
    STATE_RISK_TOLERANCE,
    STATE_EXPERIENCE,
    STATE_PROFILE_SYNTHESIS,
    STATE_COMPLETE,
]

STATE_PROMPTS = {
    STATE_DEMOGRAPHICS: (
        "Welcome to your AI Wealth Advisory consultation! To tailor our advice, let's start with a few basics: "
        "How old are you, what is your current employment status, and do you have any dependents?"
    ),
    STATE_FINANCIAL_SITUATION: (
        "Thank you. Next, let's look at your financial foundation: What is your approximate annual income, "
        "how much do you hold in liquid savings, and what are your typical monthly expenses and outstanding debts?"
    ),
    STATE_TIME_HORIZON: (
        "Great. What is your intended investment time horizon (in years), and what is your primary objective "
        "(e.g., capital preservation, balanced income, long-term wealth growth, or retirement)?"
    ),
    STATE_RISK_TOLERANCE: (
        "How would you rate your risk tolerance on a scale of 1 to 10? Also, if your portfolio dropped 20% "
        "during a severe market correction, would you sell your investments, hold steady, or buy more at discounted prices?"
    ),
    STATE_EXPERIENCE: (
        "Lastly, how would you describe your investment experience (e.g. none, novice, intermediate, advanced)? "
        "For regulatory compliance, what is the primary source of your investment funds (e.g. salary, business), "
        "and are you or an immediate family member a Politically Exposed Person (PEP)?"
    ),
}


class RiskProfilerAgent:
    """
    State-machine driven conversational risk profiler agent with quantitative
    scoring, KYC/AML validation, draft session caching, and database persistence.
    """

    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        openai_client: Optional[Any] = None,
    ) -> None:
        self.cache = cache_service or get_cache_service()
        self.openai_client = openai_client
        if self.openai_client is None:
            api_key = os_env_key = None
            try:
                import os
                api_key = os.getenv("OPENAI_API_KEY")
                if api_key and api_key != "your_openai_api_key_here":
                    from openai import AsyncOpenAI
                    self.openai_client = AsyncOpenAI(api_key=api_key)
            except Exception as e:
                logger.warning(f"Could not initialize AsyncOpenAI client: {e}")

    # ------------------------------------------------------------------
    # FSM State & Session Cache Management
    # ------------------------------------------------------------------

    async def _load_or_create_draft(self, session_id: str) -> Dict[str, Any]:
        """Loads draft state from cache or initializes a new profiling session."""
        cache_key = key_profile_draft(session_id)
        cached = await self.cache.get_json(cache_key)
        if cached and isinstance(cached, dict):
            return cached

        new_draft = {
            "session_id": session_id,
            "client_id": str(uuid.uuid4()),
            "user_id": None,
            "current_state": STATE_DEMOGRAPHICS,
            "extracted_data": {
                "dependents": 0,
                "net_worth": None,
                "liquid_assets": 0.0,
                "monthly_expenses": 0.0,
                "existing_debts": 0.0,
                "target_return": 7.0,
                "specific_goals": [],
                "detected_biases": [],
                "loss_capacity": "medium",
                "liquidity_needs": "medium",
                "pep_status": False,
                "high_risk_jurisdiction": False,
                "source_of_funds": "salary",
                "drawdown_reaction": "hold",
                "monitoring_frequency": "monthly",
            },
            "conversation_history": [],
            "started_at": datetime.utcnow().isoformat(),
            "last_updated": datetime.utcnow().isoformat(),
        }
        await self.cache.set_json(cache_key, new_draft, expire=TTL_PROFILE_DRAFT)
        return new_draft

    async def _save_draft(self, session_id: str, draft: Dict[str, Any]) -> None:
        """Persists the session draft to cache."""
        draft["last_updated"] = datetime.utcnow().isoformat()
        cache_key = key_profile_draft(session_id)
        await self.cache.set_json(cache_key, draft, expire=TTL_PROFILE_DRAFT)

    async def _evict_draft(self, session_id: str) -> None:
        """Evicts completed profiling session draft from cache."""
        cache_key = key_profile_draft(session_id)
        await self.cache.delete(cache_key)

    # ------------------------------------------------------------------
    # Heuristic & Deterministic Extraction
    # ------------------------------------------------------------------

    def _parse_currency_value(self, val_str: str, multiplier_str: Optional[str] = None) -> float:
        cleaned = val_str.replace(",", "").strip()
        if not cleaned:
            return 0.0
        try:
            val = float(cleaned)
        except ValueError:
            return 0.0
        if multiplier_str:
            m = multiplier_str.lower()
            if m.startswith("k"):
                val *= 1_000.0
            elif m.startswith("m"):
                val *= 1_000_000.0
            elif m.startswith("b"):
                val *= 1_000_000_000.0
        return val

    def extract_heuristic_data(self, text: str, current_extracted: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extracts profiling parameters deterministically from user text using calibrated regexes.
        """
        extracted = dict(current_extracted)
        text_lower = text.lower()

        # 1. Demographics
        # Age
        age_match = re.search(r"\b(?:i am|i'm|im|i’m|age\s*(?:is|:)?)\s*(\d{1,3})\b", text_lower)
        if not age_match:
            # Match stand-alone 2-digit number when discussing age or bare 2-digit input
            age_match = re.search(r"\b(\d{2})\s*(?:years?\s*old|yo)\b", text_lower)
        if not age_match and ("age" in text_lower or re.match(r"^\s*(\d{2})\s*$", text_lower)):
            age_match = re.search(r"\b(\d{2})\b", text_lower)
        if age_match:
            try:
                extracted["age"] = int(age_match.group(1))
            except ValueError:
                pass

        # Employment status
        if re.search(r"\b(self[- ]employed|freelanc\w+|business owner|entrepreneur)\b", text_lower):
            extracted["employment_status"] = "self-employed"
        elif re.search(r"\b(retir\w+)\b", text_lower):
            extracted["employment_status"] = "retired"
        elif re.search(r"\b(student)\b", text_lower):
            extracted["employment_status"] = "student"
        elif re.search(r"\b(unemployed|jobless)\b", text_lower):
            extracted["employment_status"] = "unemployed"
        elif re.search(r"\b(employed|software|engineer|doctor|lawyer|teacher|manager|analyst|worker|consultant|full[- ]time)\b", text_lower):
            extracted["employment_status"] = "employed"

        # Dependents
        dep_match = re.search(r"\b(\d+)\s*(?:dependents?|kids?|children)\b", text_lower)
        if dep_match:
            extracted["dependents"] = int(dep_match.group(1))
        elif re.search(r"\b(no|zero|none|without)\s+(?:dependents?|kids?|children)\b", text_lower):
            extracted["dependents"] = 0

        # 2. Financial Situation
        # Annual Income
        inc_match = re.search(r"\b(?:income|earn|make|salary)\s*(?:is|of|around|about|:)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\b", text_lower)
        if inc_match:
            extracted["annual_income"] = self._parse_currency_value(inc_match.group(1), inc_match.group(2))
        elif re.search(r"\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:dollars?|bucks|usd)?\s*(?:per year|annually|a year|annual|\/yr)", text_lower):
            m = re.search(r"\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:dollars?|bucks|usd)?\s*(?:per year|annually|a year|annual|\/yr)", text_lower)
            extracted["annual_income"] = self._parse_currency_value(m.group(1), m.group(2))
        elif current_extracted.get("annual_income") is None:
            # Stand-alone dollar amount when asking for income
            lone_match = re.search(r"(?:like|around|about|approx)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:dollars?|bucks|usd)?\b", text_lower)
            if lone_match and lone_match.group(1) and float(lone_match.group(1).replace(",", "")) > 1000:
                extracted["annual_income"] = self._parse_currency_value(lone_match.group(1), lone_match.group(2))

        # Liquid Assets / Savings
        liq_match = re.search(r"\b(?:savings|liquid(?:ity)?|cash|in bank)\s*(?:is|of|around|about|:)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\b", text_lower)
        if not liq_match:
            liq_match = re.search(r"\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:in\s+)?(?:liquid\s+savings|liquid\s+assets|savings|cash|in\s+bank)\b", text_lower)
        if liq_match:
            extracted["liquid_assets"] = self._parse_currency_value(liq_match.group(1), liq_match.group(2))

        # Monthly Expenses
        exp_match = re.search(r"\b(?:expenses?|spend|spending)\s*(?:is|of|around|about|:)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:per month|monthly|\/mo)?\b", text_lower)
        if not exp_match:
            exp_match = re.search(r"\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\s*(?:in\s+)?(?:monthly\s+expenses|expenses?|per\s+month|\/mo)\b", text_lower)
        if exp_match:
            extracted["monthly_expenses"] = self._parse_currency_value(exp_match.group(1), exp_match.group(2))

        # Debts
        debt_match = re.search(r"\b(?:debts?|loans?|mortgage|liabilities)\s*(?:is|of|around|about|:)?\s*\$?(\d[\d,]*(?:\.\d+)?)\s*([kmb])?\b", text_lower)
        if debt_match:
            extracted["existing_debts"] = self._parse_currency_value(debt_match.group(1), debt_match.group(2))
        elif re.search(r"\b(no|zero|none)\s+(?:debts?|loans?|liabilities)\b", text_lower):
            extracted["existing_debts"] = 0.0

        # Net worth calculation fallback
        if extracted.get("net_worth") is None and extracted.get("liquid_assets") is not None:
            extracted["net_worth"] = max(extracted.get("liquid_assets", 0.0) - extracted.get("existing_debts", 0.0), 0.0)

        # 3. Time Horizon & Goals
        # Horizon (avoid matching age such as '40 years old')
        hor_match = re.search(r"\b(\d{1,2})\s*(?:years?|yrs?)\b(?!\s*old)", text_lower)
        if hor_match:
            val_h = int(hor_match.group(1))
            if not (extracted.get("age") == val_h and re.search(rf"\b{val_h}\s*years?\s*old\b", text_lower)):
                extracted["investment_horizon_years"] = val_h

        # Primary goal (personal investment goals)
        if re.search(r"\b(capital preservation|preserve capital|safety of principal)\b", text_lower):
            extracted["primary_goal"] = "capital_preservation"
        elif (
            re.search(r"\b(?:(?:my\s+)?(?:primary\s+)?(?:goal|objective|aim|target)\s*(?:is|:)?\s*.*)?\b(dividend\s+income|steady\s+income|passive\s+income|dividend|dividends|cash\s+flow)\b", text_lower)
            or re.search(r"\b(?:goal|objective|aim|target)\s*(?:is|to\s+generate)?\s*(?:steady\s+)?income\b", text_lower)
            or re.search(r"\b(investing\s+for\s+income|seeking\s+income|focus(?:ed)?\s+on\s+income)\b", text_lower)
        ) and not re.search(r"\b(?:annual|monthly|yearly|current|my)\s+income\b|\bincome\s+(?:is|of|around|about|:)\s*\$?\d+|\bearn\b", text_lower):
            extracted["primary_goal"] = "income"
        elif re.search(r"\b(?:(?:my\s+)?(?:primary\s+)?(?:goal|objective|aim|target)\b.*)?\b(balanced|moderate)\b", text_lower):
            extracted["primary_goal"] = "balanced"
        elif re.search(r"\b(aggressive growth|maximum growth|speculat\w+)\b", text_lower):
            extracted["primary_goal"] = "aggressive_growth"
        elif (
            re.search(r"\b(?:(?:my\s+)?(?:primary\s+)?(?:goal|objective|aim|target)|seeking|investing for|saving for|for (?:wealth )?growth)\b", text_lower)
            or re.search(r"\b(wealth accumulation|planning for retirement)\b", text_lower)
            or (re.search(r"\bgrowth\b", text_lower) and not re.search(r"\b(analyze|potential for|stock|price|earnings|revenue|market|gdp|historical|supplier|supply|chain)\b", text_lower))
        ):
            extracted["primary_goal"] = "growth"

        # Liquidity Needs
        if re.search(r"\b(high liquidity|need cash soon|short term need)\b", text_lower):
            extracted["liquidity_needs"] = "high"
        elif re.search(r"\b(low liquidity|don'?t need cash|locked up)\b", text_lower):
            extracted["liquidity_needs"] = "low"
        elif re.search(r"\b(medium liquidity|moderate liquidity)\b", text_lower):
            extracted["liquidity_needs"] = "medium"

        # 4. Risk Tolerance & Loss Capacity
        # Risk Score (1-10)
        risk_match = re.search(r"\b(?:risk(?:\s*(?:score|tolerance))?\s*(?:is|of|:)?\s*|rated?\s*)?([1-9]|10)(?:\.([0-9]))?\s*(?:out of 10|\/10)?\b", text_lower)
        # Look specifically for rating/score
        explicit_risk = re.search(r"\b([1-9]|10)(?:\.([0-9]))?\s*(?:\/10|out of 10)\b", text_lower)
        if explicit_risk:
            base = float(explicit_risk.group(1))
            if explicit_risk.group(2):
                base += float(f"0.{explicit_risk.group(2)}")
            extracted["risk_tolerance_score"] = min(10.0, max(1.0, base))
        elif risk_match and ("risk" in text_lower or "score" in text_lower or "tolerance" in text_lower or "rate" in text_lower):
            base = float(risk_match.group(1))
            if risk_match.group(2):
                base += float(f"0.{risk_match.group(2)}")
            extracted["risk_tolerance_score"] = min(10.0, max(1.0, base))

        # Drawdown reaction
        if re.search(r"\b(sell (?:all|everything)|dump (?:all|everything)|panic|liquidate)\b", text_lower):
            extracted["drawdown_reaction"] = "sell_all"
        elif re.search(r"\b(sell some|reduce (?:risk|exposure)|trim)\b", text_lower):
            extracted["drawdown_reaction"] = "sell_some"
        elif re.search(r"\b(anxious|nervous|worry|lose sleep)\b", text_lower):
            extracted["drawdown_reaction"] = "anxious"
        elif re.search(r"\b(buy more|discount|bargain|accumulate|add more)\b", text_lower):
            extracted["drawdown_reaction"] = "buy_more"
        elif re.search(r"\b(hold|stay the course|do nothing|wait it out)\b", text_lower):
            extracted["drawdown_reaction"] = "hold"

        # Loss capacity
        if re.search(r"\b(low loss capacity|cannot afford (?:any )?loss|can'?t take loss)\b", text_lower):
            extracted["loss_capacity"] = "low"
        elif re.search(r"\b(high loss capacity|can take high loss|absorb loss)\b", text_lower):
            extracted["loss_capacity"] = "high"
        elif re.search(r"\b(medium loss capacity|moderate loss)\b", text_lower):
            extracted["loss_capacity"] = "medium"

        # 5. Experience & Compliance / KYC
        # Investment Experience
        if re.search(r"\b(none|no experience|never invested|beginner)\b", text_lower):
            extracted["investment_experience"] = "none"
        elif re.search(r"\b(novice)\b", text_lower):
            extracted["investment_experience"] = "novice"
        elif re.search(r"\b(intermediate|a few years|some experience)\b", text_lower):
            extracted["investment_experience"] = "intermediate"
        elif re.search(r"\b(advanced|experienced|veteran)\b", text_lower):
            extracted["investment_experience"] = "advanced"
        elif re.search(r"\b(expert|professional)\b", text_lower):
            extracted["investment_experience"] = "expert"

        # Source of funds
        if re.search(r"\b(salary|employment|wages|job)\b", text_lower):
            extracted["source_of_funds"] = "salary"
        elif re.search(r"\b(business|company profits)\b", text_lower):
            extracted["source_of_funds"] = "business"
        elif re.search(r"\b(investments?|capital gains?)\b", text_lower):
            extracted["source_of_funds"] = "investments"
        elif re.search(r"\b(inheritance|family gift|estate)\b", text_lower):
            extracted["source_of_funds"] = "inheritance"
        elif re.search(r"\b(crypto mixing|cash deposits?|gambling|anonymous)\b", text_lower):
            extracted["source_of_funds"] = "crypto_mixing" if "mixing" in text_lower else "cash"

        # PEP Status
        if re.search(r"\b(i am a pep|is a pep|politically exposed person)\b", text_lower) and not re.search(r"\b(not|no|never)\b", text_lower):
            extracted["pep_status"] = True
        elif re.search(r"\b(not a pep|no pep|not politically exposed)\b", text_lower):
            extracted["pep_status"] = False

        # High risk jurisdiction
        if re.search(r"\b(sanctioned|iran|north korea|syria|russia|fatf blacklist)\b", text_lower):
            extracted["high_risk_jurisdiction"] = True

        return extracted

    # ------------------------------------------------------------------
    # FSM Validation & Advancement
    # ------------------------------------------------------------------

    def validate_state_completion(self, state: str, data: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """
        Validates if mandatory fields for the current state are collected and valid.
        Returns (is_complete, prompt_or_error_message).
        """
        if state == STATE_DEMOGRAPHICS:
            age = data.get("age")
            if age is None:
                return False, "To tailor our advisory strategy, could you share your approximate age?"
            if age < 18:
                return False, "Under regulatory requirements, advisory clients must be at least 18 years old."
            if not data.get("employment_status"):
                return False, "Thanks! What is your current employment status (e.g., employed, self-employed, or retired)?"
            return True, None

        elif state == STATE_FINANCIAL_SITUATION:
            if data.get("annual_income") is None:
                return False, "Could you share your approximate annual income so we can assess your cash flow capacity?"
            if data.get("liquid_assets") is None:
                return False, "Roughly how much do you have set aside in liquid savings or emergency reserves?"
            return True, None

        elif state == STATE_TIME_HORIZON:
            if data.get("investment_horizon_years") is None:
                return False, "What timeframe are you looking at for these investments (e.g., 2 years, 5 years, or long-term 10+ years)?"
            if not data.get("primary_goal"):
                return False, "What is your main financial objective (such as capital preservation, steady income, or long-term growth)?"
            return True, None

        elif state == STATE_RISK_TOLERANCE:
            if data.get("risk_tolerance_score") is None:
                return False, "On a scale from 1 (very conservative) to 10 (very aggressive), how comfortable are you taking on portfolio volatility?"
            return True, None

        elif state == STATE_EXPERIENCE:
            if not data.get("investment_experience"):
                return False, "How would you describe your overall investment experience (none, novice, intermediate, or advanced)?"
            return True, None

        elif state == STATE_PROFILE_SYNTHESIS:
            return True, None

        return True, None

    def get_state_options(self, state: str, data: Dict[str, Any]) -> List[str]:
        """
        Returns tap-to-answer quick-reply options tailored to the currently missing field in state.
        """
        if state == STATE_DEMOGRAPHICS:
            if data.get("age") is None:
                return ["18-25", "26-35", "36-50", "51-65", "65+"]
            if not data.get("employment_status"):
                return ["Employed (Full-time)", "Self-Employed / Business", "Retired", "Student"]
            return []

        elif state == STATE_FINANCIAL_SITUATION:
            if data.get("annual_income") is None:
                return ["$45,000", "$90,000", "$150,000", "$300,000+"]
            if data.get("liquid_assets") is None:
                return ["$15,000", "$50,000", "$100,000", "$250,000+"]
            return []

        elif state == STATE_TIME_HORIZON:
            if data.get("investment_horizon_years") is None:
                return ["1 to 3 years", "3 to 5 years", "5 to 10 years", "10+ years"]
            if not data.get("primary_goal"):
                return ["Capital Preservation", "Balanced Growth", "Long-term Growth", "Aggressive Growth"]
            return []

        elif state == STATE_RISK_TOLERANCE:
            if data.get("risk_tolerance_score") is None:
                return ["Conservative (3/10)", "Moderate (5/10)", "Growth (7/10)", "Aggressive (9/10)"]
            if not data.get("drawdown_reaction"):
                return ["Buy more at a discount", "Hold steady", "Trim some exposure", "Sell all"]
            return []

        elif state == STATE_EXPERIENCE:
            if not data.get("investment_experience"):
                return ["Beginner / None", "Novice (1-2 years)", "Intermediate (3-5 years)", "Advanced / Active"]
            if not data.get("source_of_funds"):
                return ["Employment Salary", "Business Profits", "Investments", "Savings / Inheritance"]
            if data.get("pep_status") is None:
                return ["Not a PEP", "I or a family member am a PEP"]
            return []

        return []

    async def _extract_with_model(self, user_message: str, current_state: str, current_extracted: Dict[str, Any]) -> Dict[str, Any]:
        """
        Model-assisted field extraction for ambiguous free-text inputs.
        Does NOT calculate scores or make decisions; strictly extracts entity attributes.
        """
        if not self.openai_client:
            return current_extracted

        try:
            prompt = (
                f"You are a structured data extraction engine for client onboarding. "
                f"Extract any mentioned client attributes from the user's message into strict JSON.\n"
                f"User message: \"{user_message}\"\n"
                f"Current state: {current_state}\n"
                f"Fields to extract (return null if unmentioned):\n"
                f"- age: integer (e.g. 19)\n"
                f"- employment_status: string ('employed', 'self-employed', 'retired', 'student', 'unemployed')\n"
                f"- dependents: integer\n"
                f"- annual_income: float in dollars/naira numeric (e.g. 90000)\n"
                f"- liquid_assets: float in dollars/naira numeric (e.g. 25000)\n"
                f"- monthly_expenses: float\n"
                f"- existing_debts: float\n"
                f"- investment_horizon_years: integer\n"
                f"- primary_goal: string ('capital_preservation', 'income', 'balanced', 'growth', 'aggressive_growth')\n"
                f"- risk_tolerance_score: float from 1.0 to 10.0\n"
                f"- drawdown_reaction: string ('buy_more', 'hold', 'anxious', 'sell_some', 'sell_all')\n"
                f"- investment_experience: string ('none', 'novice', 'intermediate', 'advanced', 'expert')\n"
                f"- source_of_funds: string ('salary', 'business', 'investments', 'inheritance', 'savings')\n"
                f"- pep_status: boolean\n\n"
                f"Respond ONLY with a valid JSON object."
            )
            try:
                from core.config import settings
                model = getattr(settings, "openai_model", "gpt-4o")
            except Exception:
                model = "gpt-4o"

            resp = await self.openai_client.chat.completions.create(
                model=model,
                messages=[{"role": "system", "content": "You are a JSON-only entity extractor."}, {"role": "user", "content": prompt}],
                temperature=0.0,
                response_format={"type": "json_object"},
                max_tokens=300,
            )
            raw = resp.choices[0].message.content or "{}"
            parsed = json.loads(raw)
            updated = dict(current_extracted)
            for k, v in parsed.items():
                if v is not None and (updated.get(k) is None or updated.get(k) == 0):
                    updated[k] = v
            return updated
        except Exception as e:
            logger.debug("Model-based field extraction fallback skipped: %s", e)
            return current_extracted

    # ------------------------------------------------------------------
    # Quantitative Scoring Engines
    # ------------------------------------------------------------------

    def calculate_suitability_score(self, data: Dict[str, Any]) -> Tuple[float, str]:
        """
        Calculates composite suitability score S in [1.0, 10.0] and maps to category
        with regulatory guardrails per FINRA Rule 2111 / Reg BI.
        """
        # 1. Risk Tolerance Score S_rt (1-10)
        s_rt = float(data.get("risk_tolerance_score", 5.0))

        # 2. Horizon Score S_h
        h = int(data.get("investment_horizon_years", 5))
        if h < 2:
            s_h = 2.0
        elif h < 5:
            s_h = 4.0
        elif h < 10:
            s_h = 6.5
        elif h < 20:
            s_h = 8.5
        else:
            s_h = 10.0

        # 3. Loss Capacity Score S_lc
        lc = str(data.get("loss_capacity", "medium")).lower()
        if lc == "low":
            s_lc = 2.5
        elif lc == "high":
            s_lc = 9.0
        else:
            s_lc = 6.0

        # Emergency reserve check
        liquid = float(data.get("liquid_assets", 0.0))
        expenses = float(data.get("monthly_expenses", 0.0))
        if expenses > 0 and (liquid / expenses) < 3.0:
            s_lc = min(s_lc, 3.0)

        # 4. Goal Score S_g
        goal = str(data.get("primary_goal", "growth")).lower()
        if "capital_preservation" in goal or "preserv" in goal:
            s_g = 2.0
        elif "income" in goal:
            s_g = 4.0
        elif "balanced" in goal:
            s_g = 5.5
        elif "aggressive" in goal or "speculat" in goal:
            s_g = 10.0
        elif "growth" in goal or "wealth" in goal or "retire" in goal:
            s_g = 8.0
        else:
            s_g = 6.0

        # 5. Experience Score S_exp
        exp = str(data.get("investment_experience", "intermediate")).lower()
        if exp == "none":
            s_exp = 2.0
        elif exp == "novice":
            s_exp = 4.0
        elif exp == "intermediate":
            s_exp = 6.5
        elif exp == "advanced":
            s_exp = 8.5
        elif exp == "expert":
            s_exp = 10.0
        else:
            s_exp = 6.0

        # Composite score
        s_raw = 0.35 * s_rt + 0.25 * s_lc + 0.20 * s_h + 0.10 * s_g + 0.10 * s_exp
        s = s_raw

        # Regulatory Guardrails
        # 1. Short horizon guard (< 3 years -> max 4.0)
        if h < 3:
            s = min(s, 4.0)

        # 2. Low loss capacity guard
        if lc == "low" or (expenses > 0 and liquid / max(expenses, 1.0) < 3.0):
            s = min(s, 5.0)

        # 3. Inexperience guard
        if exp == "none" and s_rt > 7.0:
            s = min(s, 6.5)

        s = round(max(1.0, min(10.0, s)), 2)

        # Category mapping
        if s < 3.0:
            category = "Conservative"
        elif s < 5.0:
            category = "Moderate Conservative"
        elif s < 7.0:
            category = "Moderate"
        elif s < 8.5:
            category = "Growth"
        else:
            category = "Aggressive Growth"

        return s, category

    def calculate_emotional_risk_score(self, data: Dict[str, Any]) -> float:
        """
        Calculates emotional risk score on a 0 - 100 scale.
        """
        # Drawdown vulnerability
        reaction = str(data.get("drawdown_reaction", "hold")).lower()
        if reaction == "sell_all":
            e_drawdown = 100.0
        elif reaction == "sell_some":
            e_drawdown = 75.0
        elif reaction == "anxious":
            e_drawdown = 50.0
        elif reaction == "buy_more":
            e_drawdown = 5.0
        else:  # hold or other
            e_drawdown = 20.0

        # Frequency vulnerability
        freq = str(data.get("monitoring_frequency", "monthly")).lower()
        if "multiple" in freq or "daily" in freq and "multiple" in freq:
            e_freq = 90.0
        elif "daily" in freq:
            e_freq = 70.0
        elif "weekly" in freq:
            e_freq = 40.0
        elif "monthly" in freq:
            e_freq = 20.0
        elif "annual" in freq or "yearly" in freq:
            e_freq = 5.0
        else:
            e_freq = 40.0

        # Behavioral biases
        biases = data.get("detected_biases", [])
        bias_weights = {
            "loss_aversion": 35.0,
            "recency_bias": 25.0,
            "herding": 20.0,
            "herd_mentality": 20.0,
            "overconfidence": 15.0,
            "disposition_effect": 20.0,
        }
        bias_score = sum(bias_weights.get(b, 15.0) for b in biases)
        e_biases = min(100.0, bias_score)

        # Financial stress buffer
        income = float(data.get("annual_income", 100000.0))
        debts = float(data.get("existing_debts", 0.0))
        liquid = float(data.get("liquid_assets", 20000.0))
        expenses = float(data.get("monthly_expenses", 3000.0))

        dti = (debts / income) if income > 0 else 1.0
        reserves = (liquid / expenses) if expenses > 0 else 6.0

        if dti > 0.5 or reserves < 2.0:
            e_stress = 85.0
        elif dti >= 0.2 or reserves <= 6.0:
            e_stress = 45.0
        else:
            e_stress = 10.0

        e = 0.40 * e_drawdown + 0.20 * e_freq + 0.20 * e_biases + 0.20 * e_stress
        return round(max(0.0, min(100.0, e)), 1)

    def calculate_panic_sell_likelihood(
        self,
        data: Dict[str, Any],
        emotional_risk: float,
        composite_score: float,
    ) -> float:
        """
        Calibrated logistic model predicting P(panic sell | market dip >= 20%).
        """
        reaction = str(data.get("drawdown_reaction", "hold")).lower()
        delta_map = {
            "sell_all": 2.5,
            "sell_some": 1.2,
            "anxious": 0.3,
            "hold": -1.0,
            "buy_more": -2.2,
        }
        delta_drawdown = delta_map.get(reaction, 0.0)

        s_rt = float(data.get("risk_tolerance_score", 5.0))
        exp = str(data.get("investment_experience", "intermediate")).lower()
        exp_score_map = {"none": 2.0, "novice": 4.0, "intermediate": 6.5, "advanced": 8.5, "expert": 10.0}
        s_exp = exp_score_map.get(exp, 6.0)
        h = int(data.get("investment_horizon_years", 5))

        z = (
            -2.2
            + 3.8 * (emotional_risk / 100.0)
            - 1.0 * (s_rt / 10.0)
            - 1.0 * (s_exp / 10.0)
            - 0.6 * (min(h, 20) / 20.0)
            + delta_drawdown
        )
        p = 1.0 / (1.0 + math.exp(-z))
        return round(max(0.01, min(0.99, p)), 3)

    # ------------------------------------------------------------------
    # KYC & AML Typology Engine
    # ------------------------------------------------------------------

    def evaluate_compliance_kyc_aml(self, data: Dict[str, Any]) -> Tuple[bool, bool]:
        """
        Evaluates KYC verification and AML red flag typology rules.
        Returns (kyc_verified, aml_flag).
        """
        pep = bool(data.get("pep_status", False))
        high_risk_jur = bool(data.get("high_risk_jurisdiction", False))
        source_funds = str(data.get("source_of_funds", "salary")).lower()
        emp_status = str(data.get("employment_status", "")).lower()
        income = float(data.get("annual_income", 0.0) or 0.0)
        liquid = float(data.get("liquid_assets", 0.0) or 0.0)
        age = int(data.get("age", 0) or 0)

        # AML Typology Triggers
        aml_flag = False

        # AML-001: PEP status
        if pep:
            aml_flag = True

        # AML-002: High-risk jurisdiction
        if high_risk_jur:
            aml_flag = True

        # AML-003: Suspicious source of funds
        suspicious_sources = {"unspecified", "cash", "crypto_mixing", "anonymous_gift", "gambling", "crypto", "illicit"}
        if source_funds in suspicious_sources:
            aml_flag = True

        # AML-004: Income/Asset disproportionality anomaly
        if emp_status in {"unemployed", "student"} and income < 10000 and liquid > 500000:
            if source_funds not in {"inheritance", "family", "settlement"}:
                aml_flag = True

        # KYC Verification Rule
        legitimate_sources = {"salary", "business", "investments", "pension", "inheritance", "savings", "employment"}
        kyc_verified = (
            age >= 18
            and bool(emp_status)
            and income >= 0
            and source_funds in legitimate_sources
            and not aml_flag
        )

        return kyc_verified, aml_flag

    # ------------------------------------------------------------------
    # Public Execution Interfaces
    # ------------------------------------------------------------------

    async def process_input(
        self,
        session_id: str,
        user_message: str,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Process user message in the active profiling session.
        Advances FSM, extracts parameters, persists draft to cache,
        and executes synthesis when interview completes.
        """
        draft = await self._load_or_create_draft(session_id)
        current_state = draft["current_state"]

        # Append user turn to transcript history
        draft["conversation_history"].append({
            "role": "user",
            "content": user_message,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # Dual extraction: deterministic regex/heuristic first
        draft["extracted_data"] = self.extract_heuristic_data(user_message, draft["extracted_data"])

        # Check state transitions
        # We can advance through multiple states if the user provided info for multiple states
        state_idx = FSM_STATES.index(current_state) if current_state in FSM_STATES else 0

        # Attempt to transition forward as much as validly possible
        while state_idx < FSM_STATES.index(STATE_PROFILE_SYNTHESIS):
            this_state = FSM_STATES[state_idx]
            is_complete, prompt = self.validate_state_completion(this_state, draft["extracted_data"])
            
            # If heuristic extraction was incomplete, try model-based extraction fallback
            if not is_complete and self.openai_client:
                draft["extracted_data"] = await self._extract_with_model(user_message, this_state, draft["extracted_data"])
                is_complete, prompt = self.validate_state_completion(this_state, draft["extracted_data"])

            if is_complete:
                state_idx += 1
                current_state = FSM_STATES[state_idx]
                draft["current_state"] = current_state
            else:
                # Underage check check:
                if this_state == STATE_DEMOGRAPHICS and draft["extracted_data"].get("age", 18) < 18:
                    response_text = prompt
                    draft["conversation_history"].append({
                        "role": "assistant",
                        "content": response_text,
                        "timestamp": datetime.utcnow().isoformat(),
                    })
                    await self._save_draft(session_id, draft)
                    return {
                        "status": "in_progress",
                        "current_state": current_state,
                        "response": response_text,
                        "options": [],
                        "client_id": draft["client_id"],
                        "extracted_data": draft["extracted_data"],
                        "profile": None,
                    }

                # Missing info in this state -> prompt user and break
                response_text = prompt or STATE_PROMPTS.get(this_state, "Please provide more details.")
                opts = self.get_state_options(this_state, draft["extracted_data"])
                draft["conversation_history"].append({
                    "role": "assistant",
                    "content": response_text,
                    "options": opts,
                    "timestamp": datetime.utcnow().isoformat(),
                })
                await self._save_draft(session_id, draft)
                return {
                    "status": "in_progress",
                    "current_state": current_state,
                    "response": response_text,
                    "options": opts,
                    "client_id": draft["client_id"],
                    "extracted_data": draft["extracted_data"],
                    "profile": None,
                }

        # If reached PROFILE_SYNTHESIS
        if current_state == STATE_PROFILE_SYNTHESIS:
            ext = draft["extracted_data"]

            # Quantitative Scoring
            composite_score, suitability_cat = self.calculate_suitability_score(ext)
            emotional_score = self.calculate_emotional_risk_score(ext)
            panic_prob = self.calculate_panic_sell_likelihood(ext, emotional_score, composite_score)
            kyc_ok, aml_flag = self.evaluate_compliance_kyc_aml(ext)

            transcript_str = json.dumps(draft["conversation_history"])

            profile_data = {
                "client_id": draft["client_id"],
                "user_id": draft.get("user_id"),
                "age": ext.get("age", 35),
                "employment_status": ext.get("employment_status", "employed"),
                "dependents": ext.get("dependents", 0),
                "annual_income": float(ext.get("annual_income", 100000.0)),
                "net_worth": float(ext.get("net_worth", 300000.0)),
                "liquid_assets": float(ext.get("liquid_assets", 50000.0)),
                "monthly_expenses": float(ext.get("monthly_expenses", 4000.0)),
                "existing_debts": float(ext.get("existing_debts", 0.0)),
                "investment_experience": ext.get("investment_experience", "intermediate"),
                "risk_tolerance_score": float(ext.get("risk_tolerance_score", 5.0)),
                "investment_horizon_years": int(ext.get("investment_horizon_years", 10)),
                "liquidity_needs": ext.get("liquidity_needs", "medium"),
                "loss_capacity": ext.get("loss_capacity", "medium"),
                "primary_goal": ext.get("primary_goal", "growth"),
                "target_return": float(ext.get("target_return", 7.0)),
                "specific_goals": ext.get("specific_goals", []),
                "suitability_category": suitability_cat,
                "detected_biases": ext.get("detected_biases", []),
                "emotional_risk_score": emotional_score,
                "panic_sell_likelihood": panic_prob,
                "kyc_verified": kyc_ok,
                "aml_flag": aml_flag,
                "source_of_funds": ext.get("source_of_funds", "salary"),
                "drawdown_reaction": ext.get("drawdown_reaction", "hold"),
                "monitoring_frequency": ext.get("monitoring_frequency", "monthly"),
                "pep_status": bool(ext.get("pep_status", False)),
                "high_risk_jurisdiction": bool(ext.get("high_risk_jurisdiction", False)),
                "profiling_session_transcript": transcript_str,
            }

            # Persist to database if db is provided or via standalone session
            if db:
                await self.save_profile(db, draft["client_id"], profile_data)
            else:
                async with AsyncSessionLocal() as session:
                    await self.save_profile(session, draft["client_id"], profile_data)

            # Evict cache draft
            await self._evict_draft(session_id)
            draft["current_state"] = STATE_COMPLETE

            response_text = (
                f"Profile synthesis complete! Based on your responses, your suitability tier is "
                f"'{suitability_cat}' with an emotional risk score of {emotional_score}/100 and "
                f"panic sell likelihood of {panic_prob:.1%}. Your Client ID is {draft['client_id']}."
            )

            return {
                "status": "complete",
                "current_state": STATE_COMPLETE,
                "response": response_text,
                "client_id": draft["client_id"],
                "extracted_data": ext,
                "profile": profile_data,
            }

        return {
            "status": "in_progress",
            "current_state": current_state,
            "response": STATE_PROMPTS.get(current_state, "How can I assist you today?"),
            "client_id": draft["client_id"],
            "extracted_data": draft["extracted_data"],
            "profile": None,
        }

    async def get_profile(
        self,
        client_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[DBClientProfile]:
        """Fetch client profile from database by client_id."""
        if db:
            result = await db.execute(
                select(DBClientProfile).where(DBClientProfile.client_id == client_id)
            )
            return result.scalars().first()

        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(DBClientProfile).where(DBClientProfile.client_id == client_id)
            )
            return result.scalars().first()

    async def save_profile(
        self,
        db: AsyncSession,
        client_id: str,
        profile_data: Dict[str, Any],
    ) -> DBClientProfile:
        """Create or update DBClientProfile in database."""
        result = await db.execute(
            select(DBClientProfile).where(DBClientProfile.client_id == client_id)
        )
        existing = result.scalars().first()

        clean_data = {k: v for k, v in profile_data.items() if hasattr(DBClientProfile, k)}
        clean_data["client_id"] = client_id

        if existing:
            for k, v in clean_data.items():
                setattr(existing, k, v)
            await db.commit()
            await db.refresh(existing)
            return existing
        else:
            new_profile = DBClientProfile(**clean_data)
            db.add(new_profile)
            await db.commit()
            await db.refresh(new_profile)
            return new_profile

    async def process_conversation(
        self,
        conversation_history: List[Dict[str, str]],
        session_id: Optional[str] = None,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Backwards-compatible wrapper supporting the legacy main.py signature.
        Delegates to process_input using session_id or derives synthetic session.
        """
        if not conversation_history:
            return {"status": "in_progress", "response": STATE_PROMPTS[STATE_DEMOGRAPHICS]}

        sid = session_id or f"session_{id(conversation_history)}"
        last_user_message = ""
        for msg in reversed(conversation_history):
            if msg.get("role") == "user":
                last_user_message = msg.get("content", "")
                break

        return await self.process_input(sid, last_user_message, db=db)

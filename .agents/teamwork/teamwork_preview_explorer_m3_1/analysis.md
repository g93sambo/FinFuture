# Milestone 3 Architecture & Implementation Specification: Risk Profiler Agent

**Document**: `analysis.md`  
**Author**: Explorer 1 (Milestone 3: Core Agents - Risk Profiler)  
**Target Path**: `backend/agents/risk_profiler.py`  
**Related Models & Services**: `backend/db/models.py` (`DBClientProfile`), `backend/models/client_profile.py` (`ClientProfile`), `backend/services/cache.py` (`CacheService`)  
**Status**: COMPLETE SPECIFICATION  

---

## 1. Executive Summary

This specification defines the complete architectural design, mathematical scoring models, KYC/AML typology rules, session caching mechanics, database persistence logic, public interfaces, and test scenarios for the **Risk Profiler Agent** (`backend/agents/risk_profiler.py`).

The existing scaffold at `backend/agents/risk_profiler.py` consists of a basic 76-line OpenAI prompt loop that attempts single-turn extraction of 6 fields. It lacks state machine mechanics, session draft caching, quantitative scoring formulas, KYC/AML validation, database persistence, and resilience against offline/missing API keys.

The updated `RiskProfilerAgent` implements:
1. **6-State Finite State Machine (FSM)**: Sequentially guiding clients through `DEMOGRAPHICS` $\to$ `FINANCIAL_SITUATION` $\to$ `TIME_HORIZON` $\to$ `RISK_TOLERANCE` $\to$ `EXPERIENCE` $\to$ `PROFILE_SYNTHESIS`.
2. **Dual Extraction Architecture**: Deterministic regex/heuristic parser paired with OpenAI LLM extraction, guaranteeing 100% offline testability, zero token costs during CI, and high conversational adaptability.
3. **Session Draft Caching**: Redis-backed with in-memory TTL fallback via `services/cache.py` (`profile:draft:{session_id}`, 1-hour TTL `TTL_PROFILE_DRAFT`).
4. **Quantitative Scoring Engine**:
   - **Suitability Category**: Composite score $S \in [1.0, 10.0]$ mapped to 5 regulatory tiers (`Conservative`, `Moderate Conservative`, `Moderate`, `Growth`, `Aggressive Growth`) with prudential caps for short horizons and low loss capacity.
   - **Emotional Risk Score**: 0 to 100 scale measuring psychological vulnerability, panic susceptibility, and checking anxiety.
   - **Panic Sell Likelihood**: Calibrated logistic probability $P \in [0.0, 1.0]$ quantifying the likelihood of liquidating risk assets during an acute market drop ($\ge 20\%$).
5. **KYC & AML Assessment**: Multi-typology rule checks covering Politically Exposed Persons (PEP), FATF/OFAC high-risk jurisdictions, unverified fund sources, and disproportional income-to-asset anomalies.
6. **Transcript & Audit Preservation**: Preserving complete timestamped conversation transcripts and structured JSON summaries.
7. **Database Persistence**: Fully typed CRUD operations for `DBClientProfile` in PostgreSQL / SQLite.
8. **Public Interface**: Canonical `process_input(session_id, user_message)`, `get_profile(client_id, db)`, and `save_profile(db, client_id, profile_data)` with backwards-compatible `process_conversation(history)`.

---

## 2. Codebase Baseline & Field Inventory

### 2.1 Database Model (`DBClientProfile` in `backend/db/models.py`)
Table `client_profiles` contains 25 active columns + 2 synonyms:

| Category | Column | Type | Nullable | Default | Description |
|---|---|---|---|---|---|
| **Identity** | `client_id` | String(64) | False (PK) | uuid4 | Primary unique identifier |
| | `user_id` | String(64) | True (FK) | None | Associated user in `users` table |
| **Demographics** | `age` | Integer | True | None | Client age (18 - 120) |
| | `employment_status` | String | True | None | Employed, self-employed, retired, etc. |
| | `dependents` | Integer | True | 0 | Number of financial dependents |
| **Financial Situation** | `annual_income` | Float | True | None | Gross annual income in USD |
| | `net_worth` | Float | True | None | Total assets minus liabilities |
| | `liquid_assets` | Float | True | 0.0 | Cash, savings, money market funds |
| | `monthly_expenses` | Float | True | 0.0 | Living expenses per month |
| | `existing_debts` | Float | True | 0.0 | Outstanding debt obligations |
| **Parameters & Horizon** | `investment_experience` | String | True | None | none, novice, intermediate, advanced, expert |
| | `risk_tolerance_score` | Float | True | None | 1.0 to 10.0 scale |
| | `investment_horizon_years`| Integer | True | None | Investment horizon in years |
| | `liquidity_needs` | String | True | None | low, medium, high |
| | `loss_capacity` | String | True | None | low, medium, high |
| | `primary_goal` | String | True | None | capital_preservation, income, growth, etc. |
| | `target_return` | Float | True | None | Target annual return percentage (e.g. 7.5%) |
| | `specific_goals` | JSON | True | `[]` | Specific milestones (e.g. retirement, college) |
| **Synthesis & Psychology**| `suitability_category` | String | True | None | Conservative to Aggressive Growth |
| | `detected_biases` | JSON | True | `[]` | Detected behavioral biases (e.g. loss_aversion) |
| | `emotional_risk_score` | Float | True | 0.0 | 0 to 100 psychological risk index |
| | `panic_sell_likelihood` | Float | True | 0.0 | 0.0 to 1.0 probability |
| | `profiling_session_transcript` | Text | True | `""` | Chronological session dialogue record |
| **Compliance & Flags** | `kyc_verified` | Boolean | True | False | True if KYC criteria satisfied |
| | `aml_flag` | Boolean | True | False | True if AML red flags triggered |
| **Timestamps** | `created_at` | DateTime | False | utcnow | Record creation timestamp |
| | `updated_at` | DateTime | False | utcnow | Record update timestamp |

### 2.2 Cache Service (`backend/services/cache.py`)
`CacheService` provides:
- Key formatter: `key_profile_draft(session_id: str) -> str` $\to$ `"profile:draft:{session_id}"`
- TTL constant: `TTL_PROFILE_DRAFT = 3600` (1 hour)
- Methods: `get_json(key)`, `set_json(key, value, expire=TTL_PROFILE_DRAFT)`, `delete(key)`
- Resilient in-memory fallback: transparently operates when Redis is unavailable.

---

## 3. Finite State Machine (FSM) Architecture

### 3.1 State Diagram & Transition Flow

```
                      ┌────────────────────────┐
                      │      DEMOGRAPHICS      │
                      └───────────┬────────────┘
                                  │ age, employment, dependents collected
                                  ▼
                      ┌────────────────────────┐
                      │  FINANCIAL_SITUATION   │
                      └───────────┬────────────┘
                                  │ income, net worth, liquids, expenses, debts
                                  ▼
                      ┌────────────────────────┐
                      │      TIME_HORIZON      │
                      └───────────┬────────────┘
                                  │ horizon years, liquidity needs, primary goal
                                  ▼
                      ┌────────────────────────┐
                      │     RISK_TOLERANCE     │
                      └───────────┬────────────┘
                                  │ risk score (1-10), loss capacity, drawdown reaction
                                  ▼
                      ┌────────────────────────┐
                      │       EXPERIENCE       │
                      └───────────┬────────────┘
                                  │ experience level, source of funds, PEP, jurisdiction
                                  ▼
                      ┌────────────────────────┐
                      │   PROFILE_SYNTHESIS    │
                      └───────────┬────────────┘
                                  │ quantitative scoring, KYC/AML validation, DB save
                                  ▼
                      ┌────────────────────────┐
                      │        COMPLETE        │ (Terminal / Ready for Orchestrator)
                      └────────────────────────┘
```

### 3.2 State Definitions, Requirements, and Prompts

#### State 1: `DEMOGRAPHICS`
- **Objective**: Establish client age, employment background, and family dependency obligations.
- **Mandatory Fields**: `age` (int), `employment_status` (str).
- **Optional/Derived Fields**: `dependents` (int, default 0).
- **Validation Rules**:
  - $18 \le \text{age} \le 120$. If $\text{age} < 18$, return rejection: *"Clients must be at least 18 years old to open an advisory account."*
  - `employment_status` must normalize to: `"employed"`, `"self-employed"`, `"retired"`, `"student"`, `"unemployed"`, `"other"`.
  - `dependents` $\ge 0$.
- **Standard Advisor Prompt**:
  > *"Welcome to your AI Wealth Advisory consultation! To tailor our advice, let's start with a few basics: How old are you, what is your current employment status, and do you have any dependents?"*
- **Transition Condition**: `age` and `employment_status` are present and valid $\to$ transition to `FINANCIAL_SITUATION`.

#### State 2: `FINANCIAL_SITUATION`
- **Objective**: Establish the client's financial capacity, balance sheet, and income statement.
- **Mandatory Fields**: `annual_income` (float), `liquid_assets` (float).
- **Optional/Derived Fields**: `net_worth` (float), `monthly_expenses` (float), `existing_debts` (float).
- **Validation Rules**:
  - `annual_income` $\ge 0.0$, `liquid_assets` $\ge 0.0$, `monthly_expenses` $\ge 0.0$, `existing_debts` $\ge 0.0$.
  - If `net_worth` is omitted, estimate: $\text{net\_worth} = \max(\text{liquid\_assets} - \text{existing\_debts}, 0.0)$.
- **Standard Advisor Prompt**:
  > *"Thank you. Next, let's look at your financial foundation: What is your approximate annual income, how much do you hold in liquid savings, and what are your typical monthly expenses and outstanding debts?"*
- **Transition Condition**: `annual_income` and `liquid_assets` populated $\to$ transition to `TIME_HORIZON`.

#### State 3: `TIME_HORIZON`
- **Objective**: Determine investment horizon, liquidity timeline, and primary financial goals.
- **Mandatory Fields**: `investment_horizon_years` (int), `primary_goal` (str).
- **Optional/Derived Fields**: `liquidity_needs` (str), `target_return` (float), `specific_goals` (list of str).
- **Validation Rules**:
  - $\text{investment\_horizon\_years} \ge 1$.
  - `primary_goal` normalized to: `"capital_preservation"`, `"income"`, `"balanced"`, `"growth"`, `"wealth_accumulation"`, `"aggressive_growth"`.
  - `liquidity_needs`: `"low"`, `"medium"`, `"high"`. If unstated, inferred from horizon (e.g. horizon $\le 3$ years $\to$ "high", $4-9$ years $\to$ "medium", $\ge 10$ years $\to$ "low").
- **Standard Advisor Prompt**:
  > *"Great. What is your intended investment time horizon (in years), and what is your primary objective (e.g., capital preservation, balanced income, long-term wealth growth, or retirement)?"*
- **Transition Condition**: `investment_horizon_years` and `primary_goal` populated $\to$ transition to `RISK_TOLERANCE`.

#### State 4: `RISK_TOLERANCE`
- **Objective**: Gauge psychological risk tolerance, willingness to take risk, capacity for loss, and panic behavior under market stress.
- **Mandatory Fields**: `risk_tolerance_score` (float $1.0 - 10.0$), `loss_capacity` (str), `drawdown_reaction` (str).
- **Validation Rules**:
  - $1.0 \le \text{risk\_tolerance\_score} \le 10.0$.
  - `loss_capacity` normalized to: `"low"`, `"medium"`, `"high"`.
  - `drawdown_reaction`: `"sell_all"`, `"sell_some"`, `"anxious"`, `"hold"`, `"buy_more"`.
- **Standard Advisor Prompt**:
  > *"How would you rate your risk tolerance on a scale of 1 to 10? Also, if your portfolio dropped 20% during a severe market correction, would you sell your investments, hold steady, or buy more at discounted prices?"*
- **Transition Condition**: `risk_tolerance_score` populated $\to$ transition to `EXPERIENCE`.

#### State 5: `EXPERIENCE`
- **Objective**: Assess investment sophistication, past product familiarity, and perform KYC/AML preliminary screening.
- **Mandatory Fields**: `investment_experience` (str), `source_of_funds` (str), `pep_status` (bool), `high_risk_jurisdiction` (bool).
- **Validation Rules**:
  - `investment_experience` normalized to: `"none"`, `"novice"`, `"intermediate"`, `"advanced"`, `"expert"`.
  - `source_of_funds`: string description (e.g. `"salary"`, `"business"`, `"investments"`, `"inheritance"`, `"unspecified"`).
  - `pep_status`: boolean (True if client or immediate family is a Politically Exposed Person).
  - `high_risk_jurisdiction`: boolean (True if resident/national of sanctioned or FATF blacklist country).
- **Standard Advisor Prompt**:
  > *"Lastly, how would you describe your investment experience (e.g. none, novice, intermediate, advanced)? For regulatory compliance, what is the primary source of your investment funds (e.g. salary, business), and are you or an immediate family member a Politically Exposed Person (PEP)?"*
- **Transition Condition**: `investment_experience` and basic KYC/AML parameters populated $\to$ transition to `PROFILE_SYNTHESIS`.

#### State 6: `PROFILE_SYNTHESIS`
- **Objective**: Execute quantitative scoring engines, assess KYC/AML rules, assemble complete profile data, format audit transcript, persist to database, delete session draft cache, and return synthesized profile.
- **Actions**:
  1. Calculate `suitability_category` (with regulatory guardrail caps).
  2. Calculate `emotional_risk_score` ($0 - 100$).
  3. Calculate `panic_sell_likelihood` ($0.0 - 1.0$).
  4. Perform KYC status verification (`kyc_verified`) and AML red flag checks (`aml_flag`).
  5. Assemble complete profile dict conforming to `DBClientProfile` / `ClientProfile`.
  6. Serialize session transcript into `profiling_session_transcript`.
  7. Persist to database (`DBClientProfile`).
  8. Evict draft from `CacheService`.
  9. Transition to `COMPLETE`.

---

## 4. Quantitative Scoring Engine Design

### 4.1 Suitability Category Formulation
In accordance with FINRA Rule 2111 (Suitability) and SEC Regulation Best Interest (Reg BI), the client's suitability category must balance their subjective willingness to bear risk with objective loss capacity and time horizon.

#### Component Scores (All normalized to $1.0 - 10.0$ scale):
1. **Risk Tolerance Score ($S_{rt}$)**: Direct value from State 4 ($1.0 \le S_{rt} \le 10.0$).
2. **Horizon Score ($S_h$)**:
   $$\begin{cases}
   2.0, & \text{if } H < 2 \\
   4.0, & \text{if } 2 \le H < 5 \\
   6.5, & \text{if } 5 \le H < 10 \\
   8.5, & \text{if } 10 \le H < 20 \\
   10.0, & \text{if } H \ge 20
   \end{cases}$$
3. **Loss Capacity Score ($S_{lc}$)**:
   $$\begin{cases}
   2.5, & \text{if } LC = \text{"low"} \\
   6.0, & \text{if } LC = \text{"medium"} \\
   9.0, & \text{if } LC = \text{"high"}
   \end{cases}$$
   *Emergency Reserve Floor*: If monthly expenses $M > 0$ and liquid assets $L / M < 3.0$, override $S_{lc} = \min(S_{lc}, 3.0)$.
4. **Primary Goal Score ($S_g$)**:
   $$\begin{cases}
   2.0, & \text{if } G \in \{\text{"capital\_preservation"}\} \\
   4.0, & \text{if } G \in \{\text{"income"}\} \\
   5.5, & \text{if } G \in \{\text{"balanced"}\} \\
   8.0, & \text{if } G \in \{\text{"growth"}, \text{"wealth\_accumulation"}\} \\
   10.0, & \text{if } G \in \{\text{"aggressive\_growth"}, \text{"speculation"}\} \\
   6.0, & \text{otherwise}
   \end{cases}$$
5. **Experience Score ($S_{exp}$)**:
   $$\begin{cases}
   2.0, & \text{if } EXP = \text{"none"} \\
   4.0, & \text{if } EXP = \text{"novice"} \\
   6.5, & \text{if } EXP = \text{"intermediate"} \\
   8.5, & \text{if } EXP = \text{"advanced"} \\
   10.0, & \text{if } EXP = \text{"expert"}
   \end{cases}$$

#### Composite Score Formula:
$$S_{\text{raw}} = 0.35 \cdot S_{rt} + 0.25 \cdot S_{lc} + 0.20 \cdot S_h + 0.10 \cdot S_g + 0.10 \cdot S_{exp}$$

#### Prudential Regulatory Guardrails:
1. **Short Horizon Guard**: If $H < 3$ years, the investor cannot sustain equity drawdown cycles:
   $$S = \min(S_{\text{raw}}, 4.0)$$
2. **Low Loss Capacity Guard**: If $LC = \text{"low"}$ or $L / \max(M, 1.0) < 3.0$:
   $$S = \min(S, 5.0)$$
3. **Inexperience Guard**: If $EXP = \text{"none"}$ and $S_{rt} > 7.0$:
   $$S = \min(S, 6.5)$$

#### Category Mapping:
| Composite Score $S$ | Suitability Category | Permitted Asset Mix |
|---|---|---|
| $1.0 \le S < 3.0$ | **Conservative** | 10-20% Equities / 80-90% Bonds & Cash |
| $3.0 \le S < 5.0$ | **Moderate Conservative** | 30-40% Equities / 60-70% Bonds |
| $5.0 \le S < 7.0$ | **Moderate** | 50-65% Equities / 35-50% Bonds |
| $7.0 \le S < 8.5$ | **Growth** | 70-85% Equities / 15-30% Bonds |
| $8.5 \le S \le 10.0$ | **Aggressive Growth** | 90-100% Equities / 0-10% Cash/Alt |

---

### 4.2 Emotional Risk Score ($0 - 100$ Scale)
Measures psychological vulnerability to market turbulence, behavioral irrationality, and anxiety.

$$E = 0.40 \cdot E_{\text{drawdown}} + 0.20 \cdot E_{\text{frequency}} + 0.20 \cdot E_{\text{biases}} + 0.20 \cdot E_{\text{stress}}$$

Where:
- **Drawdown Vulnerability ($E_{\text{drawdown}}$)**:
  * `"sell_all"` $\to 100.0$
  * `"sell_some"` $\to 75.0$
  * `"anxious"` $\to 50.0$
  * `"hold"` $\to 20.0$
  * `"buy_more"` $\to 5.0$
- **Monitoring Frequency ($E_{\text{frequency}}$)**:
  * Multiple times daily $\to 90.0$
  * Daily $\to 70.0$
  * Weekly $\to 40.0$
  * Monthly $\to 20.0$
  * Annually $\to 5.0$
  * Default/Unstated $\to 40.0$
- **Detected Behavioral Biases ($E_{\text{biases}}$)**:
  $$\text{bias\_score} = \sum_{b \in \text{biases}} w_b \quad \text{where } w_{\text{loss\_aversion}} = 35, w_{\text{recency\_bias}} = 25, w_{\text{herding}} = 20, w_{\text{overconfidence}} = 15$$
  $$E_{\text{biases}} = \min(100.0, \text{bias\_score})$$
- **Financial Stress Buffer ($E_{\text{stress}}$)**:
  * Debt-to-income $> 0.5$ or liquid reserves $< 2$ months $\to 85.0$
  * Debt-to-income $0.2 - 0.5$ or reserves $3 - 6$ months $\to 45.0$
  * Debt-to-income $< 0.2$ and reserves $> 6$ months $\to 10.0$

$E$ is clamped between $0.0$ and $100.0$, rounded to 1 decimal place.

---

### 4.3 Panic Sell Likelihood ($0.0 - 1.0$ Probability)
Calibrated statistical model computing $P(\text{panic sell} \mid \text{market dip} \ge 20\%)$:

$$z = -2.2 + 3.8 \cdot \left(\frac{E}{100.0}\right) - 1.0 \cdot \left(\frac{S_{rt}}{10.0}\right) - 1.0 \cdot \left(\frac{S_{exp}}{10.0}\right) - 0.6 \cdot \left(\frac{\min(H, 20)}{20.0}\right) + \Delta_{\text{drawdown}}$$

Where drawdown adjustment $\Delta_{\text{drawdown}}$:
- `"sell_all"`: $+2.5$
- `"sell_some"`: $+1.2$
- `"anxious"`: $+0.3$
- `"hold"`: $-1.0$
- `"buy_more"`: $-2.2$

The logistic probability:
$$P = \frac{1}{1 + e^{-z}}$$
Clamped strictly to $[0.01, 0.99]$, rounded to 3 decimal places.

---

### 4.4 KYC Status & AML Flag Typology Rules

#### AML Red Flag Triggers (`aml_flag: bool`):
`aml_flag` is set to `True` if **ANY** of the following 4 typology triggers evaluate to True:
1. **AML-001 (PEP Without Clearance)**:
   `pep_status == True` without verified enhanced due diligence.
2. **AML-002 (Sanctioned / High-Risk Jurisdictions)**:
   `high_risk_jurisdiction == True` or residence in OFAC/FATF blacklist regimes (e.g. North Korea, Iran, Syria, Russia).
3. **AML-003 (Suspicious Source of Wealth)**:
   `source_of_funds` belongs to suspicious categories: `{"unspecified", "cash", "crypto_mixing", "anonymous_gift", "gambling"}`.
4. **AML-004 (Income/Asset Disproportionality Anomaly)**:
   `employment_status in {"unemployed", "student"}` and `annual_income < 10000` while `liquid_assets > 500000` with no declared inheritance or business exit.

#### KYC Verification Rule (`kyc_verified: bool`):
`kyc_verified` is set to `True` if **ALL** of the following conditions are met:
1. `age >= 18` and valid.
2. `employment_status` is documented and non-empty.
3. `annual_income` is documented and non-negative.
4. `source_of_funds` is legitimate (e.g. `"salary"`, `"business"`, `"investments"`, `"pension"`, `"inheritance"`).
5. `aml_flag == False` (zero AML red flags).
Otherwise, `kyc_verified` is `False`.

---

## 5. Draft Session State Caching Specification

### 5.1 Storage Lifecycle
- **Cache Key**: `profile:draft:{session_id}` (generated via `services.cache.key_profile_draft(session_id)`)
- **TTL**: `TTL_PROFILE_DRAFT = 3600` (1 hour)
- **Engine**: Redis with automatic in-memory fallback via `CacheService`.

### 5.2 JSON Payload Schema
```json
{
  "session_id": "9a373ef1-f0ce-404c-8c1f-a3b98412fc79",
  "client_id": "c7a8b9d0-1234-5678-90ab-cdef12345678",
  "user_id": null,
  "current_state": "DEMOGRAPHICS",
  "extracted_data": {
    "age": 35,
    "employment_status": "employed",
    "dependents": 1,
    "annual_income": 150000.0,
    "liquid_assets": 75000.0,
    "net_worth": 450000.0,
    "monthly_expenses": 5000.0,
    "existing_debts": 12000.0,
    "investment_horizon_years": 15,
    "liquidity_needs": "medium",
    "primary_goal": "growth",
    "target_return": 8.0,
    "specific_goals": ["retirement"],
    "risk_tolerance_score": 7.0,
    "loss_capacity": "medium",
    "drawdown_reaction": "buy_more",
    "investment_experience": "intermediate",
    "source_of_funds": "salary",
    "pep_status": false,
    "high_risk_jurisdiction": false
  },
  "conversation_history": [
    {"role": "assistant", "content": "Welcome..."},
    {"role": "user", "content": "I am 35 years old..."}
  ],
  "started_at": "2026-10-10T16:00:00Z",
  "last_updated": "2026-10-10T16:05:00Z"
}
```

### 5.3 Cache Invalidation
Upon successful transition to `PROFILE_SYNTHESIS` and database commit:
```python
await self.cache.delete(key_profile_draft(session_id))
```

---

## 6. Public Interfaces and Method Signatures

```python
class RiskProfilerAgent:
    """
    State-machine driven conversational risk profiler agent with quantitative
    scoring, KYC/AML validation, draft session caching, and database persistence.
    """

    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        openai_client: Optional[AsyncOpenAI] = None,
    ) -> None:
        ...

    async def process_input(
        self,
        session_id: str,
        user_message: str,
        db: Optional[AsyncSession] = None,
    ) -> Dict[str, Any]:
        """
        Process user message in the context of the active session.
        Advances FSM state, extracts parameters, persists draft to cache,
        and triggers profile synthesis when questionnaire completes.

        Returns:
            {
                "status": "in_progress" | "complete" | "error",
                "current_state": str,
                "response": str,
                "client_id": Optional[str],
                "extracted_data": dict,
                "profile": Optional[dict]
            }
        """
        ...

    async def get_profile(
        self,
        client_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[DBClientProfile]:
        """
        Fetch client profile from database by client_id.
        If db session is passed, uses it directly; otherwise opens a standalone session.
        """
        ...

    async def save_profile(
        self,
        db: AsyncSession,
        client_id: str,
        profile_data: Dict[str, Any],
    ) -> DBClientProfile:
        """
        Create or update DBClientProfile in database.
        Returns the saved ORM model instance.
        """
        ...

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
        ...
```

---

## 7. Deterministic Extraction & Offline Fallback Engine

To guarantee that unit tests run fast, offline, and deterministically without requiring live OpenAI API keys or incurring token charges, `RiskProfilerAgent` implements a regex/heuristic extractor that handles each state's inputs:

### Heuristic Extraction Patterns:
- **Age**: `\b(?:age\s*(?:is|:)?\s*|i am\s*|i'm\s*)?(\d{2})\b` $\to$ validate $18 \le \text{age} \le 120$.
- **Employment**: Keywords: `employed`, `software`, `engineer`, `doctor`, `teacher`, `manager` $\to$ `"employed"`; `self-employed`, `freelance`, `business owner` $\to$ `"self-employed"`; `retired` $\to$ `"retired"`; `student` $\to$ `"student"`; `unemployed` $\to$ `"unemployed"`.
- **Dependents**: `(\d+)\s*(?:dependents?|kids?|children)` or `no dependents|none` $\to$ `0`.
- **Income & Currency**: `(?:income|earn|make|salary)\s*(?:is|of|around|about|:)?\s*\$?([\d,]+)(k|m)?` $\to$ normalize multipliers ($k = \times 10^3, m = \times 10^6$).
- **Savings / Liquid Assets**: `(?:savings|liquid|cash)\s*(?:is|of|around|about|:)?\s*\$?([\d,]+)(k|m)?`.
- **Horizon**: `(\d+)\s*(?:years?|yrs?)\s*(?:horizon|timeline|period)?`.
- **Risk Score**: `(?:risk\s*(?:score|tolerance)?\s*(?:is|of|:)?\s*|rated?\s*)?(\d+(?:\.\d+)?)\s*(?:out of 10|\/10)?`.
- **Drawdown Reaction**: Matches for `sell all|sell everything` $\to$ `"sell_all"`; `sell some|reduce` $\to$ `"sell_some"`; `anxious|nervous|worry` $\to$ `"anxious"`; `hold|stay the course` $\to$ `"hold"`; `buy more|discount|bargain` $\to$ `"buy_more"`.
- **Experience**: Matches for `none|beginner|novice|intermediate|advanced|expert`.
- **KYC/PEP**: Matches for `not a pep|no pep|not politically exposed` $\to$ `pep_status = False`; `i am a pep|politically exposed` $\to$ `pep_status = True`.

When an OpenAI client is configured and available, it is invoked for nuanced contextual clarification, but falls back gracefully to heuristic parsing if the API fails or is unconfigured.

---

## 8. Unit Test Suite Specification (`tests/unit/test_risk_profiler.py`)

A comprehensive test suite covering $\ge 20$ test cases across 8 functional areas must be implemented:

### Scenario Matrix:
1. `test_fsm_initial_state_demographics`: Session starts in `DEMOGRAPHICS` with initial welcome prompt.
2. `test_fsm_demographics_transition`: Valid age and employment advances state to `FINANCIAL_SITUATION`.
3. `test_fsm_financial_situation_transition`: Valid income and liquid assets advances state to `TIME_HORIZON`.
4. `test_fsm_time_horizon_transition`: Valid horizon and goal advances state to `RISK_TOLERANCE`.
5. `test_fsm_risk_tolerance_transition`: Valid risk tolerance score advances state to `EXPERIENCE`.
6. `test_fsm_experience_to_synthesis_transition`: Valid experience and KYC answers advances state to `PROFILE_SYNTHESIS` $\to$ `complete`.
7. `test_fsm_incomplete_input_stays_in_state`: If user only states age without employment, agent prompts for missing field and remains in `DEMOGRAPHICS`.
8. `test_fsm_multi_field_extraction`: User providing age, employment, and income in a single turn populates all fields across states.
9. `test_fsm_underage_rejection`: Age $< 18$ triggers polite rejection and remains in `DEMOGRAPHICS`.
10. `test_cache_draft_persistence_and_resume`: Mid-interview draft is stored in `CacheService` under `profile:draft:{session_id}`; a resumed session reads existing draft.
11. `test_cache_draft_eviction_on_completion`: Completed profile causes `key_profile_draft` to be deleted from cache.
12. `test_scoring_suitability_mapping`:
    - Horizon 1y, low loss capacity, risk 2.0 $\to$ `"Conservative"`
    - Horizon 3y, medium loss capacity, risk 4.0 $\to$ `"Moderate Conservative"`
    - Horizon 7y, medium loss capacity, risk 6.0 $\to$ `"Moderate"`
    - Horizon 15y, high loss capacity, risk 7.5 $\to$ `"Growth"`
    - Horizon 25y, high loss capacity, risk 9.5 $\to$ `"Aggressive Growth"`
13. `test_scoring_suitability_regulatory_guardrails`:
    - Aggressive score (9.0) with low loss capacity is capped at `"Moderate"`.
    - Long-term growth investor with horizon $< 2$ years is capped at `"Moderate Conservative"`.
14. `test_scoring_emotional_risk_score`:
    - Stoic client ("buy_more", checks annually, no biases) $\to E < 25$.
    - Panicky client ("sell_all", checks multiple times daily, loss aversion) $\to E > 75$.
15. `test_scoring_panic_sell_likelihood`:
    - Panicky client $\to P > 0.80$.
    - Disciplined client $\to P < 0.05$.
    - Bounds test: $0.0 \le P \le 1.0$.
16. `test_kyc_aml_standard_pass`: Salary source, non-PEP, standard jurisdiction $\to$ `kyc_verified = True`, `aml_flag = False`.
17. `test_kyc_aml_pep_flag`: PEP client $\to$ `aml_flag = True`, `kyc_verified = False`.
18. `test_kyc_aml_high_risk_jurisdiction`: High-risk jurisdiction client $\to$ `aml_flag = True`, `kyc_verified = False`.
19. `test_kyc_aml_suspicious_funds`: Anonymous or crypto mixing funds $\to$ `aml_flag = True`, `kyc_verified = False`.
20. `test_db_save_profile_new_and_update`: `save_profile` creates a new profile in SQLite/Postgres and updates an existing profile without ID collision.
21. `test_db_get_profile`: `get_profile` retrieves profile by `client_id` with and without an explicit `db` session argument.
22. `test_transcript_preservation`: Transcript includes all user and assistant turns with timestamps and synthesis summary.
23. `test_legacy_process_conversation_compatibility`: `process_conversation(history)` works seamlessly with legacy `main.py` callers.

---

## 9. Downstream Milestone Integration

1. **Milestone 3 Peer Agents**:
   - `BehavioralBiasAgent`: Supplies detected biases to `detected_biases` in profile synthesis.
   - `ProductComparisonAgent`: Reads `suitability_category` and `loss_capacity` as pre-filters for ETF/bond recommendations.
   - `AllocationEngine`: Reads `risk_tolerance_score`, `investment_horizon_years`, and `liquidity_needs` as skfolio optimization constraints.
2. **Milestone 4 Compliance & Execution**:
   - `ComplianceGuard`: Validates all proposed allocations against `suitability_category` (`SUIT-001`) and checks `kyc_verified == True` (`AML-001`).
   - `ExecutionModule`: Hard blocks trade submission if `client.kyc_verified != True`.
3. **Milestone 5 Orchestration & WebSocket API**:
   - `/ws/chat`: Routes first-time users through `process_input` until `status == "complete"`, streaming the resulting `client_id` to the client.

# Architecture & Implementation Analysis: Behavioral Bias Agent

**Milestone**: M3 (Core Agents: Behavioral Bias)  
**Agent Role**: Explorer 2 (`teamwork_preview_explorer_m3_2`)  
**Target File**: `backend/agents/behavioral_bias.py`  
**Database Model**: `backend/db/models.py` (`DBBehavioralMemory`, `DBClientProfile`)  
**Timestamp**: 2026-10-10T16:42:00Z  

---

## 1. Executive Summary & Problem Boundary

In wealth advisory and quantitative wealth management, emotional cognitive biases (such as panic selling during market drawdowns, overconfidence, FOMO herding, and disposition effect) represent one of the primary drivers of retail portfolio underperformance and elevated drawdown risk.

Per the master project requirements (`ORIGINAL_REQUEST.md` and `PROJECT.md`), the `BehavioralBiasAgent` must provide:
1. **Dual-Layer Bias Detection**:
   - **Layer 1 (Heuristic Engine)**: Fast, deterministic regex pattern scoring with a calibrated threshold ($\ge 0.60$) detecting five major cognitive biases: *Loss Aversion*, *Recency Bias*, *Overconfidence*, *Herd Mentality (Herding)*, and *Disposition Effect*.
   - **Layer 2 (LLM Contextual Confirmation)**: Advanced cognitive evaluation using an LLM (e.g., `gpt-4o`) when online and configured, with a **robust deterministic fallback** to Layer 1 heuristics when the LLM is offline, unconfigured (`OPENAI_API_KEY` is None/empty), or encounters API/network errors.
2. **Behavioral Telemetry Signals**:
   - Continuous operational detection of behavioral signals from investor activity:
     - **Check Frequency Tracking**: Detects rapid portfolio refreshes/checks ($\ge 3$ checks in 10 minutes) as an anxiety and loss aversion indicator.
     - **Panic Dip Selling Detection**: Detects sell orders placed after sharp asset or market drawdowns ($\le -3\%$ in 24h), recommending a cool-off window.
     - **Concentration Bias Detection**: Detects excessive single-asset concentration ($> 25\%$ or $> 40\%$ of total portfolio value) reflecting overconfidence and lack of diversification.
     - **Excessive Trading Frequency**: Detects short-term day-trading churn ($\ge 5$ trades in 24h) reflecting overconfidence and market timing speculation.
3. **Database Persistence**:
   - Complete asynchronous persistence to the `behavioral_memory` table (`DBBehavioralMemory`), recording `client_id`, `bias_type`, `severity`, `trigger_context`, `intervention_text`, and `timestamp`.
   - Dynamic updating of `DBClientProfile`: synchronizing `detected_biases` array, recalibrating `emotional_risk_score` (0-100 scale), and elevating `panic_sell_likelihood` (0.0-1.0 probability).
4. **Tailored Interventions**:
   - Research-grounded educational reframing (anchoring on long-term base rates, expected utility, tax-loss harvesting, and mean reversion).
   - Actionable cool-off periods (e.g., 24-hour reflection windows before volatile liquidations).
5. **Deterministic Offline Scenario Fixtures**:
   - A suite of 12 calibrated scenario fixtures covering all bias types, boundary cases, and neutral inquiries, running 100% offline without network calls or external API keys.

---

## 2. Dual-Layer Bias Detection Specification

### 2.1 The Five Target Cognitive Biases

| Bias Identifier | Psychological Definition | Dialogue & Behavioral Symptoms | Target Reframing / Intervention |
|---|---|---|---|
| `loss_aversion` | Asymmetric pain from financial losses vs gains (Kahneman & Tversky Prospect Theory). Extreme reluctance to absorb paper fluctuations. | *"Can't afford to lose"*, *"sell everything"*, *"liquidate to cash"*, panic selling during dips, rapid portfolio checking. | Reframe to multi-year compound horizon, highlight cash buffer safety, propose 24h cooling-off window. |
| `recency_bias` | Overweighting recent market performance or macro events; extrapolating short-term momentum indefinitely into the future. | *"Market only goes up"*, *"it's been dropping every day so it will keep falling"*, *"past week proves it"*. | Illustrate historical mean reversion, show cyclical asset rotation, review 10-year rolling asset returns. |
| `overconfidence` | Overestimating private predictive accuracy or skill; dismissing market efficiency, risk metrics, or diversification. | *"I'm 100% sure"*, *"can't go wrong"*, *"easy 10x"*, *"diversification is for idiots"*, single-stock concentration. | Demonstrate single-stock failure statistics, explain uncompensated idiosyncratic risk, quantify risk-adjusted returns. |
| `herd_mentality` (or `herding`) | Mimicking crowd, social media, or peer behavior without independent financial analysis; acute FOMO. | *"Everyone on Reddit/TikTok is buying"*, *"all my friends are in"*, *"don't want to miss the boat"*. | Highlight contrarian valuation risks, remind that sentiment peaks at market tops, anchor on personal financial goals. |
| `disposition_effect` | Selling winning investments prematurely to lock in small paper gains, while obstinately holding losing positions hoping to break even. | *"Sell winners to lock in profit"*, *"refuse to sell losers at a loss"*, *"hold until it gets back to even"*. | Explain opportunity cost of holding declining assets, tax-loss harvesting benefits, dismantle sunk-cost fallacy. |

---

### 2.2 Layer 1: Heuristic Keyword & Regex Pattern Scoring Engine

#### Pattern Catalog & Calibration
All text is normalized: lowercased, whitespace collapsed, and curly apostrophes normalized to standard ASCII (`’` $\to$ `'`).  
Each bias has a curated set of regular expressions with calibrated weights ($w_i \in [0.40, 0.85]$).

```python
# Regex catalog with calibrated weights
HEURISTIC_PATTERNS = {
    "loss_aversion": [
        # Panic exit actions
        (r"\b(sell|dump|liquidate|pull\s*out)\s+(everything|all\s+(my\s+)?(stocks|holdings|positions|shares|money))\b", 0.80),
        (r"\b(put|keep|move)\s+(everything|it\s+all|my\s+money)\s+(in|into|to)\s+cash\b", 0.75),
        # Severe loss fear
        (r"\b(can'?t|cannot)\s+afford\s+to\s+lose\b", 0.65),
        (r"\b(scared|terrified|fearful|worried|dreading)\s+(of\s+losing|about\s+losses|of\s+a\s+crash)\b", 0.65),
        (r"\b(hate|despise)\s+losing\s+money\b", 0.55),
        (r"\b(stop\s+the\s+bleeding|cut\s+all\s+(my\s+)?losses)\b", 0.60),
        # Crash / Zero catastrophe
        (r"\b(market\s+is\s+crashing|going\s+to\s+zero|lose\s+all\s+(my\s+)?savings|wiped?\s*out)\b", 0.60),
        (r"\b(can'?t\s+take\s+the\s+pain|losing\s+sleep)\b", 0.60),
    ],
    "recency_bias": [
        # Upward extrapolation
        (r"\b(only\s+goes\s+up|going\s+up\s+every\s+day|will\s+never\s+drop)\b", 0.75),
        (r"\b(can'?t\s+fail\s+right\s+now|unstoppable\s+momentum|guaranteed\s+rally)\b", 0.70),
        (r"\b(doubled\s+last\s+(week|month)|soaring\s+recently)\b", 0.60),
        # Downward extrapolation
        (r"\b(dropping\s+every\s+day|keep\s+(dropping|falling|crashing|bleeding))\b", 0.70),
        (r"\b(will\s+keep\s+going\s+down|never\s+going\s+to\s+recover)\b", 0.70),
        # Short-term projection
        (r"\b(based\s+on\s+the\s+last\s+(few\s+days|week|month))\b", 0.60),
        (r"\b(past\s+(week|month)\s+proves?)\b", 0.65),
        (r"\b(since\s+it\s+(surged|dropped|crashed)\s+yesterday)\b", 0.60),
    ],
    "overconfidence": [
        # Certainty claims
        (r"\b(i('?m| am)\s+100%\s+sure|i\s+know\s+for\s+sure|no\s+way\s+this\s+drops)\b", 0.75),
        (r"\b(can'?t\s+go\s+wrong|cannot\s+go\s+wrong|foolproof)\b", 0.70),
        (r"\b(guaranteed\s+(to\s+double|10x|profit|gains?))\b", 0.85),
        (r"\b(easy\s+(money|10x|5x|doubler))\b", 0.70),
        # Arrogance & Outperformance claims
        (r"\b(i\s+always\s+beat\s+the\s+market|better\s+than\s+any\s+(advisor|fund\s+manager))\b", 0.80),
        (r"\b(gut\s+feeling\s+is\s+never\s+wrong|insider\s+intuition)\b", 0.70),
        # Anti-diversification / YOLO
        (r"\b(diversification\s+is\s+for\s+(idiots|wimps|losers)|don'?t\s+need\s+diversification)\b", 0.85),
        (r"\b(all\s+in\s+on|yolo\s+(into|on)|put\s+100%\s+(of\s+my\s+money\s+)?into)\b", 0.75),
    ],
    "herd_mentality": [
        # Crowd / Peer imitation
        (r"\b(everyone\s+is\s+(buying|investing\s+in|talking\s+about))\b", 0.75),
        (r"\b(all\s+my\s+friends\s+are\s+(buying|in|making\s+money))\b", 0.75),
        (r"\b(everyone\s+else\s+is\s+making\s+(money|gains))\b", 0.75),
        # Social media hype
        (r"\b(reddit\s+(says|hype)|wallstreetbets|wsb|tiktok\s+(trend|told\s+me)|twitter\s+hype)\b", 0.70),
        (r"\b(going\s+to\s+the\s+moon|rocket\s+ship|diamond\s+hands)\b", 0.70),
        # FOMO
        (r"\b(fomo|fear\s+of\s+missing\s+out|don'?t\s+want\s+to\s+miss\s+(out|the\s+boat|the\s+train))\b", 0.75),
        (r"\b(before\s+it'?s\s+too\s+late|everyone\s+knows\s+it'?s\s+the\s+next)\b", 0.65),
    ],
    "disposition_effect": [
        # Lock in winner premature
        (r"\b(sell\s+(my\s+)?winners?\s+to\s+lock\s+in|lock\s+in\s+(a\s+)?small\s+(gain|profit))\b", 0.70),
        (r"\b(take\s+profit\s+before\s+it\s+disappears|take\s+the\s+money\s+and\s+run)\b", 0.65),
        # Hold loser / Break-even anchor
        (r"\b(hold\s+(onto\s+)?(my\s+)?losers?|refuse\s+to\s+sell\s+at\s+a\s+loss)\b", 0.75),
        (r"\b(can'?t\s+sell\s+(at\s+a\s+loss|in\s+the\s+red)|cannot\s+take\s+a\s+loss)\b", 0.75),
        (r"\b(wait\s+until\s+it\s+(gets\s+back\s+to\s+even|breaks\s+even|recovers\s+to\s+what\s+i\s+paid))\b", 0.75),
        (r"\b(it'?s\s+not\s+a\s+loss\s+until\s+you\s+sell)\b", 0.70),
    ],
}
```

#### Scoring Formulation
For a normalized user message $M$ and a bias $B$:
$$\text{Score}(B, M) = \min\left(1.0, \sum_{p \in \text{Matches}(B, M)} w_p\right)$$

- **Threshold Guard**: If $\text{Score}(B, M) \ge 0.60$, Layer 1 flags the bias.
- **Severity Mapping**:
  $$\text{Severity} = \begin{cases} 
  \text{"high"}, & \text{if } \text{Score} \ge 0.90 \text{ or message contains explicit liquidations ("sell everything", "dump all")} \\
  \text{"medium"}, & \text{if } 0.75 \le \text{Score} < 0.90 \\
  \text{"low"}, & \text{if } 0.60 \le \text{Score} < 0.75 
  \end{cases}$$

---

### 2.3 Layer 2: LLM Contextual Confirmation & Deterministic Fallback

#### LLM Prompting & Schema
When Layer 1 detects a candidate bias ($\text{Score} \ge 0.60$) or in advisory conversation, Layer 2 queries the LLM:

```json
[
  {
    "bias_type": "loss_aversion",
    "confidence": 0.88,
    "severity": "high",
    "reasoning": "The user expresses extreme distress over market volatility and demands immediate liquidation to cash.",
    "intervention": "Market pullbacks of 3-5% are normal short-term volatility. Cashing out crystallizes paper losses and forfeits recoveries. Let's initiate a 24-hour cool-off period.",
    "cool_off_recommended": true
  }
]
```

#### Deterministic Fallback Logic
The system evaluates the availability of LLM services through a multi-stage check:
1. **Config Check**: If `not settings.openai_api_key` or `settings.dry_run` is True or `openai_client` is None $\to$ **Immediate Heuristic Fallback**.
2. **Execution Guard**: If the OpenAI client raises any exception (`APIConnectionError`, `RateLimitError`, `Timeout`, `AuthenticationError`, `json.JSONDecodeError`) $\to$ **Catch, Log Warning, Fallback to Layer 1**.
3. **Fallback Construction**:
   - `bias_type = layer1.bias_type`
   - `confidence = layer1.score`
   - `severity = layer1.severity`
   - `trigger_source = "dialogue_heuristic"`
   - `matched_patterns = layer1.matched_patterns`
   - `intervention = CALIBRATED_INTERVENTIONS[bias_type][severity]`
   - `cool_off_recommended = (severity == "high" or bias_type == "loss_aversion")`

This guarantees that **100% of unit tests pass offline with zero external dependencies**.

---

## 3. Behavioral Telemetry Signals Specification

Real-world investors do not only communicate bias through conversation; their actions and behavioral patterns emit quantitative telemetry signals. The `BehavioralBiasAgent` monitors four distinct telemetry channels:

```
                                  ┌─────────────────────────────┐
                                  │  Behavioral Telemetry Bus   │
                                  └──────────────┬──────────────┘
                                                 │
          ┌───────────────────────┬──────────────┴──────────────┬────────────────────────┐
          ▼                       ▼                             ▼                        ▼
┌──────────────────┐   ┌─────────────────────┐   ┌──────────────────────┐   ┌────────────────────────┐
│ 1. Check Freq    │   │ 2. Panic Dip Sell   │   │ 3. Concentration     │   │ 4. Trade Frequency     │
│ ≥3 checks / 10m  │   │ Sell on drop ≤ -3%  │   │ Single asset > 25%   │   │ ≥5 trades in 24 hours  │
│ Anxiety / Loss   │   │ Loss Aversion       │   │ Overconfidence       │   │ Speculation / Churn    │
└──────────────────┘   └─────────────────────┘   └──────────────────────┘   └────────────────────────┘
```

### 3.1 Check Frequency Tracking (Anxiety & Loss Aversion)
- **Signal**: Frequent portfolio viewing / balance requests.
- **Mechanism**:
  - Redis / InMemory key: `telemetry:check_freq:{client_id}`
  - TTL: 600 seconds (10 minutes)
  - Data: JSON list of POSIX timestamps `[t_1, t_2, ...]`.
  - On each check: append `current_time`, evict timestamps older than `current_time - 600`.
  - If `len(active_timestamps) >= 3`:
    - Detected: `signal_type="rapid_checks"`, `bias_type="loss_aversion"`
    - Severity: `"medium"` ($3 \le N < 5$), `"high"` ($N \ge 5$)
    - Intervention: *"You have viewed your portfolio {N} times in the past 10 minutes. Research shows frequent portfolio monitoring significantly elevates emotional anxiety and the probability of premature panic selling. We encourage setting a weekly or monthly review cadence."*

### 3.2 Panic Dip Selling Detection (Loss Aversion & Recency Bias)
- **Signal**: Submitting a `SELL` order on an asset or equity sleeve immediately following a sharp market or asset decline.
- **Criteria**:
  - `trade_side.upper() == "SELL"`
  - AND `asset_price_change_24h <= -3.0%` OR `market_drawdown_24h <= -2.0%`
- **Output**:
  - `signal_type="panic_dip_sell"`, `bias_type="loss_aversion"`
  - `severity="high"`, `cool_off_recommended=True`
  - Intervention: *"Selling {symbol} following a {drawdown}% decline crystallizes temporary paper losses. Historically, knee-jerk exits during market dips result in missing the subsequent strongest recovery days. A 24-hour cool-off reflection period is strongly advised before executing."*

### 3.3 Concentration Bias Detection (Overconfidence & Lack of Diversification)
- **Signal**: Single asset allocation dominating the portfolio.
- **Criteria**:
  - For non-cash / non-broad-index assets (e.g. individual equities, niche thematic funds):
  - Single asset weight $W_i = \frac{\text{position\_value}}{\text{total\_portfolio\_value}} > 0.25$ (25%).
- **Output**:
  - `signal_type="concentration_risk"`, `bias_type="overconfidence"`
  - `severity="medium"` if $0.25 < W_i \le 0.40$; `severity="high"` if $W_i > 0.40$
  - Intervention: *"{symbol} constitutes {weight*100:.1f}% of your total portfolio. Heavy single-asset concentration exposes your wealth to uncompensated idiosyncratic risk. Even world-class companies experience 40%+ drawdowns. Reallocating toward diversified asset classes protects long-term capital."*

### 3.4 Excessive Trading Frequency (Overconfidence & Market Timing)
- **Signal**: Frequent buy/sell order submissions over a rolling 24-hour window.
- **Criteria**:
  - Total trade count within rolling 24h $\ge 5$ orders.
- **Output**:
  - `signal_type="excessive_trading"`, `bias_type="overconfidence"`
  - `severity="medium"` if $5 \le N < 8$; `severity="high"` if $N \ge 8$
  - `cool_off_recommended=True`
  - Intervention: *"You have initiated {N} trades in the last 24 hours. Hyperactive trading dramatically increases friction costs, spreads, and tax drag, and usually reflects illusory market timing confidence. Let's pause to verify if these trades align with your strategic asset allocation."*

---

## 4. Database Persistence & Client Profile Synchronization

### 4.1 `DBBehavioralMemory` Schema Mapping
Defined in `backend/db/models.py`:
```python
class DBBehavioralMemory(Base):
    __tablename__ = "behavioral_memory"

    id = Column(String, primary_key=True, default=generate_uuid)
    client_id = Column(String, ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False, index=True)
    bias_type = Column(String, nullable=False, index=True)      # loss_aversion, recency_bias, overconfidence, herd_mentality, disposition_effect
    severity = Column(String, nullable=False, default="medium")  # low, medium, high
    trigger_context = Column(JSON, nullable=True)                # dictionary with matched patterns, scores, telemetry values
    intervention_text = Column(Text, nullable=True)              # exact educational reframing provided
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)
```

### 4.2 Synchronization with `DBClientProfile`
When a bias is detected and recorded via `record_bias_event`:
1. **Append to `detected_biases`**:
   - `client.detected_biases`: JSON list of unique bias types detected over the client's lifetime (e.g. `["loss_aversion", "overconfidence"]`).
2. **Update `emotional_risk_score` (0.0 to 100.0)**:
   - Increments based on severity:
     - `low`: $+5.0$
     - `medium`: $+12.0$
     - `high`: $+20.0$
   - Capped at $100.0$.
3. **Update `panic_sell_likelihood` (0.0 to 1.0)**:
   - If `bias_type == "loss_aversion"` or signal is `panic_dip_sell`:
     - Increments by $+0.15$ (high severity) or $+0.08$ (medium/low).
   - Capped at $1.0$.

---

## 5. Complete Public Class & Method Signatures

```python
class BiasDetectionResult(BaseModel):
    bias_type: str
    confidence: float
    severity: str  # "low", "medium", "high"
    trigger_source: str  # "dialogue_heuristic", "dialogue_llm", "telemetry"
    matched_patterns: List[str] = Field(default_factory=list)
    trigger_context: Dict[str, Any] = Field(default_factory=dict)
    intervention: str
    cool_off_recommended: bool = False
    reasoning: Optional[str] = None

class TelemetrySignal(BaseModel):
    signal_type: str  # "rapid_checks", "panic_dip_sell", "concentration_risk", "excessive_trading"
    detected: bool
    bias_type: Optional[str] = None
    severity: str = "low"  # "low", "medium", "high"
    metrics: Dict[str, Any] = Field(default_factory=dict)
    intervention: Optional[str] = None
    cool_off_recommended: bool = False

class BehavioralBiasAgent:
    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        openai_client: Optional[AsyncOpenAI] = None,
        settings: Optional[Settings] = None,
        heuristic_threshold: float = 0.60,
    ):
        ...

    async def detect_bias(
        self,
        client_id: str,
        user_message: str,
        portfolio_context: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> List[BiasDetectionResult]:
        """
        Dual-layer bias detection executing Layer 1 heuristic pattern scoring,
        followed by Layer 2 LLM contextual confirmation with automatic fallback.
        Optionally persists detected events to DB if db session is provided.
        """
        ...

    async def analyze_message(self, message: str) -> List[Dict[str, Any]]:
        """
        Backwards-compatible interface for main.py / WebSocket chat handler.
        Returns list of dictionary bias results.
        """
        ...

    def evaluate_heuristic_layer(self, text: str) -> List[HeuristicDetection]:
        """
        Execute Layer 1 regex pattern scoring across all 5 biases.
        Returns list of HeuristicDetection objects with score >= heuristic_threshold.
        """
        ...

    async def record_portfolio_check(
        self,
        client_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[TelemetrySignal]:
        """
        Tracks user portfolio viewing frequency in cache.
        Returns TelemetrySignal if rapid check threshold (>=3 in 10 mins) is breached.
        """
        ...

    def check_panic_dip_sell(
        self,
        trade_side: str,
        symbol: str,
        asset_price_change_24h: float,
        market_change_24h: Optional[float] = None,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if a trade represents emotional panic selling after a price decline.
        """
        ...

    def check_concentration_bias(
        self,
        positions: Dict[str, float],
        total_value: float,
        threshold: float = 0.25,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if any single non-cash position exceeds the concentration threshold.
        """
        ...

    def check_trading_frequency(
        self,
        trades_count_recent: int,
        window_hours: int = 24,
        threshold: int = 5,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if trading count over a recent time window indicates hyperactive trading.
        """
        ...

    async def evaluate_telemetry(
        self,
        client_id: str,
        telemetry_data: Dict[str, Any],
        db: Optional[AsyncSession] = None,
    ) -> List[TelemetrySignal]:
        """
        Evaluates all incoming telemetry signals and optionally persists events.
        """
        ...

    async def record_bias_event(
        self,
        db: AsyncSession,
        client_id: str,
        bias_type: str,
        severity: str,
        trigger_context: Dict[str, Any],
        intervention_text: str,
    ) -> DBBehavioralMemory:
        """
        Persists a detected bias event to the behavioral_memory table,
        and updates DBClientProfile.detected_biases, emotional_risk_score,
        and panic_sell_likelihood.
        """
        ...

    async def get_bias_history(
        self,
        db: AsyncSession,
        client_id: str,
        limit: int = 50,
    ) -> List[DBBehavioralMemory]:
        """
        Retrieves chronological history of detected biases for a client.
        """
        ...

    async def get_client_bias_profile(
        self,
        db: AsyncSession,
        client_id: str,
    ) -> Dict[str, Any]:
        """
        Returns an aggregated summary profile of client behavioral tendencies.
        """
        ...
```

---

## 6. Calibrated Offline Scenario Fixtures

To ensure 100% deterministic offline unit and integration testing, the following 12 test fixtures must be formalized:

```python
FIXTURE_SCENARIOS = {
    # 1. Loss Aversion - Severe Panic Liquidation
    "loss_aversion_panic": {
        "text": "The market dropped 4% today, I can't take the pain! Sell everything right now and put it all in cash.",
        "expected_bias": "loss_aversion",
        "expected_min_score": 0.80,
        "expected_severity": "high",
        "cool_off": True,
    },
    # 2. Loss Aversion - Fear of Loss
    "loss_aversion_fear": {
        "text": "I cannot afford to lose any money in this portfolio. I am terrified of losing my savings.",
        "expected_bias": "loss_aversion",
        "expected_min_score": 0.65,
        "expected_severity": "low",
        "cool_off": False,
    },
    # 3. Recency Bias - Bull Market Extrapolation
    "recency_bias_bull": {
        "text": "Tech stocks only go up, look at the last week! It will keep going up forever, so let's put more in.",
        "expected_bias": "recency_bias",
        "expected_min_score": 0.75,
        "expected_severity": "medium",
        "cool_off": False,
    },
    # 4. Recency Bias - Bear Market Despair
    "recency_bias_bear": {
        "text": "The market has been dropping every day this week, it will keep falling forever. It is never going to recover.",
        "expected_bias": "recency_bias",
        "expected_min_score": 0.70,
        "expected_severity": "medium",
        "cool_off": False,
    },
    # 5. Overconfidence - Certainty & Anti-Diversification
    "overconfidence_certainty": {
        "text": "I'm 100% sure this stock is guaranteed to double in 3 months. Diversification is for idiots, let's go all in.",
        "expected_bias": "overconfidence",
        "expected_min_score": 0.85,
        "expected_severity": "high",
        "cool_off": True,
    },
    # 6. Herd Mentality - Social Media / FOMO
    "herd_mentality_fomo": {
        "text": "Everyone on Reddit and WallStreetBets is buying this coin. All my friends are making money, I have huge FOMO!",
        "expected_bias": "herd_mentality",
        "expected_min_score": 0.75,
        "expected_severity": "medium",
        "cool_off": False,
    },
    # 7. Disposition Effect - Lock Winner / Refuse Loss
    "disposition_effect": {
        "text": "I want to sell my winners to lock in this small profit, but for my losing positions I refuse to sell at a loss until they get back to even.",
        "expected_bias": "disposition_effect",
        "expected_min_score": 0.80,
        "expected_severity": "medium",
        "cool_off": False,
    },
    # 8. Neutral Dialogue - No Bias
    "neutral_advisory": {
        "text": "Can you explain the difference between broad market index funds and intermediate Treasury bonds for a 10-year retirement goal?",
        "expected_bias": None,
        "expected_max_score": 0.0,
        "cool_off": False,
    },
    # 9. Telemetry - Rapid Portfolio Checks
    "telemetry_rapid_checks": {
        "check_count": 4,
        "window_seconds": 600,
        "expected_signal": "rapid_checks",
        "expected_bias": "loss_aversion",
        "expected_severity": "medium",
    },
    # 10. Telemetry - Panic Dip Sell
    "telemetry_panic_dip_sell": {
        "trade_side": "SELL",
        "symbol": "NVDA",
        "asset_price_change_24h": -5.2,
        "expected_signal": "panic_dip_sell",
        "expected_bias": "loss_aversion",
        "expected_severity": "high",
        "cool_off": True,
    },
    # 11. Telemetry - Concentration Bias
    "telemetry_concentration": {
        "positions": {"TSLA": 42000.0, "SPY": 8000.0},
        "total_value": 50000.0,  # TSLA = 84%
        "expected_signal": "concentration_risk",
        "expected_bias": "overconfidence",
        "expected_severity": "high",
    },
    # 12. Telemetry - Excessive Trading
    "telemetry_excessive_trades": {
        "trades_count_recent": 6,
        "window_hours": 24,
        "expected_signal": "excessive_trading",
        "expected_bias": "overconfidence",
        "expected_severity": "medium",
        "cool_off": True,
    },
}
```

---

## 7. Comprehensive Unit Test Plan

A new test suite file `backend/tests/unit/test_behavioral_bias.py` will be created covering 21 discrete test cases:

1. `test_heuristic_loss_aversion_panic()`: Verifies "sell everything" scores $\ge 0.80$ with `"high"` severity and cool-off recommendation.
2. `test_heuristic_loss_aversion_fear()`: Verifies "can't afford to lose" scores $\ge 0.65$ with `"low"`/`"medium"` severity.
3. `test_heuristic_recency_bias_bull()`: Verifies "only goes up" scores $\ge 0.75$.
4. `test_heuristic_recency_bias_bear()`: Verifies "dropping every day ... never recover" scores $\ge 0.70$.
5. `test_heuristic_overconfidence()`: Verifies "100% sure ... diversification is for idiots" scores $\ge 0.85$ with `"high"` severity.
6. `test_heuristic_herd_mentality()`: Verifies "everyone on reddit ... fomo" scores $\ge 0.75$.
7. `test_heuristic_disposition_effect()`: Verifies "sell winners to lock in ... refuse to sell at a loss" scores $\ge 0.80$.
8. `test_heuristic_neutral_message()`: Verifies objective portfolio questions yield 0 matches and score $0.0$.
9. `test_heuristic_multiple_biases()`: Tests a combined message triggering both herd mentality and overconfidence, verifying multiple detected results ranked by confidence.
10. `test_llm_confirmation_online_mock()`: Tests Layer 2 with a mock `AsyncOpenAI` client returning valid structured JSON.
11. `test_llm_fallback_no_api_key()`: Verifies that when `openai_api_key` is None, the agent falls back to Layer 1 heuristics without error.
12. `test_llm_fallback_on_api_exception()`: Verifies graceful fallback to Layer 1 heuristics when the mock client raises `openai.APIConnectionError`.
13. `test_llm_fallback_on_malformed_json()`: Verifies fallback to Layer 1 when LLM outputs non-JSON or invalid schema.
14. `test_telemetry_rapid_portfolio_checks()`: Verifies 3 checks within 10 minutes triggers `rapid_checks` and `loss_aversion`.
15. `test_telemetry_spaced_checks_pass()`: Verifies checks spaced across hours do not trigger the anxiety signal.
16. `test_telemetry_panic_dip_sell()`: Verifies a SELL order on an asset down $-5.2\%$ triggers `panic_dip_sell` with `"high"` severity.
17. `test_telemetry_normal_sell_pass()`: Verifies a SELL order on an asset with flat or $+2.0\%$ performance does not trigger panic sell.
18. `test_telemetry_concentration_bias()`: Verifies a portfolio with an $84\%$ single-stock position triggers `concentration_risk` with `"high"` severity.
19. `test_telemetry_excessive_trading()`: Verifies $6$ trades in 24 hours triggers `excessive_trading` and cool-off.
20. `test_database_persistence_and_profile_sync()`: Verifies inserting into `DBBehavioralMemory`, querying history, and validating that `DBClientProfile.detected_biases`, `emotional_risk_score`, and `panic_sell_likelihood` are properly updated and committed.
21. `test_backwards_compatible_analyze_message()`: Verifies that `analyze_message(message)` returns the expected list-of-dicts format required by `backend/main.py`.

---

## 8. Cross-Agent Integration Points

1. **Risk Profiler Agent (`risk_profiler.py`)**:
   - During the 6-state profiling interview, dialogue inputs are analyzed by `BehavioralBiasAgent`.
   - Identified biases are saved to `DBClientProfile.detected_biases` and factor directly into `emotional_risk_score` and `panic_sell_likelihood`.
2. **Orchestrator Agent (`orchestrator.py`)**:
   - Central chat endpoint passes user messages to `bias_agent.detect_bias()`.
   - If an intervention or cool-off is returned, Orchestrator interweaves the debiasing education into the response before proposing any asset allocation adjustments.
3. **Execution Module (`execution_module.py`)**:
   - Before executing market orders, Execution Module checks `bias_agent.check_panic_dip_sell()` and `bias_agent.check_trading_frequency()`.
   - If a high-severity panic sell or hyperactive trading is detected, execution can require explicit cool-off confirmation.
4. **Compliance Guard (`compliance_guard.py`)**:
   - While Compliance Guard enforces hard portfolio concentration limits (`CONC-001`), the Behavioral Bias Agent provides the behavioral psychological explanation and educational reframing to the client.

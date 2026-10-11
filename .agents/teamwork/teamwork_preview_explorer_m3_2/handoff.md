# Handoff Report: Behavioral Bias Agent Specification

**Milestone**: M3 (Core Agents: Behavioral Bias)  
**Agent Role**: Explorer 2 (`teamwork_preview_explorer_m3_2`)  
**Target Module**: `backend/agents/behavioral_bias.py`  
**Handoff Type**: Hard (Task Complete)  
**Recipient**: Orchestrator (`498f461a-015a-42ad-98d2-3a9070fe1d9a`) / Worker  
**Date**: 2026-10-10T16:44:00Z  

---

## 1. Observation

1. **Current Agent Implementation (`backend/agents/behavioral_bias.py:30-55`)**:
   ```python
   class BehavioralBiasAgent:
       def __init__(self):
           self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

       async def analyze_message(self, message: str) -> list:
           try:
               response = await self.client.chat.completions.create(
                   model="gpt-4o",
                   messages=[
                       {"role": "system", "content": BIAS_PROMPT},
                       {"role": "user", "content": message}
                   ],
                   temperature=0.2, # Low temperature for more deterministic analysis
               )
               content = response.choices[0].message.content.strip()
               if content.startswith("```json"):
                   content = content[7:-3]
               biases = json.loads(content)
               return biases
           except Exception as e:
               logger.error(f"Error in Bias Detection: {e}")
               return []
   ```
   *Direct Finding*: The current module is a 55-line preliminary stub that only invokes `gpt-4o` directly. It lacks Layer 1 heuristic regex pattern scoring, does not support behavioral telemetry signals, has no database persistence to `behavioral_memory`, lacks cool-off / educational reframing logic, and fails completely when `OPENAI_API_KEY` is absent (returning an empty list `[]` instead of performing deterministic bias detection).

2. **Database Models (`backend/db/models.py:193-207`)**:
   ```python
   class DBBehavioralMemory(Base):
       """Persistent storage for detected client behavioral biases and debiasing interventions."""
       __tablename__ = "behavioral_memory"

       id = Column(String, primary_key=True, default=generate_uuid)
       client_id = Column(String, ForeignKey("client_profiles.client_id", ondelete="CASCADE"), nullable=False, index=True)
       bias_type = Column(String, nullable=False, index=True)  # loss_aversion, recency_bias, overconfidence, etc.
       severity = Column(String, nullable=False, default="medium")  # low, medium, high
       trigger_context = Column(JSON, nullable=True)
       intervention_text = Column(Text, nullable=True)
       timestamp = Column(DateTime, default=datetime.utcnow, nullable=False, index=True)

       # Relationship
       client = relationship("DBClientProfile", back_populates="behavioral_memories")
   ```
   *Direct Finding*: In addition, `DBClientProfile` (`backend/db/models.py:84-86`) defines:
   - `detected_biases = Column(JSON, default=list)`
   - `emotional_risk_score = Column(Float, nullable=True, default=0.0)`
   - `panic_sell_likelihood = Column(Float, nullable=True, default=0.0)`
   The Behavioral Bias Agent must update these profile metrics upon recording bias events.

3. **Master Project Plan (`.agents/teamwork/orchestrator/PROJECT.md:14, 36`)**:
   - Line 14: `"agents/behavioral_bias.py: Dual-layer bias detection (keyword/regex pattern scoring threshold 0.6 + LLM contextual confirmation), behavioral telemetry signals (check frequency, panic dip selling, concentration, trade frequency), persistent memory in behavioral_memory table, calibrated offline scenario fixtures"`
   - Line 36: Feature 12: `"Behavioral Bias Detection & Memory: Keyword heuristic (0.6 threshold) + LLM, behavioral telemetry, behavioral_memory storage | M3"`

4. **Integration in `backend/main.py:255-262`**:
   ```python
   # 1. Bias Detection (runs in parallel mentally)
   biases = await bias_agent.analyze_message(data)
   if biases:
       for bias in biases:
           await websocket.send_json({
               "agent": "BehavioralBias",
               "type": "alert",
               "text": f"[Bias Detected: {bias.get('bias_type')}] {bias.get('intervention')}"
           })
   ```
   *Direct Finding*: The public API must preserve backward compatibility with `analyze_message(message)` returning `List[Dict[str, Any]]` while introducing the full signature `detect_bias(client_id, user_message, portfolio_context, db)`.

5. **Existing Test & Cache Suite (`backend/services/cache.py:240-279`)**:
   - `CacheService` provides `get_json` and `set_json`, with thread-safe `InMemoryCache` fallback. Telemetry check frequency can leverage `telemetry:check_freq:{client_id}` with 600s TTL.

---

## 2. Logic Chain

1. **Dual-Layer Bias Architecture Rationale (connecting Obs 1 & Obs 3)**:
   - Retail investors frequently express emotional biases using distinct, predictable linguistic markers (*"can't afford to lose"*, *"sell everything"*, *"guaranteed to double"*, *"all my friends on reddit"*).
   - An LLM-only approach is slow (network round-trip), costly, and non-deterministic in offline test environments.
   - Therefore, a dual-layer architecture is optimal:
     - **Layer 1**: Evaluates weighted regular expressions across the 5 biases (`loss_aversion`, `recency_bias`, `overconfidence`, `herd_mentality`, `disposition_effect`). If the cumulative score meets or exceeds the calibrated threshold of $0.60$, the bias is detected deterministically with confidence and mapped severity.
     - **Layer 2**: Invokes LLM contextual confirmation when `OPENAI_API_KEY` is present and active. If the LLM is unconfigured, offline, or returns invalid JSON, the agent seamlessly falls back to Layer 1's heuristic detection with calibrated educational reframing templates.

2. **Telemetry Signal Grounding (connecting Obs 1, 3, & 5)**:
   - Biases also manifest through client actions before they are spoken:
     - Hyper-vigilant portfolio checking ($\ge 3$ times in 10 minutes) signals loss aversion and anxiety.
     - Submitting a sell order when an asset has dropped $\le -3.0\%$ in 24 hours signals panic dip selling.
     - Holding $> 25\%$ of portfolio value in a single non-cash asset indicates concentration bias / overconfidence.
     - Submitting $\ge 5$ trades within 24 hours indicates hyperactive trading / day-trading churn.
   - By implementing telemetry evaluation methods (`record_portfolio_check`, `check_panic_dip_sell`, `check_concentration_bias`, `check_trading_frequency`), the agent proactively intercepts emotional trades and recommends 24h cool-off periods.

3. **Database Persistence & Profile Synchronization (connecting Obs 2)**:
   - When biases are detected, inserting into `DBBehavioralMemory` creates an immutable audit of client psychological events.
   - Simultaneously updating `DBClientProfile.detected_biases`, incrementing `emotional_risk_score` (by $+5$, $+12$, or $+20$ depending on severity), and elevating `panic_sell_likelihood` (by $+0.15$ on panic selling) ensures downstream agents (Risk Profiler, Allocation Engine, Execution Module) adapt to the client's actual behavioral profile.

4. **Testability & Fixtures**:
   - Unit tests must be 100% executable offline without live OpenAI API keys.
   - Formulating 12 deterministic scenario fixtures and mocking OpenAI ensures total test reproducibility and $>85\%$ test coverage compliance.

---

## 3. Caveats

1. **LLM Grounding vs Heavy HuggingFace Models**:
   - While `ORIGINAL_REQUEST.md` mentioned "HuggingFace grounding", `backend/requirements.txt` does not include `transformers` or `torch` (only `datasets>=2.16.0`). Per `PROJECT.md` line 14, the master architecture explicitly specifies: *"Dual-layer bias detection (keyword/regex pattern scoring threshold 0.6 + LLM contextual confirmation), behavioral telemetry signals, persistent memory in behavioral_memory table, calibrated offline scenario fixtures"*. The dual-layer design with offline calibrated heuristic fixtures fulfills this requirement without adding multi-gigabyte PyTorch dependencies.
2. **Database Foreign Key Invariant**:
   - In PostgreSQL and strict SQLite configurations, inserting a record into `behavioral_memory` requires a valid existing record in `client_profiles` (`client_id`). Unit tests testing DB persistence must create a `DBClientProfile` first.
3. **No Caveats Regarding Scope**: All required features (dual-layer, 5 biases, 4 telemetry signals, persistence, profile sync, interventions, cool-off, fixtures, signatures, test plan) are fully addressed.

---

## 4. Conclusion

The specification for `backend/agents/behavioral_bias.py` is fully designed and documented in `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m3_2\analysis.md`.

The implementation worker must implement:
1. `BehavioralBiasAgent` with:
   - Pre-compiled regex catalog for `loss_aversion`, `recency_bias`, `overconfidence`, `herd_mentality`, `disposition_effect` (threshold $\ge 0.60$).
   - Dual-layer `detect_bias(client_id, user_message, portfolio_context, db)` with Layer 2 LLM confirmation and graceful heuristic fallback.
   - Backward-compatible `analyze_message(message)`.
   - Telemetry signals: `record_portfolio_check`, `check_panic_dip_sell`, `check_concentration_bias`, `check_trading_frequency`, `evaluate_telemetry`.
   - Asynchronous persistence: `record_bias_event`, `get_bias_history`, `get_client_bias_profile` synchronizing with `DBBehavioralMemory` and `DBClientProfile`.
2. `backend/tests/unit/test_behavioral_bias.py` implementing the 21 test scenarios defined in `analysis.md`.

---

## 5. Verification Method

1. **Artifact Verification**:
   - Review `c:\Users\HP VICTUS\Documents\wealth_agent\.agents\teamwork\teamwork_preview_explorer_m3_2\analysis.md` for complete pattern weights, signatures, and fixture data.
2. **Implementation Verification (Post-Worker Implementation)**:
   - Run the dedicated unit test suite:
     ```powershell
     cd "c:\Users\HP VICTUS\Documents\wealth_agent\backend"
     pytest -v tests/unit/test_behavioral_bias.py
     ```
   - Verify coverage meets the project $\ge 80\%$ gate:
     ```powershell
     pytest -q --cov=agents.behavioral_bias tests/unit/test_behavioral_bias.py
     ```
   - Verify existing tests still pass without regressions:
     ```powershell
     pytest -q tests/unit/
     ```
3. **Invalidation Conditions**:
   - If heuristic detection fails to trigger on any of the 12 calibrated scenario fixtures with score $< 0.60$.
   - If the agent crashes when `OPENAI_API_KEY` is unset or empty instead of returning heuristic fallback results.
   - If inserting a bias event fails to update `DBBehavioralMemory` or fails to adjust `DBClientProfile.detected_biases`.

"""
backend/agents/behavioral_bias.py
=================================
Dual-layer behavioral bias detection agent with keyword/regex heuristic scoring,
LLM contextual confirmation with deterministic fallback, behavioral telemetry monitoring,
and database persistence to behavioral_memory and client_profiles.
"""

from __future__ import annotations

import os
import re
import time
import json
import logging
from datetime import datetime
from typing import Dict, Any, List, Optional, Tuple

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import settings
from db.database import AsyncSessionLocal
from db.models import DBBehavioralMemory, DBClientProfile
from services.cache import CacheService, get_cache_service

logger = logging.getLogger("wealth_advisor.agents.behavioral_bias")

# --- Calibrated Regex Patterns with Factor Weights ---
HEURISTIC_PATTERNS: Dict[str, List[Tuple[str, float]]] = {
    "loss_aversion": [
        (r"\b(sell|dump|liquidate|pull\s*out)\s+(everything|all\s+(my\s+)?(stocks|holdings|positions|shares|money))\b", 0.80),
        (r"\b(put|keep|move)\s+(everything|it\s+all|my\s+money)\s+(in|into|to)\s+cash\b", 0.75),
        (r"\b(can'?t|cannot)\s+afford\s+to\s+lose\b", 0.65),
        (r"\b(scared|terrified|fearful|worried|dreading)\s+(of\s+losing|about\s+losses|of\s+a\s+crash)\b", 0.65),
        (r"\b(hate|despise)\s+losing\s+money\b", 0.55),
        (r"\b(stop\s+the\s+bleeding|cut\s+all\s+(my\s+)?losses)\b", 0.60),
        (r"\b(market\s+is\s+crashing|going\s+to\s+zero|lose\s+all\s+(my\s+)?savings|wiped?\s*out)\b", 0.60),
        (r"\b(can'?t\s+take\s+the\s+pain|losing\s+sleep)\b", 0.60),
    ],
    "recency_bias": [
        (r"\b(only\s+go(?:es)?\s+up|going\s+up\s+every\s+day|keep\s+going\s+up|will\s+never\s+drop)\b", 0.75),
        (r"\b(can'?t\s+fail\s+right\s+now|unstoppable\s+momentum|guaranteed\s+rally)\b", 0.70),
        (r"\b(doubled\s+last\s+(week|month)|soaring\s+recently)\b", 0.60),
        (r"\b(dropping\s+every\s+day|keep\s+(dropping|falling|crashing|bleeding))\b", 0.70),
        (r"\b(will\s+keep\s+going\s+down|never\s+going\s+to\s+recover)\b", 0.70),
        (r"\b((?:based\s+on|look\s+at)\s+the\s+last\s+(few\s+days|week|month))\b", 0.60),
        (r"\b(past\s+(week|month)\s+proves?)\b", 0.65),
        (r"\b(since\s+it\s+(surged|dropped|crashed)\s+yesterday)\b", 0.60),
    ],
    "overconfidence": [
        (r"\b(i('?m| am)\s+100%\s+sure|i\s+know\s+for\s+sure|no\s+way\s+this\s+drops)\b", 0.75),
        (r"\b(can'?t\s+go\s+wrong|cannot\s+go\s+wrong|foolproof)\b", 0.70),
        (r"\b(guaranteed\s+(to\s+double|10x|profit|gains?))\b", 0.85),
        (r"\b(easy\s+(money|10x|5x|doubler))\b", 0.70),
        (r"\b(i\s+always\s+beat\s+the\s+market|better\s+than\s+any\s+(advisor|fund\s+manager))\b", 0.80),
        (r"\b(gut\s+feeling\s+is\s+never\s+wrong|insider\s+intuition)\b", 0.70),
        (r"\b(diversification\s+is\s+for\s+(idiots|wimps|losers)|don'?t\s+need\s+diversification)\b", 0.85),
        (r"\b(all\s+in\s+on|yolo\s+(into|on)|put\s+100%\s+(of\s+my\s+money\s+)?into)\b", 0.75),
    ],
    "herd_mentality": [
        (r"\b(everyone\s+is\s+(buying|investing\s+in|talking\s+about))\b", 0.75),
        (r"\b(all\s+my\s+friends\s+are\s+(buying|in|making\s+money))\b", 0.75),
        (r"\b(everyone\s+else\s+is\s+making\s+(money|gains))\b", 0.75),
        (r"\b(reddit\s+(says|hype)|wallstreetbets|wsb|tiktok\s+(trend|told\s+me)|twitter\s+hype)\b", 0.70),
        (r"\b(going\s+to\s+the\s+moon|rocket\s+ship|diamond\s+hands)\b", 0.70),
        (r"\b(fomo|fear\s+of\s+missing\s+out|don'?t\s+want\s+to\s+miss\s+(out|the\s+boat|the\s+train))\b", 0.75),
        (r"\b(before\s+it'?s\s+too\s+late|everyone\s+knows\s+it'?s\s+the\s+next)\b", 0.65),
    ],
    "disposition_effect": [
        (r"\b(sell\s+(my\s+)?winners?\s+to\s+lock\s+in|lock\s+in\s+(a\s+)?small\s+(gain|profit))\b", 0.70),
        (r"\b(take\s+profit\s+before\s+it\s+disappears|take\s+the\s+money\s+and\s+run)\b", 0.65),
        (r"\b(hold\s+(onto\s+)?(my\s+)?losers?|refuse\s+to\s+sell\s+at\s+a\s+loss)\b", 0.75),
        (r"\b(can'?t\s+sell\s+(at\s+a\s+loss|in\s+the\s+red)|cannot\s+take\s+a\s+loss)\b", 0.75),
        (r"\b(wait\s+until\s+it\s+(gets\s+back\s+to\s+even|breaks\s+even|recovers\s+to\s+what\s+i\s+paid))\b", 0.75),
        (r"\b(it'?s\s+not\s+a\s+loss\s+until\s+you\s+sell)\b", 0.70),
    ],
}

CALIBRATED_INTERVENTIONS: Dict[str, Dict[str, str]] = {
    "loss_aversion": {
        "high": "Market pullbacks of 3-5% are normal short-term volatility. Cashing out crystallizes paper losses and forfeits recoveries. We strongly recommend a 24-hour cool-off period before liquidating assets.",
        "medium": "Short-term declines can be uncomfortable, but holding diversified assets preserves your long-term compound growth. Research shows knee-jerk exits frequently result in missing the fastest recovery days.",
        "low": "It is natural to worry about losses. We maintain a balanced allocation designed to withstand volatility while pursuing your goals.",
    },
    "recency_bias": {
        "high": "Extrapolating short-term market momentum indefinitely creates significant vulnerability to mean reversion. Historically, markets cycle regularly. Let's ground our allocation in multi-year base rates.",
        "medium": "Recent performance is not a guarantee of future trajectory. Asset classes rotate cyclically; staying disciplined through full market cycles outperforms chasing momentum.",
        "low": "While recent price action is notable, strategic long-term allocations should not be dictated by weekly or monthly price swings.",
    },
    "overconfidence": {
        "high": "Concentrating capital in high-conviction bets creates uncompensated idiosyncratic risk. Even leading companies experience 40%+ drawdowns. Diversification remains essential for capital preservation.",
        "medium": "High confidence in specific outcomes can obscure downside scenarios. Risk management requires stress-testing against adverse conditions.",
        "low": "Remember that active stock picking and timing rarely outperform diversified low-cost index allocations consistently over time.",
    },
    "herd_mentality": {
        "high": "Social media and crowd enthusiasm often peak near market tops. Investing based on FOMO exposes you to heightened correction risk. Anchor your portfolio in your personal financial plan.",
        "medium": "Popular sentiment does not equate to sound valuation. Peer chatter can amplify speculative bubbles; independent fundamental analysis is essential.",
        "low": "Be cautious of market trends popularized online. Stick with assets that match your defined risk capacity and timeline.",
    },
    "disposition_effect": {
        "high": "Refusing to sell losing assets while trimming winners is the disposition effect. Holding declining assets carries opportunity cost and prevents tax-loss harvesting benefits. Evaluate positions based on forward outlook, not purchase price.",
        "medium": "Anchor prices to initial purchase cost can lead to poor capital allocation. Tax-loss harvesting may turn paper losses into valuable tax deductions.",
        "low": "Ensure you evaluate each holding on its future expected risk/return rather than whether it currently shows a paper gain or loss.",
    },
}

BIAS_PROMPT = """
Analyze the following user message for behavioral finance cognitive biases.
We evaluate:
1. "loss_aversion": Asymmetric pain from losses, panic selling, liquidation to cash.
2. "recency_bias": Overweighting recent momentum, believing trends will continue forever.
3. "overconfidence": Absolute certainty, rejection of diversification, hubris.
4. "herd_mentality": FOMO, following crowds/social media without analysis.
5. "disposition_effect": Selling winners prematurely, obstinately holding losers to break even.

If detected, return a JSON array of objects with:
- "bias_type": str
- "confidence": float (0.0 to 1.0)
- "severity": "low" | "medium" | "high"
- "reasoning": str
- "intervention": str
- "cool_off_recommended": bool

If no bias is detected, return [].
Respond ONLY with raw JSON.
"""


class HeuristicDetection(BaseModel):
    bias_type: str
    score: float
    severity: str
    matched_patterns: List[str] = Field(default_factory=list)


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
    """
    Behavioral Bias Detection Agent providing dual-layer bias scoring,
    behavioral telemetry evaluation, cool-off recommendations, and persistence.
    """

    def __init__(
        self,
        cache_service: Optional[CacheService] = None,
        openai_client: Optional[Any] = None,
        heuristic_threshold: float = 0.60,
    ) -> None:
        self.cache = cache_service or get_cache_service()
        self.heuristic_threshold = heuristic_threshold
        self.client = openai_client
        if self.client is None:
            try:
                api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
                if api_key and api_key != "your_openai_api_key_here":
                    import httpx
                    from openai import AsyncOpenAI
                    http_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
                    self.client = AsyncOpenAI(api_key=api_key, http_client=http_client)
            except Exception as e:
                logger.warning(f"Could not initialize AsyncOpenAI client: {e}")

    # ------------------------------------------------------------------
    # Layer 1: Heuristic Regex Pattern Scoring
    # ------------------------------------------------------------------

    def evaluate_heuristic_layer(self, text: str) -> List[HeuristicDetection]:
        """
        Evaluates input text against calibrated regex patterns across the 5 biases.
        Returns list of HeuristicDetection with score >= heuristic_threshold.
        """
        if not text:
            return []

        # Normalize text: lowercased, curly quotes replaced
        normalized = text.lower().replace("’", "'").replace("`", "'")
        results: List[HeuristicDetection] = []

        for bias_type, pattern_list in HEURISTIC_PATTERNS.items():
            matched_patterns = []
            score_sum = 0.0

            for pattern, weight in pattern_list:
                if re.search(pattern, normalized):
                    matched_patterns.append(pattern)
                    score_sum += weight

            total_score = min(1.0, score_sum)

            if total_score >= self.heuristic_threshold:
                # Severity determination
                if total_score >= 0.85 or any("sell" in p and "everything" in p for p in matched_patterns):
                    severity = "high"
                elif total_score >= 0.70:
                    severity = "medium"
                else:
                    severity = "low"

                results.append(
                    HeuristicDetection(
                        bias_type=bias_type,
                        score=round(total_score, 2),
                        severity=severity,
                        matched_patterns=matched_patterns,
                    )
                )

        # Sort by score descending
        results.sort(key=lambda x: x.score, reverse=True)
        return results

    # ------------------------------------------------------------------
    # Layer 2: LLM Confirmation & Dual-Layer Integration
    # ------------------------------------------------------------------

    async def detect_bias(
        self,
        client_id: str,
        user_message: str,
        portfolio_context: Optional[Dict[str, Any]] = None,
        db: Optional[AsyncSession] = None,
    ) -> List[BiasDetectionResult]:
        """
        Executes Layer 1 heuristic pattern scoring, followed by Layer 2 LLM confirmation
        if available, with transparent fallback to Layer 1.
        Optionally persists detected events and synchronizes client profile.
        """
        heuristic_detections = self.evaluate_heuristic_layer(user_message)
        final_results: List[BiasDetectionResult] = []

        # Attempt Layer 2 if LLM client is available
        llm_used = False
        api_key = settings.openai_api_key or os.getenv("OPENAI_API_KEY")
        client = self.client
        if client is None and bool(api_key) and api_key != "your_openai_api_key_here":
            try:
                import httpx
                from openai import AsyncOpenAI

                http_client = httpx.AsyncClient(timeout=httpx.Timeout(20.0, connect=10.0))
                client = AsyncOpenAI(api_key=api_key, http_client=http_client)
            except Exception as e:
                logger.warning(f"Could not initialize AsyncOpenAI client: {e}")
                client = None

        if client is not None:
            try:
                response = await client.chat.completions.create(
                    model=settings.openai_model or os.getenv("OPENAI_MODEL", "gpt-4o"),
                    messages=[
                        {"role": "system", "content": BIAS_PROMPT},
                        {"role": "user", "content": user_message},
                    ],
                    temperature=0.2,
                )
                content = response.choices[0].message.content.strip()
                if content.startswith("```json"):
                    content = content[7:-3].strip()
                elif content.startswith("```"):
                    content = content[3:-3].strip()

                parsed = json.loads(content)
                if isinstance(parsed, list) and len(parsed) > 0:
                    for item in parsed:
                        b_type = item.get("bias_type", "loss_aversion")
                        sev = item.get("severity", "medium")
                        final_results.append(
                            BiasDetectionResult(
                                bias_type=b_type,
                                confidence=float(item.get("confidence", 0.85)),
                                severity=sev,
                                trigger_source="dialogue_llm",
                                matched_patterns=[],
                                trigger_context={"llm_confirmed": True, "raw": item},
                                intervention=item.get(
                                    "intervention",
                                    CALIBRATED_INTERVENTIONS.get(b_type, {}).get(sev, "Please stay disciplined."),
                                ),
                                cool_off_recommended=bool(item.get("cool_off_recommended", sev == "high")),
                                reasoning=item.get("reasoning"),
                            )
                        )
                    llm_used = True
            except Exception as e:
                logger.warning(f"Layer 2 LLM bias evaluation failed or offline ({e}), falling back to Layer 1.")
                llm_used = False

        # Fallback to Layer 1 if LLM not used or produced no results but heuristic detected
        if not llm_used:
            for d in heuristic_detections:
                interv = CALIBRATED_INTERVENTIONS.get(d.bias_type, {}).get(
                    d.severity,
                    "Let's review your long-term goals before making emotional portfolio changes.",
                )
                cool_off = (d.severity == "high" or d.bias_type == "loss_aversion" and d.score >= 0.80)
                final_results.append(
                    BiasDetectionResult(
                        bias_type=d.bias_type,
                        confidence=d.score,
                        severity=d.severity,
                        trigger_source="dialogue_heuristic",
                        matched_patterns=d.matched_patterns,
                        trigger_context={"heuristic_score": d.score, "patterns": d.matched_patterns},
                        intervention=interv,
                        cool_off_recommended=cool_off,
                        reasoning=f"Detected linguistic markers for {d.bias_type} with confidence {d.score:.2f}.",
                    )
                )

        # Database persistence and profile sync if db provided
        if db and final_results:
            for res in final_results:
                await self.record_bias_event(
                    db=db,
                    client_id=client_id,
                    bias_type=res.bias_type,
                    severity=res.severity,
                    trigger_context=res.trigger_context,
                    intervention_text=res.intervention,
                )

        return final_results

    async def analyze_message(self, message: str) -> List[Dict[str, Any]]:
        """
        Backwards-compatible interface supporting main.py / WebSocket chat handler.
        Returns a list of dicts: [{"bias_type": ..., "confidence": ..., "intervention": ...}].
        """
        results = await self.detect_bias(client_id="anonymous", user_message=message)
        return [
            {
                "bias_type": r.bias_type,
                "confidence": r.confidence,
                "severity": r.severity,
                "intervention": r.intervention,
                "cool_off_recommended": r.cool_off_recommended,
            }
            for r in results
        ]

    # ------------------------------------------------------------------
    # Telemetry Monitoring Channels
    # ------------------------------------------------------------------

    async def record_portfolio_check(
        self,
        client_id: str,
        db: Optional[AsyncSession] = None,
    ) -> Optional[TelemetrySignal]:
        """
        Tracks user portfolio viewing frequency in cache.
        Returns TelemetrySignal if rapid check threshold (>=3 in 10 mins) is breached.
        """
        cache_key = f"telemetry:check_freq:{client_id}"
        now = time.time()
        window_seconds = 600.0  # 10 minutes

        timestamps_raw = await self.cache.get_json(cache_key)
        timestamps: List[float] = timestamps_raw if isinstance(timestamps_raw, list) else []

        # Filter out timestamps older than 10 minutes
        active_timestamps = [t for t in timestamps if now - t <= window_seconds]
        active_timestamps.append(now)

        await self.cache.set_json(cache_key, active_timestamps, expire=int(window_seconds))

        count = len(active_timestamps)
        if count >= 3:
            severity = "high" if count >= 5 else "medium"
            signal = TelemetrySignal(
                signal_type="rapid_checks",
                detected=True,
                bias_type="loss_aversion",
                severity=severity,
                metrics={"check_count": count, "window_seconds": int(window_seconds)},
                intervention=(
                    f"You have viewed your portfolio {count} times in the past 10 minutes. "
                    "Research shows frequent monitoring significantly elevates emotional anxiety "
                    "and the probability of premature panic selling. We encourage setting a regular review cadence."
                ),
                cool_off_recommended=(severity == "high"),
            )

            if db:
                await self.record_bias_event(
                    db=db,
                    client_id=client_id,
                    bias_type="loss_aversion",
                    severity=severity,
                    trigger_context=signal.metrics,
                    intervention_text=signal.intervention or "",
                )

            return signal

        return None

    def check_panic_dip_sell(
        self,
        trade_side: str,
        symbol: str,
        asset_price_change_24h: float,
        market_change_24h: Optional[float] = None,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if a trade represents emotional panic selling after a price decline (<= -3.0%).
        """
        if trade_side.upper() == "SELL" and (asset_price_change_24h <= -3.0 or (market_change_24h and market_change_24h <= -2.0)):
            drop_pct = abs(asset_price_change_24h)
            return TelemetrySignal(
                signal_type="panic_dip_sell",
                detected=True,
                bias_type="loss_aversion",
                severity="high",
                metrics={
                    "trade_side": "SELL",
                    "symbol": symbol,
                    "asset_price_change_24h": asset_price_change_24h,
                    "market_change_24h": market_change_24h,
                },
                intervention=(
                    f"Selling {symbol} following a {drop_pct:.1f}% decline crystallizes temporary paper losses. "
                    "Historically, knee-jerk exits during market dips result in missing subsequent recoveries. "
                    "A 24-hour cool-off reflection period is strongly advised before executing."
                ),
                cool_off_recommended=True,
            )
        return None

    def check_concentration_bias(
        self,
        positions: Dict[str, float],
        total_value: float,
        threshold: float = 0.25,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if any single non-cash position exceeds the concentration threshold (> 25%).
        """
        if total_value <= 0:
            return None

        for sym, pos_val in positions.items():
            if sym.upper() in {"CASH", "USD"}:
                continue
            weight = pos_val / total_value
            if weight > threshold:
                sev = "high" if weight > 0.40 else "medium"
                return TelemetrySignal(
                    signal_type="concentration_risk",
                    detected=True,
                    bias_type="overconfidence",
                    severity=sev,
                    metrics={"symbol": sym, "weight": round(weight, 4), "position_value": pos_val, "total_value": total_value},
                    intervention=(
                        f"{sym} constitutes {weight * 100:.1f}% of your total portfolio value. "
                        "Heavy single-asset concentration exposes your wealth to uncompensated idiosyncratic risk. "
                        "Reallocating toward diversified asset classes protects long-term capital."
                    ),
                    cool_off_recommended=(sev == "high"),
                )
        return None

    def check_trading_frequency(
        self,
        trades_count_recent: int,
        window_hours: int = 24,
        threshold: int = 5,
    ) -> Optional[TelemetrySignal]:
        """
        Checks if trading count over a recent window indicates hyperactive trading (>= 5 trades).
        """
        if trades_count_recent >= threshold:
            sev = "high" if trades_count_recent >= 8 else "medium"
            return TelemetrySignal(
                signal_type="excessive_trading",
                detected=True,
                bias_type="overconfidence",
                severity=sev,
                metrics={"trades_count": trades_count_recent, "window_hours": window_hours},
                intervention=(
                    f"You have initiated {trades_count_recent} trades in the last {window_hours} hours. "
                    "Hyperactive trading increases friction costs, spreads, and tax drag, and usually reflects "
                    "illusory market timing confidence. Let's pause to verify if these align with your strategic allocation."
                ),
                cool_off_recommended=True,
            )
        return None

    async def evaluate_telemetry(
        self,
        client_id: str,
        telemetry_data: Dict[str, Any],
        db: Optional[AsyncSession] = None,
    ) -> List[TelemetrySignal]:
        """Evaluates all incoming telemetry signals and optionally persists detected events."""
        signals: List[TelemetrySignal] = []

        # 1. Panic dip sell check
        if "trade_side" in telemetry_data and "asset_price_change_24h" in telemetry_data:
            sig = self.check_panic_dip_sell(
                trade_side=telemetry_data["trade_side"],
                symbol=telemetry_data.get("symbol", "ASSET"),
                asset_price_change_24h=float(telemetry_data["asset_price_change_24h"]),
                market_change_24h=telemetry_data.get("market_change_24h"),
            )
            if sig:
                signals.append(sig)

        # 2. Concentration risk check
        if "positions" in telemetry_data and "total_value" in telemetry_data:
            sig = self.check_concentration_bias(
                positions=telemetry_data["positions"],
                total_value=float(telemetry_data["total_value"]),
                threshold=telemetry_data.get("threshold", 0.25),
            )
            if sig:
                signals.append(sig)

        # 3. Excessive trading check
        if "trades_count_recent" in telemetry_data:
            sig = self.check_trading_frequency(
                trades_count_recent=int(telemetry_data["trades_count_recent"]),
                window_hours=int(telemetry_data.get("window_hours", 24)),
                threshold=int(telemetry_data.get("threshold", 5)),
            )
            if sig:
                signals.append(sig)

        # 4. Rapid checks check (if portfolio_checked is True)
        if telemetry_data.get("portfolio_checked"):
            sig = await self.record_portfolio_check(client_id, db=None)
            if sig:
                signals.append(sig)

        # Persist signals if db provided
        if db and signals:
            for s in signals:
                if s.bias_type:
                    await self.record_bias_event(
                        db=db,
                        client_id=client_id,
                        bias_type=s.bias_type,
                        severity=s.severity,
                        trigger_context=s.metrics,
                        intervention_text=s.intervention or "",
                    )

        return signals

    # ------------------------------------------------------------------
    # Database Persistence & Profile Synchronization
    # ------------------------------------------------------------------

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
        Persists a detected bias event to behavioral_memory and updates DBClientProfile.
        """
        memory_record = DBBehavioralMemory(
            client_id=client_id,
            bias_type=bias_type,
            severity=severity,
            trigger_context=trigger_context,
            intervention_text=intervention_text,
            timestamp=datetime.utcnow(),
        )
        db.add(memory_record)

        # Synchronize DBClientProfile if client exists
        result = await db.execute(
            select(DBClientProfile).where(DBClientProfile.client_id == client_id)
        )
        client_profile = result.scalars().first()

        if client_profile:
            # 1. Update detected_biases
            existing_biases = list(client_profile.detected_biases or [])
            if bias_type not in existing_biases:
                existing_biases.append(bias_type)
                client_profile.detected_biases = existing_biases

            # 2. Increment emotional_risk_score
            delta_emotional = 20.0 if severity == "high" else (12.0 if severity == "medium" else 5.0)
            cur_emotional = float(client_profile.emotional_risk_score or 0.0)
            client_profile.emotional_risk_score = min(100.0, cur_emotional + delta_emotional)

            # 3. Elevate panic_sell_likelihood if loss aversion
            if bias_type == "loss_aversion":
                delta_panic = 0.15 if severity == "high" else 0.08
                cur_panic = float(client_profile.panic_sell_likelihood or 0.0)
                client_profile.panic_sell_likelihood = min(1.0, round(cur_panic + delta_panic, 3))

        await db.commit()
        await db.refresh(memory_record)
        return memory_record

    async def get_bias_history(
        self,
        db: AsyncSession,
        client_id: str,
        limit: int = 50,
    ) -> List[DBBehavioralMemory]:
        """Retrieves chronological history of detected biases for a client."""
        result = await db.execute(
            select(DBBehavioralMemory)
            .where(DBBehavioralMemory.client_id == client_id)
            .order_by(DBBehavioralMemory.timestamp.desc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def get_client_bias_profile(
        self,
        db: AsyncSession,
        client_id: str,
    ) -> Dict[str, Any]:
        """Returns an aggregated summary profile of client behavioral tendencies."""
        history = await self.get_bias_history(db, client_id, limit=100)
        profile_res = await db.execute(
            select(DBClientProfile).where(DBClientProfile.client_id == client_id)
        )
        client_profile = profile_res.scalars().first()

        bias_counts: Dict[str, int] = {}
        for h in history:
            bias_counts[h.bias_type] = bias_counts.get(h.bias_type, 0) + 1

        return {
            "client_id": client_id,
            "total_bias_events": len(history),
            "bias_distribution": bias_counts,
            "emotional_risk_score": getattr(client_profile, "emotional_risk_score", 0.0) if client_profile else 0.0,
            "panic_sell_likelihood": getattr(client_profile, "panic_sell_likelihood", 0.0) if client_profile else 0.0,
            "primary_biases": list(bias_counts.keys()),
        }

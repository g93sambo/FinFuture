"""
backend/agents/product_comparison.py
====================================
Six-factor composite scoring engine for ETFs and Fixed Income instruments,
with compliance suitability pre-filtering (SUIT-001) and ranked comparative rationales.
"""

from __future__ import annotations

import os
import math
import logging
from typing import Optional, List, Dict, Any, Tuple

import pandas as pd
from pydantic import BaseModel, Field

from agents.market_data import MarketDataAgent
from services.providers.screener import AssetScreenerProvider, AssetMetadata

logger = logging.getLogger("wealth_advisor.agents.product_comparison")


class FactorScores(BaseModel):
    expense_ratio_score: float = Field(..., ge=0.0, le=10.0)
    tracking_error_score: float = Field(..., ge=0.0, le=10.0)
    liquidity_score: float = Field(..., ge=0.0, le=10.0)
    aum_scale_score: float = Field(..., ge=0.0, le=10.0)
    historical_return_score: float = Field(..., ge=0.0, le=10.0)
    reputation_score: float = Field(..., ge=0.0, le=10.0)
    raw_metrics: Dict[str, Any] = Field(default_factory=dict)


class ProductComparisonItem(BaseModel):
    symbol: str
    name: str
    asset_class: str
    sub_category: str
    risk_level: int
    composite_score: float = Field(..., ge=0.0, le=10.0)
    rank: int = 1
    is_suitable: bool = True
    suitability_reason: Optional[str] = None
    factor_breakdown: FactorScores
    key_advantages: List[str] = Field(default_factory=list)
    key_risks: List[str] = Field(default_factory=list)


class ComparisonReport(BaseModel):
    category: str  # "ETF" | "BOND"
    client_id: Optional[str] = None
    client_risk_tier: int = 3
    ranked_products: List[ProductComparisonItem] = Field(default_factory=list)
    unsuitable_products: List[ProductComparisonItem] = Field(default_factory=list)
    winner_symbol: str
    summary_rationale: str
    methodology: str = "Six-factor composite weighting (0.30/0.15/0.20/0.10/0.15/0.10)"


class ProductComparisonAgent:
    """
    Multi-criteria quantitative evaluation and ranking engine for ETFs and Bonds.
    """

    FACTOR_WEIGHTS = {
        "expense_ratio": 0.30,
        "tracking_error": 0.15,
        "liquidity": 0.20,
        "aum_scale": 0.10,
        "historical_return": 0.15,
        "reputation": 0.10,
    }

    def __init__(
        self,
        market_data_agent: Optional[MarketDataAgent] = None,
        screener_provider: Optional[AssetScreenerProvider] = None,
        openai_api_key: Optional[str] = None,
        openai_model: Optional[str] = None,
    ) -> None:
        self.market_data = market_data_agent or MarketDataAgent()
        self.screener = screener_provider or AssetScreenerProvider()
        self.openai_api_key = openai_api_key or os.getenv("OPENAI_API_KEY")
        try:
            from core.config import settings
            default_model = getattr(settings, "openai_model", "gpt-4o")
        except Exception:
            default_model = "gpt-4o"
        self.openai_model = openai_model or os.getenv("OPENAI_MODEL", default_model)

    # ------------------------------------------------------------------
    # Factor Scoring Engine
    # ------------------------------------------------------------------

    def score_expense_ratio(self, expense_ratio: float) -> float:
        """
        Calculates normalized expense ratio score s1 in [0.0, 10.0].
        Lower expense ratio produces strictly higher score.
        Formula: max(0.0, min(10.0, 10.0 - 1000.0 * expense_ratio))
        """
        score = 10.0 - (1000.0 * max(0.0, expense_ratio))
        return round(max(0.0, min(10.0, score)), 2)

    def score_tracking_error(
        self,
        returns_series: Optional[pd.Series],
        benchmark_series: Optional[pd.Series],
        asset_class: str = "equity",
        sub_category: str = "",
    ) -> Tuple[float, float]:
        """
        Calculates tracking error and normalized score s2 in [0.0, 10.0].
        Formula: max(0.0, min(10.0, 10.0 - 500.0 * TE))
        """
        te = 0.0015  # 15 bps default
        if returns_series is not None and benchmark_series is not None and len(returns_series) > 10:
            try:
                aligned = pd.concat([returns_series, benchmark_series], axis=1).dropna()
                if len(aligned) > 10:
                    diff = aligned.iloc[:, 0] - aligned.iloc[:, 1]
                    te = float(diff.std() * math.sqrt(252))
            except Exception:
                pass
        elif asset_class == "fixed_income":
            te = 0.0010
        elif "large_cap" in sub_category or "total_market" in sub_category:
            te = 0.0005

        score = 10.0 - (500.0 * te)
        return round(max(0.0, min(10.0, score)), 2), round(te, 6)

    def score_liquidity(
        self,
        quote: Optional[Any],
        aum_billions: float,
    ) -> Tuple[float, float, float]:
        """
        Calculates liquidity score s3 based on bid-ask spread (65%) and trading volume (35%).
        """
        if quote is None and aum_billions >= 100.0:
            spread_pct = 0.00015  # Institutional 1.5 bps default for mega-cap funds without live quote
        else:
            spread_pct = 0.0005  # 5 bps default
        volume = max(100.0, aum_billions * 50_000)

        if quote:
            bid = getattr(quote, "bid_price", None) or getattr(quote, "bid", None)
            ask = getattr(quote, "ask_price", None) or getattr(quote, "ask", None)
            price = getattr(quote, "price", None) or getattr(quote, "last_price", 100.0)
            q_vol = getattr(quote, "volume", None)

            if bid and ask and ask > bid and price and price > 0:
                spread_pct = (ask - bid) / price
            if q_vol and q_vol > 0:
                volume = float(q_vol)

        s_spread = max(0.0, min(10.0, 10.0 - 4000.0 * spread_pct))
        s_volume = max(1.0, min(10.0, 2.0 * math.log10(max(100.0, volume)) - 4.0))

        s_liquidity = 0.65 * s_spread + 0.35 * s_volume
        return round(max(0.0, min(10.0, s_liquidity)), 2), spread_pct, volume

    def score_aum(self, aum_billions: float) -> float:
        """
        Calculates AUM scale score s4 in [1.0, 10.0].
        """
        if aum_billions >= 50.0:
            return 10.0
        elif aum_billions >= 10.0:
            return 9.0
        elif aum_billions >= 2.0:
            return 7.5
        elif aum_billions >= 0.5:
            return 6.0
        elif aum_billions >= 0.1:
            return 4.5
        else:
            return 2.0

    def score_historical_return(
        self,
        returns_series: Optional[pd.Series],
        asset_class: str = "equity",
        yield_30d: float = 0.02,
    ) -> Tuple[float, float]:
        """
        Calculates historical return score s5 in [0.0, 10.0].
        Formula: max(0.0, min(10.0, 5.0 + 20.0 * R_1y))
        """
        if returns_series is not None and len(returns_series) > 10:
            try:
                # Cumulative return
                r_cum = float((1.0 + returns_series).prod() - 1.0)
                if len(returns_series) < 252:
                    if 1.0 + r_cum > 0:
                        r_1y = float((1.0 + r_cum) ** (252.0 / len(returns_series)) - 1.0)
                    else:
                        r_1y = -1.0
                else:
                    r_1y = r_cum
            except Exception:
                r_1y = 0.10 if asset_class == "equity" else 0.04
        else:
            r_1y = (yield_30d + 0.05) if asset_class == "equity" else (yield_30d + 0.01)

        score = 5.0 + (20.0 * r_1y)
        return round(max(0.0, min(10.0, score)), 2), round(r_1y, 4)

    def score_reputation(self, name: str, symbol: str) -> float:
        """
        Calculates manager reputation score s6 based on institutional tiering.
        """
        s = f"{name} {symbol}".lower()
        if any(b in s for b in ["vanguard", "blackrock", "ishares", "spdr", "state street", "webank", "gba"]):
            return 10.0
        elif any(b in s for b in ["invesco", "schwab", "charles schwab", "fidelity"]):
            return 8.5
        elif any(b in s for b in ["first trust", "wisdomtree", "vaneck", "proshares"]):
            return 7.0
        else:
            return 5.0

    def score_product(
        self,
        metadata: AssetMetadata,
        quote: Optional[Any],
        returns_series: Optional[pd.Series],
        benchmark_series: Optional[pd.Series],
    ) -> Tuple[float, FactorScores]:
        """
        Calculates 6-factor composite score and returns (composite_score, factor_breakdown).
        """
        # 1. Expense ratio (0.30)
        s_exp = self.score_expense_ratio(metadata.expense_ratio)

        # 2. Tracking error (0.15)
        s_te, te_val = self.score_tracking_error(
            returns_series, benchmark_series, metadata.asset_class, metadata.sub_category
        )

        # 3. Liquidity (0.20)
        s_liq, spread_pct, vol = self.score_liquidity(quote, metadata.aum_billions)

        # 4. AUM Scale (0.10)
        s_aum = self.score_aum(metadata.aum_billions)

        # 5. Historical return (0.15)
        s_ret, r_1y = self.score_historical_return(
            returns_series, metadata.asset_class, metadata.yield_30d
        )

        # 6. Reputation (0.10)
        s_rep = self.score_reputation(metadata.name, metadata.symbol)

        # Composite score
        composite = (
            0.30 * s_exp
            + 0.15 * s_te
            + 0.20 * s_liq
            + 0.10 * s_aum
            + 0.15 * s_ret
            + 0.10 * s_rep
        )
        composite = round(max(0.0, min(10.0, composite)), 2)

        breakdown = FactorScores(
            expense_ratio_score=s_exp,
            tracking_error_score=s_te,
            liquidity_score=s_liq,
            aum_scale_score=s_aum,
            historical_return_score=s_ret,
            reputation_score=s_rep,
            raw_metrics={
                "expense_ratio": metadata.expense_ratio,
                "tracking_error": te_val,
                "spread_pct": spread_pct,
                "volume": vol,
                "aum_billions": metadata.aum_billions,
                "return_1y": r_1y,
                "yield_30d": metadata.yield_30d,
            },
        )

        return composite, breakdown

    # ------------------------------------------------------------------
    # Suitability Pre-Filtering (SUIT-001)
    # ------------------------------------------------------------------

    def evaluate_suitability(
        self,
        metadata: AssetMetadata,
        profile: Optional[Any],
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifies product risk level and duration compatibility against client profile.
        Satisfies SUIT-001 compliance invariant.
        """
        if not profile:
            return True, None

        # Extract risk tolerance score and category
        score = 5.0
        cat = "Moderate"
        horizon = 10

        if isinstance(profile, dict):
            score = float(profile.get("risk_tolerance_score", 5.0))
            cat = profile.get("suitability_category", "Moderate")
            horizon = int(profile.get("investment_horizon_years", 10))
        else:
            score = float(getattr(profile, "risk_tolerance_score", 5.0))
            cat = getattr(profile, "suitability_category", "Moderate")
            horizon = int(getattr(profile, "investment_horizon_years", 10))

        # Map to maximum allowed product risk level (1 to 5)
        if score <= 2.5 or cat == "Conservative":
            max_risk_level = 1
        elif score <= 4.5 or cat == "Moderate Conservative":
            max_risk_level = 2
        elif score <= 6.5 or cat == "Moderate":
            max_risk_level = 3
        elif score <= 8.5 or cat == "Growth":
            max_risk_level = 4
        else:
            max_risk_level = 5

        # 1. Product Risk Level Check
        if metadata.risk_level > max_risk_level:
            return (
                False,
                f"Product risk level ({metadata.risk_level}) exceeds client maximum allowed risk tier ({max_risk_level})",
            )

        # 2. Fixed Income Duration vs Horizon Check
        if metadata.asset_class == "fixed_income" and metadata.duration:
            if horizon < 3 and metadata.duration > 7.0:
                return (
                    False,
                    f"Product duration ({metadata.duration:.1f}y) exceeds short-term investment horizon ({horizon}y)",
                )

        return True, None

    # ------------------------------------------------------------------
    # Comparison Pipelines
    # ------------------------------------------------------------------

    def _derive_advantages_and_risks(
        self,
        metadata: AssetMetadata,
        scores: FactorScores,
    ) -> Tuple[List[str], List[str]]:
        """Derives bullet points for key advantages and risks based on factor breakdown."""
        advantages = []
        risks = []

        if scores.expense_ratio_score >= 9.0:
            advantages.append(f"Ultra-low expense ratio ({metadata.expense_ratio * 100:.2f}%)")
        elif scores.expense_ratio_score < 6.0:
            risks.append(f"Higher expense ratio ({metadata.expense_ratio * 100:.2f}%) creates cost drag")

        if scores.aum_scale_score >= 9.0:
            advantages.append(f"Institutional scale (${metadata.aum_billions:.1f}B AUM)")
        elif scores.aum_scale_score <= 4.5:
            risks.append("Smaller fund size carries liquidity and closure risk")

        if scores.liquidity_score >= 8.5:
            advantages.append("Exceptional market liquidity with tight bid-ask spreads")

        if metadata.risk_level >= 4:
            risks.append("Elevated equity market volatility")
        elif metadata.asset_class == "fixed_income" and metadata.duration and metadata.duration > 10.0:
            risks.append(f"High sensitivity to interest rate fluctuations ({metadata.duration}y duration)")

        return advantages, risks

    async def _execute_comparison_pipeline(
        self,
        symbols: List[str],
        category: str,
        profile: Optional[Any] = None,
        client_id: Optional[str] = None,
    ) -> ComparisonReport:
        """Core comparison execution pipeline shared by ETFs and Bonds."""
        if not symbols:
            raise ValueError("Symbols list must not be empty.")

        client_risk_tier = 3
        if profile:
            score = profile.get("risk_tolerance_score", 5.0) if isinstance(profile, dict) else getattr(profile, "risk_tolerance_score", 5.0)
            if score <= 2.5:
                client_risk_tier = 1
            elif score <= 4.5:
                client_risk_tier = 2
            elif score <= 6.5:
                client_risk_tier = 3
            elif score <= 8.5:
                client_risk_tier = 4
            else:
                client_risk_tier = 5

        # Fetch market data history for tracking error and returns
        history_df = None
        try:
            history_df = await self.market_data.get_history(symbols, period="1y")
        except Exception as e:
            logger.warning(f"Could not retrieve price history for {symbols}: {e}")

        # Benchmark mapping
        benchmark_symbol = "SPY" if category == "ETF" else "BND"
        benchmark_series = None
        if history_df is not None and benchmark_symbol in history_df.columns:
            benchmark_series = history_df[benchmark_symbol].pct_change().dropna()

        all_items: List[ProductComparisonItem] = []
        suitable_items: List[ProductComparisonItem] = []
        unsuitable_items: List[ProductComparisonItem] = []

        for sym in symbols:
            sym_clean = sym.strip().upper()
            metadata = self.screener.get_by_symbol(sym_clean)
            if not metadata:
                # Fallback synthesized metadata
                metadata = AssetMetadata(
                    symbol=sym_clean,
                    name=f"{sym_clean} Fund",
                    asset_class="fixed_income" if category == "BOND" else "equity",
                    sub_category="broad_market",
                    expense_ratio=0.0010,
                    aum_billions=10.0,
                    yield_30d=0.03,
                    risk_level=2 if category == "BOND" else 3,
                )

            # Check suitability pre-filtering
            is_suitable, reason = self.evaluate_suitability(metadata, profile)

            # Get quote
            quote = None
            try:
                quote = await self.market_data.get_quote(sym_clean)
            except Exception:
                pass

            # Returns series
            returns_series = None
            if history_df is not None and sym_clean in history_df.columns:
                returns_series = history_df[sym_clean].pct_change().dropna()

            # Score product
            composite_score, factor_breakdown = self.score_product(
                metadata=metadata,
                quote=quote,
                returns_series=returns_series,
                benchmark_series=benchmark_series,
            )

            advantages, risks = self._derive_advantages_and_risks(metadata, factor_breakdown)

            item = ProductComparisonItem(
                symbol=sym_clean,
                name=metadata.name,
                asset_class=metadata.asset_class,
                sub_category=metadata.sub_category,
                risk_level=metadata.risk_level,
                composite_score=composite_score,
                rank=1,
                is_suitable=is_suitable,
                suitability_reason=reason,
                factor_breakdown=factor_breakdown,
                key_advantages=advantages,
                key_risks=risks,
            )

            if is_suitable:
                suitable_items.append(item)
            else:
                unsuitable_items.append(item)
            all_items.append(item)

        # Rank suitable items by composite score descending
        suitable_items.sort(key=lambda x: x.composite_score, reverse=True)
        for idx, item in enumerate(suitable_items):
            item.rank = idx + 1

        # Winner selection
        if suitable_items:
            winner_symbol = suitable_items[0].symbol
        elif all_items:
            all_items.sort(key=lambda x: x.composite_score, reverse=True)
            winner_symbol = all_items[0].symbol
        else:
            winner_symbol = symbols[0].upper()

        summary_rationale = await self.generate_rationale(
            ranked=suitable_items,
            unsuitable=unsuitable_items,
            profile=profile,
            category=category,
        )

        return ComparisonReport(
            category=category,
            client_id=client_id,
            client_risk_tier=client_risk_tier,
            ranked_products=suitable_items,
            unsuitable_products=unsuitable_items,
            winner_symbol=winner_symbol,
            summary_rationale=summary_rationale,
        )

    async def compare_etfs(
        self,
        symbols: List[str],
        profile: Optional[Any] = None,
        client_id: Optional[str] = None,
    ) -> ComparisonReport:
        """Executes full ETF comparison pipeline with suitability pre-filtering."""
        return await self._execute_comparison_pipeline(
            symbols=symbols, category="ETF", profile=profile, client_id=client_id
        )

    async def compare_bonds(
        self,
        symbols: List[str],
        profile: Optional[Any] = None,
        client_id: Optional[str] = None,
    ) -> ComparisonReport:
        """Executes full Bond comparison pipeline including duration and credit metrics."""
        return await self._execute_comparison_pipeline(
            symbols=symbols, category="BOND", profile=profile, client_id=client_id
        )

    # ------------------------------------------------------------------
    # Natural Language Rationale Generation
    # ------------------------------------------------------------------

    async def generate_rationale(
        self,
        ranked: List[ProductComparisonItem],
        unsuitable: List[ProductComparisonItem],
        profile: Optional[Any],
        category: str,
    ) -> str:
        """
        Generates comparative natural language rationale with deterministic fallback.
        """
        # If OpenAI is configured, attempt generation
        if self.openai_api_key and self.openai_api_key != "your_openai_api_key_here":
            try:
                from openai import AsyncOpenAI
                client = AsyncOpenAI(api_key=self.openai_api_key)
                prompt = (
                    f"You are a fiduciary AI wealth advisor. Summarize this product comparison for a client:\n"
                    f"Category: {category}\n"
                    f"Suitable Ranked Products: {[f'{p.symbol} (Score: {p.composite_score})' for p in ranked]}\n"
                    f"Unsuitable Products: {[f'{p.symbol} (Reason: {p.suitability_reason})' for p in unsuitable]}\n"
                    f"Provide a concise, 2-paragraph comparative recommendation explaining the top choice."
                )
                resp = await client.chat.completions.create(
                    model=self.openai_model,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.3,
                    max_tokens=250,
                )
                return resp.choices[0].message.content.strip()
            except Exception as e:
                logger.warning(f"OpenAI rationale generation failed ({e}), using deterministic fallback.")

        # Deterministic fallback rationale
        if not ranked:
            return (
                f"None of the evaluated {category} products met the client's current suitability criteria. "
                f"All candidate products were flagged for exceeding risk or horizon thresholds per SUIT-001."
            )

        top = ranked[0]
        top_exp = top.factor_breakdown.raw_metrics.get("expense_ratio", 0.0)
        top_aum = top.factor_breakdown.raw_metrics.get("aum_billions", 0.0)

        unsuitable_msg = ""
        if unsuitable:
            flagged = ", ".join(f"{u.symbol} ({u.suitability_reason})" for u in unsuitable)
            unsuitable_msg = f" Note: {flagged} were excluded from recommendations due to risk suitability guardrails."

        return (
            f"Among the evaluated {category} options, {top.symbol} ({top.name}) ranks #1 with a composite score "
            f"of {top.composite_score}/10.0. It offers an optimal combination of low expense ratio ({top_exp * 100:.2f}%), "
            f"robust liquidity, and institutional scale (${top_aum:.1f}B AUM).{unsuitable_msg} "
            f"This recommendation aligns with your defined risk profile and investment horizon."
        )

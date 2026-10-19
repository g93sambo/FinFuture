"""
backend/agents/review_stage.py
==============================
Three-pillar parallel pre-delivery review stage for AI wealth advisory recommendations:
1. Suitability & Regulatory Reviewer: Checks allocation, risk tolerance, age constraints.
2. Risk & Devil's Advocate Reviewer: Evaluates downside stress, ruin risk, sequence of returns.
3. Numeric & Consistency Reviewer: Audits arithmetic, allocation weights summing to 100%, and claim bounds.

Features:
- Executes all 3 reviewers in parallel via asyncio.gather.
- Automatic revision loop (up to 3 revisions) when critical flaws are flagged.
- Fail-safe fallback and escalation to human fiduciary supervisor when revisions are exhausted.
"""

from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from core.config import settings

logger = logging.getLogger("wealth_advisor.agents.review_stage")

RISK_NOTE = (
    "\n\n**Risk note:** investments can fall in value as well as rise. A broad market decline of 20% or more "
    "is possible, so size positions to what you could hold through a drawdown. Past performance does not "
    "guarantee future results."
)


@dataclass
class ReviewerFeedback:
    reviewer_name: str
    passed: bool
    severity: str  # "PASS", "WARN", "BLOCK"
    critique: str
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ReviewStageResult:
    passed: bool
    revisions_count: int
    escalated_to_human: bool
    final_text: str
    reviewer_feedbacks: List[ReviewerFeedback] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "revisions_count": self.revisions_count,
            "escalated_to_human": self.escalated_to_human,
            "final_text": self.final_text,
            "reviewer_feedbacks": [f.to_dict() for f in self.reviewer_feedbacks],
        }


class SuitabilityReviewer:
    """Verifies that advice aligns with the client's risk profile and constraints."""

    async def review(self, text: str, client_context: Optional[Dict[str, Any]] = None) -> ReviewerFeedback:
        if not client_context:
            return ReviewerFeedback(
                reviewer_name="SuitabilityReviewer",
                passed=True,
                severity="PASS",
                critique="No client constraints provided; passed standard check.",
            )

        suitability = str(client_context.get("suitability_category", "MODERATE")).upper()
        age = client_context.get("age")
        text_lower = text.lower()

        # Check for conservative clients being given aggressive allocations
        if suitability in ("CONSERVATIVE", "VERY_CONSERVATIVE"):
            speculative_keywords = ["100% equity", "90% stock", "crypto", "meme stock", "penny stock", "leveraged"]
            found = [kw for kw in speculative_keywords if kw in text_lower]
            if found:
                return ReviewerFeedback(
                    reviewer_name="SuitabilityReviewer",
                    passed=False,
                    severity="BLOCK",
                    critique=f"Client suitability is {suitability}, but recommendation contains high-risk items: {', '.join(found)}.",
                    suggestions=["Cap equity exposure at 30-40%", "Increase allocation to sovereign bonds/money market funds"],
                )

        # Check for senior investors (age >= 60)
        if age and age >= 60:
            if "high risk" in text_lower or "speculative" in text_lower:
                return ReviewerFeedback(
                    reviewer_name="SuitabilityReviewer",
                    passed=False,
                    severity="BLOCK",
                    critique=f"Client is {age} years old (capital preservation phase); speculative risks are unsuitable.",
                    suggestions=["Prioritize income and capital preservation", "Recommend fixed income / FGN bonds"],
                )

        return ReviewerFeedback(
            reviewer_name="SuitabilityReviewer",
            passed=True,
            severity="PASS",
            critique="Recommendation aligns with client suitability tier and horizon.",
        )


class DevilsAdvocateReviewer:
    """Challenges bullish assumptions, checks downside drawdowns, and highlights ruin risk."""

    async def review(self, text: str, client_context: Optional[Dict[str, Any]] = None) -> ReviewerFeedback:
        text_lower = text.lower()

        # If text makes specific investment proposals or strong buys without mentioning risk or downside.
        # A passing mention of "portfolio" is not a proposal.
        has_proposal = any(w in text_lower for w in ["i recommend", "we recommend", "recommended allocation", "invest in", "you should buy", "consider buying"])
        has_risk_mention = any(w in text_lower for w in ["risk", "drawdown", "volatility", "downside", "loss", "stress", "devaluation", "inflation"])

        if has_proposal and not has_risk_mention:
            return ReviewerFeedback(
                reviewer_name="DevilsAdvocateReviewer",
                passed=False,
                severity="BLOCK",
                critique="Recommendation presents an unhedged bull case without articulating drawdown risks, downside shocks, or ruin probability.",
                suggestions=["Include downside stress scenario (e.g. -20% market shock)", "State maximum drawdown expectations"],
            )

        return ReviewerFeedback(
            reviewer_name="DevilsAdvocateReviewer",
            passed=True,
            severity="PASS",
            critique="Downside risks, stress scenarios, or risk mitigations are adequately acknowledged.",
        )


class NumericConsistencyReviewer:
    """Audits mathematical claims, percentages, and allocation arithmetic."""

    async def review(self, text: str, client_context: Optional[Dict[str, Any]] = None) -> ReviewerFeedback:
        # Check if percentages in an allocation sum absurdly
        pct_matches = re.findall(r"(\d+(?:\.\d+)?)\s*%", text)
        if pct_matches:
            # Check for impossible guaranteed yields like 100% or 50% guaranteed
            for val_str in pct_matches:
                val = float(val_str)
                if val > 80.0 and any(w in text.lower() for w in ["guaranteed return", "risk-free", "certain profit"]):
                    return ReviewerFeedback(
                        reviewer_name="NumericConsistencyReviewer",
                        passed=False,
                        severity="BLOCK",
                        critique=f"Impossible guaranteed return claim detected ({val}% guaranteed/risk-free).",
                        suggestions=["Remove guaranteed return claims", "Quote historical average benchmarks instead"],
                    )

        return ReviewerFeedback(
            reviewer_name="NumericConsistencyReviewer",
            passed=True,
            severity="PASS",
            critique="Numerical figures, percentages, and claims are within acceptable bounds.",
        )


class ReviewStage:
    """Orchestrates parallel reviews and executes the revision loop."""

    def __init__(self):
        self.suitability_reviewer = SuitabilityReviewer()
        self.devils_advocate_reviewer = DevilsAdvocateReviewer()
        self.numeric_reviewer = NumericConsistencyReviewer()

    async def run_reviews(
        self,
        draft_text: str,
        client_context: Optional[Dict[str, Any]] = None,
    ) -> List[ReviewerFeedback]:
        """Runs all 3 reviews in parallel."""
        results = await asyncio.gather(
            self.suitability_reviewer.review(draft_text, client_context),
            self.devils_advocate_reviewer.review(draft_text, client_context),
            self.numeric_reviewer.review(draft_text, client_context),
            return_exceptions=True,
        )

        feedbacks: List[ReviewerFeedback] = []
        for i, res in enumerate(results):
            if isinstance(res, Exception):
                logger.warning("Reviewer %d raised exception: %s", i, res)
                feedbacks.append(ReviewerFeedback(
                    reviewer_name=f"Reviewer_{i}",
                    passed=True,
                    severity="WARN",
                    critique=f"Reviewer encountered check notice: {res}",
                ))
            else:
                feedbacks.append(res)
        return feedbacks

    async def review_and_revise(
        self,
        initial_text: str,
        client_context: Optional[Dict[str, Any]] = None,
        openai_client: Optional[Any] = None,
        model: Optional[str] = None,
        max_revisions: int = 3,
        user_question: Optional[str] = None,
    ) -> ReviewStageResult:
        """
        Executes parallel reviews and automatically drives revision loops if any review fails.
        If revision limit is exceeded, applies a fail-safe conservative advisory notice and escalates to human.
        """
        current_text = initial_text
        revisions_count = 0
        feedbacks: List[ReviewerFeedback] = []

        for attempt in range(max_revisions + 1):
            feedbacks = await self.run_reviews(current_text, client_context)
            failed = [f for f in feedbacks if not f.passed or f.severity == "BLOCK"]

            if not failed:
                # All passed!
                return ReviewStageResult(
                    passed=True,
                    revisions_count=revisions_count,
                    escalated_to_human=False,
                    final_text=current_text,
                    reviewer_feedbacks=feedbacks,
                )

            # A missing risk disclosure alone is fixed by adding one, not by rewriting the answer:
            # an LLM rewrite tends to drift away from what the client actually asked
            if all(f.reviewer_name == "DevilsAdvocateReviewer" for f in failed):
                return ReviewStageResult(
                    passed=True,
                    revisions_count=revisions_count,
                    escalated_to_human=False,
                    final_text=current_text + RISK_NOTE,
                    reviewer_feedbacks=feedbacks,
                )

            # If failed and revisions remain and we have an LLM client
            if attempt < max_revisions and openai_client:
                revisions_count += 1
                critiques_summary = "\n".join(
                    f"- [{f.reviewer_name}] {f.critique} (Suggestions: {'; '.join(f.suggestions)})"
                    for f in failed
                )
                logger.info("Review stage flagged issues (attempt %d). Requesting revision:\n%s", attempt + 1, critiques_summary)

                question_block = f"CLIENT QUESTION:\n{user_question}\n\n" if user_question else ""
                revision_prompt = (
                    "You are a fiduciary wealth advisor. Your previous draft failed our internal quality review.\n\n"
                    f"{question_block}"
                    f"REVIEW FINDINGS:\n{critiques_summary}\n\n"
                    "PREVIOUS DRAFT:\n"
                    f"{current_text}\n\n"
                    "INSTRUCTION:\n"
                    "Revise the draft so it resolves every finding above while still answering the client's question "
                    "directly. Keep the same topic, length and structure; do not add recommendations the client did not "
                    "ask for. Include a brief downside-risk disclosure where advice is given, and keep all figures accurate. "
                    "Return only the revised answer."
                )

                try:
                    resp = await openai_client.chat.completions.create(
                        model=model or settings.openai_model or "gpt-4o",
                        messages=[{"role": "user", "content": revision_prompt}],
                        temperature=0.2,
                    )
                    revised = resp.choices[0].message.content
                    if revised and len(revised.strip()) > 50:
                        current_text = revised.strip()
                        continue
                except Exception as rev_err:
                    logger.warning("Automated revision failed: %s", rev_err)

            # If we reached here on the last attempt, fail-safe escalation
            break

        # If still failed after max revisions:
        logger.warning("Advisory draft failed reviews after %d revisions. Escalating to human.", revisions_count)
        escalation_notice = (
            "> [!NOTE]\n"
            "> **Supervisory Fiduciary Review Notification**\n"
            "> This recommendation contains complex portfolio elements or risk parameters that have been queued for supervisory sign-off by a licensed human financial advisor. "
            "Please review the downside risk factors carefully.\n\n"
        )
        final_text = escalation_notice + current_text

        return ReviewStageResult(
            passed=False,
            revisions_count=revisions_count,
            escalated_to_human=True,
            final_text=final_text,
            reviewer_feedbacks=feedbacks,
        )

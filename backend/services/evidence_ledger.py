"""
backend/services/evidence_ledger.py
===================================
Auditable Evidence Ledger, Source Provenance, and Clickable Citation Generator.
Milestone 2 (R2, R4 Part A) - Fiduciary & Institutional Research Architecture.

Features:
- EvidenceItem: Validated Pydantic v2 model tracking factual propositions,
  supporting facts, contradictions, confidence scores, and verification status.
- CompetingHypothesis: Evaluates adversarial and alternative operating theses
  with weighted evidence aggregation and fatal dealbreaker detection.
- EvidenceLedger: Complete ledger with SHA-256 content deduplication,
  source corroboration, temporal stratification, clickable markdown citation
  generation, and institutional markdown table exporting.
"""

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Any, Optional, Literal, Union
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

from pydantic import BaseModel, Field, ConfigDict, model_validator

logger = logging.getLogger("wealth_advisor.services.evidence_ledger")

# Canonical Type Enums
VerificationStatus = Literal["VERIFIED", "CONTRADICTED", "UNCONFIRMED"]
EvidencePolarity = Literal["SUPPORTING", "CONTRADICTING", "NEUTRAL"]
SourceType = Literal[
    "SEC_FILING",
    "STATUTORY_PROSPECTUS",
    "MARKET_DATA",
    "MACRO_FEED",
    "WEB_INTELLIGENCE",
    "MATH_SERVICE",
    "OTHER",
]
TemporalStratum = Literal["STATUTORY_CURRENT", "HISTORICAL_ANNUAL", "OUTDATED"]
HypothesisVerdict = Literal["PLAUSIBLE", "UNLIKELY", "FATAL_RISK", "SUPPORTED"]

# Tracking parameters to strip during URL canonicalization
TRACKING_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "ref", "fbclid", "gclid", "msclkid", "session_id", "token"
}


def sanitize_url(raw_url: str) -> str:
    """
    Canonicalizes URL by stripping tracking parameters and standardizing format.
    """
    if not raw_url:
        return ""
    try:
        parsed = urlparse(raw_url.strip())
        if not parsed.scheme or not parsed.netloc:
            return raw_url.strip()
        query_dict = parse_qs(parsed.query)
        cleaned_query = {k: v for k, v in query_dict.items() if k.lower() not in TRACKING_PARAMS}
        new_query = urlencode(cleaned_query, doseq=True)
        return urlunparse((
            parsed.scheme.lower(),
            parsed.netloc.lower(),
            parsed.path.rstrip("/") if parsed.path != "/" else "/",
            parsed.params,
            new_query,
            ""
        ))
    except Exception:
        return raw_url.strip()


def compute_content_hash(text: str) -> str:
    """
    Computes deterministic SHA-256 fingerprint for normalized claim text.
    Collapses whitespace and lowercases string to prevent formatting duplicates.
    """
    if not text:
        return hashlib.sha256(b"").hexdigest()
    normalized = " ".join(text.strip().lower().split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def format_clickable_citation(publisher: str, year: Union[int, str], url: str) -> str:
    """
    Formats a verifiable clickable markdown citation with publisher metadata.
    Enforces secure HTTPS protocol per Feature 12 & test_clickable_citation_generator.
    Example: '[U.S. SEC EDGAR (2024)](https://sec.gov/edgar/data/320193)'
    """
    assert url.startswith("https://"), "Citations must use secure HTTPS URLs"
    clean_publisher = publisher.strip() if publisher else "Unknown Publisher"
    clean_year = str(year).strip() if year else "2024"
    return f"[{clean_publisher} ({clean_year})]({url.strip()})"


class EvidenceItem(BaseModel):
    """
    Atomic evidence record storing an individual factual claim, its provenance,
    supporting/contradicting corroborations, and current verification status.
    Directly implements PROJECT.md §2 Interface Contract and test_tier1_contracts.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, populate_by_name=True)

    id: str = Field(..., description="Unique evidence identifier, e.g. 'ev_001'")
    claim: str = Field(..., description="The factual proposition or metric assertion")
    supporting_facts: List[str] = Field(
        default_factory=list,
        description="Corroborating quotes, data points, or excerpts"
    )
    contradicting_facts: List[str] = Field(
        default_factory=list,
        description="Refuting data points, counterarguments, or dissenting metrics"
    )
    source_urls: List[str] = Field(
        default_factory=list,
        description="List of verified URLs where evidence was extracted"
    )
    publisher: str = Field(..., description="Originating authority or publisher name")
    retrieval_timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of when evidence was ingested"
    )
    confidence_score: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Bounded credibility metric from 0.0 (unreliable) to 1.0 (verified primary filing)"
    )
    verification_status: VerificationStatus = Field(
        default="UNCONFIRMED",
        description="Status state machine: UNCONFIRMED -> VERIFIED or CONTRADICTED"
    )

    # Institutional Enrichment Attributes
    published_date: Optional[str] = Field(
        default=None,
        description="Filing, statement, or article publication date (e.g. '2024-03-15' or '2024')"
    )
    content_hash: str = Field(
        default="",
        description="Deterministic SHA-256 hash of normalized claim text"
    )
    source_type: SourceType = Field(
        default="WEB_INTELLIGENCE",
        description="Categorization of source provider"
    )
    metric_name: Optional[str] = Field(
        default=None,
        description="Standardized financial metric name (e.g. 'revenue', 'yield_3m', 'net_debt')"
    )
    metric_value: Optional[float] = Field(
        default=None,
        description="Numeric metric value if quantitative"
    )
    metric_unit: Optional[str] = Field(
        default=None,
        description="Unit of measurement (e.g. 'USD', 'percentage', 'ratio')"
    )
    polarity: EvidencePolarity = Field(
        default="NEUTRAL",
        description="Initial hypothesis polarity"
    )
    adversarial_notes: Optional[str] = Field(
        default=None,
        description="Observations from Risk & Devil's Advocate persona"
    )

    @model_validator(mode="before")
    @classmethod
    def normalize_inputs(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # Support alias evidence_id -> id
            if "evidence_id" in data and "id" not in data:
                data["id"] = data["evidence_id"]
            # Auto-compute content_hash if missing
            claim_text = data.get("claim", "")
            if not data.get("content_hash") and claim_text:
                data["content_hash"] = compute_content_hash(claim_text)
            # Sanitize source URLs
            if "source_urls" in data and isinstance(data["source_urls"], list):
                data["source_urls"] = [sanitize_url(u) for u in data["source_urls"] if u]
            elif "source_url" in data and data["source_url"]:
                data["source_urls"] = [sanitize_url(data["source_url"])]
        return data

    @property
    def evidence_id(self) -> str:
        """Alias for id ensuring cross-compatibility."""
        return self.id

    @property
    def publication_year(self) -> str:
        """Extracts 4-digit year from published_date or falls back to retrieval year."""
        if self.published_date:
            match = re.search(r"\b(19\d\d|20\d\d)\b", self.published_date)
            if match:
                return match.group(1)
        return str(self.retrieval_timestamp.year)


class CompetingHypothesis(BaseModel):
    """
    Represents an investment thesis, valuation assumption, or macro scenario
    subjected to evidence-driven Bayesian/adversarial evaluation.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    hypothesis_id: str = Field(..., description="Unique identifier, e.g. 'hyp_01'")
    title: str = Field(..., description="Short title of the hypothesis")
    description: str = Field(..., description="Detailed description of the claim/thesis")
    supporting_evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of EvidenceItems supporting this hypothesis"
    )
    contradicting_evidence_ids: List[str] = Field(
        default_factory=list,
        description="IDs of EvidenceItems refuting this hypothesis"
    )
    assigned_probability: float = Field(
        default=0.5,
        ge=0.0,
        le=1.0,
        description="Calculated probability [0.0, 1.0] reflecting net evidentiary weight"
    )
    verdict: HypothesisVerdict = Field(
        default="PLAUSIBLE",
        description="Qualitative assessment: SUPPORTED, PLAUSIBLE, UNLIKELY, or FATAL_RISK"
    )
    dealbreakers_triggered: List[str] = Field(
        default_factory=list,
        description="List of triggered fatal dealbreakers (e.g. 'UNHEDGED_FX_DEBT')"
    )
    notes: Optional[str] = Field(
        default=None,
        description="Analytical synthesis notes"
    )


class EvidenceLedger(BaseModel):
    """
    Auditable Evidence Ledger service maintaining factual integrity,
    source citations, SHA-256 deduplication, and hypothesis resolution.
    Directly satisfies PROJECT.md §2 Interface Contract and Research Orchestrator.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True, validate_assignment=True)

    items: Dict[str, EvidenceItem] = Field(default_factory=dict)
    hash_index: Dict[str, str] = Field(default_factory=dict)
    hypotheses: Dict[str, CompetingHypothesis] = Field(default_factory=dict)

    def add_claim(
        self,
        claim_or_id: str,
        claim_or_source: Any = None,
        source_or_url: Any = None,
        publisher: Optional[str] = None,
        source: Optional[Dict[str, Any]] = None,
        source_url: Optional[str] = None,
        published_date: Optional[str] = None,
        confidence_score: float = 1.0,
        source_type: SourceType = "WEB_INTELLIGENCE",
        metric_name: Optional[str] = None,
        metric_value: Optional[float] = None,
        metric_unit: Optional[str] = None,
        **kwargs: Any
    ) -> str:
        """
        Ingests a factual proposition with SHA-256 deduplication and source corroboration.
        Supports both signatures:
        1. add_claim(claim, source={...}) -> returns generated claim_id
        2. add_claim(claim_id, claim, source_url, publisher) -> stores with explicit ID
        """
        # Signature Disambiguation
        if claim_or_source is not None and isinstance(claim_or_source, str):
            # Called as add_claim(claim_id, claim, source_url, publisher)
            claim_id = claim_or_id.strip()
            claim_text = claim_or_source.strip()
            url_str = (
                source_url
                or (source_or_url if isinstance(source_or_url, str) and source_or_url.startswith("http") else None)
                or (source.get("url") if isinstance(source, dict) else None)
            )
            if "source_urls" in kwargs:
                source_urls_raw = kwargs["source_urls"]
            else:
                source_urls_raw = [url_str] if url_str else []
            pub = (
                publisher
                or (source_or_url if isinstance(source_or_url, str) and not source_or_url.startswith("http") else None)
                or kwargs.get("publisher")
                or "Unknown Publisher"
            )
        else:
            # Called as add_claim(claim, source={...})
            claim_text = claim_or_id.strip()
            src_dict = (
                (claim_or_source if isinstance(claim_or_source, dict) else None)
                or (source_or_url if isinstance(source_or_url, dict) else None)
                or source
                or kwargs.get("source")
                or {}
            )
            claim_id = src_dict.get("id") or kwargs.get("id") or kwargs.get("claim_id")
            source_urls_raw = src_dict.get("source_urls") or ([src_dict["url"]] if "url" in src_dict else [])
            if source_url:
                source_urls_raw.append(source_url)
            elif isinstance(source_or_url, str) and source_or_url.startswith("http"):
                source_urls_raw.append(source_or_url)
            pub = src_dict.get("publisher") or publisher or kwargs.get("publisher") or "Unknown Publisher"
            published_date = published_date or src_dict.get("published_date") or src_dict.get("date")

        if not claim_text:
            raise ValueError("Claim text cannot be empty.")

        # Compute SHA-256 fingerprint of normalized claim
        content_hash = compute_content_hash(claim_text)

        # Check for duplicate claim in hash index (SHA-256 deduplication)
        if content_hash in self.hash_index:
            existing_id = self.hash_index[content_hash]
            existing_item = self.items[existing_id]
            # Corroborate: merge source URLs
            for s_url in source_urls_raw:
                cleaned_u = sanitize_url(s_url)
                if cleaned_u and cleaned_u not in existing_item.source_urls:
                    existing_item.source_urls.append(cleaned_u)
            # Boost confidence slightly on corroboration
            existing_item.confidence_score = min(1.0, existing_item.confidence_score + 0.05)
            logger.info("Deduplicated claim [%s]. Corroborated with new source.", existing_id)
            return existing_id

        # Determine definitive item ID
        final_id = claim_id if claim_id else f"ev_{content_hash[:8]}"
        if final_id in self.items and self.items[final_id].content_hash != content_hash:
            final_id = f"{final_id}_{content_hash[:6]}"

        clean_urls = [sanitize_url(u) for u in source_urls_raw if u]

        item = EvidenceItem(
            id=final_id,
            claim=claim_text,
            source_urls=clean_urls,
            publisher=pub,
            confidence_score=max(0.0, min(1.0, confidence_score)),
            verification_status="UNCONFIRMED",
            published_date=published_date,
            content_hash=content_hash,
            source_type=source_type,
            metric_name=metric_name,
            metric_value=metric_value,
            metric_unit=metric_unit,
        )

        self.items[final_id] = item
        self.hash_index[content_hash] = final_id
        return final_id

    def add_contradiction(
        self,
        claim_id: str,
        contradiction: str,
        source: Optional[Dict[str, Any]] = None,
        source_url: Optional[str] = None,
        publisher: Optional[str] = None,
    ) -> None:
        """
        Records a dissenting fact, counterargument, or refutation against an existing claim.
        Transitions claim status to 'CONTRADICTED' and decrements confidence score.
        """
        if claim_id not in self.items:
            raise KeyError(f"Claim ID '{claim_id}' not found in evidence ledger.")

        if not contradiction or not contradiction.strip():
            raise ValueError("Contradiction text cannot be empty.")

        item = self.items[claim_id]
        item.contradicting_facts.append(contradiction.strip())
        item.verification_status = "CONTRADICTED"

        # Apply confidence penalty on contradiction
        item.confidence_score = max(0.1, round(item.confidence_score * 0.5, 2))

        # Append source if provided
        src_url = source_url or (source.get("url") if source else None)
        if src_url:
            clean_u = sanitize_url(src_url)
            if clean_u and clean_u not in item.source_urls:
                item.source_urls.append(clean_u)

        logger.warning(
            "Claim [%s] contradicted by: '%s'. Status set to CONTRADICTED.",
            claim_id, contradiction
        )

    def verify_claim(self, claim_id: str, confidence_score: Optional[float] = None) -> None:
        """
        Marks an existing claim as VERIFIED by primary statutory or audited source.
        """
        if claim_id not in self.items:
            raise KeyError(f"Claim ID '{claim_id}' not found in evidence ledger.")

        item = self.items[claim_id]
        item.verification_status = "VERIFIED"
        if confidence_score is not None:
            item.confidence_score = max(0.0, min(1.0, confidence_score))
        else:
            item.confidence_score = max(item.confidence_score, 0.95)

    def add_hypothesis(self, hypothesis: Union[CompetingHypothesis, Dict[str, Any]]) -> str:
        """
        Registers a competing hypothesis for adversarial resolution.
        """
        if isinstance(hypothesis, dict):
            hyp = CompetingHypothesis(**hypothesis)
        else:
            hyp = hypothesis
        self.hypotheses[hyp.hypothesis_id] = hyp
        return hyp.hypothesis_id

    def resolve_competing_hypotheses(
        self,
        hypotheses: Optional[List[CompetingHypothesis]] = None
    ) -> Dict[str, Any]:
        """
        Weighs supporting vs contradicting evidence across competing hypotheses.
        Calculates normalized probabilities and detects fatal dealbreakers.
        Returns resolution summary with dominant hypothesis verdict.
        """
        active_hypotheses = hypotheses if hypotheses is not None else list(self.hypotheses.values())
        if not active_hypotheses:
            return {"dominant_hypothesis": None, "hypotheses": []}

        fatal_keywords = {
            "unhedged fx", "fx mismatch", "unaudited", "insolvency", "ruin",
            "fraud", "default", "breach", "going concern", "fatal"
        }

        evaluations = []
        for hyp in active_hypotheses:
            support_weight = 0.0
            for ev_id in hyp.supporting_evidence_ids:
                if ev_id in self.items:
                    ev = self.items[ev_id]
                    if ev.verification_status == "VERIFIED":
                        support_weight += ev.confidence_score * 1.5
                    elif ev.verification_status == "UNCONFIRMED":
                        support_weight += ev.confidence_score * 0.8

            contradict_weight = 0.0
            dealbreakers = []
            for ev_id in hyp.contradicting_evidence_ids:
                if ev_id in self.items:
                    ev = self.items[ev_id]
                    contra_mult = 2.0 if ev.verification_status == "CONTRADICTED" else 1.0
                    contradict_weight += ev.confidence_score * contra_mult

                    combined_contra_text = " ".join(ev.contradicting_facts).lower()
                    for kw in fatal_keywords:
                        if kw in combined_contra_text or kw in ev.claim.lower():
                            if kw.upper() not in dealbreakers:
                                dealbreakers.append(kw.upper())

            total_weight = support_weight + contradict_weight + 0.05
            raw_prob = (support_weight + 0.025) / total_weight

            # Enforce Fatal Dealbreaker Rule
            if dealbreakers:
                hyp.dealbreakers_triggered = dealbreakers
                hyp.verdict = "FATAL_RISK"
                hyp.assigned_probability = min(0.05, round(raw_prob * 0.1, 4))
            elif contradict_weight > support_weight * 1.5:
                hyp.verdict = "UNLIKELY"
                hyp.assigned_probability = round(min(0.25, raw_prob), 4)
            elif support_weight >= 1.5 and contradict_weight == 0.0:
                hyp.verdict = "SUPPORTED"
                hyp.assigned_probability = round(max(0.75, raw_prob), 4)
            else:
                hyp.verdict = "PLAUSIBLE"
                hyp.assigned_probability = round(raw_prob, 4)

            self.hypotheses[hyp.hypothesis_id] = hyp
            evaluations.append({
                "hypothesis_id": hyp.hypothesis_id,
                "title": hyp.title,
                "assigned_probability": hyp.assigned_probability,
                "verdict": hyp.verdict,
                "dealbreakers": hyp.dealbreakers_triggered,
                "support_weight": round(support_weight, 2),
                "contradict_weight": round(contradict_weight, 2),
            })

        valid_candidates = [e for e in evaluations if e["verdict"] != "FATAL_RISK"]
        if valid_candidates:
            dominant = max(valid_candidates, key=lambda x: x["assigned_probability"])
        else:
            dominant = max(evaluations, key=lambda x: x["assigned_probability"])

        return {
            "dominant_hypothesis": dominant["hypothesis_id"],
            "dominant_verdict": dominant["verdict"],
            "hypotheses": evaluations
        }

    def get_citations(self) -> List[Dict[str, str]]:
        """
        Extracts verified source URLs and publisher metadata for reporting.
        Matches format required by render_institutional_markdown_report:
        [{'publisher': ..., 'date': ..., 'url': ..., 'claim': ...}]
        """
        citations = []
        seen = set()

        for item in self.items.values():
            if not item.source_urls:
                continue
            primary_url = item.source_urls[0]
            key = (item.publisher, primary_url, item.claim)
            if key in seen:
                continue
            seen.add(key)

            citations.append({
                "publisher": item.publisher,
                "date": item.publication_year,
                "url": primary_url,
                "claim": item.claim,
                "status": item.verification_status,
            })

        return citations

    def format_clickable_citation(self, publisher: str, year: Union[int, str], url: str) -> str:
        """Instance convenience delegator for format_clickable_citation."""
        return format_clickable_citation(publisher=publisher, year=year, url=url)

    def export_markdown_table(self, filter_status: Optional[VerificationStatus] = None) -> str:
        """
        Renders an unabridged GitHub-flavored Markdown table of evidence items.
        Escapes pipes to ensure robust formatting.
        """
        filtered_items = [
            item for item in self.items.values()
            if filter_status is None or item.verification_status == filter_status
        ]

        if not filtered_items:
            return "*No evidence records found.*"

        lines = [
            "| ID | Claim | Publisher | Source URL | Confidence | Status | Year |",
            "|---|---|---|---|---|---|---|"
        ]

        for item in filtered_items:
            clean_claim = item.claim.replace("|", "\\|").replace("\n", " ").strip()
            clean_pub = item.publisher.replace("|", "\\|").strip()
            primary_url = item.source_urls[0] if item.source_urls else "N/A"
            if primary_url.startswith("https://"):
                url_display = f"[Link]({primary_url})"
            else:
                url_display = primary_url

            lines.append(
                f"| `{item.id}` | {clean_claim} | {clean_pub} | {url_display} | "
                f"{item.confidence_score:.2f} | **{item.verification_status}** | {item.publication_year} |"
            )

        return "\n".join(lines)

    def export_citations_markdown(self) -> str:
        """
        Renders bulleted list of clickable citations matching institutional report standards:
        - [U.S. SEC EDGAR (2024)](https://sec.gov/...) — Apple 10-K reported $391.0B revenue
        """
        citations = self.get_citations()
        if not citations:
            return "*No verified citations available.*"

        lines = []
        for cit in citations:
            link = format_clickable_citation(cit["publisher"], cit["date"], cit["url"])
            lines.append(f"- {link} — {cit['claim']}")
        return "\n".join(lines)

    def get_items_by_time(
        self,
        ascending: bool = False,
        sort_by: Literal["retrieval", "published"] = "retrieval"
    ) -> List[EvidenceItem]:
        """
        Sorts evidence items chronologically.
        """
        if sort_by == "retrieval":
            return sorted(
                self.items.values(),
                key=lambda x: x.retrieval_timestamp,
                reverse=not ascending
            )
        else:
            return sorted(
                self.items.values(),
                key=lambda x: x.published_date or "1900-01-01",
                reverse=not ascending
            )

    def get_items_by_stratum(
        self,
        reference_date: Optional[datetime] = None
    ) -> Dict[TemporalStratum, List[EvidenceItem]]:
        """
        Stratifies evidence into temporal categories:
        - STATUTORY_CURRENT: <= 90 days from reference date
        - HISTORICAL_ANNUAL: 90 days to 3 years
        - OUTDATED: > 3 years
        """
        ref = reference_date or datetime.now(timezone.utc)
        ninety_days_ago = ref - timedelta(days=90)
        three_years_ago = ref - timedelta(days=365 * 3)

        result: Dict[TemporalStratum, List[EvidenceItem]] = {
            "STATUTORY_CURRENT": [],
            "HISTORICAL_ANNUAL": [],
            "OUTDATED": []
        }

        for item in self.items.values():
            item_date = item.retrieval_timestamp
            if item.published_date:
                try:
                    item_date = datetime.fromisoformat(item.published_date.replace("Z", "+00:00"))
                    if item_date.tzinfo is None:
                        item_date = item_date.replace(tzinfo=timezone.utc)
                except Exception:
                    pass

            if item_date >= ninety_days_ago:
                result["STATUTORY_CURRENT"].append(item)
            elif item_date >= three_years_ago:
                result["HISTORICAL_ANNUAL"].append(item)
            else:
                result["OUTDATED"].append(item)

        return result

    @property
    def claims(self) -> Dict[str, Dict[str, Any]]:
        """
        Backward-compatibility projection matching MockEvidenceLedger schema
        used in test_tier2_functional_core.py.
        """
        return {
            item_id: {
                "id": item.id,
                "claim": item.claim,
                "source_urls": item.source_urls,
                "publisher": item.publisher,
                "contradictions": item.contradicting_facts,
                "status": item.verification_status,
                "confidence": item.confidence_score,
            }
            for item_id, item in self.items.items()
        }

    def __getitem__(self, item_id: str) -> EvidenceItem:
        return self.items[item_id]

    def __len__(self) -> int:
        return len(self.items)

    def __contains__(self, item_id: str) -> bool:
        return item_id in self.items

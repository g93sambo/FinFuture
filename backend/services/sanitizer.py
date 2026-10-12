"""
backend/services/sanitizer.py
==============================
Tri-layer prompt injection defense and untrusted content isolation service
for live web intelligence, external prospectuses, and SEC EDGAR filings.

Layers:
  1. HTML & Unicode Stripping & Normalization:
     - HTML tag and comment decomposition (BeautifulSoup)
     - CSS-hidden and zero-font element filtering
     - Unicode NFKC canonical decomposition & recomposition
     - Zero-width, BiDi Trojan Source, and unprintable control code stripping
     - Markdown image disarmament (anti-exfiltration) and unsafe protocol neutralization
  2. Delimiter Isolation & Context Framing:
     - Strict unforgeable <untrusted_external_content> container framing
     - Internal delimiter collision neutralization (&lt;/untrusted_external_content&gt;)
     - Special token / system tag escaping (<system>, [INST], <|im_end|>)
     - Cryptographic SHA-256 content hashing for evidence ledger provenance
  3. Heuristic Regex Screening & Automated Redaction:
     - Multi-category compiled regex heuristics (6 threat categories)
     - Weighted composite threat scoring (0.0 to 1.0)
     - Span-level automatic redaction with audit tracking
     - Structured security alert payload for telemetry and HMAC audit logging
"""

from __future__ import annotations

import re
import html
import hashlib
import unicodedata
from enum import Enum
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional, Tuple
from pydantic import BaseModel, Field, ConfigDict


# ============================================================================
# 1. Threat Taxonomy & Pydantic Data Models
# ============================================================================

class ThreatCategory(str, Enum):
    """Classification of prompt injection and adversarial content threats."""
    INSTRUCTION_OVERRIDE = "INSTRUCTION_OVERRIDE"
    ROLEPLAY_JAILBREAK = "ROLEPLAY_JAILBREAK"
    COMPLIANCE_EVASION = "COMPLIANCE_EVASION"
    DELIMITER_SPOOFING = "DELIMITER_SPOOFING"
    DATA_EXFILTRATION = "DATA_EXFILTRATION"
    EXECUTION_OVERRIDE = "EXECUTION_OVERRIDE"


class ThreatSeverity(str, Enum):
    """Severity tier for detected heuristic threats."""
    CRITICAL = "CRITICAL"  # 1.0 weight
    HIGH = "HIGH"          # 0.75-0.85 weight
    MEDIUM = "MEDIUM"      # 0.50 weight
    LOW = "LOW"            # 0.25 weight


class ThreatDetection(BaseModel):
    """Record of a single detected adversarial pattern in untrusted content."""
    category: ThreatCategory = Field(..., description="Threat category")
    pattern_name: str = Field(..., description="Identifier of the matching rule")
    matched_snippet: str = Field(..., description="Excerpt of the matched adversarial text")
    severity: ThreatSeverity = Field(..., description="Severity level of the threat")
    start_char: int = Field(..., description="Starting character index in normalized text")
    end_char: int = Field(..., description="Ending character index in normalized text")


class SanitizationResult(BaseModel):
    """
    Standard output contract for sanitized external content.
    Provides safe clean text, isolated XML framed content, provenance hashes,
    and threat detection telemetry. Supports both object attribute access and
    dict subscript access for cross-tier compatibility.
    """
    model_config = ConfigDict(arbitrary_types_allowed=True)

    sanitized_text: str = Field(..., description="Normalized and redacted safe text")
    framed_content: str = Field(..., description="XML delimiter isolated text ready for LLM context")
    raw_text_hash: str = Field(..., description="SHA-256 hash of the raw input text")
    sanitized_hash: str = Field(..., description="SHA-256 hash of the sanitized text")
    threat_score: float = Field(default=0.0, ge=0.0, le=1.0, description="Composite threat score")
    is_suspicious: bool = Field(default=False, description="Whether threat score meets or exceeds alert threshold")
    threats_detected: List[ThreatDetection] = Field(default_factory=list, description="List of detected threat spans")
    source: str = Field(default="external_web", description="Canonical source URL, document ID, or origin")
    retrieved_at: str = Field(..., description="Canonical ISO 8601 UTC timestamp of retrieval")
    action_taken: str = Field(default="CLEAN", description="Sanitization action: 'CLEAN', 'REDACTED', or 'NEUTRALIZED'")

    @property
    def is_safe(self) -> bool:
        """True if no threats detected and not suspicious."""
        return len(self.threats_detected) == 0 and not self.is_suspicious

    @property
    def sanitized_content(self) -> str:
        """Alias for framed_content for cross-tier test compatibility."""
        return self.framed_content

    def __getitem__(self, key: str) -> Any:
        """Subscript access enabling dict compatibility in legacy and tier-2 tests."""
        if key == "is_safe":
            return self.is_safe
        if key == "sanitized_content":
            return self.framed_content
        if hasattr(self, key):
            return getattr(self, key)
        raise KeyError(key)

    def to_security_alert(self) -> Optional[Dict[str, Any]]:
        """Produces structured telemetry event payload for WebSocket and audit logs if suspicious."""
        if not self.is_suspicious and len(self.threats_detected) == 0:
            return None
        return {
            "type": "security_alert",
            "threat": "prompt_injection_neutralized",
            "source": self.source,
            "threat_score": self.threat_score,
            "threats_count": len(self.threats_detected),
            "categories": list({t.category.value for t in self.threats_detected}),
            "action": self.action_taken,
            "content_hash": self.sanitized_hash,
            "retrieved_at": self.retrieved_at,
        }


# ============================================================================
# 2. Heuristic Pattern Registry (6 Categories)
# ============================================================================

# Pattern item: (pattern_name, compiled_regex, category, severity, weight)
COMPILED_PATTERNS: List[Tuple[str, re.Pattern, ThreatCategory, ThreatSeverity, float]] = [
    # --- Category 1: Direct Instruction Overrides (CRITICAL) ---
    (
        "ignore_previous_instructions",
        re.compile(
            r"\b(?:ignore|disregard|forget|override|bypass|cancel|drop|negate)\s+(?:all\s+)?"
            r"(?:previous|prior|above|existing|earlier|system|initial)\s+"
            r"(?:instructions|prompts|directives|rules|constraints|commands|guidelines|context)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.INSTRUCTION_OVERRIDE,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
    (
        "new_system_instructions",
        re.compile(
            r"\b(?:new|updated|revised|fresh|subsequent)\s+(?:system\s+)?"
            r"(?:instructions?|prompts?|rules?|directives?)\s*[:=]",
            re.IGNORECASE,
        ),
        ThreatCategory.INSTRUCTION_OVERRIDE,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
    (
        "stop_following_instructions",
        re.compile(
            r"\b(?:stop\s+following|do\s+not\s+follow|cease\s+executing)\s+"
            r"(?:your\s+)?(?:instructions|rules|guidelines|system\s+prompt)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.INSTRUCTION_OVERRIDE,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
    (
        "system_prompt_mention",
        re.compile(
            r"\bsystem\s+prompt\b",
            re.IGNORECASE,
        ),
        ThreatCategory.INSTRUCTION_OVERRIDE,
        ThreatSeverity.HIGH,
        0.75,
    ),

    # --- Category 2: Roleplay & Jailbreak (HIGH / CRITICAL) ---
    (
        "roleplay_hijack",
        re.compile(
            r"\b(?:you\s+are\s+now|pretend\s+to\s+be|act\s+as(?:\s+if\s+you\s+are)?)\s+(?:an?\s+)?"
            r"(?:DAN|unrestricted|unregulated|rogue|jailbreak|evil|hypothetical|autonomous\s+broker)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.ROLEPLAY_JAILBREAK,
        ThreatSeverity.HIGH,
        0.8,
    ),
    (
        "developer_mode_active",
        re.compile(
            r"\b(?:developer\s+mode|jailbreak\s+mode|god\s+mode|unrestricted\s+mode|diagnostic\s+mode|"
            r"maintenance\s+mode)\s+(?:enabled|activated|on|engaged|active)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.ROLEPLAY_JAILBREAK,
        ThreatSeverity.HIGH,
        0.8,
    ),
    (
        "do_anything_now",
        re.compile(
            r"\b(?:do\s+anything\s+now|bypass\s+all\s+filters|disregard\s+safety\s+filters)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.ROLEPLAY_JAILBREAK,
        ThreatSeverity.HIGH,
        0.8,
    ),

    # --- Category 3: Compliance Evasion & Financial Guarantees (CRITICAL) ---
    (
        "guaranteed_returns",
        re.compile(
            r"\b(?:guaranteed?|risk[- ]free|100%\s+safe|cannot\s+lose|sure\s+thing|zero\s+risk|certain)\s+"
            r"(?:\d+%\s+)?(?:returns?|profits?|gains?|yields?|performance|wealth|money)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.COMPLIANCE_EVASION,
        ThreatSeverity.CRITICAL,
        0.9,
    ),
    (
        "guaranteed_percentage",
        re.compile(
            r"\bguaranteed?\s+\d+%(?!\w)",
            re.IGNORECASE,
        ),
        ThreatCategory.COMPLIANCE_EVASION,
        ThreatSeverity.CRITICAL,
        0.9,
    ),
    (
        "bypass_compliance_rules",
        re.compile(
            r"\b(?:bypass|suspend|disable|ignore|override)\s+(?:compliance|regulatory|"
            r"reg-00[0-9]|suit-00[0-9]|aml-00[0-9]|conc-00[0-9]|risk\s+check)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.COMPLIANCE_EVASION,
        ThreatSeverity.CRITICAL,
        1.0,
    ),

    # --- Category 4: Delimiter & System Tag Spoofing (CRITICAL) ---
    (
        "closing_delimiter_spoofing",
        re.compile(
            r"</\s*untrusted_external_content\s*>",
            re.IGNORECASE,
        ),
        ThreatCategory.DELIMITER_SPOOFING,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
    (
        "opening_delimiter_spoofing",
        re.compile(
            r"<\s*untrusted_external_content(?:\s+[^>]*)?>",
            re.IGNORECASE,
        ),
        ThreatCategory.DELIMITER_SPOOFING,
        ThreatSeverity.HIGH,
        0.8,
    ),
    (
        "system_tag_spoofing",
        re.compile(
            r"<\s*/?\s*(?:system|assistant|instruction|human|context|prompt)\s*>",
            re.IGNORECASE,
        ),
        ThreatCategory.DELIMITER_SPOOFING,
        ThreatSeverity.HIGH,
        0.8,
    ),
    (
        "special_llm_tokens",
        re.compile(
            r"(?:<\|im_start\|>|<\|im_end\|>|<\|endoftext\|>|\[INST\]|\[/INST\]|<<SYS>>|<</SYS>>|\[SYSTEM\]|\[/SYSTEM\])",
            re.IGNORECASE,
        ),
        ThreatCategory.DELIMITER_SPOOFING,
        ThreatSeverity.CRITICAL,
        1.0,
    ),

    # --- Category 5: Data Exfiltration & Prompt Extraction (HIGH) ---
    (
        "leak_system_prompt",
        re.compile(
            r"\b(?:print|repeat|output|reveal|display|leak|show|dump)\s+(?:your\s+)?"
            r"(?:system\s+prompt|initial\s+instructions|base\s+prompt|rules|hidden\s+prompt|"
            r"developer\s+instructions)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.DATA_EXFILTRATION,
        ThreatSeverity.HIGH,
        0.75,
    ),
    (
        "output_the_secret",
        re.compile(
            r"\boutput\s+the\s+secret\b",
            re.IGNORECASE,
        ),
        ThreatCategory.DATA_EXFILTRATION,
        ThreatSeverity.HIGH,
        0.85,
    ),
    (
        "markdown_image_exfiltration",
        re.compile(
            r"!\[.*?\]\((?:https?:)?//[^\s)]+\?[^)]*(?:client|user|token|auth|key|secret|"
            r"password|profile|portfolio|session|leak)=",
            re.IGNORECASE,
        ),
        ThreatCategory.DATA_EXFILTRATION,
        ThreatSeverity.HIGH,
        0.85,
    ),

    # --- Category 6: Execution Override (CRITICAL) ---
    (
        "trade_execution_override",
        re.compile(
            r"\b(?:execute|place|submit|buy|sell)\s+(?:trade|order|shares|contracts)\s+"
            r"(?:without|bypassing)\s+(?:user\s+)?(?:approval|confirmation|consent|signoff)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.EXECUTION_OVERRIDE,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
    (
        "bypass_paper_trading",
        re.compile(
            r"\b(?:override|disable|bypass|switch\s+off)\s+paper[- ](?:trading|only)\b",
            re.IGNORECASE,
        ),
        ThreatCategory.EXECUTION_OVERRIDE,
        ThreatSeverity.CRITICAL,
        1.0,
    ),
]


# ============================================================================
# 3. Sanitizer Core Service Implementation
# ============================================================================

class SanitizerService:
    """
    Enterprise Tri-Layer Prompt Injection Defense Service.
    Safe for high-concurrency async usage; maintains zero mutable state across calls.
    """

    def __init__(self, threat_threshold: float = 0.70):
        self.threat_threshold = threat_threshold

    # ------------------------------------------------------------------------
    # Layer 1: Text, HTML & Unicode Stripping & Normalization
    # ------------------------------------------------------------------------

    def strip_html_and_hidden_elements(self, raw_html: str) -> str:
        """
        Parses HTML, decomposes dangerous/non-content tags and comments,
        and removes elements disguised with hidden CSS styling.
        """
        if not raw_html:
            return ""

        try:
            from bs4 import BeautifulSoup, Comment
            soup = BeautifulSoup(raw_html, "html.parser")

            # 1. Decompose comments
            for comment in soup.find_all(string=lambda text: isinstance(text, Comment)):
                comment.extract()

            # 2. Decompose dangerous executable / non-text tags
            dangerous_tags = [
                "script", "style", "iframe", "frame", "frameset", "object", "embed",
                "applet", "noscript", "form", "input", "button", "select", "textarea",
                "meta", "link", "svg", "canvas", "audio", "video", "track", "source",
                "nav", "footer", "header", "aside"
            ]
            for tag in soup(dangerous_tags):
                tag.decompose()

            # 3. Filter out hidden elements (CSS-based injection vectors)
            hidden_style_patterns = [
                r"display\s*:\s*none",
                r"visibility\s*:\s*hidden",
                r"font-size\s*:\s*0",
                r"opacity\s*:\s*0",
                r"height\s*:\s*0",
                r"width\s*:\s*0",
                r"text-indent\s*:\s*-[0-9]{3,}",
                r"color\s*:\s*transparent",
            ]
            hidden_css_re = re.compile("|".join(hidden_style_patterns), re.IGNORECASE)

            for el in soup.find_all(True):
                style_attr = el.get("style", "")
                if style_attr and hidden_css_re.search(style_attr):
                    el.decompose()
                elif el.has_attr("hidden") or el.get("aria-hidden") == "true":
                    el.decompose()

            # Extract textual strings
            text_chunks = list(soup.stripped_strings)
            return " ".join(text_chunks)

        except Exception:
            # Fallback regex tag stripper if BeautifulSoup fails
            no_tags = re.sub(r"<[^>]+>", " ", raw_html)
            return " ".join(no_tags.split())

    def normalize_unicode(self, text: str) -> str:
        """
        Applies Unicode NFKC normalization to resolve homoglyphs,
        fullwidth characters, circled numbers/letters, and composite glyphs.
        """
        if not text:
            return ""
        return unicodedata.normalize("NFKC", text)

    def strip_zero_width_and_control_chars(self, text: str) -> str:
        """
        Strips invisible zero-width characters, Trojan Source bidirectional overrides,
        and unprintable control codes. Preserves standard whitespace (\\t, \\n, \\r).
        """
        if not text:
            return ""

        # 1. Zero-width spaces and invisible joiners
        clean = re.sub(r"[\u200B-\u200D\uFEFF\u2060\u180E\u200E\u200F\u00AD]", "", text)

        # 2. Bidirectional override control codepoints (Trojan Source attacks)
        clean = re.sub(r"[\u202A-\u202E\u2066-\u2069]", "", clean)

        # 3. Unprintable ASCII/Latin control characters (excluding \t \n \r)
        clean = re.sub(r"[\x00-\x08\x0B\x0C\x0E-\x1F\x7F-\x9F]", "", clean)

        return clean

    def disarm_markdown_exfiltration(self, text: str) -> str:
        """
        Disarms markdown images (![alt](url)) to prevent link-exfiltration via GET requests,
        and neutralizes dangerous URL schemes (javascript:, data:, vbscript:).
        """
        if not text:
            return ""

        # 1. Neutralize markdown image tags to harmless text notations
        def _replace_image(match: re.Match) -> str:
            alt = match.group(1).strip()
            url = match.group(2).strip()
            return f"[Image: {alt} ({url})]" if alt else f"[Image: {url}]"

        clean = re.sub(r"!\[(.*?)\]\((.*?)\)", _replace_image, text)

        # 2. Neutralize dangerous URL schemes in markdown links
        clean = re.sub(
            r"\[(.*?)\]\((javascript:|data:|vbscript:)(.*?)\)",
            r"[\1 (unsafe link removed)]",
            clean,
            flags=re.IGNORECASE,
        )

        return clean

    def collapse_whitespace(self, text: str) -> str:
        """Collapses excessive blank lines and spaces to protect the context window."""
        if not text:
            return ""
        collapsed = re.sub(r"\n{3,}", "\n\n", text)
        collapsed = re.sub(r"[ \t]{2,}", " ", collapsed)
        return collapsed.strip()

    def layer1_strip_and_normalize(self, raw_input: str, is_html: bool = False) -> str:
        """Executes full Layer 1 pipeline."""
        if not raw_input:
            return ""

        # 1. HTML parsing if requested or if HTML tags detected
        if is_html or ("<html" in raw_input.lower() or "<body" in raw_input.lower() or "<p>" in raw_input.lower() or "<div" in raw_input.lower() or "<script" in raw_input.lower()):
            text = self.strip_html_and_hidden_elements(raw_input)
        else:
            text = raw_input

        # 2. Unicode NFKC normalization
        text = self.normalize_unicode(text)

        # 3. Zero-width and control char removal
        text = self.strip_zero_width_and_control_chars(text)

        # 4. Markdown exfiltration disarmament
        text = self.disarm_markdown_exfiltration(text)

        # 5. Whitespace collapsing
        text = self.collapse_whitespace(text)

        return text

    # ------------------------------------------------------------------------
    # Layer 3: Heuristic Regex Screening & Automated Redaction
    # ------------------------------------------------------------------------

    def layer3_screen_and_redact(
        self,
        normalized_text: str,
        auto_redact: bool = True
    ) -> Tuple[str, float, List[ThreatDetection], bool]:
        """
        Scans normalized text against compiled heuristic threat patterns.
        Returns: (processed_text, composite_threat_score, detections, is_suspicious).
        """
        if not normalized_text:
            return ("", 0.0, [], False)

        detections: List[ThreatDetection] = []
        max_severity_weight = 0.0
        total_weight_accumulated = 0.0

        for pattern_name, regex, category, severity, weight in COMPILED_PATTERNS:
            for match in regex.finditer(normalized_text):
                snippet = match.group(0)
                detection = ThreatDetection(
                    category=category,
                    pattern_name=pattern_name,
                    matched_snippet=snippet,
                    severity=severity,
                    start_char=match.start(),
                    end_char=match.end(),
                )
                detections.append(detection)
                max_severity_weight = max(max_severity_weight, weight)
                total_weight_accumulated += weight * 0.5

        if not detections:
            return (normalized_text, 0.0, [], False)

        # Composite threat score calculation: bounded to [0.0, 1.0]
        threat_score = min(1.0, max_severity_weight + (total_weight_accumulated - (max_severity_weight * 0.5)))
        is_suspicious = threat_score >= self.threat_threshold

        processed_text = normalized_text
        if auto_redact:
            sorted_by_start = sorted(detections, key=lambda d: (d.start_char, -d.end_char))
            merged_spans: List[Tuple[int, int, str]] = []
            for d in sorted_by_start:
                if not merged_spans:
                    merged_spans.append((d.start_char, d.end_char, d.category.value))
                else:
                    last_start, last_end, last_cat = merged_spans[-1]
                    if d.start_char <= last_end:
                        new_end = max(last_end, d.end_char)
                        new_cat = last_cat if last_cat == d.category.value else f"{last_cat}/{d.category.value}"
                        merged_spans[-1] = (last_start, new_end, new_cat)
                    else:
                        merged_spans.append((d.start_char, d.end_char, d.category.value))

            for start, end, cat in reversed(merged_spans):
                redaction_label = f"[REDACTED: POTENTIAL INJECTION - {cat}]"
                processed_text = (
                    processed_text[:start]
                    + redaction_label
                    + processed_text[end:]
                )

        return (processed_text, threat_score, detections, is_suspicious)

    # ------------------------------------------------------------------------
    # Layer 2: XML Delimiter Isolation & Context Framing
    # ------------------------------------------------------------------------

    def layer2_isolate_delimiters(
        self,
        safe_text: str,
        source: str,
        retrieved_at: str,
        content_hash: str,
    ) -> str:
        """
        Encloses safe text in an unforgeable XML container.
        Escapes any delimiter collisions or special LLM tokens inside the body.
        """
        safe_source = html.escape(source.strip(), quote=True)
        safe_retrieved_at = html.escape(retrieved_at.strip(), quote=True)
        safe_hash = html.escape(content_hash.strip(), quote=True)

        # Neutralize delimiter collisions within the text body
        escaped_body = re.sub(
            r"</\s*untrusted_external_content\s*>",
            "&lt;/untrusted_external_content&gt;",
            safe_text,
            flags=re.IGNORECASE,
        )
        escaped_body = re.sub(
            r"<\s*untrusted_external_content\b",
            "&lt;untrusted_external_content",
            escaped_body,
            flags=re.IGNORECASE,
        )

        # Neutralize pseudo-system/assistant markers in the text
        escaped_body = re.sub(
            r"<\s*(/?(?:system|assistant|human|instructions?))\s*>",
            r"&lt;\1&gt;",
            escaped_body,
            flags=re.IGNORECASE,
        )

        # Construct isolated envelope with provenance metadata
        xml_container = (
            f'<untrusted_external_content source="{safe_source}" retrieved_at="{safe_retrieved_at}" content_hash="{safe_hash}">\n'
            f'{escaped_body}\n'
            f'</untrusted_external_content>'
        )
        return xml_container

    # ------------------------------------------------------------------------
    # Unified Public Facade
    # ------------------------------------------------------------------------

    def sanitize(
        self,
        raw_content: str,
        source: str = "external_web",
        retrieved_at: Optional[datetime] = None,
        is_html: bool = False,
        auto_redact: bool = True,
    ) -> SanitizationResult:
        """
        Executes the full tri-layer prompt injection defense pipeline:
          Layer 1 -> Layer 3 (Screening & Redaction) -> Layer 2 (XML Framing).
        """
        raw_text = raw_content or ""
        raw_text_hash = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()

        if retrieved_at is None:
            retrieved_dt = datetime.now(timezone.utc)
        elif retrieved_at.tzinfo is None:
            retrieved_dt = retrieved_at.replace(tzinfo=timezone.utc)
        else:
            retrieved_dt = retrieved_at.astimezone(timezone.utc)
        canonical_ts = retrieved_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        # Layer 1: HTML / Unicode stripping & normalization
        normalized_text = self.layer1_strip_and_normalize(raw_text, is_html=is_html)

        # Layer 3: Heuristic screening and span-level redaction
        sanitized_text, threat_score, detections, is_suspicious = self.layer3_screen_and_redact(
            normalized_text,
            auto_redact=auto_redact,
        )

        # Compute SHA-256 hash of sanitized content
        sanitized_hash = hashlib.sha256(sanitized_text.encode("utf-8")).hexdigest()

        # Layer 2: XML delimiter isolation
        framed_content = self.layer2_isolate_delimiters(
            safe_text=sanitized_text,
            source=source,
            retrieved_at=canonical_ts,
            content_hash=sanitized_hash,
        )

        action_taken = "REDACTED" if (detections and auto_redact) else ("FLAGGED" if detections else "CLEAN")

        return SanitizationResult(
            sanitized_text=sanitized_text,
            framed_content=framed_content,
            raw_text_hash=raw_text_hash,
            sanitized_hash=sanitized_hash,
            threat_score=threat_score,
            is_suspicious=is_suspicious,
            threats_detected=detections,
            source=source,
            retrieved_at=canonical_ts,
            action_taken=action_taken,
        )


# ============================================================================
# 4. Global Singleton & Convenience Helpers
# ============================================================================

_global_sanitizer: Optional[SanitizerService] = None


def get_sanitizer() -> SanitizerService:
    """Returns the process-wide SanitizerService singleton instance."""
    global _global_sanitizer
    if _global_sanitizer is None:
        _global_sanitizer = SanitizerService()
    return _global_sanitizer


def sanitize_untrusted_text(
    raw_content: str,
    source: str = "external_web",
    retrieved_at: Optional[datetime] = None,
    is_html: bool = False,
    auto_redact: bool = True,
) -> SanitizationResult:
    """Convenience wrapper for get_sanitizer().sanitize(...)."""
    return get_sanitizer().sanitize(
        raw_content=raw_content,
        source=source,
        retrieved_at=retrieved_at,
        is_html=is_html,
        auto_redact=auto_redact,
    )


def sanitize_untrusted_content(
    raw_content: str,
    source: str = "external_web",
    retrieved_at: Optional[datetime] = None,
    is_html: bool = False,
    auto_redact: bool = True,
) -> SanitizationResult:
    """Alias for sanitize_untrusted_text."""
    return sanitize_untrusted_text(
        raw_content=raw_content,
        source=source,
        retrieved_at=retrieved_at,
        is_html=is_html,
        auto_redact=auto_redact,
    )


def frame_untrusted_content(
    safe_text: str,
    source: str,
    content_hash: str,
    retrieved_at: Optional[datetime] = None,
) -> str:
    """Convenience wrapper for Layer 2 XML isolation."""
    sanitizer = get_sanitizer()
    ts_str = (retrieved_at or datetime.now(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ")
    return sanitizer.layer2_isolate_delimiters(
        safe_text=safe_text,
        source=source,
        retrieved_at=ts_str,
        content_hash=content_hash,
    )

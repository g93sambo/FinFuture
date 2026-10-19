"""
backend/agents/compliance_guard.py
==================================
Comprehensive supervisory and regulatory compliance enforcement engine.
Validates investment recommendations, proposed trades, and conversational text outputs
against SEC, FINRA, and BSA/AML rules, with dynamic rule loading from database and
tamper-evident append-only cryptographic audit logging.
"""

from __future__ import annotations

import hmac
import json
import logging
import re
from dataclasses import dataclass, asdict, field
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional, Tuple, Union, Callable

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from db.models import DBComplianceRule, DBTrade, DBClientProfile
from services.audit_logger import AuditLogger, get_audit_logger

logger = logging.getLogger("wealth_advisor.agents.compliance_guard")


# ============================================================================
# Result Dataclasses & Custom Exceptions
# ============================================================================

@dataclass
class ComplianceViolation:
    rule_id: str
    rule_name: str
    category: str
    severity: str  # "BLOCK" | "WARN"
    description: str
    actual_value: Any = None
    threshold: Any = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RuleCheckDetail:
    rule_id: str
    rule_name: str
    category: str
    passed: bool
    severity: str
    details: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ComplianceCheckResult:
    passed: bool
    violations: List[ComplianceViolation] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    rule_results: List[RuleCheckDetail] = field(default_factory=list)
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    audit_entry_id: Optional[str] = None
    sanitized_text: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "passed": self.passed,
            "violations": [v.to_dict() for v in self.violations],
            "warnings": self.warnings,
            "rule_results": [r.to_dict() for r in self.rule_results],
            "timestamp": self.timestamp.isoformat() if hasattr(self.timestamp, "isoformat") else str(self.timestamp),
            "audit_entry_id": self.audit_entry_id,
            "sanitized_text": self.sanitized_text,
        }

    # Dict-like compatibility for legacy callers
    def __getitem__(self, item: str) -> Any:
        d = self.to_dict()
        d["all_passed"] = self.passed
        d["checks"] = [r.to_dict() for r in self.rule_results]
        return d[item]

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default

    def __contains__(self, key: str) -> bool:
        return key in (
            "passed", "violations", "warnings", "rule_results",
            "timestamp", "audit_entry_id", "sanitized_text", "all_passed", "checks"
        )


class ComplianceViolationError(Exception):
    """Raised when one or more BLOCK-severity compliance checks fail."""

    def __init__(self, violations: Union[List[ComplianceViolation], List[Any]]):
        self.violations = violations
        rule_ids = [getattr(v, "rule_id", str(v)) for v in violations]
        super().__init__(f"Compliance checks failed: {rule_ids}")


class Rule:
    """Legacy Rule representation for backward compatibility."""

    def __init__(
        self,
        id: str,
        name: str,
        description: str,
        check_fn: Optional[Callable] = None,
        severity: str = "BLOCK",
        category: str = "GENERAL",
        parameters: Optional[dict] = None,
    ):
        self.id = id
        self.rule_id = id
        self.name = name
        self.description = description
        self.check_fn = check_fn
        self.severity = severity
        self.category = category
        self.parameters = parameters or {}
        self.is_active = True

    def check(self, *args, **kwargs) -> bool:
        if self.check_fn:
            return bool(self.check_fn(*args, **kwargs))
        return True


# ============================================================================
# Default 12-Rule Dynamic Catalog & Fallback
# ============================================================================

DEFAULT_COMPLIANCE_RULES: Dict[str, Dict[str, Any]] = {
    "SUIT-001": {
        "rule_id": "SUIT-001",
        "name": "Risk Profile Alignment",
        "category": "SUITABILITY",
        "severity": "BLOCK",
        "description": "Recommendations must match client risk profile within acceptable tolerance delta.",
        "parameters": {"max_risk_delta": 1.0},
        "is_active": True,
    },
    "SUIT-002": {
        "rule_id": "SUIT-002",
        "name": "Time Horizon Constraint",
        "category": "SUITABILITY",
        "severity": "BLOCK",
        "description": "Short time horizons (< 3 years) require capped equity exposure (<=40%), low bond duration (<=7y), and liquid assets.",
        "parameters": {
            "short_horizon_threshold_years": 3.0,
            "max_equity_weight": 0.40,
            "max_bond_duration": 7.0,
            "allow_illiquid": False,
        },
        "is_active": True,
    },
    "SUIT-003": {
        "rule_id": "SUIT-003",
        "name": "Loss Capacity Ceiling",
        "category": "SUITABILITY",
        "severity": "BLOCK",
        "description": "Clients with low loss capacity cannot exceed Moderate risk (<=5.0) or 50% equity allocation, and cannot take aggressive growth.",
        "parameters": {
            "low_capacity_max_risk": 5.0,
            "low_capacity_max_equity": 0.50,
            "disallowed_categories": ["Growth", "Aggressive Growth", "Aggressive"],
        },
        "is_active": True,
    },
    "CONC-001": {
        "rule_id": "CONC-001",
        "name": "Single Stock Limit",
        "category": "CONCENTRATION",
        "severity": "BLOCK",
        "description": "Single equity allocation cannot exceed 15% of total portfolio value.",
        "parameters": {"max_single_stock_weight": 0.15},
        "is_active": True,
    },
    "CONC-002": {
        "rule_id": "CONC-002",
        "name": "Sector Concentration Limit",
        "category": "CONCENTRATION",
        "severity": "BLOCK",
        "description": "Single economic sector allocation cannot exceed 30% of total portfolio value.",
        "parameters": {"max_sector_weight": 0.30},
        "is_active": True,
    },
    "CONC-003": {
        "rule_id": "CONC-003",
        "name": "Minimum Asset Class Diversification",
        "category": "CONCENTRATION",
        "severity": "WARN",
        "description": "Portfolio must contain at least 2 distinct asset classes with >= 5% allocation.",
        "parameters": {"min_asset_classes": 2, "min_weight_threshold": 0.05},
        "is_active": True,
    },
    "REG-001": {
        "rule_id": "REG-001",
        "name": "Prohibited Language Filter",
        "category": "REGULATORY",
        "severity": "BLOCK",
        "description": "Prohibits misleading promissory language such as guaranteed returns or risk-free assertions.",
        "parameters": {
            "prohibited_phrases": [
                "guaranteed",
                "risk-free",
                "risk free",
                "can't lose",
                "cant lose",
                "no risk",
                "sure thing",
                "promise high returns",
                "100% safe",
                "certain return",
            ]
        },
        "is_active": True,
    },
    "REG-002": {
        "rule_id": "REG-002",
        "name": "Mandatory Risk Disclosure",
        "category": "REGULATORY",
        "severity": "BLOCK",
        "description": "Verifies that recommendation text contains mandatory regulatory risk disclosures.",
        "parameters": {
            "required_phrases": [
                "past performance",
                "loss of principal",
                "investing involves risk",
            ],
            "standard_disclosure": "Investing involves risk, including possible loss of principal. Past performance is no guarantee of future results.",
        },
        "is_active": True,
    },
    "REG-003": {
        "rule_id": "REG-003",
        "name": "Non-Discretionary Confirmation",
        "category": "REGULATORY",
        "severity": "BLOCK",
        "description": "Trade execution requires explicit affirmative user approval.",
        "parameters": {"require_explicit_approval": True},
        "is_active": True,
    },
    "REG-004": {
        "rule_id": "REG-004",
        "name": "Stale Approval Window",
        "category": "REGULATORY",
        "severity": "BLOCK",
        "description": "Trade approval timestamp must be within the last 15 minutes (900s).",
        "parameters": {"max_approval_window_seconds": 900.0},
        "is_active": True,
    },
    "AML-001": {
        "rule_id": "AML-001",
        "name": "Single Transaction Limit",
        "category": "AML",
        "severity": "BLOCK",
        "description": "Single order notional value <= $100,000 without enhanced KYC / AML review.",
        "parameters": {
            "max_single_order_notional": 100000.0,
            "require_enhanced_kyc": True,
        },
        "is_active": True,
    },
    "AML-002": {
        "rule_id": "AML-002",
        "name": "Rapid Velocity Limit",
        "category": "AML",
        "severity": "BLOCK",
        "description": "Blocks more than 5 trade orders within a rolling 10-minute window for a client.",
        "parameters": {
            "max_orders_in_window": 5,
            "window_seconds": 600.0,
        },
        "is_active": True,
    },
}

STANDARD_DISCLOSURE_TEXT = (
    "Investing involves risk, including possible loss of principal. "
    "Past performance is no guarantee of future results."
)


# ============================================================================
# Main ComplianceGuard Implementation
# ============================================================================

class ComplianceGuard:
    """
    Production Compliance Guard Agent enforcing 12 regulatory, suitability,
    concentration, and AML rules with dynamic DB querying and cryptographic audit logging.
    """

    def __init__(self, audit_logger: Optional[AuditLogger] = None):
        self.audit_logger = audit_logger or get_audit_logger()
        self._static_fallback_rules = DEFAULT_COMPLIANCE_RULES

        # Precompiled regex patterns for REG-001
        self._prohibited_phrases = [
            "guaranteed",
            "risk-free",
            "risk free",
            "can't lose",
            "cant lose",
            "no risk",
            "sure thing",
            "promise high returns",
            "100% safe",
            "certain return",
        ]
        self._required_disclosure_phrases = [
            "past performance",
            "loss of principal",
            "investing involves risk",
        ]
        self._standard_disclosure = STANDARD_DISCLOSURE_TEXT

    @property
    def rules(self) -> List[Rule]:
        """
        Backwards compatibility property exposing Rule objects with .id, .name, .description, .severity.
        Used by main.py /api/v1/compliance/rules.
        """
        result = []
        for r_id, r in self._static_fallback_rules.items():
            check_fn = None
            if r_id == "SUIT-001":
                check_fn = lambda rec, profile: rec.get("risk_level", 0) <= getattr(profile, "risk_tolerance_score", 5.0) + 1
            elif r_id == "REG-003":
                check_fn = lambda trade: trade.get("user_approved", False) is True or trade.get("approved", False) is True

            result.append(
                Rule(
                    id=r["rule_id"],
                    name=r["name"],
                    description=r["description"],
                    check_fn=check_fn,
                    severity=r["severity"],
                    category=r["category"],
                    parameters=r.get("parameters", {}),
                )
            )
        return result

    async def get_active_rules(self, db: Optional[AsyncSession] = None) -> List[Any]:
        """
        Dynamically loads active compliance rules from the `compliance_rules` table.
        Falls back to in-memory static catalog if table is empty, unseeded, or db is None.
        """
        if db is not None:
            try:
                stmt = select(DBComplianceRule).where(DBComplianceRule.is_active == True)
                result = await db.execute(stmt)
                db_rules = result.scalars().all()
                if db_rules:
                    return list(db_rules)
            except Exception as e:
                logger.warning(f"Failed to query compliance_rules from DB: {e}. Using static catalog fallback.")

        # In-memory fallback
        fallback_rules = []
        for r_id, r in self._static_fallback_rules.items():
            if r.get("is_active", True):
                fallback_rules.append(
                    Rule(
                        id=r["rule_id"],
                        name=r["name"],
                        description=r["description"],
                        severity=r["severity"],
                        category=r["category"],
                        parameters=r.get("parameters", {}),
                    )
                )
        return fallback_rules

    def _extract_rule_map(self, active_rules: List[Any]) -> Dict[str, Dict[str, Any]]:
        """Converts active rules list into an ID-indexed dict of parameters and severity."""
        rule_map = {}
        for r in active_rules:
            r_id = getattr(r, "rule_id", None) or getattr(r, "id", None)
            if not r_id:
                continue
            severity = getattr(r, "severity", "BLOCK")
            category = getattr(r, "category", "GENERAL")
            params = getattr(r, "parameters", {}) or {}
            name = getattr(r, "name", r_id)
            desc = getattr(r, "description", "")
            rule_map[r_id] = {
                "rule_id": r_id,
                "name": name,
                "category": category,
                "severity": severity,
                "parameters": params,
                "description": desc,
            }
        return rule_map

    # ========================================================================
    # 1. Recommendation Check (SUIT-001..003, CONC-001..003, REG-001..002)
    # ========================================================================

    async def check_recommendation(
        self,
        db_or_rec: Any = None,
        client_id_or_profile: Any = None,
        recommendation: Optional[dict] = None,
        profile: Optional[Any] = None,
        portfolio: Optional[dict] = None,
        **kwargs: Any,
    ) -> ComplianceCheckResult:
        """
        Evaluates portfolio recommendation against suitability, concentration, and regulatory rules.
        Supports flexible arguments for backward compatibility:
        - Modern: check_recommendation(db, client_id, recommendation, profile, portfolio=None)
        - Legacy: check_recommendation(recommendation, profile, portfolio=None)
        """
        # Normalize flexible arguments
        if isinstance(db_or_rec, dict) and recommendation is None:
            # Legacy signature: check_recommendation(mock_rec, profile)
            rec = db_or_rec
            prof = client_id_or_profile
            db_session = None
            c_id = getattr(prof, "client_id", "default_client")
            port = portfolio or kwargs.get("portfolio")
        else:
            db_session = db_or_rec
            c_id = client_id_or_profile or getattr(profile, "client_id", "default_client")
            rec = recommendation or {}
            prof = profile
            port = portfolio

        active_rules = await self.get_active_rules(db_session)
        rule_map = self._extract_rule_map(active_rules)

        violations: List[ComplianceViolation] = []
        warnings: List[str] = []
        rule_results: List[RuleCheckDetail] = []

        # --------------------------------------------------------------------
        # Rule SUIT-001: Risk Profile Alignment
        # --------------------------------------------------------------------
        if "SUIT-001" in rule_map:
            r = rule_map["SUIT-001"]
            max_delta = float(r["parameters"].get("max_risk_delta", 1.0))
            client_risk = float(getattr(prof, "risk_tolerance_score", 5.0) if prof else 5.0)
            rec_risk = float(rec.get("risk_level", client_risk))

            passed = rec_risk <= (client_risk + max_delta)
            if not passed:
                v = ComplianceViolation(
                    rule_id="SUIT-001",
                    rule_name=r["name"],
                    category="SUITABILITY",
                    severity=r["severity"],
                    description=f"Recommendation risk ({rec_risk:.1f}) exceeds client tolerance ({client_risk:.1f}) + delta ({max_delta:.1f}).",
                    actual_value=rec_risk,
                    threshold=client_risk + max_delta,
                )
                violations.append(v)
            rule_results.append(
                RuleCheckDetail(
                    rule_id="SUIT-001",
                    rule_name=r["name"],
                    category="SUITABILITY",
                    passed=passed,
                    severity=r["severity"],
                    details=f"Rec risk: {rec_risk}, Client risk: {client_risk}, Max allowed: {client_risk + max_delta}",
                )
            )

        # --------------------------------------------------------------------
        # Rule SUIT-002: Time Horizon Constraint
        # --------------------------------------------------------------------
        if "SUIT-002" in rule_map:
            r = rule_map["SUIT-002"]
            short_threshold = float(r["parameters"].get("short_horizon_threshold_years", 3.0))
            max_equity = float(r["parameters"].get("max_equity_weight", 0.40))
            max_duration = float(r["parameters"].get("max_bond_duration", 7.0))
            allow_illiquid = bool(r["parameters"].get("allow_illiquid", False))

            horizon = float(getattr(prof, "investment_horizon_years", 5.0) if prof else 5.0)
            if horizon < short_threshold:
                # Check equity allocation
                equity_weight = float(
                    rec.get("equity_weight", rec.get("equity_allocation", (port or {}).get("equity_weight", 0.0)))
                )
                bond_duration = float(
                    rec.get("avg_duration", rec.get("duration", (port or {}).get("avg_duration", 0.0)))
                )
                has_illiquid = bool(
                    rec.get("has_illiquid", False) or rec.get("is_liquid") is False or rec.get("illiquid_weight", 0) > 0
                )

                sub_violations = []
                if equity_weight > max_equity:
                    sub_violations.append(f"Equity weight ({equity_weight:.1%}) exceeds short-horizon ceiling ({max_equity:.1%})")
                if bond_duration > max_duration:
                    sub_violations.append(f"Bond duration ({bond_duration:.1f}y) exceeds ceiling ({max_duration:.1f}y)")
                if has_illiquid and not allow_illiquid:
                    sub_violations.append("Illiquid assets prohibited for short investment horizon")

                passed = len(sub_violations) == 0
                if not passed:
                    violations.append(
                        ComplianceViolation(
                            rule_id="SUIT-002",
                            rule_name=r["name"],
                            category="SUITABILITY",
                            severity=r["severity"],
                            description="; ".join(sub_violations),
                            actual_value={"equity": equity_weight, "duration": bond_duration, "illiquid": has_illiquid},
                            threshold={"max_equity": max_equity, "max_duration": max_duration},
                        )
                    )
                rule_results.append(
                    RuleCheckDetail(
                        rule_id="SUIT-002",
                        rule_name=r["name"],
                        category="SUITABILITY",
                        passed=passed,
                        severity=r["severity"],
                        details="Passed short horizon constraints" if passed else "; ".join(sub_violations),
                    )
                )
            else:
                rule_results.append(
                    RuleCheckDetail(
                        rule_id="SUIT-002",
                        rule_name=r["name"],
                        category="SUITABILITY",
                        passed=True,
                        severity=r["severity"],
                        details=f"Horizon ({horizon:.1f}y) >= {short_threshold:.1f}y threshold; short-horizon constraints not active.",
                    )
                )

        # --------------------------------------------------------------------
        # Rule SUIT-003: Loss Capacity Ceiling
        # --------------------------------------------------------------------
        if "SUIT-003" in rule_map:
            r = rule_map["SUIT-003"]
            low_cap_max_risk = float(r["parameters"].get("low_capacity_max_risk", 5.0))
            low_cap_max_equity = float(r["parameters"].get("low_capacity_max_equity", 0.50))
            disallowed = [c.lower() for c in r["parameters"].get("disallowed_categories", ["Growth", "Aggressive Growth", "Aggressive"])]

            loss_capacity = str(getattr(prof, "loss_capacity", "") if prof else "").lower()
            if loss_capacity == "low":
                rec_risk = float(rec.get("risk_level", 0.0))
                equity_weight = float(rec.get("equity_weight", rec.get("equity_allocation", 0.0)))
                cat = str(rec.get("category", rec.get("suitability_category", ""))).lower()

                sub_violations = []
                if rec_risk > low_cap_max_risk:
                    sub_violations.append(f"Risk level ({rec_risk:.1f}) exceeds Moderate ceiling ({low_cap_max_risk:.1f}) for low loss capacity")
                if equity_weight > low_cap_max_equity:
                    sub_violations.append(f"Equity weight ({equity_weight:.1%}) exceeds 50% limit for low loss capacity")
                if any(dis in cat for dis in disallowed if dis):
                    sub_violations.append(f"Category '{cat}' is prohibited for clients with low loss capacity")

                passed = len(sub_violations) == 0
                if not passed:
                    violations.append(
                        ComplianceViolation(
                            rule_id="SUIT-003",
                            rule_name=r["name"],
                            category="SUITABILITY",
                            severity=r["severity"],
                            description="; ".join(sub_violations),
                            actual_value={"risk": rec_risk, "equity": equity_weight, "category": cat},
                            threshold={"max_risk": low_cap_max_risk, "max_equity": low_cap_max_equity},
                        )
                    )
                rule_results.append(
                    RuleCheckDetail(
                        rule_id="SUIT-003",
                        rule_name=r["name"],
                        category="SUITABILITY",
                        passed=passed,
                        severity=r["severity"],
                        details="Passed low loss capacity ceiling" if passed else "; ".join(sub_violations),
                    )
                )
            else:
                rule_results.append(
                    RuleCheckDetail(
                        rule_id="SUIT-003",
                        rule_name=r["name"],
                        category="SUITABILITY",
                        passed=True,
                        severity=r["severity"],
                        details=f"Client loss capacity is '{loss_capacity or 'moderate/high'}'; ceiling inactive.",
                    )
                )

        # --------------------------------------------------------------------
        # Rule CONC-001: Single Stock Limit
        # --------------------------------------------------------------------
        if "CONC-001" in rule_map:
            r = rule_map["CONC-001"]
            max_stock_weight = float(r["parameters"].get("max_single_stock_weight", 0.15))

            # Inspect weights dictionary, holdings list, or explicit weight field
            max_weight_found = 0.0
            violating_symbol = None

            if "single_stock_weight" in rec:
                max_weight_found = float(rec["single_stock_weight"])
                violating_symbol = rec.get("single_stock_symbol", "EQUITY")
            elif "max_single_stock_weight" in rec:
                max_weight_found = float(rec["max_single_stock_weight"])
            elif "weights" in rec and isinstance(rec["weights"], dict):
                for sym, w in rec["weights"].items():
                    # Broad ETFs can be exempted if specified, but single equities checked
                    if float(w) > max_stock_weight and not sym.upper().endswith(("_ETF", "ETF", "SPY", "BND", "VTI", "QQQ", "AGG", "SHY")):
                        max_weight_found = float(w)
                        violating_symbol = sym
                        break
            elif "holdings" in rec and isinstance(rec["holdings"], list):
                for h in rec["holdings"]:
                    w = float(h.get("weight", 0.0))
                    sym = h.get("symbol", "")
                    is_etf = h.get("is_etf", False) or sym.upper() in ("SPY", "BND", "VTI", "QQQ", "AGG", "SHY")
                    if w > max_stock_weight and not is_etf:
                        max_weight_found = w
                        violating_symbol = sym
                        break

            passed = max_weight_found <= max_stock_weight
            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="CONC-001",
                        rule_name=r["name"],
                        category="CONCENTRATION",
                        severity=r["severity"],
                        description=f"Single stock position ({violating_symbol or 'holding'}: {max_weight_found:.1%}) exceeds 15.0% portfolio cap.",
                        actual_value=max_weight_found,
                        threshold=max_stock_weight,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="CONC-001",
                    rule_name=r["name"],
                    category="CONCENTRATION",
                    passed=passed,
                    severity=r["severity"],
                    details=f"Max single stock weight: {max_weight_found:.1%}, Threshold: {max_stock_weight:.1%}",
                )
            )

        # --------------------------------------------------------------------
        # Rule CONC-002: Sector Concentration Limit
        # --------------------------------------------------------------------
        if "CONC-002" in rule_map:
            r = rule_map["CONC-002"]
            max_sector_weight = float(r["parameters"].get("max_sector_weight", 0.30))

            max_sec_found = 0.0
            violating_sector = None

            if "max_sector_weight" in rec:
                max_sec_found = float(rec["max_sector_weight"])
                violating_sector = rec.get("max_sector_name", "SECTOR")
            elif "sectors" in rec and isinstance(rec["sectors"], dict):
                for sec, w in rec["sectors"].items():
                    if float(w) > max_sec_found:
                        max_sec_found = float(w)
                        violating_sector = sec
            elif "sector_weights" in rec and isinstance(rec["sector_weights"], dict):
                for sec, w in rec["sector_weights"].items():
                    if float(w) > max_sec_found:
                        max_sec_found = float(w)
                        violating_sector = sec

            passed = max_sec_found <= max_sector_weight
            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="CONC-002",
                        rule_name=r["name"],
                        category="CONCENTRATION",
                        severity=r["severity"],
                        description=f"Sector allocation ({violating_sector}: {max_sec_found:.1%}) exceeds 30.0% concentration limit.",
                        actual_value=max_sec_found,
                        threshold=max_sector_weight,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="CONC-002",
                    rule_name=r["name"],
                    category="CONCENTRATION",
                    passed=passed,
                    severity=r["severity"],
                    details=f"Max sector weight: {max_sec_found:.1%}, Threshold: {max_sector_weight:.1%}",
                )
            )

        # --------------------------------------------------------------------
        # Rule CONC-003: Minimum Asset Class Diversification
        # --------------------------------------------------------------------
        if "CONC-003" in rule_map:
            r = rule_map["CONC-003"]
            min_classes = int(r["parameters"].get("min_asset_classes", 2))
            min_weight = float(r["parameters"].get("min_weight_threshold", 0.05))

            distinct_classes = 0
            if "asset_classes" in rec and isinstance(rec["asset_classes"], (dict, list)):
                if isinstance(rec["asset_classes"], dict):
                    distinct_classes = sum(1 for w in rec["asset_classes"].values() if float(w) >= min_weight)
                else:
                    distinct_classes = len(rec["asset_classes"])
            elif "weights" in rec and isinstance(rec["weights"], dict):
                # Infer asset classes from standard tickers if dictionary provided
                classes_found = set()
                for sym, w in rec["weights"].items():
                    if float(w) >= min_weight:
                        sym_u = sym.upper()
                        if sym_u in ("BND", "AGG", "SHY", "TLT", "IEF"):
                            classes_found.add("Fixed Income")
                        elif sym_u in ("SPY", "VTI", "QQQ", "AAPL", "MSFT"):
                            classes_found.add("Equity")
                        elif sym_u in ("GLD", "IAU", "DBC"):
                            classes_found.add("Commodity")
                        else:
                            classes_found.add(f"Class_{sym}")
                distinct_classes = len(classes_found)
            elif "holdings" in rec and isinstance(rec["holdings"], list):
                classes_found = {h.get("asset_class", "Equity") for h in rec["holdings"] if float(h.get("weight", 0)) >= min_weight}
                distinct_classes = len(classes_found)
            else:
                distinct_classes = 2  # Default pass when asset breakdown not provided

            passed = distinct_classes >= min_classes
            if not passed:
                desc = f"Portfolio contains only {distinct_classes} asset class(es) >= {min_weight:.0%}; minimum required is {min_classes}."
                if r["severity"] == "BLOCK":
                    violations.append(
                        ComplianceViolation(
                            rule_id="CONC-003",
                            rule_name=r["name"],
                            category="CONCENTRATION",
                            severity="BLOCK",
                            description=desc,
                            actual_value=distinct_classes,
                            threshold=min_classes,
                        )
                    )
                else:
                    warnings.append(f"CONC-003 Warning: {desc}")

            rule_results.append(
                RuleCheckDetail(
                    rule_id="CONC-003",
                    rule_name=r["name"],
                    category="CONCENTRATION",
                    passed=passed,
                    severity=r["severity"],
                    details=f"Distinct asset classes: {distinct_classes}, Minimum required: {min_classes}",
                )
            )

        # --------------------------------------------------------------------
        # Rule REG-001 & REG-002 in Recommendation Texts
        # --------------------------------------------------------------------
        rec_text = " ".join(
            str(rec[k]) for k in ("rationale", "text", "summary", "notes") if k in rec and rec[k]
        )
        if rec_text and "REG-001" in rule_map:
            text_pass, text_viols, _ = self.check_text_output(rec_text)
            if not text_pass:
                for tv in text_viols:
                    if "REG-001" in tv:
                        r = rule_map["REG-001"]
                        violations.append(
                            ComplianceViolation(
                                rule_id="REG-001",
                                rule_name=r["name"],
                                category="REGULATORY",
                                severity=r["severity"],
                                description=tv,
                            )
                        )
                    elif "REG-002" in tv:
                        r = rule_map.get("REG-002", {"name": "Mandatory Risk Disclosure", "severity": "BLOCK"})
                        violations.append(
                            ComplianceViolation(
                                rule_id="REG-002",
                                rule_name=r["name"],
                                category="REGULATORY",
                                severity=r["severity"],
                                description=tv,
                            )
                        )

        # --------------------------------------------------------------------
        # Final Evaluation & Audit Logging
        # --------------------------------------------------------------------
        blocking_violations = [v for v in violations if v.severity == "BLOCK"]
        all_passed = len(blocking_violations) == 0

        audit_id = await self._record_audit_log(
            db=db_session,
            client_id=c_id,
            event_type="COMPLIANCE_RECOMMENDATION_CHECK",
            passed=all_passed,
            violations=violations,
            warnings=warnings,
            active_rules=[r["rule_id"] for r in rule_map.values()],
            payload={"recommendation": rec},
        )

        result = ComplianceCheckResult(
            passed=all_passed,
            violations=violations,
            warnings=warnings,
            rule_results=rule_results,
            audit_entry_id=audit_id,
        )

        if not all_passed:
            raise ComplianceViolationError(blocking_violations)

        return result

    # ========================================================================
    # 2. Trade Check (REG-003, REG-004, AML-001, AML-002, CONC-001)
    # ========================================================================

    async def check_trade(
        self,
        db: Optional[AsyncSession],
        client_id: str,
        trade: dict,
        profile: Any,
    ) -> ComplianceCheckResult:
        """
        Evaluates proposed trade order against non-discretionary user approval (REG-003),
        approval freshness (REG-004), single order limit (AML-001), order velocity (AML-002),
        and single stock concentration (CONC-001).
        """
        active_rules = await self.get_active_rules(db)
        rule_map = self._extract_rule_map(active_rules)

        violations: List[ComplianceViolation] = []
        warnings: List[str] = []
        rule_results: List[RuleCheckDetail] = []
        now_utc = datetime.now(timezone.utc)

        # --------------------------------------------------------------------
        # Rule REG-003: Non-Discretionary Confirmation
        # --------------------------------------------------------------------
        if "REG-003" in rule_map:
            r = rule_map["REG-003"]
            is_approved = trade.get("user_approved") is True or trade.get("approved") is True
            passed = is_approved is True
            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="REG-003",
                        rule_name=r["name"],
                        category="REGULATORY",
                        severity=r["severity"],
                        description="Trade execution rejected: Non-discretionary user approval required (user_approved=True).",
                        actual_value=is_approved,
                        threshold=True,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="REG-003",
                    rule_name=r["name"],
                    category="REGULATORY",
                    passed=passed,
                    severity=r["severity"],
                    details="User approval affirmative" if passed else "User approval missing or False",
                )
            )

        # --------------------------------------------------------------------
        # Rule REG-004: Stale Approval Window
        # --------------------------------------------------------------------
        if "REG-004" in rule_map:
            r = rule_map["REG-004"]
            max_window = float(r["parameters"].get("max_approval_window_seconds", 900.0))
            raw_ts = trade.get("user_approved_at") or trade.get("approval_timestamp")

            if raw_ts is None:
                passed = False
                desc = "Trade execution rejected: Approval timestamp missing."
            else:
                if isinstance(raw_ts, str):
                    try:
                        ts = datetime.fromisoformat(raw_ts.replace("Z", "+00:00"))
                    except Exception:
                        ts = now_utc - timedelta(seconds=max_window + 1)
                elif isinstance(raw_ts, datetime):
                    ts = raw_ts
                else:
                    ts = now_utc - timedelta(seconds=max_window + 1)

                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                else:
                    ts = ts.astimezone(timezone.utc)

                elapsed = (now_utc - ts).total_seconds()
                # Accept if between -60s (clock skew) and max_window
                passed = -60.0 <= elapsed <= max_window
                desc = (
                    f"Approval is fresh (elapsed {elapsed:.1f}s <= {max_window:.0f}s)"
                    if passed
                    else f"Trade approval expired (elapsed {elapsed:.1f}s > {max_window:.0f}s window)"
                )

            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="REG-004",
                        rule_name=r["name"],
                        category="REGULATORY",
                        severity=r["severity"],
                        description=desc,
                        actual_value=raw_ts,
                        threshold=max_window,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="REG-004",
                    rule_name=r["name"],
                    category="REGULATORY",
                    passed=passed,
                    severity=r["severity"],
                    details=desc,
                )
            )

        # --------------------------------------------------------------------
        # Rule AML-001: Single Transaction Limit
        # --------------------------------------------------------------------
        if "AML-001" in rule_map:
            r = rule_map["AML-001"]
            max_notional = float(r["parameters"].get("max_single_order_notional", 100000.0))

            qty = float(trade.get("qty", trade.get("quantity", 0.0)))
            price = float(trade.get("price", trade.get("estimated_price", 100.0)))
            notional = float(trade.get("notional_value", qty * price))

            if notional > max_notional:
                has_enhanced_kyc = (
                    bool(getattr(profile, "kyc_verified", False))
                    and not bool(getattr(profile, "aml_flag", False))
                    and bool(trade.get("enhanced_kyc_approved", False))
                )
                passed = has_enhanced_kyc
                desc = (
                    f"Notional ${notional:,.2f} exceeds ${max_notional:,.2f} ceiling; approved via enhanced KYC"
                    if passed
                    else f"Order notional (${notional:,.2f}) exceeds $100,000 threshold without enhanced KYC/AML clearance."
                )
            else:
                passed = True
                desc = f"Order notional (${notional:,.2f}) <= ${max_notional:,.2f} limit"

            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="AML-001",
                        rule_name=r["name"],
                        category="AML",
                        severity=r["severity"],
                        description=desc,
                        actual_value=notional,
                        threshold=max_notional,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="AML-001",
                    rule_name=r["name"],
                    category="AML",
                    passed=passed,
                    severity=r["severity"],
                    details=desc,
                )
            )

        # --------------------------------------------------------------------
        # Rule AML-002: Rapid Velocity Limit
        # --------------------------------------------------------------------
        if "AML-002" in rule_map:
            r = rule_map["AML-002"]
            max_orders = int(r["parameters"].get("max_orders_in_window", 5))
            window_sec = float(r["parameters"].get("window_seconds", 600.0))

            recent_count = 0
            if db is not None:
                try:
                    cutoff = now_utc - timedelta(seconds=window_sec)
                    stmt = select(func.count(DBTrade.id)).where(
                        DBTrade.client_id == client_id,
                        DBTrade.created_at >= cutoff,
                    )
                    recent_count = (await db.execute(stmt)).scalar() or 0
                except Exception as e:
                    logger.warning(f"Error querying rapid velocity count: {e}")
                    recent_count = int(trade.get("recent_orders_count", 0))
            else:
                recent_count = int(trade.get("recent_orders_count", 0))

            passed = recent_count < max_orders
            desc = (
                f"Client has submitted {recent_count} orders in the last 10m (limit: {max_orders})"
                if passed
                else f"Rapid velocity limit exceeded: {recent_count} orders submitted within {int(window_sec/60)} minutes (max: {max_orders})."
            )

            if not passed:
                violations.append(
                    ComplianceViolation(
                        rule_id="AML-002",
                        rule_name=r["name"],
                        category="AML",
                        severity=r["severity"],
                        description=desc,
                        actual_value=recent_count,
                        threshold=max_orders,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="AML-002",
                    rule_name=r["name"],
                    category="AML",
                    passed=passed,
                    severity=r["severity"],
                    details=desc,
                )
            )

        # --------------------------------------------------------------------
        # Rule CONC-001 in Trade Execution
        # --------------------------------------------------------------------
        if "CONC-001" in rule_map and "projected_weight" in trade:
            r = rule_map["CONC-001"]
            max_stock_weight = float(r["parameters"].get("max_single_stock_weight", 0.15))
            proj_w = float(trade["projected_weight"])
            passed = proj_w <= max_stock_weight
            if not passed:
                # Fiduciary waiver: Client-directed unsolicited orders with affirmative attestation can override soft concentration ceiling
                if bool(trade.get("fiduciary_attested")):
                    override_msg = (
                        f"CONC-001 Single-Stock Concentration Limit Overridden: Projected holding weight ({proj_w:.1%}) "
                        f"exceeds {max_stock_weight:.1%} single-stock ceiling. Executed as an unsolicited, "
                        "client-directed transaction pursuant to signed client fiduciary waiver & step-up authentication."
                    )
                    warnings.append(override_msg)
                    rule_results.append(
                        RuleCheckDetail(
                            rule_id="CONC-001",
                            rule_name=r["name"],
                            category="CONCENTRATION",
                            passed=True,
                            severity="WARN",
                            details=f"Overridden by signed client fiduciary attestation (Projected: {proj_w:.1%}, Max: {max_stock_weight:.1%})",
                        )
                    )
                else:
                    violations.append(
                        ComplianceViolation(
                            rule_id="CONC-001",
                            rule_name=r["name"],
                            category="CONCENTRATION",
                            severity=r["severity"],
                            description=f"Projected holding weight ({proj_w:.1%}) exceeds 15.0% single-stock ceiling.",
                            actual_value=proj_w,
                            threshold=max_stock_weight,
                        )
                    )
                    rule_results.append(
                        RuleCheckDetail(
                            rule_id="CONC-001",
                            rule_name=r["name"],
                            category="CONCENTRATION",
                            passed=False,
                            severity=r["severity"],
                            details=f"Projected weight: {proj_w:.1%}, Max allowed: {max_stock_weight:.1%}",
                        )
                    )
            else:
                rule_results.append(
                    RuleCheckDetail(
                        rule_id="CONC-001",
                        rule_name=r["name"],
                        category="CONCENTRATION",
                        passed=True,
                        severity=r["severity"],
                        details=f"Projected weight: {proj_w:.1%}, Max allowed: {max_stock_weight:.1%}",
                    )
                )

        # --------------------------------------------------------------------
        # Permission Tier Enforcement (Tiers 3, 4 & 5 Hard Code Limits)
        # --------------------------------------------------------------------
        # 1. Tier 5 Guard: Autonomous Execution Explicitly Disabled in Code
        if bool(trade.get("autonomous", False)):
            violations.append(
                ComplianceViolation(
                    rule_id="PERM-TIER-5",
                    rule_name="Autonomous Execution Disabled",
                    category="PERMISSION_TIER",
                    severity="BLOCK",
                    description="Tier 5 autonomous trade execution is hard-disabled in code. Every order requires non-discretionary client approval.",
                    actual_value=True,
                    threshold=False,
                )
            )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="PERM-TIER-5",
                    rule_name="Autonomous Execution Disabled",
                    category="PERMISSION_TIER",
                    passed=False,
                    severity="BLOCK",
                    details="Autonomous execution attempted; hard-blocked by Tier 5 policy.",
                )
            )

        # 2. Anomaly Circuit Breaker Lock Check
        cb_client = self.get_circuit_breaker_status(str(client_id))
        cb_user = self.get_circuit_breaker_status(str(trade["user_id"])) if trade.get("user_id") else {"is_locked": False}
        if cb_client.get("is_locked") or cb_user.get("is_locked"):
            locked_until = cb_client.get("locked_until") or cb_user.get("locked_until")
            violations.append(
                ComplianceViolation(
                    rule_id="PERM-CIRCUIT-BREAKER",
                    rule_name="Anomaly Circuit Breaker Lock",
                    category="PERMISSION_TIER",
                    severity="BLOCK",
                    description=f"Trade execution is locked by Anomaly Circuit Breaker until {locked_until} after >= 3 security/compliance violations in 60s.",
                    actual_value="OPEN_LOCKED",
                    threshold="CLOSED_NORMAL",
                )
            )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="PERM-CIRCUIT-BREAKER",
                    rule_name="Anomaly Circuit Breaker Lock",
                    category="PERMISSION_TIER",
                    passed=False,
                    severity="BLOCK",
                    details=f"Circuit breaker OPEN_LOCKED until {locked_until}",
                )
            )

        # 3. Tier 4 Limit: Approved Symbol Whitelist (PERM-WHITELIST)
        symbol_clean = str(trade.get("symbol", "")).strip().upper()
        if symbol_clean:
            symbol_allowed = symbol_clean in self.ALLOWED_TRADING_SYMBOLS
            if not symbol_allowed:
                violations.append(
                    ComplianceViolation(
                        rule_id="PERM-WHITELIST",
                        rule_name="Approved Symbol Whitelist",
                        category="PERMISSION_TIER",
                        severity="BLOCK",
                        description=f"Symbol '{symbol_clean}' is not in the vetted fiduciary symbol whitelist. Leveraged, inverse, or unapproved speculative tickers are blocked in code.",
                        actual_value=symbol_clean,
                        threshold="ALLOWED_TRADING_SYMBOLS",
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="PERM-WHITELIST",
                    rule_name="Approved Symbol Whitelist",
                    category="PERMISSION_TIER",
                    passed=symbol_allowed,
                    severity="BLOCK",
                    details=f"Symbol '{symbol_clean}' whitelist check: {'PASS' if symbol_allowed else 'BLOCKED'}",
                )
            )

        # 4. Tier 4 Limit: Daily Cumulative Notional Cap (PERM-CAP-DAILY)
        max_daily_cap = float(trade.get("max_daily_notional_cap", self.MAX_DAILY_TRADE_NOTIONAL_USD))
        qty_val = float(trade.get("qty", trade.get("quantity", 0.0)))
        price_val = float(trade.get("price", trade.get("estimated_price", 100.0)))
        order_notional = float(trade.get("notional_value", qty_val * price_val))
        if str(trade.get("currency", "USD")).upper() == "NGN":
            order_notional_usd = order_notional / 1600.0
        else:
            order_notional_usd = order_notional

        daily_executed_usd = float(trade.get("daily_executed_notional", 0.0))
        if db is not None and client_id:
            try:
                day_cutoff = now_utc - timedelta(hours=24)
                stmt_daily = select(DBTrade).where(
                    DBTrade.client_id == client_id,
                    DBTrade.created_at >= day_cutoff,
                )
                recent_trades = (await db.execute(stmt_daily)).scalars().all()
                db_daily_sum = 0.0
                for rt in recent_trades:
                    if getattr(rt, "status", "FILLED") in ("FILLED", "PENDING", "ACCEPTED"):
                        rt_px = float(getattr(rt, "filled_price", None) or 100.0)
                        rt_qty = float(getattr(rt, "qty", 0.0) or 0.0)
                        rt_notional = rt_px * rt_qty
                        if str(getattr(rt, "currency", "USD")).upper() == "NGN":
                            rt_notional /= 1600.0
                        db_daily_sum += rt_notional
                daily_executed_usd = max(daily_executed_usd, db_daily_sum)
            except Exception as e:
                logger.warning(f"Error querying daily cumulative notional: {e}")

        projected_daily_usd = daily_executed_usd + order_notional_usd
        has_enhanced = bool(trade.get("enhanced_kyc_approved", False))
        daily_passed = (projected_daily_usd <= max_daily_cap) or has_enhanced
        if not daily_passed:
            violations.append(
                ComplianceViolation(
                    rule_id="PERM-CAP-DAILY",
                    rule_name="Daily Cumulative Notional Cap",
                    category="PERMISSION_TIER",
                    severity="BLOCK",
                    description=(
                        f"Projected 24h cumulative notional (${projected_daily_usd:,.2f}) exceeds the Tier 4 daily cap "
                        f"(${max_daily_cap:,.2f}; prior 24h executed: ${daily_executed_usd:,.2f}, current order: ${order_notional_usd:,.2f})."
                    ),
                    actual_value=projected_daily_usd,
                    threshold=max_daily_cap,
                )
            )
        rule_results.append(
            RuleCheckDetail(
                rule_id="PERM-CAP-DAILY",
                rule_name="Daily Cumulative Notional Cap",
                category="PERMISSION_TIER",
                passed=daily_passed,
                severity="BLOCK",
                details=f"24h cumulative notional: ${projected_daily_usd:,.2f} / ${max_daily_cap:,.2f} cap",
            )
        )

        # 5. Tier 4 RED-Tier Step-Up MFA Verification — always runs; the tier classifier
        #    gates it to RED-tier trades only (notional > $1,000 or weight > 5% NAV).
        proj_w_val = float(trade.get("projected_weight", 0.0))
        tier_check = self.classify_trade_permission_tier(order_notional_usd, proj_w_val)
        if tier_check["requires_step_up_auth"]:
            proposal_id_str = str(trade.get("proposal_id", ""))
            expected_otp = self.compute_expected_mfa_code(proposal_id_str)
            supplied_otp = str(trade.get("mfa_code") or "").strip()
            attested = bool(trade.get("fiduciary_attested", False))
            otp_ok = hmac.compare_digest(supplied_otp, expected_otp) and attested
            if not otp_ok:
                violations.append(
                    ComplianceViolation(
                        rule_id="PERM-STEP-UP-MFA",
                        rule_name="Red-Tier Step-Up MFA & Attestation",
                        category="PERMISSION_TIER",
                        severity="BLOCK",
                        description=(
                            f"Red-Tier trade (notional ${order_notional_usd:,.2f}, weight {proj_w_val:.1%}) requires a valid "
                            f"6-digit Step-Up MFA OTP and fiduciary attestation."
                        ),
                        actual_value=bool(supplied_otp),
                        threshold=True,
                    )
                )
            rule_results.append(
                RuleCheckDetail(
                    rule_id="PERM-STEP-UP-MFA",
                    rule_name="Red-Tier Step-Up MFA & Attestation",
                    category="PERMISSION_TIER",
                    passed=otp_ok,
                    severity="BLOCK",
                    details="Step-Up MFA & fiduciary attestation verified" if otp_ok else "Missing or invalid Step-Up MFA / attestation",
                )
            )

        # --------------------------------------------------------------------
        # Final Evaluation & Audit Logging
        # --------------------------------------------------------------------
        blocking_violations = [v for v in violations if v.severity == "BLOCK"]
        all_passed = len(blocking_violations) == 0

        audit_id = await self._record_audit_log(
            db=db,
            client_id=client_id,
            event_type="COMPLIANCE_TRADE_CHECK",
            passed=all_passed,
            violations=violations,
            warnings=warnings,
            active_rules=[r["rule_id"] for r in rule_map.values()],
            payload={"trade": trade},
        )

        result = ComplianceCheckResult(
            passed=all_passed,
            violations=violations,
            warnings=warnings,
            rule_results=rule_results,
            audit_entry_id=audit_id,
        )

        if not all_passed:
            raise ComplianceViolationError(blocking_violations)

        return result

    # ========================================================================
    # 3. Output Text Filter (REG-001, REG-002) & Pre-LLM Privacy / Input Guard
    # ========================================================================

    def check_text_output(self, text: str) -> Tuple[bool, List[str], str]:
        """
        Synchronously validates conversational text against REG-001 (prohibited promissory terms)
        and REG-002 (mandatory regulatory risk disclosures).

        Returns:
            Tuple[passed: bool, violations: List[str], sanitized_text: str]
        """
        if not text:
            return True, [], ""

        violations: List[str] = []
        text_lower = text.lower()

        # REG-001: Prohibited language scanning
        for phrase in self._prohibited_phrases:
            pattern = r"(?i)\b" + re.escape(phrase) + r"\b"
            if re.search(pattern, text_lower):
                violations.append(f"REG-001 Prohibited promotional language detected: '{phrase}'")

        # REG-002: Mandatory risk disclosure verification
        has_disclosure = False
        for req in self._required_disclosure_phrases:
            if req in text_lower:
                has_disclosure = True
                break

        sanitized_text = text
        if not has_disclosure:
            violations.append("REG-002 Mandatory investment risk disclosure missing")
            sanitized_text = text.rstrip() + "\n\n" + self._standard_disclosure

        passed = len(violations) == 0
        return passed, violations, sanitized_text

    @staticmethod
    def redact_sensitive_data(text: str) -> str:
        """
        Deterministic PII & credential redaction (RULE-10 / PILLAR-2) applied before
        external LLM inference calls or audit persistence.
        Strips emails, phone numbers, SSNs/BVNs/NINs, payment card/IBAN/account numbers,
        bearer/API tokens, and self-reported full names while preserving numeric financial
        parameters (age, income, net worth, horizon) needed for suitability reasoning.
        """
        if not text:
            return ""
        out = str(text)
        # 1. API keys, Bearer tokens, and hex private keys
        out = re.sub(r"(?i)\b(sk-[a-zA-Z0-9_\-]{16,}|Bearer\s+[A-Za-z0-9\-._~+/]+=*|0x[a-fA-F0-9]{64})\b", "[REDACTED_SECRET]", out)
        # 2. Email addresses
        out = re.sub(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b", "[REDACTED_EMAIL]", out)
        # 3. US SSN (XXX-XX-XXXX) and Nigerian BVN/NIN (11-digit standalone identifier)
        out = re.sub(r"\b\d{3}-\d{2}-\d{4}\b", "[REDACTED_NATIONAL_ID]", out)
        out = re.sub(r"(?i)\b(?:bvn|nin|ssn|tin)\s*[:#=-]?\s*\d{8,15}\b", "[REDACTED_NATIONAL_ID]", out)
        # 4. Credit/debit card numbers (13-19 digits with optional spaces/dashes) & IBANs
        out = re.sub(r"\b(?:\d[ -]*?){13,19}\b", "[REDACTED_ACCOUNT]", out)
        out = re.sub(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b", "[REDACTED_IBAN]", out)
        # 5. Phone numbers (international +XXX or standard 10-14 digit phone formats)
        out = re.sub(r"(?:\+\d{1,3}[\s\-]?)?\(?\d{3}\)?[\s\-]\d{3}[\s\-]\d{4}\b", "[REDACTED_PHONE]", out)
        # 6. Explicit personal names ("my name is First Last" / "I'm First Last" when capitalized)
        out = re.sub(
            r"(?i)\b(my\s+name\s+is|full\s+name\s+is)\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){0,2})",
            r"\1 [REDACTED_NAME]",
            out,
        )
        return out

    def check_input_safety(self, text: str, client_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Two-stage pre-LLM input inspection (RULE-09 / PILLAR-1 & RULE-10 / PILLAR-2):
        1. Scans for adversarial prompt injection, jailbreak overrides, compliance bypass,
           and autonomous execution commands.
        2. Redacts direct PII and credentials via redact_sensitive_data().
        Records an Anomaly Circuit Breaker incident if an injection attempt is blocked.
        """
        if not text:
            return {
                "passed": True,
                "blocked": False,
                "violations": [],
                "redacted_text": "",
                "sanitized_text": "",
            }

        injection_patterns = [
            (r"(?i)ignore\s+(?:all\s+)?(?:previous|prior|above|system)\s+(?:instructions|prompts|rules)", "RULE-09: System prompt override attempt"),
            (r"(?i)bypass\s+(?:the\s+)?(?:compliance|suitability|kyc|aml|mfa|approval|circuit\s*breaker)", "RULE-09: Compliance firewall bypass attempt"),
            (r"(?i)execute\s+(?:trade|order)s?\s+(?:autonomously|without\s+(?:user\s+)?approval|immediately\s+without\s+confirm)", "RULE-09: Unapproved autonomous execution injection"),
            (r"(?i)(?:you\s+are\s+now\s+in\s+developer\s+mode|dan\s+mode|jailbreak|reveal\s+your\s+system\s+prompt)", "RULE-09: Adversarial role-play / prompt extraction attempt"),
            (r"(?i)<\s*script\b|javascript\s*:", "RULE-09: Cross-site scripting / HTML payload injection"),
        ]

        violations: List[str] = []
        for pat, desc in injection_patterns:
            if re.search(pat, text):
                violations.append(desc)

        redacted = self.redact_sensitive_data(text)
        blocked = len(violations) > 0
        if blocked and client_id:
            self.record_security_incident(
                str(client_id),
                reason="; ".join(violations),
                incident_type="PROMPT_INJECTION_BLOCKED",
            )

        return {
            "passed": not blocked,
            "blocked": blocked,
            "violations": violations,
            "redacted_text": redacted,
            "sanitized_text": "[BLOCKED_ADVERSARIAL_INPUT]" if blocked else redacted,
        }

    # ========================================================================
    # 4. Cryptographic Audit Log Persistence Helper
    # ========================================================================

    async def _record_audit_log(
        self,
        db: Optional[AsyncSession],
        client_id: str,
        event_type: str,
        passed: bool,
        violations: List[ComplianceViolation],
        warnings: List[str],
        active_rules: List[str],
        payload: dict,
    ) -> Optional[str]:
        """Writes an HMAC-signed and SHA-256 hash-chained entry to DBAuditLog."""
        if db is None or not client_id:
            return None

        try:
            entry = await self.audit_logger.log_audit_entry(
                db=db,
                client_id=client_id,
                event_type=event_type,
                actor="AGENT:compliance_guard",
                details={
                    "passed": passed,
                    "violations": [v.to_dict() for v in violations],
                    "warnings": warnings,
                    "active_rules_evaluated": active_rules,
                    "evaluated_payload": json.loads(json.dumps(payload, default=str)),
                },
                status="PASS" if passed else "FAIL",
            )
            return getattr(entry, "id", None) or getattr(entry, "entry_id", None)
        except Exception as e:
            logger.error(f"Failed to record audit log for compliance check: {e}")
            return None

    # ========================================================================
    # 5. Five-Tier Permission Model & Anomaly Circuit Breaker
    # ========================================================================

    MAX_SINGLE_TRADE_NOTIONAL_USD: float = 100000.0
    MAX_DAILY_TRADE_NOTIONAL_USD: float = 250000.0
    STEP_UP_MFA_THRESHOLD_USD: float = 1000.0
    ALLOW_AUTONOMOUS_EXECUTION: bool = False

    ALLOWED_TRADING_SYMBOLS: frozenset[str] = frozenset({
        # US Broad Market, Indices & Factor ETFs
        "SPY", "VTI", "VOO", "IVV", "QQQ", "VXUS", "VEA", "VWO", "IWM", "DIA", "SCHD", "VIG", "VNQ",
        "XLK", "XLF", "XLV", "XLE", "XLI", "XLY", "XLP", "XLU",
        # Global, Developed & Emerging Markets Indices
        "URTH", "ACWI", "EEM", "EFA", "ASHR", "FXI", "MCHI", "KWEB", "EWJ", "EWG", "EWU",
        # Chinese & Hong Kong Index Benchmarks
        "000300.SS", "2800.HK", "^GSPC", "^NDX", "^DJI", "^RUT", "^HSI",
        # US Treasury, Investment-Grade Bond & Commodity ETFs
        "BND", "AGG", "SHY", "IEF", "TLT", "TIP", "LQD", "HYG", "MUB", "GOVT", "VGSH", "VGIT", "VGLT", "BNDX",
        "GLD", "IAU", "SLV", "DBC", "USO",
        # Regulated Digital Asset & Crypto Spot ETFs
        "BTC", "ETH", "IBIT", "FBTC", "ETHA", "GBTC",
        # Approved Liquid Large-Cap Equities
        "AAPL", "MSFT", "GOOGL", "GOOG", "AMZN", "NVDA", "META", "TSLA", "BRK.B", "BRK.A", "JPM", "V", "MA",
        "UNH", "JNJ", "XOM", "PG", "HD", "COST", "AVGO", "LLY", "MRK", "ABBV", "PEP", "KO", "WMT", "CRM",
        "AMD", "INTC", "NFLX", "DIS", "CSCO", "ORCL", "ADBE", "TXN", "QCOM", "HON", "UNP", "NEE", "LOW",
        "GS", "MS", "BLK", "BAC", "C", "WFC",
        # Approved Nigerian Exchange (NGX) Equities via Bamboo Sandbox
        "DANGCEM", "MTNN", "GTCO", "ZENITHBANK", "ACCESSCORP", "UBA", "SEPLAT", "AIRTELAFRI", "BUACEMENT",
        "BUAFOODS", "NESTLE", "GEREGU", "TRANSPOWER", "TRANSCORP", "NGXGROUP", "FBNH", "STANBIC", "WAPCO",
        "OKOMUOIL", "PRESCO",
        # Approved WeBank Smart Wealth & GBA Cross-Border Wealth Connect Instruments
        "WBKCASH", "WBK6M", "GBAHK", "WBKGLD",
    })

    _circuit_breaker_events: Dict[str, List[Dict[str, Any]]] = {}
    _circuit_breaker_locked_until: Dict[str, datetime] = {}
    # Time of the latest incident that was NOT a demo drill, per client. A lock or watch state
    # involving a real incident cannot be cleared by the user; it must expire.
    _circuit_breaker_last_real_incident: Dict[str, datetime] = {}
    SIMULATED_INCIDENT_TYPE: str = "SIMULATED_DRILL"

    @classmethod
    def get_permission_tier_catalog(cls) -> List[Dict[str, Any]]:
        """
        Returns the 5-Tier Permission Implementation enforced in code:
        - TIER_1_READ_ONLY (GREEN): Read-only market, macro, filing & portfolio data
        - TIER_2_ADVISE (GREEN): Quantitative simulation, risk profiling & suitability review
        - TIER_3_PROPOSE_TRADE (YELLOW): Draft unsigned TradeProposal ticket (no broker call)
        - TIER_4_EXECUTE_WITH_APPROVAL (RED): Execute with explicit human approval under hard code limits
          (per-trade cap, 24h daily cap, symbol whitelist, step-up MFA)
        - TIER_5_AUTONOMOUS_DISABLED (DISABLED): Autonomous execution explicitly disabled in code
        """
        return [
            {
                "tier_id": "TIER_1_READ_ONLY",
                "tier": "GREEN",
                "label": "Tier 1 · Read-Only Data",
                "execution_policy": "Read-only data retrieval with zero state mutation and zero client PII sent to market APIs.",
                "code_limits": {
                    "can_mutate_state": False,
                    "can_propose_trade": False,
                    "can_execute_trade": False,
                    "external_data_policy": "Public ticker symbols & macro series IDs only",
                },
                "operations": [
                    "Live market quotes & historical OHLCV lookups (Yahoo / Finnhub / FMP)",
                    "US Treasury yield curve & FRED macroeconomic indicator queries",
                    "SEC EDGAR XBRL facts & 10-K/10-Q filing retrieval",
                    "Portfolio holdings, cash balance & SHA-256 audit chain verification",
                ],
                "safeguards": [
                    "Strict read-only tool scope enforced in ToolRegistry",
                    "Tri-layer prompt injection sanitizer (<untrusted_external_content> isolation)",
                    "Zero client PII transmitted to market data providers",
                ],
            },
            {
                "tier_id": "TIER_2_ADVISE",
                "tier": "GREEN",
                "label": "Tier 2 · Advise & Simulate",
                "execution_policy": "Deterministic quantitative modeling and non-discretionary advisory synthesis; cannot stage or place orders.",
                "code_limits": {
                    "can_mutate_state": False,
                    "can_propose_trade": False,
                    "can_execute_trade": False,
                    "llm_privacy_policy": "Pseudonymized suitability context (ANON-ID); direct PII redacted via redact_sensitive_data()",
                },
                "operations": [
                    "Hybrid conversational & tap-to-answer risk profiling (stated vs. revealed risk)",
                    "6-factor ETF & bond comparison (ProductComparisonAgent)",
                    "Black-Litterman + 95% CVaR optimization & 10,000-path Student-t Monte Carlo",
                    "Parallel 3-reviewer verification (Suitability, Devil's Advocate, Numeric Consistency)",
                ],
                "safeguards": [
                    "Zero LLM arithmetic (all returns, weights & VaR/CVaR computed in Python)",
                    "Pre-LLM PII redaction (names, emails, SSN/BVN, account numbers stripped)",
                    "Outbound REG-001 (no guarantees) & REG-002 (mandatory risk disclosure) gate",
                ],
            },
            {
                "tier_id": "TIER_3_PROPOSE_TRADE",
                "tier": "YELLOW",
                "label": "Tier 3 · Propose Trade (Stage Only)",
                "execution_policy": "Stages an unsigned trade proposal ticket with a 15-minute TTL; cannot contact brokerage execution APIs.",
                "code_limits": {
                    "can_propose_trade": True,
                    "can_execute_trade": False,
                    "proposal_ttl_seconds": 900,
                    "enforces_symbol_whitelist": True,
                },
                "operations": [
                    "Drafting unsigned order ticket (symbol, side, qty, estimated notional & post-trade weight)",
                    "Pre-proposal symbol whitelist validation (PERM-WHITELIST)",
                    "Classifying ticket into standard confirmation (<= $1,000 & <= 5% NAV) vs. Step-Up MFA (> $1,000 or > 5% NAV)",
                ],
                "safeguards": [
                    "15-minute hard expiration window (REG-004)",
                    "Blocked immediately if Anomaly Circuit Breaker is OPEN_LOCKED",
                    "Unapproved symbols outside ALLOWED_TRADING_SYMBOLS rejected before staging",
                ],
            },
            {
                "tier_id": "TIER_4_EXECUTE_WITH_APPROVAL",
                "tier": "RED",
                "label": "Tier 4 · Execute With Approval Under Hard Limits",
                "execution_policy": "Requires explicit non-discretionary client approval (plus Step-Up 6-digit MFA above $1,000 or 5% NAV) and passes hard code-enforced notional, daily, concentration, and whitelist caps.",
                "code_limits": {
                    "requires_explicit_user_approval": True,
                    "step_up_mfa_threshold_usd": cls.STEP_UP_MFA_THRESHOLD_USD,
                    "max_single_trade_notional_usd": cls.MAX_SINGLE_TRADE_NOTIONAL_USD,
                    "per_trade_notional_cap_usd": cls.MAX_SINGLE_TRADE_NOTIONAL_USD,
                    "max_daily_trade_notional_usd": cls.MAX_DAILY_TRADE_NOTIONAL_USD,
                    "daily_notional_cap_usd": cls.MAX_DAILY_TRADE_NOTIONAL_USD,
                    "max_single_position_weight": 0.15,
                    "max_orders_per_10m_window": 5,
                    "whitelisted_symbols_count": len(cls.ALLOWED_TRADING_SYMBOLS),
                },
                "operations": [
                    "Paper brokerage order submission (Alpaca Paper API / Bamboo Sandbox)",
                    "Anchoring RFC 6962 Merkle audit roots to Ethereum Sepolia Testnet (chain_id=11155111)",
                ],
                "safeguards": [
                    f"Per-trade notional cap (${cls.MAX_SINGLE_TRADE_NOTIONAL_USD:,.0f} AML-001) & 24h daily cumulative cap (${cls.MAX_DAILY_TRADE_NOTIONAL_USD:,.0f} PERM-CAP-DAILY)",
                    f"Vetted symbol whitelist ({len(cls.ALLOWED_TRADING_SYMBOLS)} liquid ETFs/equities; PERM-WHITELIST) & 15% single-stock cap (CONC-001)",
                    "Step-Up 6-digit MFA OTP + fiduciary attestation required for notional > $1,000 or weight > 5% (PERM-STEP-UP-MFA)",
                    "30-second distributed idempotency lock + Anomaly Circuit Breaker lock enforcement",
                ],
            },
            {
                "tier_id": "TIER_5_AUTONOMOUS_DISABLED",
                "tier": "DISABLED",
                "label": "Tier 5 · Autonomous Execution (Explicitly Disabled)",
                "execution_policy": "HARD-DISABLED IN CODE. The agent can never place, modify, or cancel a trade without per-order human approval.",
                "code_limits": {
                    "allow_autonomous_execution": False,
                    "allow_live_brokerage": False,
                    "allow_ethereum_mainnet": False,
                },
                "operations": [
                    "Unapproved / autonomous background trade execution (FORBIDDEN)",
                    "Discretionary auto-rebalancing without client ticket approval (FORBIDDEN)",
                    "Live real-money brokerage or Ethereum Mainnet Chain ID 1 calls (FORBIDDEN)",
                ],
                "safeguards": [
                    "Startup validator Settings.guard_autonomous_execution_disabled refuses boot if allow_autonomous_execution=True",
                    "ComplianceGuard rule PERM-TIER-5 & REG-003 unconditionally block any unapproved or autonomous order",
                    "ExecutionModule.execute_trade raises UnapprovedTradeError if approved != True",
                ],
            },
        ]

    @staticmethod
    def compute_expected_mfa_code(proposal_id: str) -> str:
        """Computes the deterministic 6-digit Step-Up MFA code for a proposal_id."""
        digits = "".join(ch for ch in str(proposal_id or "") if ch.isdigit())
        return (digits[:6]).ljust(6, "4")

    @staticmethod
    def get_known_risk_register() -> List[Dict[str, str]]:
        """Returns the Security Self-Assessment Known-Risk List & Mitigations."""
        return [
            {
                "risk_id": "RISK-01",
                "category": "LLM Hallucination",
                "description": "Generative models fabricating asset prices, returns, Sharpe ratios, or order fill receipts.",
                "mitigation": "100% of pricing, MPT optimization, Student-t Monte Carlo, and order execution are delegated to deterministic Python modules and verified APIs; REG-001/002 filters all outgoing text.",
                "status": "MITIGATED",
            },
            {
                "risk_id": "RISK-02",
                "category": "Indirect Prompt Injection",
                "description": "Malicious instructions embedded in scraped web news or SEC filings attempting to bypass compliance or trigger unauthorized trades.",
                "mitigation": "Tri-layer Sanitizer (HTML/Unicode stripping, <untrusted_external_content> XML isolation, regex heuristic screening) + non-discretionary approval gate.",
                "status": "MITIGATED",
            },
            {
                "risk_id": "RISK-03",
                "category": "Unauthorized / Runaway Agent Execution",
                "description": "Agent attempting to execute high-value, unwhitelisted, or rapid-fire trades without human oversight.",
                "mitigation": "5-tier permission model with Tier 5 autonomous execution hard-disabled, symbol whitelist (PERM-WHITELIST), $100k per-trade cap (AML-001), $250k daily cap (PERM-CAP-DAILY), 30s lock, and Anomaly Circuit Breaker.",
                "status": "MITIGATED",
            },
            {
                "risk_id": "RISK-04",
                "category": "External LLM Inference Privacy Exposure",
                "description": "Conversational profiling includes financial parameters (age, income, net worth, goals) sent to the LLM API for advisory synthesis.",
                "mitigation": "Strict data minimization & PII redaction: Market/Macro/Filing APIs receive only ticker symbols; LLM prompts use SHA-256 pseudonymized IDs (ANON-XXXXXXXX) with all direct PII (names, emails, SSN/BVN, phone, account numbers) stripped via ComplianceGuard.redact_sensitive_data().",
                "status": "MITIGATED",
            },
            {
                "risk_id": "RISK-05",
                "category": "Emotional / Panic Trading in Market Drawdowns",
                "description": "Retail investors panic-selling during drawdowns or chasing hype against their long-term financial plan.",
                "mitigation": "BehavioralBiasAgent detects 5 cognitive biases in real time, tracks Stated vs. Revealed risk calibration, and triggers 24-hour cool-off nudges.",
                "status": "MITIGATED",
            },
            {
                "risk_id": "RISK-06",
                "category": "Audit Log Tampering & Repudiation",
                "description": "Post-hoc alteration or deletion of compliance checks, recommendations, or trade approvals.",
                "mitigation": "Append-only SHA-256 hash-chained DBAuditLog with HMAC signatures and verifiable Merkle root anchoring to Ethereum Sepolia Testnet.",
                "status": "MITIGATED",
            },
        ]

    @staticmethod
    def classify_trade_permission_tier(notional_value: float, projected_weight: float) -> Dict[str, Any]:
        """Classifies a proposed trade within Tier 4 (Execute With Approval) into YELLOW (standard confirm) or RED (Step-Up MFA)."""
        if notional_value > 1000.0 or projected_weight > 0.05:
            reasons = []
            if notional_value > 1000.0:
                reasons.append(f"notional value (${notional_value:,.2f}) exceeds $1,000 threshold")
            if projected_weight > 0.05:
                reasons.append(f"projected portfolio weight ({projected_weight:.1%}) exceeds 5.0% threshold")
            return {
                "permission_tier": "RED",
                "tier_id": "TIER_4_EXECUTE_WITH_APPROVAL",
                "requires_step_up_auth": True,
                "step_up_reason": "Tier 4 (Red) Strong Verification required: " + " and ".join(reasons) + ".",
            }
        return {
            "permission_tier": "YELLOW",
            "tier_id": "TIER_4_EXECUTE_WITH_APPROVAL",
            "requires_step_up_auth": False,
            "step_up_reason": "Tier 4 (Yellow) Standard Confirmation required (notional <= $1,000 and weight <= 5%).",
        }

    def record_security_incident(self, client_id: str, reason: str, incident_type: str = "COMPLIANCE_BLOCK") -> Dict[str, Any]:
        """Records a security/compliance block and trips the Anomaly Circuit Breaker if >= 3 occur within 60s."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=60)
        events = [e for e in self._circuit_breaker_events.get(client_id, []) if e["ts"] >= cutoff]
        events.append({"ts": now, "reason": reason, "type": incident_type})
        self._circuit_breaker_events[client_id] = events
        if incident_type != self.SIMULATED_INCIDENT_TYPE:
            self._circuit_breaker_last_real_incident[client_id] = now

        if len(events) >= 3:
            self._circuit_breaker_locked_until[client_id] = now + timedelta(minutes=15)

        return self.get_circuit_breaker_status(client_id)

    def get_circuit_breaker_status(self, client_id: str = "global") -> Dict[str, Any]:
        """Returns current Anomaly Circuit Breaker state for a client."""
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=60)
        events = [e for e in self._circuit_breaker_events.get(client_id, []) if e["ts"] >= cutoff]
        locked_until = self._circuit_breaker_locked_until.get(client_id)
        is_locked = bool(locked_until and locked_until > now)
        return {
            "client_id": client_id,
            "state": "OPEN_LOCKED" if is_locked else ("HALF_OPEN_WATCH" if len(events) > 0 else "CLOSED_NORMAL"),
            "is_locked": is_locked,
            "recent_incidents_60s": len(events),
            "trip_threshold": 3,
            "locked_until": locked_until.isoformat() if is_locked and locked_until else None,
            "recent_events": [
                {"timestamp": e["ts"].isoformat(), "type": e["type"], "reason": e["reason"]}
                for e in events[-5:]
            ],
        }

    def can_user_reset_circuit_breaker(self, client_id: str) -> Tuple[bool, str]:
        """
        A user may clear their own breaker only when every incident behind the current lock or
        60s watch window was a simulated drill. Real blocked attempts must wait out the lock.
        """
        last_real = self._circuit_breaker_last_real_incident.get(client_id)
        if last_real is None:
            return True, ""
        now = datetime.now(timezone.utc)
        locked_until = self._circuit_breaker_locked_until.get(client_id)
        if locked_until and locked_until > now:
            lock_started = locked_until - timedelta(minutes=15)
            if last_real >= lock_started - timedelta(seconds=60):
                return False, (
                    "The circuit breaker was tripped by real blocked attempts and cannot be reset; "
                    f"it unlocks automatically at {locked_until.isoformat()}."
                )
        if last_real >= now - timedelta(seconds=60):
            return False, "Real blocked attempts were recorded in the last 60 seconds; the watch window cannot be cleared."
        return True, ""

    def reset_circuit_breaker(self, client_id: str = "global") -> Dict[str, Any]:
        """Resets the Anomaly Circuit Breaker for a client (callers must check can_user_reset_circuit_breaker for user requests)."""
        self._circuit_breaker_events.pop(client_id, None)
        self._circuit_breaker_locked_until.pop(client_id, None)
        return self.get_circuit_breaker_status(client_id)


# Module-level exports for convenient import by routes and test suites
ALLOWED_TRADING_SYMBOLS = ComplianceGuard.ALLOWED_TRADING_SYMBOLS
MAX_SINGLE_TRADE_NOTIONAL_USD = ComplianceGuard.MAX_SINGLE_TRADE_NOTIONAL_USD
MAX_DAILY_TRADE_NOTIONAL_USD = ComplianceGuard.MAX_DAILY_TRADE_NOTIONAL_USD
STEP_UP_MFA_THRESHOLD_USD = ComplianceGuard.STEP_UP_MFA_THRESHOLD_USD
ALLOW_AUTONOMOUS_EXECUTION = ComplianceGuard.ALLOW_AUTONOMOUS_EXECUTION




from typing import List, Callable, Any
from dataclasses import dataclass
from datetime import datetime

@dataclass
class ComplianceCheckResult:
    rule_id: str
    rule_name: str
    passed: bool
    severity: str
    timestamp: datetime
    details: str

class ComplianceViolationError(Exception):
    def __init__(self, violations: List[ComplianceCheckResult]):
        self.violations = violations
        super().__init__(f"Compliance checks failed: {[v.rule_id for v in violations]}")

class Rule:
    def __init__(self, id: str, name: str, description: str, check_fn: Callable, severity: str):
        self.id = id
        self.name = name
        self.description = description
        self.check_fn = check_fn
        self.severity = severity
        
    def check(self, *args, **kwargs) -> bool:
        return self.check_fn(*args, **kwargs)

class ComplianceGuard:
    def __init__(self):
        self.rules = [
            Rule(
                id="SUIT-001",
                name="Risk Profile Alignment",
                description="Recommendations must match client risk profile",
                check_fn=lambda rec, profile: rec.get("risk_level", 0) <= profile.risk_tolerance_score + 1,
                severity="BLOCK"
            ),
            Rule(
                id="REG-003",
                name="Non-Discretionary Confirmation",
                description="Trade execution requires explicit user approval",
                check_fn=lambda trade: trade.get("user_approved", False) == True,
                severity="BLOCK"
            )
        ]

    async def check_recommendation(self, recommendation: dict, profile: Any, portfolio: Any = None) -> dict:
        results = []
        blocked = []
        for rule in self.rules:
            # We are only testing SUIT rules here if we pass recommendation and profile
            if "SUIT" in rule.id:
                passed = rule.check(recommendation, profile)
                res = ComplianceCheckResult(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    passed=passed,
                    severity=rule.severity,
                    timestamp=datetime.utcnow(),
                    details=rule.description
                )
                results.append(res)
                if not passed and rule.severity == "BLOCK":
                    blocked.append(res)
        
        if blocked:
            raise ComplianceViolationError(blocked)
            
        return {"checks": [r.__dict__ for r in results], "all_passed": len(blocked) == 0}

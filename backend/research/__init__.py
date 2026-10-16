"""
backend/research/__init__.py
============================
Autonomous Research Engine: TaskGraph, Tenant Memory, Self-Verification.
"""

from .task_graph import (
    TaskGraph,
    TaskGraphState,
    ResearchTask,
    SubtaskResult,
    TaskStatus,
    AnalystRole,
)
from .memory import (
    TenantMemoryManager,
    StratifiedTTL,
    MemoryEntry,
)
from .verification import (
    SelfVerificationLoop,
    VerificationResult,
)

__all__ = [
    "TaskGraph",
    "TaskGraphState",
    "ResearchTask",
    "SubtaskResult",
    "TaskStatus",
    "AnalystRole",
    "TenantMemoryManager",
    "StratifiedTTL",
    "MemoryEntry",
    "SelfVerificationLoop",
    "VerificationResult",
]

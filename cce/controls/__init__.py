"""Control engine (L3) — the independent authority.

MUST NOT import ``cce.optimizer`` (INV-2). The validator receives a weight
vector and re-derives every metric from ``cce.risk``; it never reads a number
the optimizer reported about its own output.

Also performs NO I/O: it constructs verdicts and returns them. Persistence
and alerting belong to the service layer
(docs/02-ARCHITECTURE.md section 2).
"""

from __future__ import annotations

from .circuit_breaker import BreakerOutcome, evaluate_breaker
from .policy import (
    MATERIAL_CHANGE,
    PolicyChangePreview,
    ThresholdChange,
    diff_policies,
    is_weakening,
)
from .recovery import generate_recovery_candidates
from .state_machine import (
    CONTROL_CATEGORY,
    PORTFOLIO_METRIC,
    ClassificationResult,
    aggregate_state,
    classify,
)
from .validation import validate, validate_weights

__all__ = [
    "CONTROL_CATEGORY",
    "MATERIAL_CHANGE",
    "PORTFOLIO_METRIC",
    "BreakerOutcome",
    "ClassificationResult",
    "PolicyChangePreview",
    "ThresholdChange",
    "aggregate_state",
    "classify",
    "diff_policies",
    "evaluate_breaker",
    "generate_recovery_candidates",
    "is_weakening",
    "validate",
    "validate_weights",
]

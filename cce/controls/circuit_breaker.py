"""Circuit breaker and decision outcome generation.

Spec: docs/02-ARCHITECTURE.md section 7, docs/IMPLEMENTATION-PLAN.md Phase 6.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from ..contracts import (
    Actor, Alert, BreakerCategory, Candidate, DecisionEvent, SafeAllocation,
)

__all__ = ["BreakerOutcome", "evaluate_breaker"]


@dataclass(frozen=True)
class BreakerOutcome:
    """The result of the circuit breaker evaluation."""

    tripped: bool
    category: BreakerCategory | None
    rejected_candidate: Candidate | None
    preserved_allocation: SafeAllocation | None
    recovery_candidates: tuple[Candidate, ...]
    alert: Alert | None
    events: tuple[DecisionEvent, ...]


def evaluate_breaker(
    candidate: Candidate,
    last_safe_allocation: SafeAllocation | None,
    recovery_candidates: tuple[Candidate, ...] = (),
) -> BreakerOutcome:
    """Evaluate whether the circuit breaker should trip.

    A pure decision function: receives the candidate and the last safe
    allocation, and returns a description of what should happen, including
    constructed Alerts and DecisionEvents.

    It performs NO I/O (persistence belongs to the service layer).
    """
    now = datetime.now(timezone.utc)
    control = candidate.control

    # If not evaluated or passed, breaker does not trip
    if control is None or not control.circuit_breaker_active:
        return BreakerOutcome(
            tripped=False,
            category=None,
            rejected_candidate=None,
            preserved_allocation=last_safe_allocation,
            recovery_candidates=(),
            alert=None,
            events=(),
        )

    # Breaker trips on RED hard breach or NOT_VALIDATED
    cat = control.breaker_category or BreakerCategory.RISK

    if control.hard_breaches:
        reasons = "; ".join(b.message for b in control.hard_breaches)
    else:
        reasons = "Candidate validation could not be completed."

    alert = Alert(
        severity="RED",
        category=cat,
        title=f"Circuit Breaker Tripped ({cat.value})",
        message=reasons,
        created_at=now,
    )

    events = [
        DecisionEvent(
            sequence_no=1,
            occurred_at=now,
            actor=Actor.CONTROL,
            event_code="BREAKER_TRIPPED",
            summary=f"Circuit breaker tripped under {cat.value} category.",
            detail={"reasons": candidate.rejection_reasons},
        )
    ]

    if last_safe_allocation:
        events.append(DecisionEvent(
            sequence_no=2,
            occurred_at=now,
            actor=Actor.CONTROL,
            event_code="SAFE_ALLOCATION_PRESERVED",
            summary="Last Approved Safe Allocation preserved.",
        ))
    else:
        events.append(DecisionEvent(
            sequence_no=2,
            occurred_at=now,
            actor=Actor.CONTROL,
            event_code="NO_SAFE_ALLOCATION",
            summary="No prior safe allocation exists to preserve.",
        ))

    return BreakerOutcome(
        tripped=True,
        category=cat,
        rejected_candidate=candidate,
        preserved_allocation=last_safe_allocation,  # Returned UNCHANGED (INV-4)
        recovery_candidates=recovery_candidates,
        alert=alert,
        events=tuple(events),
    )

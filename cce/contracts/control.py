"""Control-engine, stress and candidate contracts.

Spec: docs/06-DATA-CONTRACTS.md section 6.

:attr:`Candidate.eligible_for_approval` is defined HERE, once. The UI reads
the property; it never reimplements the condition. A second implementation is
a bug waiting to diverge (INV-2, INV-10).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .enums import (
    BreakerCategory,
    CandidateRole,
    ControlStatus,
    StressStatus,
)
from .optimization import OptimizationResult
from .risk import Breach, RiskSnapshot

__all__ = ["Alert", "Candidate", "ControlResult", "StressResult"]


@dataclass(frozen=True)
class ControlResult:
    """The independent control engine's verdict on a candidate."""

    status: ControlStatus
    passed: bool
    findings: tuple[Breach, ...]
    hard_breaches: tuple[Breach, ...]
    warnings: tuple[Breach, ...]
    circuit_breaker_active: bool
    breaker_category: BreakerCategory | None
    recomputed: RiskSnapshot  # the control engine's OWN metrics
    last_safe_allocation: object | None = None  # SafeAllocation | None
    evaluated_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.passed and self.hard_breaches:
            raise ValueError(
                "cannot pass with hard breaches present (INV-3)"
            )
        if self.passed and self.status is not ControlStatus.PASSED:
            raise ValueError("passed=True requires status PASSED")


@dataclass(frozen=True)
class StressResult:
    """One scenario applied to one candidate."""

    scenario_code: str
    scenario_label: str
    is_custom: bool
    shocks: dict[str, float]
    portfolio_loss: float  # positive = loss
    loss_paise: int
    contribution: dict[str, float]
    post_shock_volatility: float | None
    post_shock_cvar: float | None
    breaches: tuple[Breach, ...]
    loss_threshold: float
    status: StressStatus
    #: Why this scenario produced no verdict. Set only when ``status`` is
    #: ERROR or NOT_RUN. An unexplained ERROR tells a risk manager that
    #: something went wrong and nothing about what, which is not enough to
    #: act on — and the log line it replaces is not in front of them.
    error_reason: str | None = None

    def __post_init__(self) -> None:
        if self.status is StressStatus.ERROR and not self.error_reason:
            raise ValueError(
                "an ERROR stress result must carry an error_reason (INV-10)"
            )
        if self.status is StressStatus.PASSED and self.error_reason:
            raise ValueError("a PASSED stress result cannot carry an error_reason")

    @property
    def passed(self) -> bool:
        return self.status is StressStatus.PASSED

    @property
    def loss_is_measured(self) -> bool:
        """Whether ``portfolio_loss`` is a real measurement.

        ``portfolio_loss`` is a plain float, so an ERROR or unrun scenario
        still carries 0.0. That zero is an artefact of the type, not a
        finding: rendering it as "0.0% loss" would report a scenario the
        portfolio never faced as one it survived. The UI renders an em dash
        unless this is true (INV-5, INV-10).
        """
        return self.status in (StressStatus.PASSED, StressStatus.FAILED)


@dataclass(frozen=True)
class Alert:
    """A breaker or breach notification. CONSTRUCTED by the engines,
    PERSISTED by the service layer — controls perform no I/O."""

    severity: str  # INFO | AMBER | RED
    category: BreakerCategory
    title: str
    message: str
    created_at: datetime


@dataclass(frozen=True)
class Candidate:
    """A proposal plus every verdict on it. The unit the UI renders."""

    role: CandidateRole
    optimization: OptimizationResult
    control: ControlResult | None = None
    stress: tuple[StressResult, ...] = ()

    @property
    def stress_status(self) -> StressStatus:
        """Aggregate stress outcome.

        An ERROR or an unrun suite is NEVER equivalent to PASSED (INV-10).
        """
        if not self.stress:
            return StressStatus.NOT_RUN
        if any(s.status is StressStatus.ERROR for s in self.stress):
            return StressStatus.ERROR
        if any(s.status is StressStatus.NOT_RUN for s in self.stress):
            return StressStatus.NOT_RUN
        return (
            StressStatus.PASSED
            if all(s.passed for s in self.stress)
            else StressStatus.FAILED
        )

    @property
    def eligible_for_approval(self) -> bool:
        """The single gate for the Approve button.

        Defined once, here. The UI reads this; ApprovalService re-checks it
        server-side. A disabled button is convenience, not enforcement
        (INV-2, INV-10).
        """
        return (
            self.control is not None
            and self.control.status is ControlStatus.PASSED
            and self.control.passed
            and self.stress_status is StressStatus.PASSED
        )

    @property
    def rejection_reasons(self) -> tuple[str, ...]:
        """Specific reasons, with observed vs threshold. Never generic."""
        reasons: list[str] = []
        if self.control is not None:
            reasons.extend(b.message for b in self.control.hard_breaches)
        reasons.extend(
            f"{s.scenario_label}: loss {s.portfolio_loss:.1%} exceeds limit "
            f"{s.loss_threshold:.1%}"
            for s in self.stress
            if s.status is StressStatus.FAILED
        )
        return tuple(reasons)

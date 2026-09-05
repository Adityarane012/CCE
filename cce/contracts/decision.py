"""Decision, explanation and audit contracts.

Spec: docs/06-DATA-CONTRACTS.md section 7.

The structured :class:`Explanation` is the SOURCE OF TRUTH for all narrative
output (FR-141). ``llm_text`` is display only and is never parsed back into
any decision, metric or state (INV-1).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from .control import Candidate
from .enums import (
    Actor, BreakerCategory, CandidateRole, ControlStatus, HumanAction,
    Strategy, TriggerType,
)
from .portfolio import PortfolioState
from .risk import RiskChange, RiskSnapshot

__all__ = [
    "Explanation", "NarratedExplanation", "HumanActionRecord",
    "DecisionEvent", "SafeAllocation", "DecisionRecord",
]


@dataclass(frozen=True)
class Explanation:
    """Deterministic, structured account of one decision (FR-140).

    All nine fields. A field that does not apply is ``None`` or an empty
    tuple — never an empty string.
    """

    trigger: str
    risk_change: RiskChange | None
    main_contributors: tuple[RiskChange, ...]
    optimizer: Strategy | None
    candidate_summary: dict[str, float]
    control_result: str  # ACCEPTED | REJECTED | NOT_VALIDATED
    reasons: tuple[str, ...]
    stress_summary: tuple[str, ...]
    action: str
    expected_improvement: str | None = None


@dataclass(frozen=True)
class NarratedExplanation:
    """Structured explanation plus its prose renderings."""

    structured: Explanation           # authoritative
    template_text: str                # deterministic, ALWAYS present (FR-142)
    llm_text: str | None = None       # DISPLAY ONLY, never parsed back (INV-1)
    llm_model: str | None = None
    llm_error: str | None = None

    def __post_init__(self) -> None:
        if not self.template_text.strip():
            raise ValueError(
                "template_text must always be populated; the deterministic "
                "narrator is the shipping default, not a placeholder (FR-142)"
            )

    @property
    def display_text(self) -> str:
        """Prefer the LLM prose when present, else the template. Both are
        display artefacts — neither is ever read back into a decision."""
        return self.llm_text or self.template_text


@dataclass(frozen=True)
class HumanActionRecord:
    """A human decision, with attribution."""

    action: HumanAction
    user_identity: str
    user_role: str
    timestamp: datetime
    candidate_role: CandidateRole | None = None
    comment: str | None = None
    is_override: bool = False
    override_reason: str | None = None
    overridden_controls: tuple[str, ...] = ()
    confirmation_token: str | None = None

    def __post_init__(self) -> None:
        if self.is_override and not (
            self.override_reason
            and self.overridden_controls
            and self.confirmation_token
        ):
            raise ValueError(
                "override requires a reason, the overridden controls and an "
                "explicit confirmation token (FR-118)"
            )
        if self.action is HumanAction.OVERRIDE and not self.is_override:
            raise ValueError("OVERRIDE action requires is_override=True")


@dataclass(frozen=True)
class DecisionEvent:
    """One row of the Decision Replay timeline.

    ``actor`` distinguishes machine action, control judgement and human
    action. That distinction is the entire point of the replay page.
    """

    sequence_no: int
    occurred_at: datetime
    actor: Actor
    event_code: str
    summary: str
    detail: dict | None = None


@dataclass(frozen=True)
class SafeAllocation:
    """The Last Approved Safe Allocation.

    It passed the configured hard controls and stress validation AT THE TIME
    IT WAS APPROVED, under ``policy_version_id``. That is not a claim of
    future safety, and the name is never shortened to imply one.
    """

    safe_allocation_id: int
    approved_at: datetime
    weights: dict[str, float]
    decision_id: int
    policy_version_id: int
    approved_by: str
    via_override: bool = False


@dataclass(frozen=True)
class DecisionRecord:
    """The complete chain for one decision cycle."""

    event_uid: str
    timestamp: datetime
    trigger: TriggerType
    trigger_detail: str | None

    portfolio_before: PortfolioState
    risk_before: RiskSnapshot

    candidates: tuple[Candidate, ...]
    recommended: CandidateRole | None

    control_status: ControlStatus
    circuit_breaker_active: bool
    breaker_category: BreakerCategory | None

    explanation: NarratedExplanation
    events: tuple[DecisionEvent, ...] = ()

    human_action: HumanActionRecord | None = None
    portfolio_after: PortfolioState | None = None

    @property
    def is_closed(self) -> bool:
        return self.human_action is not None

    def candidate(self, role: CandidateRole) -> Candidate | None:
        for c in self.candidates:
            if c.role is role:
                return c
        return None

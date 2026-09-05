"""Persistence data shapes.

Spec: docs/05-BACKEND-SCHEMA.md section 6.

Two kinds of object live here:

- **Write metadata** (``PolicyChangeMeta``, ``MarketSnapshotMeta``,
  ``DecisionContext``) — attribution and foreign keys the domain contracts do
  not carry, because they are facts about persistence rather than about
  finance.
- **Read models** (``DecisionSummary``, ``StoredCandidate``,
  ``StoredDecision``) — what actually came back out of the database.

The read models are deliberately NOT
:class:`~cce.contracts.decision.DecisionRecord`. That contract embeds a full
:class:`~cce.contracts.portfolio.PortfolioState`, which carries the return
series used to compute it; the series is not persisted, because it is derived
from market data that is. Returning a ``DecisionRecord`` would mean inventing
a return series to fill the field, and the system does not invent — on
failure it does less (Rule 2). A read model that reports exactly what was
stored is the honest shape.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from cce.contracts import Breach, DecisionEvent, StressStatus

__all__ = [
    "DecisionContext",
    "DecisionSummary",
    "MarketSnapshotMeta",
    "PolicyChangeMeta",
    "StoredCandidate",
    "StoredDecision",
    "StoredHumanAction",
    "StoredStressResult",
]


# ---------------------------------------------------------------------------
# write metadata
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PolicyChangeMeta:
    """Attribution for a policy version (INV-8).

    A weakening change — any hard limit loosened — must carry who
    acknowledged it and why. That is the entire point of versioning
    thresholds rather than editing them in place.
    """

    created_by: str
    created_by_role: str
    source: str  # FILE | UI_EDIT | SEED
    created_at: datetime | None = None
    parent_version_id: int | None = None
    change_summary: str | None = None
    is_weakening: bool = False
    weakening_ack_by: str | None = None
    weakening_reason: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"FILE", "UI_EDIT", "SEED"}:
            raise ValueError(
                f"source must be FILE, UI_EDIT or SEED; got {self.source!r}"
            )
        if self.is_weakening and not (self.weakening_ack_by and self.weakening_reason):
            raise ValueError(
                "a weakening policy change requires weakening_ack_by and "
                "weakening_reason (INV-8)"
            )


@dataclass(frozen=True)
class MarketSnapshotMeta:
    """Provenance for one market-data panel."""

    captured_at: datetime
    as_of_date: str
    provider: str
    universe_hash: str
    data_hash: str
    row_count: int
    asset_count: int
    validation_status: str
    validation_json: str
    cache_path: str | None = None


@dataclass(frozen=True)
class DecisionContext:
    """Everything known when a decision cycle opens."""

    event_uid: str
    created_at: datetime
    trigger_type: str
    trigger_detail: str | None
    snapshot_id: int
    policy_version_id: int
    portfolio_state_before: int
    risk_snapshot_before: int
    control_status: str
    circuit_breaker_active: bool
    breaker_trigger_category: str | None = None
    optimizer_strategy: str | None = None
    expected_return_method: str | None = None
    solver_status: str | None = None
    recommended_candidate_id: int | None = None


# ---------------------------------------------------------------------------
# read models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class DecisionSummary:
    """One row of the decision-history list."""

    decision_id: int
    event_uid: str
    created_at: datetime
    trigger_type: str
    control_status: str
    circuit_breaker_active: bool
    human_action: str | None
    breaker_trigger_category: str | None = None

    @property
    def is_closed(self) -> bool:
        return self.human_action is not None


@dataclass(frozen=True)
class StoredStressResult:
    """One persisted scenario outcome.

    ``status`` is kept alongside ``passed`` because NOT_RUN and ERROR are
    never equivalent to PASSED, and an audit trail that cannot tell "it
    failed" from "the engine errored" cannot explain an incident (INV-10).
    """

    scenario_code: str
    scenario_label: str
    is_custom: bool
    portfolio_loss: float
    loss_paise: int
    loss_threshold: float
    passed: bool
    status: StressStatus
    post_shock_volatility: float | None = None
    post_shock_cvar: float | None = None
    shocks: dict[str, float] = field(default_factory=dict)
    contribution: dict[str, float] = field(default_factory=dict)
    breaches: tuple[Breach, ...] = ()


@dataclass(frozen=True)
class StoredCandidate:
    """A candidate allocation as persisted, with both verdicts on it.

    The metric fields are the optimizer's ADVISORY self-report (FR-072). They
    are recorded so the audit trail shows what the optimizer claimed next to
    what the control engine independently found — never because they are
    authoritative.
    """

    candidate_id: int
    decision_id: int
    created_at: datetime
    role: str
    strategy: str
    weights: dict[str, float]
    solver_status: str
    control_status: str
    stress_status: str
    eligible_for_approval: bool
    expected_return: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None
    turnover: float | None = None
    transaction_cost_paise: int | None = None
    findings: tuple[Breach, ...] = ()
    stress: tuple[StoredStressResult, ...] = ()


@dataclass(frozen=True)
class StoredHumanAction:
    """A human decision as persisted, with full attribution (INV-6)."""

    action_id: int
    created_at: datetime
    action: str
    user_identity: str
    user_role: str
    candidate_id: int | None = None
    comment: str | None = None
    is_override: bool = False
    override_reason: str | None = None
    overridden_controls: tuple[str, ...] = ()
    confirmation_token: str | None = None


@dataclass(frozen=True)
class StoredDecision:
    """One complete decision, read back from persistence.

    Everything here was stored. Nothing is recomputed, and no field is filled
    in from a fresh calculation — that is what makes it a record rather than
    a report (INV-6).
    """

    decision_id: int
    event_uid: str
    created_at: datetime
    trigger_type: str
    trigger_detail: str | None
    snapshot_id: int
    policy_version_id: int
    portfolio_state_before: int
    risk_snapshot_before: int
    control_status: str
    circuit_breaker_active: bool
    breaker_trigger_category: str | None
    optimizer_strategy: str | None
    expected_return_method: str | None
    solver_status: str | None
    recommended_candidate_id: int | None
    portfolio_state_after: int | None
    candidates: tuple[StoredCandidate, ...] = ()
    events: tuple[DecisionEvent, ...] = ()
    human_action: StoredHumanAction | None = None
    template_text: str | None = None
    llm_text: str | None = None
    structured_explanation: dict | None = None

    @property
    def is_closed(self) -> bool:
        return self.human_action is not None

    def candidate(self, role: str) -> StoredCandidate | None:
        for c in self.candidates:
            if c.role == role:
                return c
        return None

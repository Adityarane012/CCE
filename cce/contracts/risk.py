"""Risk metric contracts.

Spec: docs/06-DATA-CONTRACTS.md section 5.

Conventions:
- Volatility and return are ANNUALISED unless the field name says otherwise.
- VaR/CVaR are 1-day at 95% unless the field name says otherwise.
- Losses are POSITIVE: ``cvar_95 = 0.087`` is an 8.7% expected tail loss.
- ``None`` means NOT COMPUTED. It never means zero, and the UI renders it as
  an em dash (INV-5).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from enum import Enum

from .enums import Comparator, ExpectedReturnMethod, RiskState, Scope, VaRMethod

__all__ = ["Breach", "ChangeAttribution", "ChangeDriver", "RiskChange", "RiskSnapshot"]


@dataclass(frozen=True)
class Breach:
    """A control that evaluated to AMBER or RED.

    Carries the observed value AND the threshold so the UI can show
    "9.4% > 8.0%" rather than an unhelpful "constraints violated" (FR-174).
    """

    control_code: str  # canonical code, docs/07-RISK-POLICY.md section 2
    control_label: str
    severity: RiskState
    is_hard: bool  # hard breaches at RED trip the circuit breaker
    observed: float
    threshold: float
    comparator: Comparator
    scope: str  # asset_id | sector | "PORTFOLIO"
    message: str

    @property
    def trips_breaker(self) -> bool:
        return self.is_hard and self.severity is RiskState.RED


@dataclass(frozen=True)
class RiskChange:
    """A single metric moving between two snapshots.

    Used by the "What Changed?" panel to separate allocation drift from a
    volatility regime change.
    """

    metric: str
    from_value: float
    to_value: float
    scope: str = Scope.PORTFOLIO.value

    @property
    def delta(self) -> float:
        return self.to_value - self.from_value


@dataclass(frozen=True)
class RiskSnapshot:
    """Every risk metric at a point in time, plus the resulting state.

    Any ``None`` field was not computed — typically too few observations. It
    must never be rendered as 0.
    """

    timestamp: datetime
    as_of_date: date

    historical_volatility: float | None
    ewma_volatility: float | None
    portfolio_volatility: float | None
    expected_return: float | None  # MODEL ESTIMATE (FR-062)
    expected_return_method: ExpectedReturnMethod | None
    sharpe: float | None

    var_95: float | None  # positive = loss
    cvar_95: float | None
    var_method: VaRMethod

    current_drawdown: float | None
    max_drawdown: float | None
    liquidity_ratio: float | None
    turnover_from_current: float | None

    risk_contribution: dict[str, float] = field(default_factory=dict)
    sector_exposure: dict[str, float] = field(default_factory=dict)
    sector_risk_contribution: dict[str, float] = field(default_factory=dict)
    concentration: dict[str, float] = field(default_factory=dict)

    risk_state: RiskState = RiskState.GREEN
    breaches: tuple[Breach, ...] = ()

    degraded: bool = False
    degraded_reason: str | None = None

    def __post_init__(self) -> None:
        if self.degraded and not self.degraded_reason:
            raise ValueError("degraded snapshot must carry a degraded_reason")
        if (
            self.cvar_95 is not None
            and self.var_95 is not None
            and self.cvar_95 < self.var_95 - 1e-9
        ):
            raise ValueError(
                f"CVaR ({self.cvar_95}) < VaR ({self.var_95}); the tail slice "
                "is wrong (docs/08-FINANCIAL-METHODS.md section 15)"
            )

    @property
    def hard_breaches(self) -> tuple[Breach, ...]:
        """RED breaches on hard controls — these trip the circuit breaker."""
        return tuple(b for b in self.breaches if b.trips_breaker)

    @property
    def warnings(self) -> tuple[Breach, ...]:
        return tuple(b for b in self.breaches if b.severity is RiskState.AMBER)


class ChangeDriver(str, Enum):
    """What actually moved the risk between two snapshots.

    The distinction the "What Changed?" panel exists to make. A portfolio
    whose weights are untouched but whose risk rose has a REGIME problem;
    one whose weights moved has an ALLOCATION problem. They call for
    opposite responses — rebalance, or reassess the model — and a panel that
    only says "volatility is up" leaves the reader to guess which.
    """

    ALLOCATION = "ALLOCATION"   # the book was traded
    REGIME = "REGIME"           # the market moved under an unchanged book
    BOTH = "BOTH"
    NONE = "NONE"


@dataclass(frozen=True)
class ChangeAttribution:
    """Why the risk moved, decomposed.

    Built by the service from two snapshots and the two weight vectors. The
    prose that describes it is rendered by the deterministic narrator, never
    assembled in the UI and never written by an LLM (docs/09 section 10).
    """

    driver: ChangeDriver
    metrics: tuple[RiskChange, ...] = ()
    contributors: tuple[RiskChange, ...] = ()
    max_weight_shift: float = 0.0
    weight_shift_threshold: float = 0.01

    @property
    def allocation_moved(self) -> bool:
        return self.max_weight_shift > self.weight_shift_threshold

    @property
    def headline(self) -> RiskChange | None:
        """The metric that moved most, in absolute terms."""
        return max(self.metrics, key=lambda c: abs(c.delta), default=None)

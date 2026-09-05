"""Optimizer input and output contracts.

Spec: docs/06-DATA-CONTRACTS.md section 6.

The optimizer PROPOSES. It never writes portfolio state, audit records or
control state (FR-063).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .enums import ExpectedReturnMethod, SolverStatus, Strategy

__all__ = ["Constraints", "OptimizationResult", "View"]


@dataclass(frozen=True)
class Constraints:
    """Everything the optimizer is told.

    The control engine does NOT reuse this to judge the result — it re-derives
    its own metrics from raw returns (FR-072). Two independent readings of the
    same policy is the point.
    """

    min_weights: dict[str, float]
    max_weights: dict[str, float]
    sector_max: dict[str, float]
    asset_class_max: dict[str, float] = field(default_factory=dict)
    min_liquid_share: float = 0.0
    min_cash_share: float = 0.0
    max_turnover: float = 1.0
    max_volatility: float | None = None
    max_cvar: float | None = None
    target_return: float | None = None
    long_only: bool = True
    include_txn_cost: bool = True

    def __post_init__(self) -> None:
        for aid, lo in self.min_weights.items():
            hi = self.max_weights.get(aid)
            if hi is not None and lo > hi:
                raise ValueError(
                    f"{aid}: min_weight {lo} exceeds max_weight {hi}"
                )
        if not 0.0 <= self.max_turnover <= 1.0:
            raise ValueError("max_turnover must be in [0, 1]")


@dataclass(frozen=True)
class OptimizationResult:
    """What the optimizer produced, and what it believes about it.

    The metric fields are ADVISORY ONLY. The control engine MUST recompute
    them independently and must never trust these values (FR-072). A test
    falsifies them and asserts the control verdict is unchanged.
    """

    strategy: Strategy
    expected_return_method: ExpectedReturnMethod
    solver_status: SolverStatus
    weights: dict[str, float] | None

    # --- optimizer's self-report. ADVISORY. Never trusted by controls. ---
    expected_return: float | None = None
    volatility: float | None = None
    sharpe: float | None = None
    var_95: float | None = None
    cvar_95: float | None = None
    turnover: float | None = None
    transaction_cost_paise: int | None = None

    solve_time_ms: int = 0
    diagnostics: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.weights is not None and not self.solver_status.usable:
            raise ValueError(
                "weights must be None unless solver_status is OPTIMAL; got "
                f"{self.solver_status.value} (INV-2)"
            )

    @property
    def succeeded(self) -> bool:
        return self.solver_status.usable and self.weights is not None


@dataclass(frozen=True)
class View:
    """One opinion, in the form a person actually states it.

    ``asset`` outperforms ``versus`` by ``outperformance`` (a decimal), with
    ``confidence`` in (0, 1]. ``versus=None`` is an absolute view on the
    asset's own return rather than a relative one.
    """

    asset: str
    outperformance: float
    confidence: float = 0.5
    versus: str | None = None

    def __post_init__(self) -> None:
        if not 0.0 < self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in (0, 1], got {self.confidence}"
            )
        if self.versus is not None and self.versus == self.asset:
            raise ValueError("a view cannot compare an asset with itself")

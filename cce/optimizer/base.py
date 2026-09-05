"""Optimizer abstraction.

Spec: docs/02-ARCHITECTURE.md section 4, docs/08-FINANCIAL-METHODS.md
section 11.

The optimizer PROPOSES. It never writes portfolio state, audit records or
control state (FR-063), and it never decides whether its own output is
acceptable — that is the control engine's job, and the control engine does
not import this package (INV-2).

Weights leave an optimizer ONLY when the solver returned OPTIMAL. The
``OptimizationResult`` contract enforces this, so a violation raises rather
than passing silently.
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..contracts import (
    Constraints,
    ExpectedReturnMethod,
    OptimizationResult,
    SolverStatus,
    Strategy,
    Universe,
)

logger = logging.getLogger(__name__)

__all__ = ["SOLVER_STATUS_MAP", "Optimizer", "OptimizerInputs", "failed_result"]

# CVXPY problem status -> our SolverStatus. Anything unmapped is an error:
# an unrecognised status must never be optimistically treated as success.
SOLVER_STATUS_MAP = {
    "optimal": SolverStatus.OPTIMAL,
    "optimal_inaccurate": SolverStatus.OPTIMAL_INACCURATE,
    "infeasible": SolverStatus.INFEASIBLE,
    "infeasible_inaccurate": SolverStatus.INFEASIBLE,
    "unbounded": SolverStatus.UNBOUNDED,
    "unbounded_inaccurate": SolverStatus.UNBOUNDED,
}


@dataclass(frozen=True)
class OptimizerInputs:
    """Everything an optimizer needs.

    Grouped so a caller cannot half-specify a problem, and validated on
    construction for the same reason ``RiskInputs`` is: an optimizer fed a
    malformed problem returns a plausible number for the wrong question.
    """

    universe: Universe
    returns: pd.DataFrame
    expected_returns: np.ndarray
    covariance: np.ndarray
    constraints: Constraints
    current_weights: dict[str, float]
    risk_free_rate: float = 0.065
    total_value_paise: int = 0
    return_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL
    frontier_points: int = 60
    #: From the policy, not assumed. The optimizer's self-reported VaR and
    #: CVaR are ADVISORY (FR-072), but an advisory number computed at a
    #: confidence nobody configured is a wrong number in an audit record —
    #: it would sit beside the control engine's figure at a different
    #: confidence and invite the comparison.
    var_confidence: float = 0.95
    min_observations: int = 250

    def __post_init__(self) -> None:
        n = len(self.asset_ids)
        if self.expected_returns.shape != (n,):
            raise ValueError(
                f"expected_returns has shape {self.expected_returns.shape}, "
                f"expected ({n},) to match the priced universe"
            )
        if self.covariance.shape != (n, n):
            raise ValueError(
                f"covariance has shape {self.covariance.shape}, expected "
                f"({n}, {n})"
            )
        total = sum(self.current_weights.values())
        if abs(total - 1.0) > 1e-6:
            raise ValueError(
                f"current_weights must sum to 1.0, got {total!r}; turnover "
                f"against a book that is not fully invested is meaningless"
            )

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """Canonical ordering. Every vector and matrix here follows it."""
        return tuple(c for c in self.returns.columns)

    @property
    def current_vector(self) -> np.ndarray:
        return np.array(
            [self.current_weights.get(a, 0.0) for a in self.asset_ids],
            dtype=float,
        )


def failed_result(
    strategy: Strategy,
    method: ExpectedReturnMethod,
    status: SolverStatus,
    reason: str,
    solve_time_ms: int = 0,
    **diagnostics,
) -> OptimizationResult:
    """A failure carrying its reason. Weights are always None.

    Constraints are NEVER silently relaxed to manufacture an answer: a
    relaxed constraint is a policy change, and policy changes go through the
    versioned, audited flow (EC-4.1).
    """
    logger.warning("optimization failed (%s): %s", status.value, reason)
    return OptimizationResult(
        strategy=strategy,
        expected_return_method=method,
        solver_status=status,
        weights=None,
        solve_time_ms=solve_time_ms,
        diagnostics={"reason": reason, **diagnostics},
    )


class Optimizer(ABC):
    """Base class. Subclasses implement :meth:`solve` only."""

    strategy: Strategy

    @abstractmethod
    def solve(self, inputs: OptimizerInputs) -> OptimizationResult:
        """Propose an allocation. Never mutates ``inputs``."""

    def _timed(self, start: float) -> int:
        return int((time.perf_counter() - start) * 1000)

    def __repr__(self) -> str:
        return f"{type(self).__name__}(strategy={self.strategy.value})"

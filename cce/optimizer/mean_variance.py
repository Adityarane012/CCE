"""Constrained maximum-Sharpe optimization — the default strategy.

Spec: docs/08-FINANCIAL-METHODS.md section 11.1, FR-050..FR-055.

The Sharpe ratio is NOT concave in ``w``, so maximising it is not directly a
convex program. Two stable resolutions exist (docs/08 section 11.1); this
module implements **the efficient-frontier scan**, deliberately:

    Solve a sequence of constrained minimum-variance QPs at target returns
    spanning the feasible range, compute the Sharpe of each, take the best.

Why this rather than the homogenisation transform: every original constraint
applies unchanged. The transform requires scaling every constraint by kappa,
and forgetting one produces a subtly wrong answer that still looks entirely
plausible. The scan is robust, easy to verify, and yields the efficient
frontier as a free UI artefact.

At 9 assets the cost is trivial.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

import cvxpy as cp
import numpy as np

from ..contracts import (
    Constraints,
    OptimizationResult,
    SolverStatus,
    Strategy,
)
from ..risk import portfolio_volatility
from .base import (
    SOLVER_STATUS_MAP,
    Optimizer,
    OptimizerInputs,
    failed_result,
)
from .constraints import (
    build_constraints,
    describe_infeasibility,
    transaction_cost_expr,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FrontierPoint",
    "MaxSharpeOptimizer",
    "efficient_frontier",
    "solve_min_variance",
    "solve_unconstrained_max_sharpe",
]


@dataclass(frozen=True)
class FrontierPoint:
    """One solved point on the efficient frontier."""

    target_return: float
    volatility: float
    expected_return: float
    sharpe: float
    weights: np.ndarray


def _solve(problem: cp.Problem) -> tuple[SolverStatus, str]:
    """Solve and map the status. An unrecognised status is an ERROR.

    Never optimistically treated as success: a near-solution to a
    risk-constrained problem may violate the constraints (EC-4.2).
    """
    try:
        problem.solve()
    except cp.error.SolverError as exc:
        return SolverStatus.SOLVER_ERROR, f"solver raised: {exc}"
    except Exception as exc:  # noqa: BLE001 - any solver blow-up is SOLVER_ERROR
        return SolverStatus.SOLVER_ERROR, f"{type(exc).__name__}: {exc}"

    raw = problem.status or "unknown"
    status = SOLVER_STATUS_MAP.get(raw, SolverStatus.SOLVER_ERROR)
    return status, raw


def solve_min_variance(
    inputs: OptimizerInputs,
    target_return: float | None = None,
    txn_penalty: float = 0.0,
) -> tuple[np.ndarray | None, SolverStatus, str]:
    """Minimum-variance QP, optionally at a target return.

    A clean convex problem: every policy constraint applies exactly as
    written, with no scaling to get wrong.
    """
    n = len(inputs.asset_ids)
    w = cp.Variable(n)
    current = inputs.current_vector

    cons = build_constraints(
        w, inputs.universe, inputs.constraints, current, inputs.asset_ids
    )
    if target_return is not None:
        cons.append(inputs.expected_returns @ w >= target_return)

    objective = cp.quad_form(w, cp.psd_wrap(inputs.covariance))
    if txn_penalty > 0.0 and inputs.constraints.include_txn_cost:
        rates = np.array(
            [inputs.universe.get(a).txn_cost_rate for a in inputs.asset_ids],
            dtype=float,
        )
        objective = objective + txn_penalty * transaction_cost_expr(
            w, current, rates
        )

    status, raw = _solve(cp.Problem(cp.Minimize(objective), cons))
    if not status.usable or w.value is None:
        return None, status, raw

    weights = np.asarray(w.value, dtype=float).ravel()
    weights = np.clip(weights, 0.0, None) if inputs.constraints.long_only else weights
    total = weights.sum()
    if total <= 0:
        return None, SolverStatus.SOLVER_ERROR, "solution sums to zero"
    return weights / total, status, raw


def efficient_frontier(
    inputs: OptimizerInputs, points: int | None = None
) -> list[FrontierPoint]:
    """Solve across the feasible return range.

    Infeasible targets are skipped rather than treated as failures — the
    ends of any scanned range are expected to be unreachable under
    constraints.
    """
    n_points = points or inputs.frontier_points
    mu = inputs.expected_returns

    # Feasible span: the constrained min-variance portfolio at the bottom,
    # the best single achievable asset return at the top.
    base, _, _ = solve_min_variance(inputs)
    if base is None:
        return []
    lo = float(mu @ base)
    hi = float(np.max(mu))
    targets = [lo] if hi <= lo else list(np.linspace(lo, hi, n_points))

    out: list[FrontierPoint] = []
    for t in targets:
        w, _, _ = solve_min_variance(inputs, target_return=t)
        if w is None:
            continue                       # target unreachable; not an error
        vol = portfolio_volatility(w, inputs.covariance)
        if vol <= 0.0:
            continue
        er = float(mu @ w)
        out.append(FrontierPoint(
            target_return=float(t), volatility=vol, expected_return=er,
            sharpe=(er - inputs.risk_free_rate) / vol, weights=w,
        ))
    return out


def solve_unconstrained_max_sharpe(
    inputs: OptimizerInputs,
) -> tuple[np.ndarray | None, SolverStatus, str]:
    """Max Sharpe under ONLY full investment and long-only.

    Produces the OPTIMAL_UNCONSTRAINED candidate for the Safe vs Optimal
    view. It is explicitly NOT policy-validated, and the UI labels it so
    (FR-055). This is the allocation a standard optimizer would hand you —
    and the one the control engine rejects.
    """
    relaxed = Constraints(
        min_weights=dict.fromkeys(inputs.asset_ids, 0.0),
        max_weights=dict.fromkeys(inputs.asset_ids, 1.0),
        sector_max={},
        asset_class_max={},
        min_liquid_share=0.0,
        min_cash_share=0.0,
        max_turnover=1.0,
        long_only=inputs.constraints.long_only,
        include_txn_cost=False,
    )
    relaxed_inputs = OptimizerInputs(
        universe=inputs.universe, returns=inputs.returns,
        expected_returns=inputs.expected_returns, covariance=inputs.covariance,
        constraints=relaxed, current_weights=inputs.current_weights,
        risk_free_rate=inputs.risk_free_rate,
        total_value_paise=inputs.total_value_paise,
        return_method=inputs.return_method,
        frontier_points=inputs.frontier_points,
    )
    frontier = efficient_frontier(relaxed_inputs)
    if not frontier:
        return None, SolverStatus.INFEASIBLE, "no feasible unconstrained point"
    best = max(frontier, key=lambda p: p.sharpe)
    return best.weights, SolverStatus.OPTIMAL, "optimal"


class MaxSharpeOptimizer(Optimizer):
    """Constrained maximum Sharpe via the efficient-frontier scan."""

    strategy = Strategy.MAX_SHARPE

    def __init__(self, txn_penalty: float = 1.0) -> None:
        self.txn_penalty = txn_penalty

    def solve(self, inputs: OptimizerInputs) -> OptimizationResult:
        start = time.perf_counter()

        frontier = efficient_frontier(inputs)
        if not frontier:
            notes = describe_infeasibility(
                inputs.universe, inputs.constraints, inputs.asset_ids
            )
            reason = "no feasible allocation satisfies the constraints"
            if notes:
                reason += ": " + "; ".join(notes)
            return failed_result(
                self.strategy, inputs.return_method, SolverStatus.INFEASIBLE,
                reason, self._timed(start), conflicts=notes,
            )

        best = max(frontier, key=lambda p: p.sharpe)
        return self._build_result(inputs, best, frontier, start)

    def _build_result(
        self,
        inputs: OptimizerInputs,
        best: FrontierPoint,
        frontier: list[FrontierPoint],
        start: float,
    ) -> OptimizationResult:
        from ..portfolio import transaction_cost_paise, turnover
        from ..risk import cvar_with_diagnostics, historical_var

        weights = inputs.universe.to_dict(best.weights) if len(
            best.weights
        ) == len(inputs.universe.assets) else dict(
            zip(inputs.asset_ids, best.weights.tolist(), strict=True)
        )

        realised = inputs.returns.to_numpy(dtype=float) @ best.weights
        import pandas as pd
        series = pd.Series(realised, index=inputs.returns.index)

        cost = (
            transaction_cost_paise(
                weights, inputs.current_weights, inputs.universe,
                inputs.total_value_paise,
            )
            if inputs.total_value_paise > 0 else None
        )

        return OptimizationResult(
            strategy=self.strategy,
            expected_return_method=inputs.return_method,
            solver_status=SolverStatus.OPTIMAL,
            weights=weights,
            # ADVISORY ONLY. The control engine recomputes all of this
            # independently and never trusts these values (FR-072).
            expected_return=best.expected_return,
            volatility=best.volatility,
            sharpe=best.sharpe,
            var_95=historical_var(series, 0.95, min_observations=250),
            cvar_95=cvar_with_diagnostics(
                series, 0.95, min_observations=250
            ).value,
            turnover=turnover(weights, inputs.current_weights),
            transaction_cost_paise=cost,
            solve_time_ms=self._timed(start),
            diagnostics={
                "frontier_points": len(frontier),
                "target_return": best.target_return,
                "method": "efficient_frontier_scan",
            },
        )

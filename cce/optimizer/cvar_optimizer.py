"""CVaR minimisation via the Rockafellar-Uryasev linearisation.

Spec: docs/08-FINANCIAL-METHODS.md section 11.5.

    minimise    zeta + (1 / ((1 - alpha) T)) * sum_t u_t
    subject to  u_t >= -(r_t . w) - zeta
                u_t >= 0
                + every policy constraint

A linear program. It optimises the TAIL DIRECTLY rather than through a
variance proxy, which is why it is the natural basis for a defensive
candidate: variance punishes upside and downside equally, and a risk manager
only loses sleep over one of them.

``zeta`` converges to the VaR at the same confidence, so the optimal value of
the objective IS the CVaR — no separate estimation step, and no chance of the
reported tail disagreeing with the optimised one.
"""

from __future__ import annotations

import logging
import time

import cvxpy as cp
import numpy as np

from ..contracts import OptimizationResult, SolverStatus, Strategy
from .base import OptimizerInputs, failed_result
from .constraints import build_constraints, transaction_cost_expr
from .mean_variance import MaxSharpeOptimizer, _solve

logger = logging.getLogger(__name__)

__all__ = ["CVaROptimizer", "solve_min_cvar"]


def solve_min_cvar(
    inputs: OptimizerInputs,
    confidence: float | None = None,
    txn_penalty: float = 0.0,
) -> tuple[np.ndarray | None, SolverStatus, str, float | None]:
    """Minimise CVaR at ``confidence`` over the historical scenarios.

    Returns ``(weights, status, note, cvar)``. ``cvar`` is the optimised tail
    loss as a POSITIVE fraction, read from the LP objective rather than
    recomputed — the two could otherwise disagree by a rounding step and the
    audit record would carry a number the optimiser never targeted.
    """
    alpha = confidence if confidence is not None else inputs.var_confidence
    scenarios = inputs.returns.to_numpy(dtype=float)
    n_obs, n_assets = scenarios.shape

    if n_obs < inputs.min_observations:
        return (
            None, SolverStatus.SOLVER_ERROR,
            f"CVaR needs at least {inputs.min_observations} scenarios, got {n_obs}",
            None,
        )

    w = cp.Variable(n_assets)
    zeta = cp.Variable()
    u = cp.Variable(n_obs, nonneg=True)

    losses = -(scenarios @ w)
    cons = build_constraints(
        w, inputs.universe, inputs.constraints, inputs.current_vector,
        inputs.asset_ids,
    )
    cons.append(u >= losses - zeta)

    objective = zeta + cp.sum(u) / ((1.0 - alpha) * n_obs)
    if txn_penalty > 0.0 and inputs.constraints.include_txn_cost:
        rates = np.array(
            [inputs.universe.get(a).txn_cost_rate for a in inputs.asset_ids],
            dtype=float,
        )
        objective = objective + txn_penalty * transaction_cost_expr(
            w, inputs.current_vector, rates
        )

    problem = cp.Problem(cp.Minimize(objective), cons)
    status, raw = _solve(problem)
    if not status.usable or w.value is None:
        return None, status, raw, None

    weights = np.clip(np.asarray(w.value, dtype=float).ravel(), 0.0, None)
    total = weights.sum()
    if total <= 0:
        return None, SolverStatus.SOLVER_ERROR, "solution sums to zero", None

    cvar = float(problem.value) if problem.value is not None else None
    return weights / total, status, raw, cvar


class CVaROptimizer(MaxSharpeOptimizer):
    """Minimum-CVaR allocation under the same policy constraints.

    Subclasses MaxSharpe to reuse ``_build_result``: the advisory metrics
    (FR-072) must be assembled identically for every strategy, or two
    strategies would report a different VaR for the same weights.
    """

    strategy = Strategy.CVAR_MIN

    def solve(self, inputs: OptimizerInputs) -> OptimizationResult:
        start = time.perf_counter()
        vector, status, note, _cvar = solve_min_cvar(
            inputs, txn_penalty=self.txn_penalty
        )
        if vector is None:
            return failed_result(
                self.strategy, inputs.return_method, status, note,
                self._timed(start),
            )
        return self._build_result(
            inputs, self._point(inputs, vector), [], start
        )

    def _point(self, inputs: OptimizerInputs, vector: np.ndarray):
        from ..risk import portfolio_volatility
        from .mean_variance import FrontierPoint

        vol = portfolio_volatility(vector, inputs.covariance)
        er = float(inputs.expected_returns @ vector)
        return FrontierPoint(
            target_return=er, volatility=vol, expected_return=er,
            sharpe=(er - inputs.risk_free_rate) / vol if vol > 0 else 0.0,
            weights=vector,
        )

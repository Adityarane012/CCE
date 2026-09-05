"""Minimum variance subject to a return floor.

Spec: docs/08-FINANCIAL-METHODS.md section 11.4.

    minimise  w' Sigma w   subject to  w' mu >= target  + policy constraints

If the target is unreachable the result is INFEASIBLE and the report names
which constraint conflicts with it. It is NEVER met by quietly relaxing a
policy limit — an allocation that hits a return target by breaching the cash
floor is not the allocation anyone asked for, and the fact that it was
impossible is the useful answer (EC-4.1, EC-5.5).
"""

from __future__ import annotations

import time

import numpy as np

from ..contracts import OptimizationResult, Strategy
from .base import OptimizerInputs, failed_result
from .constraints import describe_infeasibility
from .mean_variance import MaxSharpeOptimizer, solve_min_variance

__all__ = ["TargetReturnOptimizer"]


class TargetReturnOptimizer(MaxSharpeOptimizer):
    """Cheapest risk that still clears a required return."""

    strategy = Strategy.TARGET_RETURN

    def __init__(self, target_return: float, txn_penalty: float = 1.0) -> None:
        super().__init__(txn_penalty=txn_penalty)
        self.target_return = target_return

    def solve(self, inputs: OptimizerInputs) -> OptimizationResult:
        start = time.perf_counter()
        vector, status, _ = solve_min_variance(
            inputs, target_return=self.target_return,
            txn_penalty=self.txn_penalty,
        )
        if vector is None:
            best = float(np.max(inputs.expected_returns))
            reason = (
                f"no allocation reaches a {self.target_return:.2%} return "
                f"under the policy constraints"
            )
            if self.target_return > best:
                reason += (
                    f"; the highest expected return available on any single "
                    f"asset is {best:.2%}"
                )
            conflicts = describe_infeasibility(
                inputs.universe, inputs.constraints, inputs.asset_ids
            )
            if conflicts:
                reason += ": " + "; ".join(conflicts)
            return failed_result(
                self.strategy, inputs.return_method, status, reason,
                self._timed(start), conflicts=conflicts,
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
            target_return=self.target_return, volatility=vol,
            expected_return=er,
            sharpe=(er - inputs.risk_free_rate) / vol if vol > 0 else 0.0,
            weights=vector,
        )

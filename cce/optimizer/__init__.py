"""Optimizer (L3) — proposes allocations.

Never writes portfolio state, audit records or control state (FR-063).
Never judges its own output: the control engine does that, and it does not
import this package (INV-2).

May import ``cce.risk`` and ``cce.portfolio``; must not import
``cce.controls``, ``cce.services`` or ``ui``
(docs/02-ARCHITECTURE.md section 2).
"""

from __future__ import annotations

from .base import (
    SOLVER_STATUS_MAP, Optimizer, OptimizerInputs, failed_result,
)
from .constraints import (
    build_constraints, describe_infeasibility, transaction_cost_expr,
    turnover_expr,
)
from .mean_variance import (
    FrontierPoint, MaxSharpeOptimizer, efficient_frontier,
    solve_min_variance, solve_unconstrained_max_sharpe,
)

__all__ = [
    "Optimizer", "OptimizerInputs", "failed_result", "SOLVER_STATUS_MAP",
    "build_constraints", "turnover_expr", "transaction_cost_expr",
    "describe_infeasibility",
    "MaxSharpeOptimizer", "FrontierPoint", "efficient_frontier",
    "solve_min_variance", "solve_unconstrained_max_sharpe",
]

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
    SOLVER_STATUS_MAP,
    Optimizer,
    OptimizerInputs,
    failed_result,
)
from .black_litterman import (
    BLResult,
    View,
    black_litterman,
    equilibrium_returns,
)
from .constraints import (
    build_constraints,
    describe_infeasibility,
    transaction_cost_expr,
    turnover_expr,
)
from .cvar_optimizer import CVaROptimizer, solve_min_cvar
from .hrp import HRPOptimizer, hrp_weights
from .mean_variance import (
    FrontierPoint,
    MaxSharpeOptimizer,
    MinVolatilityOptimizer,
    efficient_frontier,
    solve_min_variance,
    solve_unconstrained_max_sharpe,
)
from .target_return import TargetReturnOptimizer

__all__ = [
    "SOLVER_STATUS_MAP",
    "BLResult",
    "CVaROptimizer",
    "FrontierPoint",
    "HRPOptimizer",
    "MaxSharpeOptimizer",
    "MinVolatilityOptimizer",
    "Optimizer",
    "OptimizerInputs",
    "TargetReturnOptimizer",
    "View",
    "black_litterman",
    "build_constraints",
    "describe_infeasibility",
    "efficient_frontier",
    "equilibrium_returns",
    "failed_result",
    "hrp_weights",
    "solve_min_cvar",
    "solve_min_variance",
    "solve_unconstrained_max_sharpe",
    "transaction_cost_expr",
    "turnover_expr",
]

"""Walk-forward backtesting.

Spec: docs/08-FINANCIAL-METHODS.md section 14.

Compares BUY_AND_HOLD, UNCONTROLLED_OPTIMIZER and CCE_CONTROLLED on
identical data. The controlled strategy holds its previous allocation
whenever validation fails; the difference between the two curves is what the
control layer cost or saved.

The optimizer and validator are INJECTED rather than imported, which keeps
this package free of both and lets the look-ahead guard be tested with a stub
that records exactly which data it was shown.
"""

from __future__ import annotations

from .engine import (
    BacktestConfig,
    BacktestRun,
    StrategyRun,
    estimation_window,
    rebalance_dates,
    run_backtest,
)
from .metrics import (
    StrategyMetrics,
    compare,
    compute_metrics,
    drawdown_series,
)

__all__ = [
    "BacktestConfig",
    "BacktestRun",
    "StrategyMetrics",
    "StrategyRun",
    "compare",
    "compute_metrics",
    "drawdown_series",
    "estimation_window",
    "rebalance_dates",
    "run_backtest",
]

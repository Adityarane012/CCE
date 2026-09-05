"""Backtest contracts.

Spec: docs/06-DATA-CONTRACTS.md section 9.

``BacktestConfig`` is built by the UI and consumed by the service;
``StrategyMetrics`` is produced by the backtest engine and rendered by the UI.
Both cross a module boundary, so both live here rather than in
``cce.backtest`` — the UI may import ``cce.services`` and ``cce.contracts``
and nothing else (INV-12), and the architecture test enforces exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from .enums import ExpectedReturnMethod

__all__ = ["BacktestConfig", "StrategyMetrics"]


@dataclass(frozen=True)
class BacktestConfig:
    """Everything the walk-forward loop needs.

    ``random_seed`` is carried even though nothing here is stochastic today:
    a backtest whose seed is not recorded is not reproducible the moment
    anything in it becomes stochastic (NFR-012).
    """

    start: date
    end: date
    rebalance: str = "MONTHLY"          # MONTHLY | WEEKLY
    initial_weights: dict[str, float] = field(default_factory=dict)
    er_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL
    min_window: int = 250
    random_seed: int = 42

    def __post_init__(self) -> None:
        if self.rebalance not in {"MONTHLY", "WEEKLY"}:
            raise ValueError(
                f"rebalance must be MONTHLY or WEEKLY, got {self.rebalance!r}"
            )
        if self.end <= self.start:
            raise ValueError("end must be after start")


@dataclass(frozen=True)
class StrategyMetrics:
    """What one strategy achieved, and at what governance cost.

    Any metric may be ``None`` — too few observations is a real outcome and
    is never reported as zero (INV-5).

    ``policy_breach_count`` and ``breaker_activations`` are deliberately
    peers of ``cumulative_return`` here rather than diagnostics tucked
    elsewhere: a strategy that earned more by breaching policy did not
    outperform, it ran a different mandate.
    """

    name: str
    cumulative_return: float | None
    annualised_return: float | None
    volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    var_95: float | None
    cvar_95: float | None
    avg_turnover: float | None
    total_txn_cost_paise: int
    policy_breach_count: int
    breaker_activations: int
    rebalances: int
    holds: int

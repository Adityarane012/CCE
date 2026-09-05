"""Performance and CONTROL metrics for a backtest run.

Spec: docs/08-FINANCIAL-METHODS.md section 14.4.

The policy-breach count and breaker activations carry the same weight as
return. The question CCE answers is not "did it make more money?" but "did it
improve the return/risk balance while reducing policy breaches and
drawdowns?"

If the controlled strategy earns slightly less with materially fewer breaches
and a shallower drawdown, that is a SUCCESSFUL result — and saying so plainly
is more credible than claiming outperformance on a single three-year sample.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from cce.contracts import StrategyMetrics
from cce.risk import TRADING_DAYS

__all__ = [
    "StrategyMetrics",
    "compare",
    "compute_metrics",
    "drawdown_series",
]


def compute_metrics(
    run, risk_free_rate: float = 0.065, periods_per_year: int | None = None
) -> StrategyMetrics:
    """Summarise one strategy run.

    ``periods_per_year`` defaults to the observed cadence rather than 252:
    a monthly-rebalanced curve has ~12 points a year, and annualising it as
    if it had 252 would inflate volatility by about 4.6x.
    """
    from cce.risk import cvar_with_diagnostics, historical_var, max_drawdown

    curve = run.equity_curve
    rets = run.returns

    if len(curve) < 2:
        return StrategyMetrics(
            name=run.name, cumulative_return=None, annualised_return=None,
            volatility=None, sharpe=None, max_drawdown=None, var_95=None,
            cvar_95=None,
            avg_turnover=float(np.mean(run.turnovers)) if run.turnovers else None,
            total_txn_cost_paise=run.transaction_cost_paise,
            policy_breach_count=run.policy_breaches,
            breaker_activations=run.breaker_activations,
            rebalances=run.rebalances, holds=run.holds,
        )

    periods = periods_per_year or _infer_periods(curve.index)
    cumulative = float(curve.iloc[-1] / curve.iloc[0] - 1.0)
    years = len(rets) / periods if periods else None
    annualised = (
        float((1.0 + cumulative) ** (1.0 / years) - 1.0)
        if years and years > 0 and (1.0 + cumulative) > 0 else None
    )
    vol = float(rets.std(ddof=1) * np.sqrt(periods)) if len(rets) > 1 else None
    sharpe = (
        (annualised - risk_free_rate) / vol
        if annualised is not None and vol and vol > 0 else None
    )

    return StrategyMetrics(
        name=run.name,
        cumulative_return=cumulative,
        annualised_return=annualised,
        volatility=vol,
        sharpe=sharpe,
        # RETURNS, not the equity curve. max_drawdown computes the peak-to-
        # trough decline of a cumulative series it builds ITSELF, so handing
        # it levels reports 0.0% for every strategy — which is exactly what
        # this did, on one of the two metrics the comparison turns on.
        max_drawdown=max_drawdown(rets),
        var_95=historical_var(rets, 0.95, min_observations=max(10, len(rets) // 4)),
        cvar_95=cvar_with_diagnostics(
            rets, 0.95, min_observations=max(10, len(rets) // 4)
        ).value,
        avg_turnover=float(np.mean(run.turnovers)) if run.turnovers else None,
        total_txn_cost_paise=run.transaction_cost_paise,
        policy_breach_count=run.policy_breaches,
        breaker_activations=run.breaker_activations,
        rebalances=run.rebalances,
        holds=run.holds,
    )


def _infer_periods(index: pd.Index) -> float:
    """Observations per year, from the actual spacing of the curve."""
    if len(index) < 2:
        return float(TRADING_DAYS)
    span = (index[-1] - index[0]).days
    if span <= 0:
        return float(TRADING_DAYS)
    return max(1.0, (len(index) - 1) * 365.25 / span)


def compare(run, risk_free_rate: float = 0.065) -> dict[str, StrategyMetrics]:
    """Every strategy in the run, keyed by name."""
    return {
        name: compute_metrics(strategy, risk_free_rate)
        for name, strategy in run.strategies.items()
    }


def drawdown_series(run) -> pd.Series:
    """Peak-to-trough decline at every point on the curve, as a NEGATIVE
    fraction.

    Lives here rather than in the chart that draws it: a drawdown is a
    financial calculation, and the UI computing one would put arithmetic
    behind a Streamlit rerun (INV-12). The chart receives a finished series.

    Negative by convention so the chart reads downward without the caller
    negating it — a drawdown plotted upward is the single most misread
    chart in a risk deck.
    """
    curve = run.equity_curve
    if len(curve) < 2:
        return pd.Series(dtype=float)
    return curve / curve.cummax() - 1.0

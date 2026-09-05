"""Walk-forward backtest with look-ahead prevention.

Spec: docs/08-FINANCIAL-METHODS.md section 14, docs/04-WORKFLOW.md A5.

At each rebalance date ``t``::

    window     = returns.loc[:t_prev]       # STRICTLY before t
    mu, Sigma  = estimate(window)
    w          = optimize(mu, Sigma, constraints, w_prev)
    w_applied  = w if validation passed else w_prev
    realise over [t, t+1)

**Look-ahead is the one bug that would invalidate every number here.** Every
slice is label-based with an exclusive upper bound. There is no ``iloc``
arithmetic anywhere in this module — an off-by-one in index arithmetic is
invisible in the output and fatal to the conclusion, and the resulting curve
looks *better*, which is exactly why nobody catches it.

The rebalance date's own return belongs to the OUTCOME period, never to the
estimation window (INV-7).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date

import pandas as pd

from cce.contracts import (
    BacktestConfig,
    Constraints,
    Policy,
    Universe,
)

logger = logging.getLogger(__name__)

__all__ = ["BacktestConfig", "BacktestRun", "StrategyRun", "run_backtest"]


@dataclass(frozen=True)
class StrategyRun:
    """One strategy's realised path."""

    name: str
    equity_curve: pd.Series
    weights_history: list[tuple[date, dict[str, float]]]
    turnovers: list[float]
    transaction_cost_paise: int
    policy_breaches: int
    breaker_activations: int
    rebalances: int
    holds: int = 0

    @property
    def returns(self) -> pd.Series:
        """Period returns implied by the equity curve."""
        return self.equity_curve.pct_change().dropna()


@dataclass(frozen=True)
class BacktestRun:
    """Every strategy over the same dates and the same data."""

    config: BacktestConfig
    strategies: dict[str, StrategyRun]
    rebalance_dates: list[date]

    def get(self, name: str) -> StrategyRun:
        return self.strategies[name]


def rebalance_dates(index: pd.Index, cadence: str) -> list:
    """The dates on which a decision is taken.

    Derived from the OBSERVED trading calendar rather than from a synthetic
    date range: a month-end that was a market holiday is not a rebalance
    date, and pretending otherwise would have the backtest trade on a day the
    exchange was shut.
    """
    frame = pd.Series(1, index=index)
    rule = "ME" if cadence == "MONTHLY" else "W"
    grouped = frame.groupby(pd.Grouper(freq=rule)).apply(
        lambda g: g.index.max() if len(g) else None
    )
    return [d for d in grouped.tolist() if d is not None and pd.notna(d)]


def _as_datetime_index(returns: pd.DataFrame) -> pd.DataFrame:
    """Normalise the index to a DatetimeIndex.

    The committed cache carries plain ``datetime.date`` objects while a
    synthetic panel carries Timestamps, and the two do not compare:
    ``Timestamp >= date`` raises. ``pd.Grouper`` also requires a real
    DatetimeIndex, so the cadence calculation would fail on the production
    panel while passing every synthetic test — a gap that only shows up on
    real data, which is the worst place to find one.
    """
    if isinstance(returns.index, pd.DatetimeIndex):
        return returns
    return returns.set_axis(pd.DatetimeIndex(returns.index), axis=0)


def estimation_window(returns: pd.DataFrame, rebalance_date) -> pd.DataFrame:
    """Everything STRICTLY before ``rebalance_date``.

    The single most important function in this module. Label-based, exclusive
    upper bound, and the rebalance date itself is excluded — its return is an
    outcome, not evidence (INV-7).

    ``.loc[:t]`` in pandas is INCLUSIVE of ``t``, which is precisely the
    off-by-one that would leak one day of the future into every decision. The
    strict mask below is not a stylistic preference over slicing.
    """
    return returns.loc[returns.index < rebalance_date]


def _apply(
    weights: dict[str, float], period: pd.DataFrame
) -> tuple[float, dict[str, float]]:
    """Realise ``weights`` over a period; return (growth, drifted weights).

    Weights DRIFT with returns rather than being held fixed — a buy-and-hold
    book that stays at its initial weights is not buy-and-hold, it is a
    continuously rebalanced portfolio wearing its name.
    """
    if period.empty:
        return 1.0, dict(weights)

    growth = {
        asset: float((1.0 + period[asset]).prod())
        for asset in period.columns
        if asset in weights
    }
    values = {a: weights.get(a, 0.0) * g for a, g in growth.items()}
    total = sum(values.values())
    if total <= 0:
        return 0.0, dict(weights)
    return total, {a: v / total for a, v in values.items()}


def run_backtest(
    returns: pd.DataFrame,
    universe: Universe,
    policy: Policy,
    config: BacktestConfig,
    propose,
    validate_fn,
    propose_uncontrolled=None,
    constraints: Constraints | None = None,
) -> BacktestRun:
    """Walk forward, comparing the three strategies on identical data.

    Args:
        propose: ``(window, current_weights) -> dict | None``. The CONSTRAINED
            optimizer, injected so this module never imports ``cce.optimizer``
            and the look-ahead guard can be tested with a stub.
        validate_fn: ``(weights, window, current) -> (passed, breaches)``.
            Injected for the same reason.
        propose_uncontrolled: the optimizer a system WITHOUT a control engine
            would run — unconstrained, chasing the optimum. Defaults to
            ``propose``.

    **The two proposers are the comparison.** Running the constrained
    optimizer down both arms makes them identical by construction: its output
    already satisfies the policy, so validation never fails and the two curves
    coincide exactly. That is a backtest that proves nothing, and it is what
    this produced before the second proposer was added.

    The uncontrolled arm adopts every recommendation from an unconstrained
    optimizer. The controlled arm holds its previous allocation whenever
    validation fails. The difference between the curves — and between the
    breach counts — is what the control layer cost or saved.
    """
    returns = _as_datetime_index(returns)
    window_all = returns.loc[
        (returns.index >= pd.Timestamp(config.start))
        & (returns.index <= pd.Timestamp(config.end))
    ]
    if window_all.empty:
        raise ValueError("no returns in the configured backtest range")

    dates = [
        d for d in rebalance_dates(window_all.index, config.rebalance)
        if len(estimation_window(returns, d)) >= config.min_window
    ]
    if not dates:
        raise ValueError(
            f"no rebalance date has {config.min_window} prior observations; "
            "widen the range or lower min_window"
        )

    initial = config.initial_weights or {
        a.asset_id: 1.0 / len(universe.assets) for a in universe.assets
    }

    runs = {
        name: _Accumulator(name, dict(initial))
        for name in ("BUY_AND_HOLD", "UNCONTROLLED_OPTIMIZER", "CCE_CONTROLLED")
    }

    for i, t in enumerate(dates):
        window = estimation_window(returns, t)
        nxt = dates[i + 1] if i + 1 < len(dates) else None
        period = returns.loc[
            (returns.index >= t) & ((returns.index < nxt) if nxt else True)
        ]

        uncontrolled_fn = propose_uncontrolled or propose

        # --- uncontrolled: adopt whatever came back -----------------------
        unc = runs["UNCONTROLLED_OPTIMIZER"]
        loose = uncontrolled_fn(window, unc.weights)
        if loose:
            # Validated only to COUNT the breaches. The result is adopted
            # either way — that is what "no control layer" means.
            passed, breaches = validate_fn(loose, window, unc.weights)
            if not passed:
                unc.policy_breaches += len(breaches) or 1
            unc.rebalance_to(loose, universe)
        unc.realise(period)

        # --- controlled: adopt only what passes ---------------------------
        ctrl = runs["CCE_CONTROLLED"]
        proposal = propose(window, ctrl.weights)
        if proposal:
            passed, breaches = validate_fn(proposal, window, ctrl.weights)
            if passed:
                ctrl.rebalance_to(proposal, universe)
            else:
                ctrl.holds += 1
                ctrl.breaker_activations += 1
        ctrl.realise(period)

        # --- buy and hold: drift only -------------------------------------
        runs["BUY_AND_HOLD"].realise(period)

    return BacktestRun(
        config=config,
        strategies={name: acc.finish() for name, acc in runs.items()},
        rebalance_dates=[d.date() if hasattr(d, "date") else d for d in dates],
    )


class _Accumulator:
    """Mutable state for one strategy as the walk-forward loop advances."""

    def __init__(self, name: str, weights: dict[str, float]) -> None:
        self.name = name
        self.weights = weights
        self.value = 1.0
        self.curve: list[tuple[object, float]] = []
        self.history: list[tuple[date, dict[str, float]]] = []
        self.turnovers: list[float] = []
        self.cost_paise = 0
        self.policy_breaches = 0
        self.breaker_activations = 0
        self.rebalances = 0
        self.holds = 0

    def rebalance_to(self, target: dict[str, float], universe: Universe) -> None:
        from cce.portfolio import transaction_cost_paise, turnover

        moved = turnover(target, self.weights)
        self.turnovers.append(moved)
        # Cost is charged against the CURRENT book value, so a rebalance late
        # in a rising backtest costs more in absolute terms than an early one.
        self.cost_paise += transaction_cost_paise(
            target, self.weights, universe, int(self.value * 1e11)
        )
        self.value *= 1.0 - _cost_ratio(target, self.weights, universe)
        self.weights = dict(target)
        self.rebalances += 1

    def realise(self, period: pd.DataFrame) -> None:
        growth, drifted = _apply(self.weights, period)
        self.value *= growth
        self.weights = drifted
        stamp = period.index[-1] if len(period) else None
        if stamp is not None:
            self.curve.append((stamp, self.value))
            self.history.append(
                (stamp.date() if hasattr(stamp, "date") else stamp, dict(drifted))
            )

    def finish(self) -> StrategyRun:
        idx = [d for d, _ in self.curve]
        vals = [v for _, v in self.curve]
        return StrategyRun(
            name=self.name,
            equity_curve=pd.Series(vals, index=pd.Index(idx), dtype=float),
            weights_history=self.history,
            turnovers=self.turnovers,
            transaction_cost_paise=self.cost_paise,
            policy_breaches=self.policy_breaches,
            breaker_activations=self.breaker_activations,
            rebalances=self.rebalances,
            holds=self.holds,
        )


def _cost_ratio(
    target: dict[str, float], current: dict[str, float], universe: Universe
) -> float:
    """Transaction cost as a fraction of NAV.

    Both legs are charged: selling A to buy B incurs cost on each. That is
    the deliberate asymmetry with turnover, which halves (docs/08 11.2).
    """
    total = 0.0
    for asset_id in set(target) | set(current):
        rate = universe.get(asset_id).txn_cost_rate
        total += rate * abs(target.get(asset_id, 0.0) - current.get(asset_id, 0.0))
    return total

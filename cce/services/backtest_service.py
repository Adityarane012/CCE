"""Backtest orchestration.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/08-FINANCIAL-METHODS.md §14.

The engine takes the optimizer and the validator as arguments rather than
importing them, so this is where they are supplied. That indirection is what
lets the look-ahead guard be tested with a stub that records exactly which
rows it was shown.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd

from cce.backtest import (
    BacktestConfig,
    BacktestRun,
    StrategyMetrics,
    compare,
    drawdown_series,
    run_backtest,
)
from cce.contracts import ExpectedReturnMethod
from cce.optimizer import MaxSharpeOptimizer, OptimizerInputs
from cce.risk import estimate_covariance, expected_returns

from .context import ServiceContext

logger = logging.getLogger(__name__)

__all__ = ["BacktestService"]


class BacktestService:
    """Controlled vs uncontrolled, on the same data."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def run(self, config: BacktestConfig) -> BacktestRun:
        """Walk forward and compare the three strategies."""
        return run_backtest(
            self._ctx.market_data.returns,
            self._ctx.universe,
            self._ctx.policy,
            config,
            propose=self._propose,
            validate_fn=self._validate,
            propose_uncontrolled=self._propose_unconstrained,
        )

    def available_range(self) -> tuple[date, date]:
        """First and last date the loaded panel actually covers.

        The UI bounds its date pickers with this instead of guessing, so a
        range the data cannot support is unselectable rather than a runtime
        error after a two-minute run.
        """
        index = self._ctx.market_data.returns.index
        first, last = index.min(), index.max()
        return (
            first.date() if hasattr(first, "date") else first,
            last.date() if hasattr(last, "date") else last,
        )

    def compare(self, run: BacktestRun) -> dict[str, StrategyMetrics]:
        return compare(run, self._ctx.policy.risk_free_rate)

    def equity_curves(self, run: BacktestRun) -> dict[str, pd.Series]:
        """Each strategy's realised path, ready to plot."""
        return {name: s.equity_curve for name, s in run.strategies.items()}

    def drawdowns(self, run: BacktestRun) -> dict[str, pd.Series]:
        """Each strategy's drawdown path, ready to plot.

        Computed here rather than in the chart: the UI holds no arithmetic
        (INV-12).
        """
        return {name: drawdown_series(s) for name, s in run.strategies.items()}

    # ------------------------------------------------------------------

    def _propose_unconstrained(self, window, current: dict[str, float]):
        """What a system with no control engine would do.

        Only long-only and fully-invested survive — without those the result
        is not an allocation at all. Every RISK limit is dropped, which is the
        point: this arm chases the optimum and the controlled arm does not.
        """
        from cce.contracts import Constraints

        loose = Constraints(
            min_weights={a.asset_id: 0.0 for a in self._ctx.universe.assets},
            max_weights={a.asset_id: 1.0 for a in self._ctx.universe.assets},
            sector_max={}, asset_class_max={},
            min_liquid_share=0.0, min_cash_share=0.0, max_turnover=1.0,
            long_only=True, include_txn_cost=False,
        )
        return self._propose(window, current, constraints=loose)

    def _propose(self, window, current: dict[str, float], constraints=None):
        """Optimize on the window ALONE.

        Nothing outside ``window`` is referenced — not the full panel held by
        the context, not a cached covariance. Every estimate is rebuilt from
        what was knowable at the time (INV-7).
        """
        try:
            cov, _ = estimate_covariance(window)
            mu = expected_returns(
                window, ExpectedReturnMethod.HISTORICAL,
                trading_days=self._ctx.policy.trading_days_per_year,
            )
            inputs = OptimizerInputs(
                universe=self._ctx.universe,
                returns=window,
                expected_returns=mu,
                covariance=cov,
                constraints=constraints or self._ctx.policy.constraints,
                current_weights=current,
                risk_free_rate=self._ctx.policy.risk_free_rate,
                var_confidence=self._ctx.policy.var_confidence,
                min_observations=min(
                    self._ctx.policy.model.min_return_observations, len(window)
                ),
                frontier_points=20,
            )
            result = MaxSharpeOptimizer().solve(inputs)
            return result.weights
        except Exception as exc:  # noqa: BLE001 - one bad window must not end the run
            logger.warning("backtest proposal failed: %s", exc)
            return None

    def _validate(self, weights, window, current) -> tuple[bool, list[str]]:
        """Re-derive the controls on the window's own data.

        A simplified check against the policy's hard weight and turnover
        limits. It does NOT read anything the optimizer reported — the point
        of the comparison is that the control layer forms its own opinion.
        """
        from cce.portfolio import turnover

        breaches: list[str] = []
        constraints = self._ctx.policy.constraints

        by_sector: dict[str, float] = {}
        for asset_id, w in weights.items():
            asset = self._ctx.universe.get(asset_id)
            by_sector[asset.sector] = by_sector.get(asset.sector, 0.0) + w
            cap = constraints.max_weights.get(asset_id, 1.0)
            if w > cap + 1e-9:
                breaches.append(f"CONC_ASSET_MAX:{asset_id}")

        for sector, weight in by_sector.items():
            # Distinct name: the asset cap above is a plain float and this one
            # is optional, so reusing `cap` widens it and hides the None case.
            sector_cap = constraints.sector_max.get(sector)
            if sector_cap is not None and weight > sector_cap + 1e-9:
                breaches.append(f"CONC_SECTOR_MAX:{sector}")

        if turnover(weights, current) > constraints.max_turnover + 1e-9:
            breaches.append("TXN_TURNOVER_MAX")

        cash = sum(
            w for a, w in weights.items()
            if self._ctx.universe.get(a).asset_class == "CASH"
        )
        if cash < constraints.min_cash_share - 1e-9:
            breaches.append("LIQ_MIN_CASH")

        realised = window.to_numpy(dtype=float) @ np.array(
            [weights.get(a, 0.0) for a in window.columns]
        )
        if len(realised) > 20:
            vol = float(np.std(realised, ddof=1) * np.sqrt(
                self._ctx.policy.trading_days_per_year
            ))
            threshold = self._ctx.policy.threshold("RISK_VOL_ANNUAL")
            if threshold.amber_max is not None and vol > threshold.amber_max:
                breaches.append("RISK_VOL_ANNUAL")

        return (not breaches), breaches

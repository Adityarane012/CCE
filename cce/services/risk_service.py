"""Risk computation and comparison.

Spec: docs/06-DATA-CONTRACTS.md section 9.

The snapshot returned here is UNCLASSIFIED — it carries metrics, not a
verdict. Classification happens in exactly one place, and it is not this one
(INV-11).
"""

from __future__ import annotations

from cce.contracts import (
    ChangeAttribution,
    ChangeDriver,
    PortfolioState,
    RiskChange,
    RiskSnapshot,
)
from cce.risk import RiskInputs, compute_risk_snapshot

from .context import ServiceContext

__all__ = ["RiskService"]

#: Metrics compared by :meth:`RiskService.what_changed`, with the label the
#: "What Changed?" panel shows. Ordered by how much a risk manager cares.
_COMPARED: tuple[tuple[str, str], ...] = (
    ("ewma_volatility", "EWMA volatility"),
    ("portfolio_volatility", "Portfolio volatility"),
    ("cvar_95", "95% CVaR"),
    ("var_95", "95% VaR"),
    ("current_drawdown", "Current drawdown"),
    ("liquidity_ratio", "Liquid share"),
)


class RiskService:
    """Metrics for a portfolio, and what moved between two readings."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def get_snapshot(self, state: PortfolioState) -> RiskSnapshot:
        """Every risk metric for this allocation, on current data."""
        snapshot, _ = compute_risk_snapshot(RiskInputs(
            weights=state.weights,
            universe=self._ctx.universe,
            market_data=self._ctx.market_data,
            risk_free_rate=self._ctx.policy.risk_free_rate,
            ewma_lambda=self._ctx.policy.ewma_lambda,
            var_confidence=self._ctx.policy.var_confidence,
            trading_days=self._ctx.policy.trading_days_per_year,
            min_observations=self._ctx.policy.model.min_return_observations,
            current_weights=state.weights,
            total_value_paise=state.total_value_paise,
        ))
        return snapshot

    def what_changed(
        self, previous: RiskSnapshot, current: RiskSnapshot
    ) -> tuple[RiskChange, ...]:
        """Portfolio metrics that moved between two snapshots.

        A metric that is ``None`` in either snapshot is OMITTED, not reported
        as a move to or from zero. "Not computed" and "fell to zero" are
        different facts, and the second one is alarming (INV-5).
        """
        changes: list[RiskChange] = []
        for field, label in _COMPARED:
            before = getattr(previous, field, None)
            after = getattr(current, field, None)
            if before is None or after is None or before == after:
                continue
            changes.append(RiskChange(
                metric=label, from_value=float(before), to_value=float(after)
            ))
        return tuple(changes)

    def sector_contributions_changed(
        self, previous: RiskSnapshot, current: RiskSnapshot
    ) -> tuple[RiskChange, ...]:
        """Per-sector risk contribution moves, largest first.

        Separates a volatility regime change from allocation drift: the
        portfolio metric says risk rose, these say which sector carried it.
        """
        changes: list[RiskChange] = []
        for sector, after in current.sector_risk_contribution.items():
            before = previous.sector_risk_contribution.get(sector)
            if before is None or before == after:
                continue
            changes.append(RiskChange(
                metric="Risk contribution", from_value=float(before),
                to_value=float(after), scope=sector,
            ))
        return tuple(sorted(changes, key=lambda c: abs(c.delta), reverse=True))

    def attribute(
        self,
        previous: RiskSnapshot,
        current: RiskSnapshot,
        previous_weights: dict[str, float],
        current_weights: dict[str, float],
        weight_tolerance: float = 0.01,
    ) -> ChangeAttribution:
        """Decompose a risk move into allocation drift vs regime change.

        This is the question the "What Changed?" panel exists to answer, and
        the two answers call for opposite responses. If the weights moved,
        the book was traded and the risk followed. If they did not, the
        market moved underneath an unchanged book — rebalancing is a
        response to the first and a reaction to the second.

        The demo case is exactly this: banking allocation unchanged at 24%
        while its risk contribution moves 27% -> 41%. A panel reporting only
        "volatility is up" leaves the reader to guess which happened.

        ``weight_tolerance`` is a MATERIALITY floor, not a policy threshold:
        a 0.3% drift from rounding is not a rebalance, and calling it one
        would attribute a regime change to a trade nobody made.
        """
        shift = max(
            (
                abs(current_weights.get(a, 0.0) - previous_weights.get(a, 0.0))
                for a in set(previous_weights) | set(current_weights)
            ),
            default=0.0,
        )
        metrics = self.what_changed(previous, current)
        contributors = self.sector_contributions_changed(previous, current)

        moved = shift > weight_tolerance
        if not metrics and not contributors:
            driver = ChangeDriver.NONE
        elif moved and contributors:
            driver = ChangeDriver.BOTH
        elif moved:
            driver = ChangeDriver.ALLOCATION
        else:
            driver = ChangeDriver.REGIME

        return ChangeAttribution(
            driver=driver, metrics=metrics, contributors=contributors,
            max_weight_shift=shift, weight_shift_threshold=weight_tolerance,
        )

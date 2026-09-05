"""Portfolio state access.

Spec: docs/06-DATA-CONTRACTS.md section 9.
"""

from __future__ import annotations

from cce.contracts import PortfolioState, SafeAllocation, Universe
from cce.portfolio import build_portfolio_state

from .context import ServiceContext

__all__ = ["PortfolioService"]


class PortfolioService:
    """The current book, and the last allocation a human approved."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def get_universe(self) -> Universe:
        return self._ctx.universe

    def get_current_state(self) -> PortfolioState:
        """The most recent persisted portfolio state, priced on current data.

        Weights come from the store; prices come from the current panel. The
        stored ``positions_json`` was priced when it was written, and showing
        those stale values as today's book would misstate the portfolio's
        value — the allocation persists, the valuation does not.
        """
        latest = self._ctx.repo.get_latest_portfolio_state(self._ctx.portfolio_id)
        if latest is None:
            raise LookupError(
                f"no portfolio state for {self._ctx.portfolio_id}; the demo "
                "seed should have created one"
            )
        _state_id, weights, total_value_paise = latest
        return build_portfolio_state(
            universe=self._ctx.universe,
            weights=weights,
            market_data=self._ctx.market_data,
            total_value_paise=total_value_paise,
            portfolio_id=self._ctx.portfolio_id,
        )

    def get_last_safe_allocation(self) -> SafeAllocation | None:
        """The Last Approved Safe Allocation, or ``None``.

        ``None`` means none has ever been approved. The caller preserves the
        current allocation rather than inventing one (INV-4).
        """
        return self._ctx.repo.get_last_safe_allocation(self._ctx.portfolio_id)

"""Portfolio state and arithmetic (L2).

The models themselves live in ``cce.contracts.portfolio`` — this package
builds and manipulates them. There is deliberately no ``models.py`` here:
a second definition of PortfolioState would be a second source of truth.
"""

from __future__ import annotations

from .calculations import (
    allocate_paise,
    asset_class_exposure,
    liquid_share,
    portfolio_returns,
    sector_exposure,
    transaction_cost_paise,
    turnover,
    value_to_units,
    weight_deltas,
)
from .state import (
    DEFAULT_CAPITAL_PAISE,
    build_portfolio_state,
    normalise_weights,
    rebalance_to,
)

__all__ = [
    "DEFAULT_CAPITAL_PAISE",
    "allocate_paise",
    "asset_class_exposure",
    "build_portfolio_state",
    "liquid_share",
    "normalise_weights",
    "portfolio_returns",
    "rebalance_to",
    "sector_exposure",
    "transaction_cost_paise",
    "turnover",
    "value_to_units",
    "weight_deltas",
]

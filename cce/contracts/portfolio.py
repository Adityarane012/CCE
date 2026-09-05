"""Portfolio state contracts.

Spec: docs/06-DATA-CONTRACTS.md section 4.

Money is INTEGER PAISE (INR x 100). Floating-point currency accumulates error
across a Rs 100 Cr portfolio, so rupee floats are permitted inside computation
but never at a persistence or contract boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import pandas as pd

from .market import Universe

__all__ = ["PAISE_PER_RUPEE", "WEIGHT_TOLERANCE", "PortfolioState", "Position"]

WEIGHT_TOLERANCE = 1e-6
PAISE_PER_RUPEE = 100
PAISE_PER_CRORE = 10_000_000 * PAISE_PER_RUPEE  # Rs 1 Cr = 1e7 rupees


@dataclass(frozen=True)
class Position:
    """A single holding."""

    asset_id: str
    ticker: str
    asset_class: str
    sector: str
    price: float
    units: float
    value_paise: int
    weight: float


@dataclass(frozen=True)
class PortfolioState:
    """An immutable snapshot of the portfolio at a point in time.

    State changes create a new object; nothing is mutated in place.
    """

    portfolio_id: str
    timestamp: datetime
    as_of_date: date
    total_value_paise: int
    cash_value_paise: int
    positions: tuple[Position, ...]
    weights: dict[str, float]
    return_series: pd.Series

    def __post_init__(self) -> None:
        total = sum(self.weights.values())
        if abs(total - 1.0) > WEIGHT_TOLERANCE:
            raise ValueError(
                f"weights must sum to 1.0 within {WEIGHT_TOLERANCE}, got {total!r}"
            )
        if self.total_value_paise <= 0:
            raise ValueError("total_value_paise must be positive")
        if self.cash_value_paise < 0:
            raise ValueError("cash_value_paise must not be negative")

    @property
    def total_value_rupees(self) -> float:
        return self.total_value_paise / PAISE_PER_RUPEE

    @property
    def total_value_crore(self) -> float:
        return self.total_value_paise / PAISE_PER_CRORE

    def sector_exposure(self) -> dict[str, float]:
        """Portfolio weight per sector."""
        out: dict[str, float] = {}
        for p in self.positions:
            out[p.sector] = out.get(p.sector, 0.0) + p.weight
        return out

    def liquid_share(self, universe: Universe) -> float:
        """Fraction of the portfolio held in instruments marked liquid."""
        liquid = set(universe.liquid_ids())
        return sum(w for a, w in self.weights.items() if a in liquid)

    def weight_of(self, asset_id: str) -> float:
        return self.weights.get(asset_id, 0.0)

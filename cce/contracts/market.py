"""Asset universe and market-data contracts.

Spec: docs/06-DATA-CONTRACTS.md section 3.

Conventions (docs/06 section 1):
- Rates, weights and ratios are decimals: 0.1568 means 15.68%.
- ``Universe.asset_ids`` is the canonical ordering for EVERY ndarray in the
  system. Convert between dict and vector exactly once, at the edge.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

import numpy as np
import pandas as pd

from .enums import DataProvider, RiskState, ValidationStatus

__all__ = [
    "Asset", "Universe", "MarketData", "ValidationFinding", "ValidationReport",
]


@dataclass(frozen=True)
class Asset:
    """A single instrument in the universe.

    Attributes
    ----------
    asset_id:
        Stable key used in every weight dict. NOT the display ticker.
    txn_cost_rate:
        Cost per unit of absolute weight change, as a decimal
        (0.0010 = 10 bps).
    adv_paise:
        Average daily value traded, in paise. ``None`` DISABLES the
        days-to-liquidate control for this asset rather than fabricating a
        figure (docs/08-FINANCIAL-METHODS.md section 10.2).
    """

    asset_id: str
    ticker: str
    name: str
    asset_class: str
    sector: str
    is_liquid: bool
    min_weight: float
    max_weight: float
    txn_cost_rate: float
    adv_paise: int | None = None
    synthetic: bool = False  # e.g. a cash proxy derived from the risk-free rate

    def __post_init__(self) -> None:
        if not 0.0 <= self.min_weight <= self.max_weight <= 1.0:
            raise ValueError(
                f"{self.asset_id}: require 0 <= min_weight <= max_weight <= 1, "
                f"got {self.min_weight} / {self.max_weight}"
            )
        if self.txn_cost_rate < 0.0:
            raise ValueError(f"{self.asset_id}: txn_cost_rate must be >= 0")


@dataclass(frozen=True)
class Universe:
    """The ordered set of investable assets."""

    assets: tuple[Asset, ...]

    def __post_init__(self) -> None:
        if not self.assets:
            raise ValueError("universe must contain at least one asset")
        ids = [a.asset_id for a in self.assets]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate asset_id in universe")

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """Canonical ordering for every ndarray in the system."""
        return tuple(a.asset_id for a in self.assets)

    def get(self, asset_id: str) -> Asset:
        for a in self.assets:
            if a.asset_id == asset_id:
                return a
        raise KeyError(f"unknown asset_id: {asset_id}")

    def to_vector(self, weights: dict[str, float]) -> np.ndarray:
        """Weight dict to ndarray ordered by :attr:`asset_ids`.

        Missing assets are 0.0; unknown keys are an error rather than a silent
        drop, because a silently dropped weight breaks ``sum(w) == 1``.
        """
        unknown = set(weights) - set(self.asset_ids)
        if unknown:
            raise KeyError(f"weights contain unknown asset_ids: {sorted(unknown)}")
        return np.array([float(weights.get(a, 0.0)) for a in self.asset_ids])

    def to_dict(self, vector: np.ndarray) -> dict[str, float]:
        """Ndarray ordered by :attr:`asset_ids` back to a weight dict."""
        vec = np.asarray(vector, dtype=float).ravel()
        if vec.size != len(self.assets):
            raise ValueError(
                f"vector length {vec.size} != universe size {len(self.assets)}"
            )
        return {a: float(v) for a, v in zip(self.asset_ids, vec)}

    def sector_map(self) -> dict[str, list[str]]:
        """Sector name to the asset_ids in it."""
        out: dict[str, list[str]] = {}
        for a in self.assets:
            out.setdefault(a.sector, []).append(a.asset_id)
        return out

    def liquid_ids(self) -> tuple[str, ...]:
        return tuple(a.asset_id for a in self.assets if a.is_liquid)


@dataclass(frozen=True)
class MarketData:
    """A validated price/return panel.

    ``returns`` NEVER contains NaN. If a gap could not be resolved
    legitimately, no ``MarketData`` is produced at all and the
    :class:`ValidationReport` is INVALID (INV-5).
    """

    prices: pd.DataFrame   # index=date, columns=asset_ids
    returns: pd.DataFrame  # simple returns, first row dropped
    as_of_date: date
    provider: DataProvider
    universe_hash: str
    data_hash: str         # reproducibility key (NFR-012)

    def __post_init__(self) -> None:
        if self.returns.isna().any().any():
            raise ValueError(
                "MarketData.returns contains NaN. Missing data is never "
                "zero-filled or silently carried (INV-5)."
            )
        if list(self.prices.columns) != list(self.returns.columns):
            raise ValueError("prices and returns must share column order")

    @property
    def n_observations(self) -> int:
        return len(self.returns)


@dataclass(frozen=True)
class ValidationFinding:
    """One problem detected in a market-data panel."""

    code: str  # MISSING_OBS | STALE_DATA | OUTLIER | GAP | SCHEMA
    asset_id: str | None
    severity: RiskState
    message: str
    detail: dict


@dataclass(frozen=True)
class ValidationReport:
    """Outcome of validating a market-data panel."""

    status: ValidationStatus
    findings: tuple[ValidationFinding, ...]
    checked_at: datetime

    @property
    def usable_for_risk(self) -> bool:
        """INVALID data must never reach the risk engine."""
        return self.status is not ValidationStatus.INVALID

    @property
    def is_degraded(self) -> bool:
        """Usable, but every figure derived from it must be labelled."""
        return self.status is ValidationStatus.DEGRADED

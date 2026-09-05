"""Risk contribution — the hidden-concentration detector.

Spec: docs/08-FINANCIAL-METHODS.md section 9.

Allocation answers *"how much capital is here?"*
Risk contribution answers *"how much of our risk is caused by this?"*

These diverge, and the divergence is where institutional risk actually hides:

    Banking allocation:        24%
    Banking risk contribution: 43%

The position is comfortably inside its 30% weight cap and is nonetheless
responsible for 43% of portfolio risk. A weight-only control framework cannot
see this. ``RC_SECTOR_MAX`` can.

Identity, checked in tests:  ``sum_i RC_i == sigma_p``  exactly.
That is a free correctness check on the whole covariance/weight pipeline.
"""

from __future__ import annotations

import numpy as np

from ..contracts import Universe
from .volatility import portfolio_volatility

__all__ = [
    "marginal_contributions",
    "percentage_risk_contributions",
    "risk_contribution_table",
    "risk_contributions",
    "sector_risk_contributions",
]


def marginal_contributions(
    weights: np.ndarray, covariance: np.ndarray
) -> np.ndarray:
    """``MCR_i = (Sigma w)_i / sigma_p``.

    Sensitivity of portfolio volatility to a small increase in asset i.
    Returns zeros when ``sigma_p`` is zero — an all-cash portfolio has no
    risk to attribute, and dividing by it would produce inf/NaN that poisons
    every downstream metric (EC-3.3).
    """
    w = np.asarray(weights, dtype=float).ravel()
    cov = np.asarray(covariance, dtype=float)
    sigma_p = portfolio_volatility(w, cov)
    if sigma_p <= 0.0:
        return np.zeros_like(w)
    return (cov @ w) / sigma_p


def risk_contributions(
    weights: np.ndarray, covariance: np.ndarray
) -> np.ndarray:
    """``RC_i = w_i * MCR_i``, in the same units as ``sigma_p``.

    Sums exactly to portfolio volatility.
    """
    w = np.asarray(weights, dtype=float).ravel()
    return w * marginal_contributions(w, covariance)


def percentage_risk_contributions(
    weights: np.ndarray, covariance: np.ndarray
) -> np.ndarray:
    """``PCR_i = RC_i / sum_j RC_j``. Sums to 1.0.

    Returns zeros when total risk is zero rather than NaN.
    """
    rc = risk_contributions(weights, covariance)
    total = float(rc.sum())
    if total == 0.0:
        return np.zeros_like(rc)
    return rc / total


def risk_contribution_table(
    weights: dict[str, float], covariance: np.ndarray, universe: Universe
) -> dict[str, float]:
    """Percentage risk contribution keyed by ``asset_id``.

    ``covariance`` must be ordered by ``Universe.asset_ids``.
    """
    w = universe.to_vector(weights)
    return universe.to_dict(percentage_risk_contributions(w, covariance))


def sector_risk_contributions(
    weights: dict[str, float], covariance: np.ndarray, universe: Universe
) -> dict[str, float]:
    """Percentage risk contribution aggregated to sector.

    This is the figure that trips ``RC_SECTOR_MAX`` in the demo: banking
    allocation stays at 24% while its risk contribution climbs from 27% to
    41% purely because banking volatility rose.
    """
    per_asset = risk_contribution_table(weights, covariance, universe)
    out: dict[str, float] = {}
    for asset_id, share in per_asset.items():
        sector = universe.get(asset_id).sector
        out[sector] = out.get(sector, 0.0) + share
    return out

"""Black-Litterman posterior expected returns.

Spec: docs/08-FINANCIAL-METHODS.md section 11.7.

    Equilibrium:  Pi   = delta * Sigma * w_market
    Posterior:    mu_BL = [(tau*Sigma)^-1 + P' Omega^-1 P]^-1
                          . [(tau*Sigma)^-1 Pi + P' Omega^-1 Q]

The point of BL here is not the mathematics but the boundary it respects:
**a view changes expected returns; it never bypasses a control.** ``mu_BL``
feeds the CONSTRAINED optimizer and the result is validated independently
like any other candidate. A user who believes IT will outperform can move the
proposal; they cannot move the sector cap.

A view is entered the way a person states one -- "IT will outperform broad
equity by 2%, and I am 60% confident" -- and turned into one row of ``P``,
one entry of ``Q`` and one diagonal entry of ``Omega``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np

from ..contracts import View

__all__ = ["BLResult", "View", "black_litterman", "equilibrium_returns"]

logger = logging.getLogger(__name__)

#: Risk-aversion. Standard market value; the posterior is not sensitive to it
#: within the usual 2-3 range.
DEFAULT_DELTA = 2.5

#: Uncertainty in the equilibrium prior. Small by convention: the prior is a
#: market-implied estimate, and tau near 1 would let a single view dominate it.
DEFAULT_TAU = 0.05


@dataclass(frozen=True)
class BLResult:
    """Posterior returns, plus what happened on the way there."""

    expected_returns: np.ndarray
    equilibrium: np.ndarray
    used_views: bool
    note: str | None = None

    @property
    def fell_back(self) -> bool:
        """True when the posterior could not be formed and the prior stands."""
        return not self.used_views and self.note is not None


def equilibrium_returns(
    covariance: np.ndarray,
    market_weights: np.ndarray,
    delta: float = DEFAULT_DELTA,
) -> np.ndarray:
    """``Pi = delta * Sigma * w_market`` — the market's implied returns.

    Used as the prior rather than a historical mean, because the historical
    mean over three years of Indian market data is exactly the fragile
    estimate BL exists to temper.
    """
    return float(delta) * (covariance @ np.asarray(market_weights, dtype=float))


def black_litterman(
    covariance: np.ndarray,
    market_weights: np.ndarray,
    views: tuple[View, ...],
    asset_ids: tuple[str, ...],
    delta: float = DEFAULT_DELTA,
    tau: float = DEFAULT_TAU,
) -> BLResult:
    """Blend the equilibrium prior with the stated views.

    Falls back to the prior, with a note, whenever the posterior cannot be
    formed -- a singular ``Omega``, a view naming an unknown asset, or a
    numerically unusable system (EC-4.5). The fallback is VISIBLE: the caller
    surfaces ``note`` rather than silently serving a different estimate than
    the user asked for.
    """
    covariance = np.asarray(covariance, dtype=float)
    pi = equilibrium_returns(covariance, market_weights, delta)

    if not views:
        return BLResult(expected_returns=pi, equilibrium=pi, used_views=False)

    index = {a: i for i, a in enumerate(asset_ids)}
    unknown = [
        name
        for v in views
        for name in (v.asset, v.versus)
        if name is not None and name not in index
    ]
    if unknown:
        note = f"view names unknown asset(s): {', '.join(sorted(set(unknown)))}"
        logger.warning("%s; falling back to the equilibrium prior", note)
        return BLResult(pi, pi, used_views=False, note=note)

    n_views, n_assets = len(views), len(asset_ids)
    P = np.zeros((n_views, n_assets))
    Q = np.zeros(n_views)
    for row, view in enumerate(views):
        P[row, index[view.asset]] = 1.0
        if view.versus is not None:
            P[row, index[view.versus]] = -1.0
        Q[row] = view.outperformance

    tau_sigma = tau * covariance

    # Omega = diag(P tau Sigma P') scaled by confidence: a more confident view
    # gets a SMALLER variance and therefore more weight in the posterior.
    base = np.diag(P @ tau_sigma @ P.T).astype(float)
    scale = np.array([(1.0 - v.confidence) / v.confidence for v in views])
    omega_diag = base * np.maximum(scale, 1e-8)

    if np.any(~np.isfinite(omega_diag)) or np.any(omega_diag <= 0):
        note = (
            "view uncertainty matrix is singular or non-positive; the views "
            "cannot be blended"
        )
        logger.warning("%s; falling back to the equilibrium prior", note)
        return BLResult(pi, pi, used_views=False, note=note)

    try:
        tau_sigma_inv = np.linalg.inv(tau_sigma)
        omega_inv = np.diag(1.0 / omega_diag)
        precision = tau_sigma_inv + P.T @ omega_inv @ P
        mu = np.linalg.solve(
            precision, tau_sigma_inv @ pi + P.T @ omega_inv @ Q
        )
    except np.linalg.LinAlgError as exc:
        note = f"posterior could not be solved ({exc}); equilibrium prior used"
        logger.warning(note)
        return BLResult(pi, pi, used_views=False, note=note)

    if not np.all(np.isfinite(mu)):
        note = "posterior contains non-finite values; equilibrium prior used"
        logger.warning(note)
        return BLResult(pi, pi, used_views=False, note=note)

    return BLResult(expected_returns=mu, equilibrium=pi, used_views=True)

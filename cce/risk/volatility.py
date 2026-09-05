"""Historical volatility.

Spec: docs/08-FINANCIAL-METHODS.md sections 0, 2.

Conventions:
- Sample standard deviation, ``ddof=1``, used consistently everywhere.
  Mixing ddof=0 and ddof=1 across modules produces small, maddening
  discrepancies.
- Annualised by ``sqrt(252)`` unless ``annualise=False``.
- Returns ``None`` when there is not enough data. NEVER 0.0 (INV-5).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

__all__ = [
    "TRADING_DAYS", "annualisation_factor", "historical_volatility",
    "portfolio_volatility", "rolling_volatility",
]

TRADING_DAYS = 252
MIN_OBSERVATIONS = 2


def annualisation_factor(trading_days: int = TRADING_DAYS) -> float:
    """``sqrt(trading_days)`` — the volatility scaling factor.

    Apply this EXACTLY ONCE. A ``sqrt(252)`` applied twice is a 15.9x error
    that still looks like a number (docs/08 section 15).
    """
    return float(np.sqrt(trading_days))


def historical_volatility(
    returns: pd.Series | np.ndarray,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> float | None:
    """Sample standard deviation of returns.

    Returns the ANNUALISED volatility as a decimal (0.156 = 15.6%) unless
    ``annualise=False``, in which case it is the daily figure.

    Returns ``None`` with fewer than two observations — a standard deviation
    of one point is not zero volatility, it is no information.
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size < MIN_OBSERVATIONS:
        return None
    sigma = float(np.std(r, ddof=1))
    return sigma * annualisation_factor(trading_days) if annualise else sigma


def portfolio_volatility(
    weights: np.ndarray,
    covariance: np.ndarray,
    annualise: bool = False,
    trading_days: int = TRADING_DAYS,
) -> float:
    """``sigma_p = sqrt(w' Sigma w)``.

    ``annualise`` defaults to False because covariance matrices in this
    codebase are annualised at construction — annualising again here would
    apply the factor twice.

    Clips a marginally negative quadratic form (float noise on a repaired
    covariance) to zero rather than returning NaN from ``sqrt``.
    """
    w = np.asarray(weights, dtype=float).ravel()
    var = float(w @ np.asarray(covariance, dtype=float) @ w)
    if var < 0:
        if var < -1e-10:
            raise ValueError(
                f"portfolio variance is negative ({var!r}); the covariance "
                f"matrix is not positive semi-definite"
            )
        var = 0.0
    sigma = float(np.sqrt(var))
    return sigma * annualisation_factor(trading_days) if annualise else sigma


def rolling_volatility(
    returns: pd.Series, window: int = 60, trading_days: int = TRADING_DAYS
) -> pd.Series:
    """Rolling annualised volatility. Leading values are NaN by construction."""
    return returns.rolling(window).std(ddof=1) * annualisation_factor(trading_days)

"""EWMA volatility — the primary responsive risk estimator.

Spec: docs/08-FINANCIAL-METHODS.md section 3.

    sigma^2_t = lambda * sigma^2_{t-1} + (1 - lambda) * r^2_{t-1}

Why EWMA is the default: if recent Indian market volatility rises sharply, a
long-window historical estimate dilutes the change across the whole window.
EWMA weights recent observations more heavily and moves within days. That
responsiveness is what lets the control engine detect a regime change while
it still matters.

Both estimates are displayed side by side, because the DIFFERENCE between
them is the evidence that CCE responds to current conditions rather than
long-run averages (docs/08 section 2).

**Zero-mean convention.** The recursion squares the raw return ``r``, not the
deviation ``(r - mu)``. This is the RiskMetrics convention and is standard for
daily horizons, where the mean is negligible beside the volatility and
estimating it adds more noise than it removes.

Two consequences worth knowing, because they are visible in the UI:

1. ``historical_volatility`` DEMEANS (``np.std(ddof=1)``) while EWMA does not,
   so the two headline figures use different mean conventions. For equities
   the gap is about 0.25% of the estimate and immaterial.
2. A constant non-zero return converges to ``|r|``, not zero. Our synthetic
   CASH proxy drifts at ``risk_free_rate / 252`` with zero variance, so it
   reports roughly 0.4% annualised EWMA volatility against 0.0% historical.
   That is the estimator behaving correctly, not a bug — but do not describe
   cash as "zero volatility" while showing an EWMA figure beside it.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .volatility import TRADING_DAYS, annualisation_factor

__all__ = [
    "DEFAULT_LAMBDA",
    "DEFAULT_SEED_WINDOW",
    "ewma_covariance",
    "ewma_step",
    "ewma_variance_series",
    "ewma_volatility",
]


DEFAULT_LAMBDA = 0.94        # RiskMetrics convention for daily data
DEFAULT_SEED_WINDOW = 60
def ewma_step(prev_var: float, r: float, lam: float = DEFAULT_LAMBDA) -> float:
    """One step of the EWMA variance recursion.

        sigma^2_t = lambda * sigma^2_{t-1} + (1 - lambda) * r^2

    Exposed separately so the recursion has a directly hand-checkable entry
    point: with prev_var=1e-4, r=0.02 and lambda=0.94 the result is
    0.94*1e-4 + 0.06*4e-4 = 9.4e-5 + 2.4e-5 = 1.18e-4.
    """
    return lam * prev_var + (1.0 - lam) * r * r


def _seed_variance(r: np.ndarray, seed_window: int) -> float:
    """Seed sigma^2_0 with the sample variance of the first n observations.

    Documented rather than starting from zero, which produces a long,
    meaningless warm-up during which the estimate is simply wrong.
    """
    n = min(seed_window, r.size)
    if n < 2:
        return float(r[0] ** 2) if r.size else 0.0
    return float(np.var(r[:n], ddof=1))


def ewma_variance_series(
    returns: pd.Series | np.ndarray,
    lam: float = DEFAULT_LAMBDA,
    seed_window: int = DEFAULT_SEED_WINDOW,
) -> np.ndarray:
    """EWMA variance series, DAILY (not annualised).

    Element ``t`` is the variance estimate available AFTER observing return
    ``t`` — so it may be used to forecast ``t+1`` without look-ahead.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError(f"lambda must be in (0, 1), got {lam}")
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size == 0:
        return np.empty(0)

    var = np.empty(r.size, dtype=float)
    prev = _seed_variance(r, seed_window)
    for i, ret in enumerate(r):
        prev = lam * prev + (1.0 - lam) * ret * ret
        var[i] = prev
    return var


def ewma_volatility(
    returns: pd.Series | np.ndarray,
    lam: float = DEFAULT_LAMBDA,
    seed_window: int = DEFAULT_SEED_WINDOW,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> float | None:
    """Latest EWMA volatility, annualised by default.

    Returns ``None`` with fewer than two observations (INV-5).
    """
    var = ewma_variance_series(returns, lam=lam, seed_window=seed_window)
    if var.size < 2:
        return None
    sigma = float(np.sqrt(var[-1]))
    return sigma * annualisation_factor(trading_days) if annualise else sigma


def ewma_covariance(
    returns: pd.DataFrame,
    lam: float = DEFAULT_LAMBDA,
    seed_window: int = DEFAULT_SEED_WINDOW,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> np.ndarray:
    """EWMA covariance matrix.

        Sigma_t = lambda * Sigma_{t-1} + (1 - lambda) * r_{t-1} r_{t-1}'

    Column order follows ``returns.columns`` — align that to
    ``Universe.asset_ids`` before calling.

    The result is symmetrised on return: the recursion is symmetric in exact
    arithmetic but accumulates asymmetry in floating point, and downstream
    eigen-decomposition assumes symmetry.
    """
    if not 0.0 < lam < 1.0:
        raise ValueError(f"lambda must be in (0, 1), got {lam}")
    r = returns.dropna().to_numpy(dtype=float)
    n, _ = r.shape
    if n < 2:
        raise ValueError("need at least two observations for a covariance")

    seed_n = min(seed_window, n)
    cov = np.cov(r[:seed_n], rowvar=False, ddof=1)
    cov = np.atleast_2d(cov)

    for t in range(n):
        outer = np.outer(r[t], r[t])
        cov = lam * cov + (1.0 - lam) * outer

    cov = (cov + cov.T) / 2.0
    return cov * trading_days if annualise else cov

"""Expected return estimation — "Model Estimates".

Spec: docs/08-FINANCIAL-METHODS.md section 5.

Placed in ``cce.risk`` rather than ``cce.optimizer`` (where the plan sketched
it) because the risk engine needs expected returns for Sharpe, and
``cce.risk`` may not import ``cce.optimizer``. The optimizer IS permitted to
import ``cce.risk``, so Phase 4 reuses this rather than defining a second
estimator.

**Mandatory display rule (FR-062):** these are labelled "Model Estimate"
wherever they appear. They are the least reliable numbers in the system —
mean estimation error dominates covariance estimation error in mean-variance
optimization — and presenting them as facts would be the single most
misleading thing CCE could do.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..contracts import ExpectedReturnMethod
from .ewma import DEFAULT_LAMBDA
from .volatility import TRADING_DAYS

__all__ = ["historical_mean", "ewma_mean", "expected_returns"]


def historical_mean(
    returns: pd.DataFrame | pd.Series,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> np.ndarray:
    """Arithmetic mean return, annualised by ``* trading_days``.

    The DEFAULT, chosen for stability and explainability rather than
    sophistication.
    """
    mu = np.asarray(pd.DataFrame(returns).mean(), dtype=float)
    return mu * trading_days if annualise else mu


def ewma_mean(
    returns: pd.DataFrame | pd.Series,
    lam: float = DEFAULT_LAMBDA,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> np.ndarray:
    """Exponentially-weighted mean return.

    More responsive than the historical mean, and correspondingly noisier.
    Weights decay as ``lambda^age``, normalised to sum to one.
    """
    df = pd.DataFrame(returns).dropna()
    n = len(df)
    if n == 0:
        raise ValueError("no observations")
    ages = np.arange(n - 1, -1, -1, dtype=float)  # most recent has age 0
    w = lam ** ages
    w /= w.sum()
    mu = np.asarray(df.to_numpy(dtype=float).T @ w, dtype=float)
    return mu * trading_days if annualise else mu


def expected_returns(
    returns: pd.DataFrame,
    method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL,
    lam: float = DEFAULT_LAMBDA,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
    posterior: np.ndarray | None = None,
) -> np.ndarray:
    """Dispatch to the configured estimator.

    ``BLACK_LITTERMAN`` requires a precomputed ``posterior`` from Phase 11;
    it is not derivable from returns alone.
    """
    if method is ExpectedReturnMethod.HISTORICAL:
        return historical_mean(returns, annualise, trading_days)
    if method is ExpectedReturnMethod.EWMA:
        return ewma_mean(returns, lam, annualise, trading_days)
    if method is ExpectedReturnMethod.BLACK_LITTERMAN:
        if posterior is None:
            raise ValueError(
                "BLACK_LITTERMAN requires a precomputed posterior vector"
            )
        return np.asarray(posterior, dtype=float)
    raise ValueError(f"unknown expected-return method: {method!r}")

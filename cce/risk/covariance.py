"""Covariance estimation and numerical repair.

Spec: docs/08-FINANCIAL-METHODS.md section 4.

The optimizer needs Sigma. Sampling noise, short windows and near-collinear
assets all break positive semi-definiteness, and a broken matrix MUST NOT
reach the solver: it will return numbers, and they will be meaningless.

Governing rule: favour numerical stability over theoretical sophistication.
A repaired-and-recorded matrix beats an exotic estimator that intermittently
fails.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..exceptions import CovarianceError
from .ewma import DEFAULT_LAMBDA, ewma_covariance
from .volatility import TRADING_DAYS

logger = logging.getLogger(__name__)

__all__ = [
    "CovarianceReport",
    "condition_number",
    "correlation_from_covariance",
    "historical_covariance",
    "is_psd",
    "prepare_covariance",
]

EIGENVALUE_FLOOR = 1e-10
MAX_CONDITION_NUMBER = 1e12
DEFAULT_SHRINKAGE = 0.10


@dataclass(frozen=True)
class CovarianceReport:
    """What had to be done to make the matrix usable.

    A repair is recorded, never silent: it becomes a MODEL_COVARIANCE finding
    so the risk manager can see the estimate needed help.
    """

    repaired: bool
    symmetrised: bool
    eigenvalues_clipped: int
    shrinkage_applied: float
    min_eigenvalue_before: float
    condition_number: float
    notes: tuple[str, ...] = ()

    @property
    def message(self) -> str:
        if not self.repaired:
            return "covariance matrix was numerically valid"
        parts = []
        if self.eigenvalues_clipped:
            parts.append(f"{self.eigenvalues_clipped} negative eigenvalue(s) clipped")
        if self.shrinkage_applied:
            parts.append(f"shrinkage {self.shrinkage_applied:.0%} applied")
        if self.symmetrised:
            parts.append("symmetrised")
        return "covariance repaired: " + ", ".join(parts)


def historical_covariance(
    returns: pd.DataFrame,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> np.ndarray:
    """Sample covariance, ``ddof=1``, annualised by default.

    Column order follows ``returns.columns``.
    """
    r = returns.dropna()
    if len(r) < 2:
        raise CovarianceError("need at least two observations for a covariance")
    cov = np.cov(r.to_numpy(dtype=float), rowvar=False, ddof=1)
    cov = np.atleast_2d(cov)
    return cov * trading_days if annualise else cov


def is_psd(matrix: np.ndarray, tol: float = -1e-10) -> bool:
    """True when every eigenvalue is non-negative within tolerance."""
    sym = (matrix + matrix.T) / 2.0
    return bool(np.linalg.eigvalsh(sym).min() >= tol)


def condition_number(matrix: np.ndarray) -> float:
    """Ratio of largest to smallest eigenvalue.

    An extreme value means near-collinear assets — typically a duplicated
    instrument or two proxies for the same exposure.
    """
    eig = np.linalg.eigvalsh((matrix + matrix.T) / 2.0)
    lo = float(np.abs(eig).min())
    if lo == 0.0:
        return float("inf")
    return float(np.abs(eig).max() / lo)


def prepare_covariance(
    covariance: np.ndarray,
    shrinkage: float = 0.0,
    max_condition: float = MAX_CONDITION_NUMBER,
) -> tuple[np.ndarray, CovarianceReport]:
    """Make a covariance matrix numerically usable, or refuse.

    The repair ladder from docs/08 section 4:

    1. Symmetrise:      ``Sigma <- (Sigma + Sigma') / 2``
    2. Eigen-decompose and clip negative eigenvalues to a small floor
    3. Optionally shrink toward the diagonal
    4. Re-check. If it STILL fails, raise :class:`CovarianceError`

    Raising is the correct outcome for an unrepairable matrix: it becomes a
    RED ``MODEL_COVARIANCE`` breach and trips the circuit breaker, which is
    the safe direction to fail (INV-4).
    """
    cov = np.asarray(covariance, dtype=float)
    if cov.ndim != 2 or cov.shape[0] != cov.shape[1]:
        raise CovarianceError(f"covariance must be square, got {cov.shape}")
    if not np.isfinite(cov).all():
        raise CovarianceError("covariance contains NaN or infinite values")

    notes: list[str] = []
    asymmetry = float(np.abs(cov - cov.T).max())
    symmetrised = asymmetry > 0.0
    sym = (cov + cov.T) / 2.0
    if symmetrised and asymmetry > 1e-12:
        notes.append(f"asymmetry {asymmetry:.2e} corrected")

    eigenvalues, vectors = np.linalg.eigh(sym)
    min_eig = float(eigenvalues.min())
    n_clipped = int((eigenvalues < EIGENVALUE_FLOOR).sum())

    repaired = sym
    if n_clipped:
        clipped = np.clip(eigenvalues, EIGENVALUE_FLOOR, None)
        repaired = vectors @ np.diag(clipped) @ vectors.T
        repaired = (repaired + repaired.T) / 2.0
        notes.append(
            f"minimum eigenvalue {min_eig:.2e} clipped to {EIGENVALUE_FLOOR:.0e}"
        )

    applied_shrinkage = 0.0
    cond = condition_number(repaired)
    if shrinkage > 0.0 or cond > max_condition:
        applied_shrinkage = shrinkage or DEFAULT_SHRINKAGE
        target = np.diag(np.diag(repaired))
        repaired = (1.0 - applied_shrinkage) * repaired + applied_shrinkage * target
        repaired = (repaired + repaired.T) / 2.0
        notes.append(
            f"condition number {cond:.2e} -> shrinkage {applied_shrinkage:.0%}"
        )
        cond = condition_number(repaired)

    if not is_psd(repaired):
        raise CovarianceError(
            f"covariance is not positive semi-definite after repair "
            f"(minimum eigenvalue {np.linalg.eigvalsh(repaired).min():.3e}). "
            f"Refusing to pass a broken matrix to the solver."
        )
    if cond > max_condition:
        raise CovarianceError(
            f"covariance remains numerically unstable after shrinkage "
            f"(condition number {cond:.3e} exceeds {max_condition:.0e}). "
            f"Two assets are probably near-collinear."
        )

    was_repaired = bool(n_clipped or applied_shrinkage
                        or (symmetrised and asymmetry > 1e-12))
    report = CovarianceReport(
        repaired=was_repaired,
        symmetrised=symmetrised,
        eigenvalues_clipped=n_clipped,
        shrinkage_applied=applied_shrinkage,
        min_eigenvalue_before=min_eig,
        condition_number=cond,
        notes=tuple(notes),
    )
    if was_repaired:
        logger.warning("%s", report.message)
    return repaired, report


def correlation_from_covariance(covariance: np.ndarray) -> np.ndarray:
    """Correlation matrix. Zero-variance assets yield zero correlation rather
    than NaN, so a cash proxy cannot poison the whole matrix."""
    cov = np.asarray(covariance, dtype=float)
    sd = np.sqrt(np.diag(cov))
    safe = np.where(sd > 0, sd, 1.0)
    corr = cov / np.outer(safe, safe)
    zero = sd <= 0
    if zero.any():
        corr[zero, :] = 0.0
        corr[:, zero] = 0.0
    np.fill_diagonal(corr, 1.0)
    return np.clip(corr, -1.0, 1.0)


def estimate_covariance(
    returns: pd.DataFrame,
    method: str = "historical",
    lam: float = DEFAULT_LAMBDA,
    annualise: bool = True,
    trading_days: int = TRADING_DAYS,
) -> tuple[np.ndarray, CovarianceReport]:
    """Estimate and repair in one call. ``method`` is 'historical' or 'ewma'."""
    if method == "historical":
        raw = historical_covariance(returns, annualise=annualise,
                                    trading_days=trading_days)
    elif method == "ewma":
        raw = ewma_covariance(returns, lam=lam, annualise=annualise,
                              trading_days=trading_days)
    else:
        raise ValueError(f"unknown covariance method: {method!r}")
    return prepare_covariance(raw)

"""Value at Risk.

Spec: docs/08-FINANCIAL-METHODS.md section 7.

All VaR figures are 1-DAY at the configured confidence, reported as a
POSITIVE loss: ``var_95 = 0.031`` means a 3.1% loss.

Historical VaR is primary. Parametric exists for COMPARISON, not authority —
it assumes normality, which returns violate in exactly the tail the metric is
about. Displaying both shows how much the normal assumption understates the
tail, which is itself useful to a risk manager.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

__all__ = [
    "MIN_OBSERVATIONS", "historical_var", "parametric_var", "monte_carlo_var",
    "scale_var_horizon",
]

# Below this, a tail estimate is not honest. Return None, never 0.0 (INV-5).
MIN_OBSERVATIONS = 250


def historical_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    min_observations: int = MIN_OBSERVATIONS,
) -> float | None:
    """Empirical VaR — the primary method.

    The loss threshold exceeded by the worst ``1 - confidence`` of observed
    returns, negated so it reads as a positive loss.

    Non-parametric, assumes no distribution, and is directly explainable:
    *on the worst 5% of days in our history, we lost at least this much.*

    Returns ``None`` below ``min_observations``. A 95% VaR from 30 points is
    not a risk limit, it is noise with a decimal point.
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size < min_observations:
        return None
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    return float(-np.percentile(r, (1.0 - confidence) * 100.0))


def parametric_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    min_observations: int = 2,
) -> float | None:
    """Normal-assumption VaR: ``-(mu + z_alpha * sigma)``.

    For COMPARISON ONLY. Returns are fat-tailed, so this systematically
    understates the tail — which is the point of showing it beside the
    historical figure.
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size < min_observations:
        return None
    mu = float(np.mean(r))
    sigma = float(np.std(r, ddof=1))
    z = float(stats.norm.ppf(1.0 - confidence))  # negative for 0.95
    return float(-(mu + z * sigma))


def monte_carlo_var(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    paths: int = 10_000,
    seed: int = 42,
    min_observations: int = 2,
) -> float | None:
    """Simulated VaR from a fitted normal. Seeded, therefore reproducible.

    Optional (P2). MUST NOT become a dependency of the core control loop —
    if it is slow or unstable, reduce ``paths``, then disable it. The loop
    keeps working (docs/08 section 7.3).
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size < min_observations:
        return None
    rng = np.random.default_rng(seed)
    sim = rng.normal(float(np.mean(r)), float(np.std(r, ddof=1)), paths)
    return float(-np.percentile(sim, (1.0 - confidence) * 100.0))


def scale_var_horizon(var_1d: float, days: int) -> float:
    """Square-root-of-time scaling.

    Assumes i.i.d. returns, which is optimistic in a crisis precisely when
    the scaled figure matters most. Label any multi-day figure produced this
    way as an approximation.
    """
    if days < 1:
        raise ValueError("horizon must be at least one day")
    return float(var_1d * np.sqrt(days))

"""Conditional VaR (Expected Shortfall) — the primary tail-risk control.

Spec: docs/08-FINANCIAL-METHODS.md section 8.

    CVaR_alpha = -mean( r | r <= -VaR_alpha )

VaR says WHERE the tail begins. CVaR says HOW BAD it is once you are in it.

CVaR is the hard control (``RISK_CVAR_95``) because two candidate portfolios
can share a VaR while having very different tail severity — and capital is
destroyed by severity, not by where the threshold sits.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .var import MIN_OBSERVATIONS, historical_var

__all__ = ["CVaRResult", "historical_cvar", "cvar_with_diagnostics",
           "MIN_TAIL_OBSERVATIONS"]

# Below this many points beyond VaR, the mean of the tail is unstable.
MIN_TAIL_OBSERVATIONS = 10


@dataclass(frozen=True)
class CVaRResult:
    """CVaR plus enough diagnostics to know whether to trust it."""

    value: float | None
    tail_observations: int
    degraded: bool
    reason: str | None = None


def historical_cvar(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    min_observations: int = MIN_OBSERVATIONS,
) -> float | None:
    """Mean loss GIVEN the VaR threshold was breached, as a positive number.

    Returns ``None`` below ``min_observations`` (INV-5).

    Use :func:`cvar_with_diagnostics` where the caller needs to know whether
    the tail was thin enough to mark the snapshot degraded.
    """
    return cvar_with_diagnostics(returns, confidence, min_observations).value


def cvar_with_diagnostics(
    returns: pd.Series | np.ndarray,
    confidence: float = 0.95,
    min_observations: int = MIN_OBSERVATIONS,
) -> CVaRResult:
    """CVaR with the tail sample size that produced it.

    If fewer than :data:`MIN_TAIL_OBSERVATIONS` points fall beyond VaR, the
    value is still returned but flagged degraded. Reporting the mean of three
    observations as a risk limit without saying so would be dishonest — and
    it is a hard control, so it gates approvals.
    """
    r = np.asarray(pd.Series(returns).dropna(), dtype=float)
    if r.size < min_observations:
        return CVaRResult(
            value=None, tail_observations=0, degraded=True,
            reason=(f"only {r.size} observations; CVaR needs "
                    f"{min_observations}+ and is reported as not computed"),
        )

    var = historical_var(r, confidence, min_observations=min_observations)
    if var is None:
        return CVaRResult(None, 0, True, "VaR could not be computed")

    tail = r[r <= -var]
    if tail.size == 0:
        # Every observation sits above the threshold; the percentile itself
        # is the best available estimate of the tail.
        return CVaRResult(
            value=float(var), tail_observations=0, degraded=True,
            reason="no observations strictly beyond VaR; using the threshold",
        )

    value = float(-np.mean(tail))
    # CVaR >= VaR is an identity. Enforce it against float noise rather than
    # returning a figure that violates it (docs/08 section 15).
    value = max(value, float(var))

    if tail.size < MIN_TAIL_OBSERVATIONS:
        return CVaRResult(
            value=value, tail_observations=int(tail.size), degraded=True,
            reason=(f"only {tail.size} observation(s) beyond VaR; the tail "
                    f"mean is unstable"),
        )
    return CVaRResult(value, int(tail.size), False)

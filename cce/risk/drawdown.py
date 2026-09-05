"""Drawdown metrics.

Spec: docs/08-FINANCIAL-METHODS.md section 12.

    M_t  = max(V_0..V_t)          running peak
    DD_t = (M_t - V_t) / M_t      current drawdown
    MDD  = max(DD_t)              maximum drawdown

Reported as POSITIVE fractions: 0.16 is a 16% decline from peak.

Drawdown is primarily a MONITORING metric. Severe configured conditions may
contribute to AMBER/RED, but the trigger is configurable rather than
hard-coded as a universal financial rule (master spec section 19), which is
why RISK_DRAWDOWN_CURRENT is a soft control by default.
"""

from __future__ import annotations

import pandas as pd

__all__ = [
    "current_drawdown",
    "drawdown_series",
    "equity_curve",
    "max_drawdown",
    "rolling_max_drawdown",
]


def equity_curve(returns: pd.Series, start_value: float = 1.0) -> pd.Series:
    """Cumulative value path from a return series."""
    return start_value * (1.0 + returns.fillna(0.0)).cumprod()


def drawdown_series(returns: pd.Series) -> pd.Series:
    """Drawdown at every point, as a positive fraction of the running peak."""
    curve = equity_curve(returns)
    peak = curve.cummax()
    return (peak - curve) / peak


def current_drawdown(returns: pd.Series) -> float | None:
    """Drawdown as at the latest observation. None if there is no data."""
    if returns is None or len(returns) == 0:
        return None
    return float(drawdown_series(returns).iloc[-1])


def max_drawdown(returns: pd.Series) -> float | None:
    """Worst peak-to-trough decline over the whole series."""
    if returns is None or len(returns) == 0:
        return None
    return float(drawdown_series(returns).max())


def rolling_max_drawdown(returns: pd.Series, window: int = 252) -> pd.Series:
    """Maximum drawdown within a trailing window."""
    return drawdown_series(returns).rolling(window, min_periods=1).max()

"""Deterministic test fixtures.

Spec: docs/11-TESTING-STRATEGY.md section 3.

Every fixture is seeded. Tests never touch the network and never use live
data. A flaky financial test is worse than no test: it teaches the team to
ignore red.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import numpy as np
import pandas as pd

from cce.contracts import (
    PAISE_PER_CRORE,
    Asset,
    PortfolioState,
    Position,
    Universe,
)

TRADING_DAYS = 252


def _dates(n: int, end: date | None = None) -> pd.DatetimeIndex:
    end = end or date(2026, 8, 31)
    return pd.bdate_range(end=pd.Timestamp(end), periods=n)


def constant_returns(n: int = 500, r: float = 0.001, assets: int = 3) -> pd.DataFrame:
    """Zero volatility. Volatility must come out exactly 0."""
    cols = [f"A{i}" for i in range(assets)]
    return pd.DataFrame(r, index=_dates(n), columns=cols)


def known_volatility_series(
    n: int = 1000, sigma_daily: float = 0.01, seed: int = 42
) -> pd.Series:
    """Seeded normal returns.

    Annualised volatility is approximately ``sigma_daily * sqrt(252)``;
    for 0.01 that is 0.1587.
    """
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0, sigma_daily, n), index=_dates(n))


def fat_tailed_series(n: int = 1000, df: int = 3, scale: float = 0.01,
                      seed: int = 42) -> pd.Series:
    """Student-t returns. Parametric VaR should understate this tail."""
    rng = np.random.default_rng(seed)
    return pd.Series(rng.standard_t(df, n) * scale, index=_dates(n))


def two_asset_known_covariance(
    rho: float = 0.5, s1: float = 0.01, s2: float = 0.02
) -> tuple[np.ndarray, np.ndarray]:
    """Weights and a hand-computable covariance matrix.

    Returns ``(weights, cov)`` so risk contributions can be verified by hand.
    """
    cov = np.array([
        [s1 * s1, rho * s1 * s2],
        [rho * s1 * s2, s2 * s2],
    ])
    return np.array([0.5, 0.5]), cov


def cov_from(sigma: dict[str, float], rho: float = 0.0) -> np.ndarray:
    """Covariance from per-asset volatilities and a single correlation."""
    s = np.array(list(sigma.values()), dtype=float)
    corr = np.full((s.size, s.size), rho)
    np.fill_diagonal(corr, 1.0)
    return corr * np.outer(s, s)


def apply_vol_regime_change(
    series: pd.Series, from_day: int, sigma_daily: float, seed: int = 7
) -> pd.Series:
    """Raise volatility from ``from_day`` onward.

    EWMA must react to this faster than a long-window historical estimate —
    that is the reason EWMA is the default estimator.
    """
    rng = np.random.default_rng(seed)
    out = series.copy()
    tail = len(series) - from_day
    out.iloc[from_day:] = rng.normal(0.0, sigma_daily, tail)
    return out


def shocked_series(
    base: pd.DataFrame, shock_day: int, shock: float = -0.18,
    column: str = "BANKNIFTY",
) -> pd.DataFrame:
    """Insert a single-day sector shock at a known index."""
    out = base.copy()
    if column in out.columns:
        out.iloc[shock_day, out.columns.get_loc(column)] = shock
    return out


# --------------------------------------------------------------------------
# Universe and portfolio
# --------------------------------------------------------------------------

def demo_universe() -> Universe:
    """A compact universe mirroring config/universe.yaml."""
    spec = [
        ("NIFTY50",   "BROAD_EQUITY", "EQUITY",       True),
        ("BANKNIFTY", "BANKING",      "EQUITY",       True),
        ("IT",        "IT",           "EQUITY",       True),
        ("PHARMA",    "PHARMA",       "EQUITY",       True),
        ("GOLD",      "GOLD",         "COMMODITY",    True),
        ("GSEC",      "GSEC",         "FIXED_INCOME", False),
        ("CASH",      "CASH",         "CASH",         True),
    ]
    return Universe(assets=tuple(
        Asset(
            asset_id=aid, ticker=aid, name=aid, asset_class=cls, sector=sec,
            is_liquid=liq, min_weight=0.0,
            max_weight=0.40 if aid == "CASH" else 0.30,
            txn_cost_rate=0.0 if aid == "CASH" else 0.0010,
        )
        for aid, sec, cls, liq in spec
    ))


def healthy_weights() -> dict[str, float]:
    """A GREEN starting allocation. Sums to 1.0 exactly."""
    return {
        "NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "PHARMA": 0.08,
        "GOLD": 0.10, "GSEC": 0.12, "CASH": 0.06,
    }


def concentrated_weights() -> dict[str, float]:
    """Banking at 43% — breaches CONC_SECTOR_MAX and RC_SECTOR_MAX.

    This is the demo's rejected optimal candidate.
    """
    return {
        "NIFTY50": 0.20, "BANKNIFTY": 0.43, "IT": 0.10, "PHARMA": 0.05,
        "GOLD": 0.06, "GSEC": 0.10, "CASH": 0.06,
    }


def illiquid_weights(liquid_share: float = 0.06) -> dict[str, float]:
    """Liquidity below the minimum — breaches LIQ_MIN_SHARE."""
    rest = 1.0 - liquid_share
    return {
        "GSEC": round(rest, 10), "CASH": round(liquid_share, 10),
        "NIFTY50": 0.0, "BANKNIFTY": 0.0, "IT": 0.0, "PHARMA": 0.0, "GOLD": 0.0,
    }


def demo_portfolio(
    weights: dict[str, float] | None = None,
    total_crore: float = 100.0,
) -> PortfolioState:
    """A Rs 100 Cr portfolio state built from a weight dict."""
    weights = weights or healthy_weights()
    universe = demo_universe()
    total_paise = round(total_crore * PAISE_PER_CRORE)

    positions = []
    for a in universe.assets:
        w = weights.get(a.asset_id, 0.0)
        value = round(total_paise * w)
        positions.append(Position(
            asset_id=a.asset_id, ticker=a.ticker, asset_class=a.asset_class,
            sector=a.sector, price=100.0, units=value / 100.0,
            value_paise=value, weight=w,
        ))

    return PortfolioState(
        portfolio_id="DEMO_100CR",
        timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
        as_of_date=date(2026, 8, 31),
        total_value_paise=total_paise,
        cash_value_paise=round(total_paise * weights.get("CASH", 0.0)),
        positions=tuple(positions),
        weights=dict(weights),
        return_series=known_volatility_series(n=500, sigma_daily=0.008),
    )


def panel_with_gap(n: int = 300, gap_at: int = 150) -> pd.DataFrame:
    """A price panel with a genuine hole. Must never be zero-filled (INV-5)."""
    idx = _dates(n)
    df = pd.DataFrame(
        100.0 + np.cumsum(
            np.random.default_rng(42).normal(0, 1, (n, 3)), axis=0
        ),
        index=idx, columns=["NIFTY50", "BANKNIFTY", "GOLD"],
    )
    df.iloc[gap_at, 1] = np.nan
    return df


def stale_panel(days_old: int = 10, n: int = 300) -> pd.DataFrame:
    """A panel whose last observation is well in the past."""
    end = date(2026, 8, 31) - timedelta(days=days_old)
    idx = pd.bdate_range(end=pd.Timestamp(end), periods=n)
    return pd.DataFrame(
        100.0 + np.cumsum(
            np.random.default_rng(1).normal(0, 1, (n, 3)), axis=0
        ),
        index=idx, columns=["NIFTY50", "BANKNIFTY", "GOLD"],
    )

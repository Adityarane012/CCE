"""Pure portfolio arithmetic.

Spec: docs/06-DATA-CONTRACTS.md section 4, docs/08-FINANCIAL-METHODS.md
sections 1 and 11.2.

Every function here is pure: same inputs, same outputs, no I/O, no globals.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from ..contracts import PAISE_PER_RUPEE, Universe

__all__ = [
    "allocate_paise",
    "asset_class_exposure",
    "liquid_share",
    "portfolio_returns",
    "sector_exposure",
    "transaction_cost_paise",
    "turnover",
    "value_to_units",
    "weight_deltas",
]


def portfolio_returns(
    weights: dict[str, float], returns: pd.DataFrame
) -> pd.Series:
    """Portfolio return series for a FIXED weight vector.

    ``r_p,t = sum_i w_i * r_i,t``

    This assumes the weights are held constant across the window — it is a
    "what would this allocation have returned" calculation, not a
    drift-and-rebalance simulation. Used for risk metrics on a candidate
    allocation, where holding weights fixed is exactly what is wanted.

    Assets absent from ``returns`` contribute nothing and are ignored rather
    than treated as zero-return holdings, because a missing column means the
    instrument was excluded upstream (INV-5).
    """
    cols = [a for a in returns.columns if a in weights]
    if not cols:
        raise ValueError("no overlap between weights and returns columns")
    w = np.array([weights[c] for c in cols], dtype=float)
    return pd.Series(returns[cols].to_numpy() @ w, index=returns.index)


def weight_deltas(
    new: dict[str, float], current: dict[str, float]
) -> dict[str, float]:
    """Per-asset weight change. Keys are the union of both allocations."""
    keys = set(new) | set(current)
    return {k: new.get(k, 0.0) - current.get(k, 0.0) for k in sorted(keys)}


def turnover(new: dict[str, float], current: dict[str, float]) -> float:
    """Fraction of the portfolio traded to move from ``current`` to ``new``.

    ``turnover = sum_i |w_new,i - w_cur,i| / 2``

    The ``/2`` makes this "share of the portfolio traded": selling 10% of A to
    buy 10% of B moves 20% of absolute weight but trades 10% of the
    portfolio.

    **State the convention wherever this is displayed.** The un-halved
    definition is also common, and the two differ by a factor of two — not a
    small confusion on a Rs 100 Cr book (docs/08 section 11.2).
    """
    return sum(abs(d) for d in weight_deltas(new, current).values()) / 2.0


def transaction_cost_paise(
    new: dict[str, float],
    current: dict[str, float],
    universe: Universe,
    total_value_paise: int,
) -> int:
    """Estimated cost of rebalancing.

    ``cost = sum_i c_i * |w_new,i - w_cur,i| * portfolio_value``

    Note this uses the FULL absolute weight change, not the halved turnover:
    both the sell and the buy leg incur cost.

    A rebalance is never free. Without this the optimizer will happily
    replace most of the portfolio to chase an expected-return difference well
    inside estimation error (docs/08 section 11.2).
    """
    total = 0.0
    for asset_id, delta in weight_deltas(new, current).items():
        if delta == 0.0:
            continue
        try:
            rate = universe.get(asset_id).txn_cost_rate
        except KeyError:
            raise KeyError(
                f"cannot cost a trade in {asset_id}: not in the universe"
            ) from None
        total += rate * abs(delta) * total_value_paise
    return round(total)


def sector_exposure(
    weights: dict[str, float], universe: Universe
) -> dict[str, float]:
    """Portfolio weight per sector."""
    out: dict[str, float] = {}
    for asset_id, w in weights.items():
        sector = universe.get(asset_id).sector
        out[sector] = out.get(sector, 0.0) + w
    return out


def asset_class_exposure(
    weights: dict[str, float], universe: Universe
) -> dict[str, float]:
    """Portfolio weight per asset class."""
    out: dict[str, float] = {}
    for asset_id, w in weights.items():
        cls = universe.get(asset_id).asset_class
        out[cls] = out.get(cls, 0.0) + w
    return out


def liquid_share(weights: dict[str, float], universe: Universe) -> float:
    """Fraction held in instruments marked liquid."""
    liquid = set(universe.liquid_ids())
    return sum(w for a, w in weights.items() if a in liquid)


def allocate_paise(total_paise: int, weights: dict[str, float]) -> dict[str, int]:
    """Split an integer paise total across weights with NO rounding residual.

    Rounding each ``weight * total`` independently leaves a residual of a few
    paise, so ``sum(positions) != total`` and the reconciliation assertion
    fails. This uses the largest-remainder method: floor everything, then hand
    the leftover paise to the assets with the largest fractional parts.

    Guarantees ``sum(result.values()) == total_paise`` exactly.
    """
    if not weights:
        return {}
    exact = {a: total_paise * w for a, w in weights.items()}
    floored = {a: int(np.floor(v)) for a, v in exact.items()}
    residual = total_paise - sum(floored.values())

    if residual:
        # largest fractional part first; asset_id breaks ties deterministically
        order = sorted(
            exact, key=lambda a: (-(exact[a] - floored[a]), a)
        )
        step = 1 if residual > 0 else -1
        for a in order[: abs(residual)]:
            floored[a] += step

    assert sum(floored.values()) == total_paise, "paise allocation lost money"
    return floored


def value_to_units(value_paise: int, price_rupees: float) -> float:
    """Units held, from a paise value and a rupee price."""
    if price_rupees <= 0:
        raise ValueError(f"price must be positive, got {price_rupees}")
    return (value_paise / PAISE_PER_RUPEE) / price_rupees

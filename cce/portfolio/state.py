"""Portfolio state construction.

Spec: docs/06-DATA-CONTRACTS.md section 4, FR-020..FR-025.

Money crosses into integer paise HERE and nowhere else. Rupee floats are fine
inside a calculation; they are never persisted or passed across a contract
boundary, because floating-point currency accumulates error across a
Rs 100 Cr book.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..contracts import (
    PAISE_PER_CRORE, MarketData, PortfolioState, Position, Universe,
)
from .calculations import allocate_paise, portfolio_returns, value_to_units

logger = logging.getLogger(__name__)

__all__ = [
    "DEFAULT_CAPITAL_PAISE", "build_portfolio_state", "rebalance_to",
    "normalise_weights",
]

# Rs 100 Cr. Large enough to make institutional liquidity and transaction
# constraints meaningful, small enough to visualise (master spec section 7.1).
DEFAULT_CAPITAL_PAISE = int(100 * PAISE_PER_CRORE)


def normalise_weights(
    weights: dict[str, float], universe: Universe, tolerance: float = 1e-6
) -> dict[str, float]:
    """Validate weights against the universe and fill absent assets with 0.

    Rejects unknown assets rather than dropping them: a silently dropped
    weight breaks ``sum(w) == 1`` in a way that is hard to trace back.

    Renormalises only within ``tolerance`` — a genuinely wrong vector is an
    error, not something to quietly rescale into looking correct.
    """
    unknown = set(weights) - set(universe.asset_ids)
    if unknown:
        raise KeyError(f"weights contain unknown asset_ids: {sorted(unknown)}")

    if any(w < 0 for w in weights.values()):
        negative = {a: w for a, w in weights.items() if w < 0}
        raise ValueError(f"negative weights are not permitted: {negative}")

    full = {aid: float(weights.get(aid, 0.0)) for aid in universe.asset_ids}
    total = sum(full.values())
    if total <= 0:
        raise ValueError("weights sum to zero")

    if abs(total - 1.0) > tolerance:
        raise ValueError(
            f"weights must sum to 1.0 within {tolerance}, got {total!r}. "
            f"Rescaling a materially wrong vector would hide the error."
        )
    # absorb float dust so the contract's own assertion cannot fail
    if total != 1.0:
        largest = max(full, key=lambda a: full[a])
        full[largest] += 1.0 - total
    return full


def build_portfolio_state(
    universe: Universe,
    weights: dict[str, float],
    market_data: MarketData,
    total_value_paise: int = DEFAULT_CAPITAL_PAISE,
    portfolio_id: str = "DEMO_100CR",
    as_of: datetime | None = None,
) -> PortfolioState:
    """Build a :class:`PortfolioState` from an allocation and a price panel.

    Position values are split with the largest-remainder method so
    ``sum(position.value_paise) == total_value_paise`` EXACTLY. Rounding each
    position independently leaves a residual of a few paise and the
    reconciliation assertion fails.

    ``cash_value_paise`` is the value of CASH-class holdings — a VIEW INTO
    the positions, not a separate pot added to them. Cash is an asset in this
    universe, so adding it again would double-count.
    """
    if total_value_paise <= 0:
        raise ValueError("total_value_paise must be positive")

    w = normalise_weights(weights, universe)
    values = allocate_paise(total_value_paise, w)
    prices = market_data.prices.iloc[-1]

    positions: list[Position] = []
    for asset in universe.assets:
        aid = asset.asset_id
        if aid not in market_data.prices.columns:
            if w[aid] > 0:
                raise KeyError(
                    f"{aid} carries weight {w[aid]:.4f} but has no price in "
                    f"the market panel; it was excluded upstream and cannot "
                    f"be held"
                )
            continue
        price = float(prices[aid])
        positions.append(Position(
            asset_id=aid,
            ticker=asset.ticker,
            asset_class=asset.asset_class,
            sector=asset.sector,
            price=price,
            units=value_to_units(values[aid], price),
            value_paise=values[aid],
            weight=w[aid],
        ))

    held = {p.asset_id for p in positions}
    reconciled = sum(p.value_paise for p in positions)
    if reconciled != total_value_paise:
        raise ValueError(
            f"positions total {reconciled} paise but portfolio is "
            f"{total_value_paise} paise"
        )

    cash_paise = sum(
        p.value_paise for p in positions if p.asset_class == "CASH"
    )

    return PortfolioState(
        portfolio_id=portfolio_id,
        timestamp=as_of or datetime.now(timezone.utc),
        as_of_date=market_data.as_of_date,
        total_value_paise=total_value_paise,
        cash_value_paise=cash_paise,
        positions=tuple(positions),
        weights={a: v for a, v in w.items() if a in held},
        return_series=portfolio_returns(w, market_data.returns),
    )


def rebalance_to(
    state: PortfolioState,
    new_weights: dict[str, float],
    universe: Universe,
    market_data: MarketData,
    transaction_cost_paise: int = 0,
) -> PortfolioState:
    """Produce the state resulting from a SIMULATED rebalance.

    No broker, no orders (FR-120). Transaction cost is deducted from the
    portfolio value, so a rebalance is never free — turnover that buys a
    marginal expected-return gain visibly shrinks the book.

    Returns a NEW state; the input is never mutated.
    """
    if transaction_cost_paise < 0:
        raise ValueError("transaction cost must not be negative")

    new_total = state.total_value_paise - transaction_cost_paise
    if new_total <= 0:
        raise ValueError(
            f"transaction cost {transaction_cost_paise} exceeds portfolio value"
        )

    return build_portfolio_state(
        universe=universe,
        weights=new_weights,
        market_data=market_data,
        total_value_paise=new_total,
        portfolio_id=state.portfolio_id,
    )

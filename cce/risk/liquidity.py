"""Liquidity measures.

Spec: docs/08-FINANCIAL-METHODS.md section 10.2.

Modelled progressively:

  Level 1  minimum liquid share          always available
  Level 2  position / turnover / trade size limits
  Level 3  days to liquidate             ONLY where volume data is reliable

**Honesty rule (master spec section 16):** days-to-liquidate is an ESTIMATE,
never a guarantee of execution. If ``Asset.adv_paise`` is ``None`` the control
is DISABLED for that asset and the UI shows an em dash. CCE falls back to
Levels 1-2 rather than fabricating precision.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..contracts import Universe

__all__ = [
    "DEFAULT_PARTICIPATION_RATE",
    "LiquidityProfile",
    "cash_share",
    "days_to_liquidate",
    "liquid_share",
    "liquidity_summary",
]

# [DEMO-CONFIG] share of a day's traded value we assume we can be
DEFAULT_PARTICIPATION_RATE = 0.20


def liquid_share(weights: dict[str, float], universe: Universe) -> float:
    """Fraction held in instruments flagged liquid."""
    liquid = set(universe.liquid_ids())
    return float(sum(w for a, w in weights.items() if a in liquid))


def cash_share(weights: dict[str, float], universe: Universe) -> float:
    """Fraction held in CASH-class instruments."""
    return float(sum(
        w for a, w in weights.items()
        if universe.get(a).asset_class == "CASH"
    ))


def days_to_liquidate(
    position_value_paise: int,
    adv_paise: int | None,
    participation_rate: float = DEFAULT_PARTICIPATION_RATE,
) -> float | None:
    """``position_value / (participation_rate * ADV)``.

    Returns ``None`` when ADV is unavailable. That DISABLES the control for
    the asset — it does not mean "zero days", and the UI must render it as an
    em dash rather than a number (INV-5, NFR-043).

    An estimate, not a guarantee of execution.
    """
    if adv_paise is None or adv_paise <= 0:
        return None
    if not 0.0 < participation_rate <= 1.0:
        raise ValueError("participation_rate must be in (0, 1]")
    return float(position_value_paise / (participation_rate * adv_paise))


@dataclass(frozen=True)
class LiquidityProfile:
    """Portfolio liquidity, with explicit coverage of the ADV-based tier."""

    liquid_share: float
    cash_share: float
    days_to_liquidate: dict[str, float | None]
    worst_days: float | None
    adv_coverage: float  # fraction of assets with usable volume data

    @property
    def adv_available(self) -> bool:
        return self.adv_coverage > 0.0


def liquidity_summary(
    weights: dict[str, float],
    universe: Universe,
    total_value_paise: int | None = None,
    participation_rate: float = DEFAULT_PARTICIPATION_RATE,
) -> LiquidityProfile:
    """Full liquidity profile.

    ``total_value_paise=None`` SKIPS the ADV-based days-to-liquidate tier
    entirely. It does not substitute a placeholder value: liquidation
    measured against a stand-in portfolio size would be a fabricated number
    wearing a real one's clothes.

    ``adv_coverage`` records how much of the portfolio actually had volume
    data. When it is zero the Level 3 control is simply not evaluated, and
    that fact is visible rather than silently absent.
    """
    days: dict[str, float | None] = {}
    covered = 0.0
    for asset_id, w in weights.items():
        asset = universe.get(asset_id)
        d = (
            None if total_value_paise is None
            else days_to_liquidate(
                round(total_value_paise * w), asset.adv_paise,
                participation_rate,
            )
        )
        days[asset_id] = d
        if d is not None:
            covered += w

    known = [d for d in days.values() if d is not None]
    return LiquidityProfile(
        liquid_share=liquid_share(weights, universe),
        cash_share=cash_share(weights, universe),
        days_to_liquidate=days,
        worst_days=max(known) if known else None,
        adv_coverage=covered,
    )

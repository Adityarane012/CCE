"""Concentration measures.

Spec: docs/08-FINANCIAL-METHODS.md section 10.1.

Four levels, because the first three are gameable:

  asset weight      CONC_ASSET_MAX
  sector weight     CONC_SECTOR_MAX
  asset-class weight CONC_ASSET_CLASS_MAX
  RISK contribution RC_ASSET_MAX / RC_SECTOR_MAX   <- closes the loophole

An optimizer can satisfy every weight cap while concentrating risk. Weight
limits alone are gameable by a sufficiently determined objective function.
"""

from __future__ import annotations

from ..contracts import Universe

__all__ = [
    "max_asset_weight", "max_sector_weight", "max_asset_class_weight",
    "herfindahl_index", "effective_number_of_assets", "concentration_summary",
]


def max_asset_weight(weights: dict[str, float]) -> tuple[str, float]:
    """Largest single-asset weight and which asset holds it."""
    if not weights:
        return ("", 0.0)
    aid = max(weights, key=lambda a: weights[a])
    return (aid, float(weights[aid]))


def _grouped_max(
    weights: dict[str, float], universe: Universe, attr: str
) -> tuple[str, float]:
    groups: dict[str, float] = {}
    for asset_id, w in weights.items():
        key = getattr(universe.get(asset_id), attr)
        groups[key] = groups.get(key, 0.0) + w
    if not groups:
        return ("", 0.0)
    key = max(groups, key=lambda k: groups[k])
    return (key, float(groups[key]))


def max_sector_weight(
    weights: dict[str, float], universe: Universe
) -> tuple[str, float]:
    """Largest sector weight and which sector."""
    return _grouped_max(weights, universe, "sector")


def max_asset_class_weight(
    weights: dict[str, float], universe: Universe
) -> tuple[str, float]:
    """Largest asset-class weight and which class."""
    return _grouped_max(weights, universe, "asset_class")


def herfindahl_index(weights: dict[str, float]) -> float:
    """Sum of squared weights. 1.0 is a single holding; 1/n is equal weight."""
    return float(sum(w * w for w in weights.values()))


def effective_number_of_assets(weights: dict[str, float]) -> float:
    """1 / HHI - how many equally-weighted positions this is equivalent to.

    More intuitive than HHI for a risk manager: "this Rs 100 Cr book behaves
    like 4.2 equal positions" lands better than "HHI 0.238".
    """
    hhi = herfindahl_index(weights)
    return float(1.0 / hhi) if hhi > 0 else 0.0


def concentration_summary(
    weights: dict[str, float], universe: Universe
) -> dict[str, float]:
    """Every concentration figure the control engine evaluates."""
    _, asset_w = max_asset_weight(weights)
    _, sector_w = max_sector_weight(weights, universe)
    _, class_w = max_asset_class_weight(weights, universe)
    return {
        "max_asset_weight": asset_w,
        "max_sector_weight": sector_w,
        "max_asset_class_weight": class_w,
        "herfindahl": herfindahl_index(weights),
        "effective_assets": effective_number_of_assets(weights),
    }

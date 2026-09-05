"""Stress scenario definitions.

Spec: docs/07-RISK-POLICY.md section 7, docs/08-FINANCIAL-METHODS.md section 13.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from ..contracts import Universe

__all__ = ["LIQUIDITY_KEY", "Scenario", "load_scenarios"]

#: Pseudo-sector recognised by the engine: it scales every asset's ADV
#: rather than shocking a price. Not an asset id and not a sector, so it
#: is excluded from the unresolved-key check.
LIQUIDITY_KEY = "LIQUIDITY"


@dataclass(frozen=True)
class Scenario:
    """A stress scenario defining instantaneous shocks."""

    code: str
    label: str
    shocks: dict[str, float]
    is_custom: bool = False

    @classmethod
    def custom(cls, label: str, shocks: dict[str, float]) -> Scenario:
        """Create a custom scenario."""
        return cls(
            code="CUSTOM",
            label=label,
            shocks=dict(shocks),
            is_custom=True,
        )

    def unresolved_keys(self, universe: Universe) -> tuple[str, ...]:
        """Shock keys that match no asset id and no sector in the universe.

        Shocks are resolved by asset id first, then by sector. A key matching
        neither applies to nothing and is silently dropped — so a typo in
        ``config/scenarios.yaml`` (``BANKNIFTY`` where the sector is
        ``BANKING``) produces a scenario that shocks nothing, reports a zero
        loss, and PASSES. That is a false safety signal on the stress gate,
        which is the one gate whose job is to catch what ordinary metrics
        miss (INV-10).

        ``LIQUIDITY`` is a recognised pseudo-sector handled separately by the
        engine, not an asset or a sector, so it is never unresolved.
        """
        known = {a.asset_id for a in universe.assets}
        known |= {a.sector for a in universe.assets}
        known.add(LIQUIDITY_KEY)
        return tuple(sorted(k for k in self.shocks if k not in known))


def load_scenarios(path: str | Path) -> tuple[Scenario, ...]:
    """Load default scenarios from configuration."""
    with open(path, encoding="utf-8") as f:
        doc = yaml.safe_load(f)

    out: list[Scenario] = []
    for s in doc.get("scenarios", []):
        out.append(
            Scenario(
                code=s["code"],
                label=s["label"],
                shocks=dict(s.get("shocks", {})),
                is_custom=False,
            )
        )
    return tuple(out)

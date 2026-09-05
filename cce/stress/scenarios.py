"""Stress scenario definitions.

Spec: docs/07-RISK-POLICY.md section 7, docs/08-FINANCIAL-METHODS.md section 13.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml


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

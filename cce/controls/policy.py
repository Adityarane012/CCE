"""Policy-change control logic.

Spec: docs/07-RISK-POLICY.md section 5, FR-084, INV-8.

Loading a policy from YAML and classifying a value against a threshold
already exist (``cce.config.load_policy`` and ``Threshold.classify``), so
they are NOT duplicated here. What lives here is the control-layer question
those cannot answer: **is a proposed policy change a WEAKENING?**

That matters because a portfolio can be moved from RED to GREEN by editing a
limit rather than by changing the portfolio. The system must be able to say
which happened.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..contracts import Comparator, Policy, Threshold

logger = logging.getLogger(__name__)

__all__ = [
    "ThresholdChange", "PolicyChangePreview", "diff_policies",
    "is_weakening", "MATERIAL_CHANGE",
]

# A relative band change beyond this is "substantial" and triggers the modal
# warning. Below it the change is still versioned and audited, just not
# escalated. [DEMO-CONFIG]
MATERIAL_CHANGE = 0.10


@dataclass(frozen=True)
class ThresholdChange:
    """One threshold moving between policy versions."""

    control_code: str
    label: str
    field: str                 # green_max | amber_max | green_min | amber_min | is_hard
    old_value: float | bool | None
    new_value: float | bool | None
    weakening: bool
    material: bool
    is_hard: bool

    @property
    def message(self) -> str:
        direction = "weakened" if self.weakening else "tightened"
        if self.field == "is_hard":
            return (f"{self.label}: hard control {direction} to "
                    f"{'hard' if self.new_value else 'SOFT'}")
        return (f"{self.label} {self.field}: {self.old_value} -> "
                f"{self.new_value} ({direction})")


@dataclass(frozen=True)
class PolicyChangePreview:
    """What a proposed policy change would do, BEFORE it is applied."""

    changes: tuple[ThresholdChange, ...]
    added: tuple[str, ...] = ()
    removed: tuple[str, ...] = ()

    @property
    def is_weakening(self) -> bool:
        """True if ANY hard control is loosened.

        Removing a control entirely counts: it is the most complete weakening
        available.
        """
        return bool(self.removed) or any(
            c.weakening and c.is_hard for c in self.changes
        )

    @property
    def is_material(self) -> bool:
        """True if a weakening is substantial enough to warrant the modal."""
        return bool(self.removed) or any(
            c.weakening and c.is_hard and c.material for c in self.changes
        )

    @property
    def weakened_controls(self) -> tuple[str, ...]:
        return tuple(sorted(
            {c.control_code for c in self.changes if c.weakening and c.is_hard}
            | set(self.removed)
        ))

    @property
    def summary(self) -> str:
        if not self.changes and not self.added and not self.removed:
            return "no threshold changes"
        parts = [c.message for c in self.changes]
        if self.added:
            parts.append(f"added: {', '.join(self.added)}")
        if self.removed:
            parts.append(f"REMOVED: {', '.join(self.removed)}")
        return "; ".join(parts)


def _field_weakens(comparator: Comparator, field: str,
                   old: float, new: float) -> bool:
    """Is moving this band from old to new a loosening?

    GT controls (volatility, CVaR): raising the band admits more risk.
    LT controls (liquidity, cash):  lowering the band admits more risk.
    """
    if comparator in (Comparator.GT, Comparator.GTE):
        return new > old
    return new < old


def is_weakening(old: Threshold, new: Threshold, field: str) -> bool:
    """Whether one band of one threshold was loosened."""
    if field == "is_hard":
        return bool(old.is_hard) and not bool(new.is_hard)
    o, n = getattr(old, field), getattr(new, field)
    if o is None or n is None:
        return False
    return _field_weakens(old.comparator, field, float(o), float(n))


def diff_policies(old: Policy, new: Policy) -> PolicyChangePreview:
    """Compare two policy versions.

    Used by the settings page to preview a change BEFORE applying it
    (FR-084), and by the audit trail to record what actually moved.
    """
    old_codes = {t.control_code for t in old.thresholds}
    new_codes = {t.control_code for t in new.thresholds}

    changes: list[ThresholdChange] = []
    for code in sorted(old_codes & new_codes):
        o, n = old.threshold(code), new.threshold(code)

        for field in ("green_max", "amber_max", "green_min", "amber_min"):
            ov, nv = getattr(o, field), getattr(n, field)
            if ov is None and nv is None:
                continue
            if ov == nv:
                continue
            weak = is_weakening(o, n, field)
            band = abs(float(ov)) if ov not in (None, 0) else 1.0
            material = abs(float(nv or 0) - float(ov or 0)) / band > MATERIAL_CHANGE
            changes.append(ThresholdChange(
                control_code=code, label=o.label, field=field,
                old_value=ov, new_value=nv, weakening=weak,
                material=material, is_hard=o.is_hard or n.is_hard,
            ))

        if o.is_hard != n.is_hard:
            changes.append(ThresholdChange(
                control_code=code, label=o.label, field="is_hard",
                old_value=o.is_hard, new_value=n.is_hard,
                weakening=is_weakening(o, n, "is_hard"),
                material=True,          # a hard->soft demotion is always material
                is_hard=o.is_hard,
            ))

    preview = PolicyChangePreview(
        changes=tuple(changes),
        added=tuple(sorted(new_codes - old_codes)),
        removed=tuple(sorted(old_codes - new_codes)),
    )
    if preview.is_weakening:
        logger.warning(
            "policy change WEAKENS hard control(s): %s",
            ", ".join(preview.weakened_controls),
        )
    return preview

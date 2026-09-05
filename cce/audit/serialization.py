"""JSON encoding for persisted contracts.

Spec: docs/05-BACKEND-SCHEMA.md section 3.

Every ``*_json`` column in the schema is written and read here, in one place,
so a column and its decoder cannot drift apart.

Two rules govern this module:

- **Lossless.** A :class:`Policy` written by :func:`policy_to_json` and read
  back by :func:`policy_from_json` is equal to the original. An audit record
  that cannot reproduce what it recorded is not an audit record (INV-8).
- **``None`` survives.** A metric that was not computed is stored as JSON
  ``null`` and read back as ``None``. It is never coerced to ``0.0`` — that
  would turn "not computed" into a false safety signal (INV-5).
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date, datetime
from typing import Any

from cce.contracts import (
    Breach,
    Comparator,
    Constraints,
    ModelParams,
    Policy,
    Position,
    RiskState,
    Scope,
    Threshold,
)

__all__ = [
    "breaches_from_json",
    "breaches_to_json",
    "dumps",
    "loads_or_none",
    "policy_from_json",
    "policy_to_json",
    "positions_to_json",
]


def _default(obj: Any) -> Any:
    """Encode the few non-JSON types that reach persistence."""
    if isinstance(obj, datetime | date):
        return obj.isoformat()
    if isinstance(obj, tuple):
        return list(obj)
    raise TypeError(f"cannot serialise {type(obj).__name__} for persistence")


def dumps(obj: Any) -> str:
    """Compact, key-sorted JSON. Sorted so two equal objects hash equal."""
    return json.dumps(obj, default=_default, sort_keys=True, separators=(",", ":"))


def loads_or_none(raw: str | None) -> Any:
    """Decode a nullable JSON column. ``NULL`` stays ``None`` (INV-5)."""
    if raw is None or raw == "":
        return None
    return json.loads(raw)


# --------------------------------------------------------------------------
# Policy
# --------------------------------------------------------------------------

def _threshold_to_dict(t: Threshold) -> dict[str, Any]:
    return {
        "control_code": t.control_code,
        "label": t.label,
        "scope": t.scope.value,
        "comparator": t.comparator.value,
        "is_hard": t.is_hard,
        "green_max": t.green_max,
        "amber_max": t.amber_max,
        "green_min": t.green_min,
        "amber_min": t.amber_min,
    }


def _threshold_from_dict(d: dict[str, Any]) -> Threshold:
    # ``code`` is the key used in config/policy.yaml; ``control_code`` is the
    # contract's field name. Accept both so a policy hand-written in the YAML
    # shape still loads.
    return Threshold(
        control_code=d.get("control_code") or d["code"],
        label=d["label"],
        scope=Scope(d["scope"]),
        comparator=Comparator(d["comparator"]),
        is_hard=bool(d["is_hard"]),
        green_max=d.get("green_max"),
        amber_max=d.get("amber_max"),
        green_min=d.get("green_min"),
        amber_min=d.get("amber_min"),
    )


def policy_to_json(policy: Policy) -> str:
    """Serialise a :class:`Policy` losslessly.

    Per-asset ``min_weights``/``max_weights`` are written out in full rather
    than as the ``*_default`` shorthand used in ``config/policy.yaml``. The
    shorthand needs the universe to expand, and an audit record must be
    readable without reloading the configuration that produced it.
    """
    return dumps(
        {
            "version": policy.version,
            "label": policy.label,
            "stress_loss_limit": policy.stress_loss_limit,
            "recovery_max_turnover": policy.recovery_max_turnover,
            "model": asdict(policy.model),
            "thresholds": [_threshold_to_dict(t) for t in policy.thresholds],
            "constraints": asdict(policy.constraints),
        }
    )


def policy_from_json(raw: str) -> Policy:
    """Rebuild a :class:`Policy` written by :func:`policy_to_json`."""
    d = json.loads(raw)
    c = d.get("constraints") or {}

    constraints = Constraints(
        min_weights={k: float(v) for k, v in (c.get("min_weights") or {}).items()},
        max_weights={k: float(v) for k, v in (c.get("max_weights") or {}).items()},
        sector_max={k: float(v) for k, v in (c.get("sector_max") or {}).items()},
        asset_class_max={
            k: float(v) for k, v in (c.get("asset_class_max") or {}).items()
        },
        min_liquid_share=float(c.get("min_liquid_share", 0.0)),
        min_cash_share=float(c.get("min_cash_share", 0.0)),
        max_turnover=float(c.get("max_turnover", 1.0)),
        max_volatility=c.get("max_volatility"),
        max_cvar=c.get("max_cvar"),
        target_return=c.get("target_return"),
        long_only=bool(c.get("long_only", True)),
        include_txn_cost=bool(c.get("include_txn_cost", True)),
    )

    return Policy(
        version=int(d["version"]),
        label=str(d["label"]),
        thresholds=tuple(_threshold_from_dict(t) for t in d["thresholds"]),
        model=ModelParams(**(d.get("model") or {})),
        constraints=constraints,
        stress_loss_limit=float(d.get("stress_loss_limit", 0.18)),
        recovery_max_turnover=float(d.get("recovery_max_turnover", 0.10)),
    )


# --------------------------------------------------------------------------
# Breaches and positions
# --------------------------------------------------------------------------

def breaches_to_json(breaches: tuple[Breach, ...]) -> str:
    """Serialise breaches. An empty tuple is ``[]``, never ``NULL``."""
    return dumps(
        [
            {
                "control_code": b.control_code,
                "control_label": b.control_label,
                "severity": b.severity.value,
                "is_hard": b.is_hard,
                "observed": b.observed,
                "threshold": b.threshold,
                "comparator": b.comparator.value,
                "scope": b.scope,
                "message": b.message,
            }
            for b in breaches
        ]
    )


def breaches_from_json(raw: str | None) -> tuple[Breach, ...]:
    """Rebuild breaches. A missing column reads as no breaches recorded."""
    rows = loads_or_none(raw) or []
    return tuple(
        Breach(
            control_code=r["control_code"],
            control_label=r["control_label"],
            severity=RiskState(r["severity"]),
            is_hard=bool(r["is_hard"]),
            observed=float(r["observed"]),
            threshold=float(r["threshold"]),
            comparator=Comparator(r["comparator"]),
            scope=r["scope"],
            message=r["message"],
        )
        for r in rows
    )


def positions_to_json(positions: tuple[Position, ...]) -> str:
    """Serialise positions in the column order documented in the schema."""
    return dumps([asdict(p) for p in positions])

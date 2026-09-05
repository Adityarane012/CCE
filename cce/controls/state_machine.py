"""Risk-state classification — the ONE place a risk state is computed.

Spec: docs/07-RISK-POLICY.md, docs/02-ARCHITECTURE.md section 6, INV-11.

No UI file, service, or other engine may classify a risk state. The risk
engine deliberately returns an UNCLASSIFIED snapshot; this module fills it in.

Aggregation is **most severe wins**. There is no averaging and no "mostly
green": a control that can be outvoted is not a control.

Two things that are easy to get wrong and are therefore explicit here:

1. **A control that cannot be EVALUATED does not pass.** If CVaR is ``None``
   because there was too little data, ``RISK_CVAR_95`` is not GREEN — it is
   unevaluated, and an unevaluated HARD control makes the whole result
   ``NOT_VALIDATED`` rather than ``PASSED``. Absence of evidence is not
   evidence of safety.
2. **Scoped controls evaluate every member.** ``CONC_SECTOR_MAX`` is checked
   against each sector, not against some aggregate, and produces one breach
   per breaching sector.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..contracts import (
    Breach,
    BreakerCategory,
    Comparator,
    Policy,
    RiskSnapshot,
    RiskState,
    Scope,
    Threshold,
    Universe,
)
from ..contracts.policy import BAND_TOLERANCE

logger = logging.getLogger(__name__)

# Alias for concise use in comparisons. Absorbs floating-point noise when
# comparing held weight against per-class caps that are not expressed as
# Threshold objects and therefore do not go through Threshold.classify().
_TOL = BAND_TOLERANCE

__all__ = [
    "CONTROL_CATEGORY",
    "PORTFOLIO_METRIC",
    "ClassificationResult",
    "aggregate_state",
    "classify",
]

# control_code -> which breaker category a RED breach falls under
CONTROL_CATEGORY: dict[str, BreakerCategory] = {
    "RISK_VOL_ANNUAL": BreakerCategory.RISK,
    "RISK_VAR_95": BreakerCategory.RISK,
    "RISK_CVAR_95": BreakerCategory.RISK,
    "RISK_DRAWDOWN_CURRENT": BreakerCategory.RISK,
    "RISK_DRAWDOWN_MAX": BreakerCategory.RISK,
    "RC_ASSET_MAX": BreakerCategory.RISK,
    "RC_SECTOR_MAX": BreakerCategory.RISK,
    "CONC_ASSET_MAX": BreakerCategory.CONSTRAINT,
    "CONC_SECTOR_MAX": BreakerCategory.CONSTRAINT,
    "CONC_ASSET_CLASS_MAX": BreakerCategory.CONSTRAINT,
    "LIQ_MIN_SHARE": BreakerCategory.CONSTRAINT,
    "LIQ_MIN_CASH": BreakerCategory.CONSTRAINT,
    "LIQ_DAYS_TO_LIQUIDATE": BreakerCategory.CONSTRAINT,
    "TXN_TURNOVER_MAX": BreakerCategory.CONSTRAINT,
    "TXN_COST_MAX": BreakerCategory.CONSTRAINT,
    "DATA_FRESHNESS": BreakerCategory.DATA,
    "DATA_COMPLETENESS": BreakerCategory.DATA,
    "MODEL_SOLVER": BreakerCategory.MODEL,
    "MODEL_COVARIANCE": BreakerCategory.MODEL,
    "STRESS_LOSS_MAX": BreakerCategory.STRESS,
}

# Portfolio-scoped controls read one field off the snapshot.
PORTFOLIO_METRIC: dict[str, str] = {
    "RISK_VOL_ANNUAL": "ewma_volatility",       # the RESPONSIVE estimator
    "RISK_VAR_95": "var_95",
    "RISK_CVAR_95": "cvar_95",
    "RISK_DRAWDOWN_CURRENT": "current_drawdown",
    "RISK_DRAWDOWN_MAX": "max_drawdown",
    "LIQ_MIN_SHARE": "liquidity_ratio",
    "TXN_TURNOVER_MAX": "turnover_from_current",
}


@dataclass(frozen=True)
class ClassificationResult:
    """Every control's verdict, plus the aggregate."""

    state: RiskState
    breaches: tuple[Breach, ...]
    unevaluated: tuple[str, ...] = ()
    unevaluated_hard: tuple[str, ...] = ()
    evaluated: tuple[str, ...] = ()

    @property
    def hard_breaches(self) -> tuple[Breach, ...]:
        return tuple(b for b in self.breaches if b.trips_breaker)

    @property
    def warnings(self) -> tuple[Breach, ...]:
        return tuple(b for b in self.breaches if b.severity is RiskState.AMBER)

    @property
    def breaker_category(self) -> BreakerCategory | None:
        """Category of the first hard breach, for the breaker."""
        for b in self.hard_breaches:
            cat = CONTROL_CATEGORY.get(b.control_code)
            if cat is not None:
                return cat
        return None

    @property
    def fully_evaluated(self) -> bool:
        """False when a HARD control could not be evaluated.

        A caller must then report NOT_VALIDATED rather than PASSED.
        """
        return not self.unevaluated_hard


def aggregate_state(states: list[RiskState]) -> RiskState:
    """Most severe wins. No averaging (docs/07 section 1)."""
    if not states:
        return RiskState.GREEN
    return max(states, key=lambda s: s.severity)


def _breach(
    t: Threshold, value: float, state: RiskState, scope: str, label_suffix: str = ""
) -> Breach:
    # The limit that was ACTUALLY crossed. An AMBER breach crossed the green
    # edge; reporting amber_max would print "26% exceeds the AMBER limit of
    # 35%", which is false and is what the UI shows beside the observed value.
    limit = t.crossed_threshold(state)
    direction = "exceeds" if t.comparator in (Comparator.GT, Comparator.GTE) else "is below"
    pretty = f"{value:.2%}" if abs(value) < 100 else f"{value:,.2f}"
    limit_pretty = f"{limit:.2%}" if abs(limit) < 100 else f"{limit:,.2f}"
    where = f" ({scope})" if scope != Scope.PORTFOLIO.value else ""
    return Breach(
        control_code=t.control_code,
        control_label=t.label + label_suffix,
        severity=state,
        is_hard=t.is_hard,
        observed=float(value),
        threshold=float(limit),
        comparator=t.comparator,
        scope=scope,
        message=(
            f"{t.label}{where} {pretty} {direction} the "
            f"{'RED' if state is RiskState.RED else 'GREEN'} limit of "
            f"{limit_pretty}"
        ),
    )


def _evaluate(
    t: Threshold, items: dict[str, float]
) -> tuple[list[Breach], list[RiskState]]:
    """Classify one control across every item in its scope."""
    breaches: list[Breach] = []
    states: list[RiskState] = []
    for scope, value in items.items():
        state = t.classify(value)
        states.append(state)
        if state is not RiskState.GREEN:
            breaches.append(_breach(t, value, state, scope))
    return breaches, states


def classify(
    snapshot: RiskSnapshot,
    weights: dict[str, float],
    universe: Universe,
    policy: Policy,
    *,
    transaction_cost_ratio: float | None = None,
    worst_stress_loss: float | None = None,
    solver_ok: bool | None = None,
    covariance_repaired: bool = False,
    covariance_note: str | None = None,
    data_staleness_days: float | None = None,
    data_completeness: float | None = None,
) -> ClassificationResult:
    """Classify every configured control and aggregate to a portfolio state.

    Keyword inputs are the controls that cannot be read off a
    :class:`RiskSnapshot` — they come from the optimizer result, the stress
    engine, the covariance report and the validation report. They are passed
    as VALUES, not as objects, so this module never needs to import the
    packages that produced them (INV-2).

    Any control whose metric is ``None`` is recorded as unevaluated rather
    than silently classified GREEN.
    """
    breaches: list[Breach] = []
    states: list[RiskState] = []
    unevaluated: list[str] = []
    unevaluated_hard: list[str] = []
    evaluated: list[str] = []

    sector_weights = _grouped(weights, universe, "sector")
    class_weights = _grouped(weights, universe, "asset_class")

    for t in policy.thresholds:
        items = _items_for(
            t, snapshot, weights, sector_weights, class_weights,
            transaction_cost_ratio, worst_stress_loss,
            data_staleness_days, data_completeness,
        )
        if items is None:
            unevaluated.append(t.control_code)
            if t.is_hard:
                unevaluated_hard.append(t.control_code)
            logger.info(
                "control %s not evaluated: metric unavailable", t.control_code
            )
            continue

        evaluated.append(t.control_code)
        b, s = _evaluate(t, items)
        breaches.extend(b)
        states.extend(s)

    # ---- constraint controls: per-item caps a single Threshold cannot express
    class_breaches = _asset_class_controls(policy, class_weights)
    breaches.extend(class_breaches)
    states.extend(b.severity for b in class_breaches)
    if class_breaches or policy.constraints.asset_class_max:
        evaluated.append("CONC_ASSET_CLASS_MAX")

    # ---- status controls: no numeric band, evaluated as pass/fail ----------
    status_breaches = _status_controls(
        policy, solver_ok, covariance_repaired, covariance_note
    )
    breaches.extend(status_breaches)
    states.extend(b.severity for b in status_breaches)

    return ClassificationResult(
        state=aggregate_state(states),
        breaches=tuple(breaches),
        unevaluated=tuple(unevaluated),
        unevaluated_hard=tuple(unevaluated_hard),
        evaluated=tuple(evaluated),
    )


def _grouped(
    weights: dict[str, float], universe: Universe, attr: str
) -> dict[str, float]:
    out: dict[str, float] = {}
    for asset_id, w in weights.items():
        key = getattr(universe.get(asset_id), attr)
        out[key] = out.get(key, 0.0) + w
    return out


def _items_for(
    t: Threshold,
    snapshot: RiskSnapshot,
    weights: dict[str, float],
    sector_weights: dict[str, float],
    class_weights: dict[str, float],
    txn_ratio: float | None,
    stress_loss: float | None,
    staleness: float | None,
    completeness: float | None,
) -> dict[str, float] | None:
    """The values this control applies to, or None if it cannot be evaluated."""
    code = t.control_code

    if code in PORTFOLIO_METRIC:
        value = getattr(snapshot, PORTFOLIO_METRIC[code])
        return None if value is None else {Scope.PORTFOLIO.value: value}

    if code == "CONC_ASSET_MAX":
        return dict(weights)
    if code == "CONC_SECTOR_MAX":
        return dict(sector_weights)
    if code == "CONC_ASSET_CLASS_MAX":
        return dict(class_weights)
    if code == "RC_ASSET_MAX":
        return dict(snapshot.risk_contribution) or None
    if code == "RC_SECTOR_MAX":
        return dict(snapshot.sector_risk_contribution) or None

    if code == "LIQ_MIN_CASH":
        cash = snapshot.concentration.get("cash_share")
        return None if cash is None else {Scope.PORTFOLIO.value: cash}
    if code == "TXN_COST_MAX":
        return None if txn_ratio is None else {Scope.PORTFOLIO.value: txn_ratio}
    if code == "STRESS_LOSS_MAX":
        return None if stress_loss is None else {Scope.PORTFOLIO.value: stress_loss}
    if code == "DATA_FRESHNESS":
        return None if staleness is None else {Scope.PORTFOLIO.value: staleness}
    if code == "DATA_COMPLETENESS":
        return None if completeness is None else {Scope.PORTFOLIO.value: completeness}

    logger.warning("no metric mapping for control %s; not evaluated", code)
    return None


def _asset_class_controls(
    policy: Policy, class_weights: dict[str, float]
) -> list[Breach]:
    """Per-asset-class exposure caps — ``CONC_ASSET_CLASS_MAX``.

    Not expressible as a ``Threshold``: that model applies ONE band to every
    item in scope, while class caps differ per class (EQUITY 75%,
    COMMODITY 25%). So the cap is read straight off
    ``policy.constraints.asset_class_max``, the same values the optimizer is
    given.

    **This is HARD.** The docs originally marked it soft, which left a real
    hole: the optimizer *enforced* the cap but nothing *checked* it, so a
    candidate arriving any other way — a controlled override, a recovery
    allocation, a hand-built weight vector — could sit at 90% equity against
    a 75% cap and never be flagged.

    A candidate that violates a constraint the optimizer was given did not
    come from the optimizer. That must block, not warn.
    """
    caps = policy.constraints.asset_class_max
    if not caps:
        return []

    out: list[Breach] = []
    for asset_class, cap in caps.items():
        held = class_weights.get(asset_class, 0.0)
        if held > cap + _TOL:
            out.append(Breach(
                control_code="CONC_ASSET_CLASS_MAX",
                control_label="Asset-class exposure",
                severity=RiskState.RED, is_hard=True,
                observed=float(held), threshold=float(cap),
                comparator=Comparator.GT, scope=asset_class,
                message=(
                    f"Asset-class exposure ({asset_class}) {held:.2%} exceeds "
                    f"the cap of {cap:.2%}"
                ),
            ))
    return out


def _status_controls(
    policy: Policy,
    solver_ok: bool | None,
    covariance_repaired: bool,
    covariance_note: str | None,
) -> list[Breach]:
    """MODEL_SOLVER and MODEL_COVARIANCE — hard controls with no numeric band.

    Deliberately absent from ``config/policy.yaml`` (it has no way to express
    a pass/fail check), so they are evaluated here.
    """
    out: list[Breach] = []

    if solver_ok is False:
        out.append(Breach(
            control_code="MODEL_SOLVER", control_label="Optimizer feasibility",
            severity=RiskState.RED, is_hard=True, observed=0.0, threshold=1.0,
            comparator=Comparator.LT, scope=Scope.PORTFOLIO.value,
            message=("Optimizer did not return a usable solution; no "
                     "allocation may be adopted from a failed solve"),
        ))

    if covariance_repaired:
        out.append(Breach(
            control_code="MODEL_COVARIANCE", control_label="Covariance validity",
            severity=RiskState.AMBER, is_hard=True, observed=1.0, threshold=0.0,
            comparator=Comparator.GT, scope=Scope.PORTFOLIO.value,
            message=(covariance_note
                     or "covariance matrix required numerical repair"),
        ))

    return out

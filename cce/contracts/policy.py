"""Risk policy contracts.

Spec: docs/06-DATA-CONTRACTS.md section 8, docs/07-RISK-POLICY.md section 4.

Threshold semantics (docs/07 section 4):

    GT  uses green_max / amber_max   breach when the value EXCEEDS the band
    LT  uses green_min / amber_min   breach when the value falls BELOW it

A boundary value belongs to the LESS SEVERE band: ``v == green_max`` is GREEN.
Off-by-one at a risk threshold is the classic embarrassing bug, so both
directions and both boundaries are tested explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .enums import Comparator, RiskState, Scope
from .optimization import Constraints

__all__ = ["BAND_TOLERANCE", "ModelParams", "Policy", "Threshold"]

# Absorbs floating-point representation error at a band edge. A solver that
# satisfies `x <= 0.25` exactly may return 0.2500000001; that must not flip a
# control from AMBER to RED. Tiny by design: it forgives float noise, never a
# real breach.
BAND_TOLERANCE = 1e-9


@dataclass(frozen=True)
class Threshold:
    """One configured control band."""

    control_code: str
    label: str
    scope: Scope
    comparator: Comparator
    is_hard: bool
    green_max: float | None = None
    amber_max: float | None = None
    green_min: float | None = None
    amber_min: float | None = None

    def __post_init__(self) -> None:
        if self.comparator in (Comparator.GT, Comparator.GTE):
            if self.green_max is None or self.amber_max is None:
                raise ValueError(
                    f"{self.control_code}: GT threshold needs green_max and amber_max"
                )
            if self.green_max > self.amber_max:
                raise ValueError(
                    f"{self.control_code}: green_max must be <= amber_max"
                )
        else:
            if self.green_min is None or self.amber_min is None:
                raise ValueError(
                    f"{self.control_code}: LT threshold needs green_min and amber_min"
                )
            if self.amber_min > self.green_min:
                raise ValueError(
                    f"{self.control_code}: amber_min must be <= green_min"
                )

    def classify(self, value: float, tolerance: float = BAND_TOLERANCE) -> RiskState:
        """Classify an observed value. Boundaries fall to the less severe band.

        ``tolerance`` absorbs floating-point noise at a band edge. Without it
        a solver that satisfies ``turnover <= 0.25`` exactly can land on
        0.2500000001 and be classified RED — the constrained optimum failing
        the very policy it was optimised under, decided by the last bit of a
        float. A control must not turn on 1e-9.

        It is deliberately tiny: it forgives representation error, never a
        real breach.
        """
        if self.comparator in (Comparator.GT, Comparator.GTE):
            if value <= self.green_max + tolerance:   # type: ignore[operator]
                return RiskState.GREEN
            if value <= self.amber_max + tolerance:   # type: ignore[operator]
                return RiskState.AMBER
            return RiskState.RED
        if value >= self.green_min - tolerance:       # type: ignore[operator]
            return RiskState.GREEN
        if value >= self.amber_min - tolerance:       # type: ignore[operator]
            return RiskState.AMBER
        return RiskState.RED

    def crossed_threshold(self, state: RiskState) -> float:
        """The limit that was actually crossed to reach ``state``.

        An AMBER breach crossed the GREEN band edge, not the amber one.
        Reporting ``amber_max`` for an AMBER breach produces messages like
        "26% exceeds the AMBER limit of 35%", which is not merely confusing —
        it is false, and it is the number the UI shows beside the observed
        value.
        """
        gt = self.comparator in (Comparator.GT, Comparator.GTE)
        if state is RiskState.AMBER:
            return float(self.green_max if gt else self.green_min)  # type: ignore[arg-type]
        if state is RiskState.RED:
            return float(self.amber_max if gt else self.amber_min)  # type: ignore[arg-type]
        return float(self.green_max if gt else self.green_min)      # type: ignore[arg-type]

    def red_threshold(self) -> float:
        """The value at which this control turns RED."""
        if self.comparator in (Comparator.GT, Comparator.GTE):
            return float(self.amber_max)     # type: ignore[arg-type]
        return float(self.amber_min)         # type: ignore[arg-type]


@dataclass(frozen=True)
class ModelParams:
    """Estimator parameters. All configurable, all documented."""

    ewma_lambda: float = 0.94
    var_confidence: float = 0.95
    trading_days_per_year: int = 252
    risk_free_rate: float = 0.065
    min_return_observations: int = 250
    monte_carlo_paths: int = 10_000
    random_seed: int = 42
    ewma_seed_window: int = 60

    def __post_init__(self) -> None:
        if not 0.0 < self.ewma_lambda < 1.0:
            raise ValueError("ewma_lambda must be in (0, 1)")
        if not 0.5 < self.var_confidence < 1.0:
            raise ValueError("var_confidence must be in (0.5, 1)")


@dataclass(frozen=True)
class Policy:
    """A versioned set of thresholds, constraints and model parameters.

    Never edited in place. A change inserts a new version (INV-8).
    """

    version: int
    label: str
    thresholds: tuple[Threshold, ...]
    model: ModelParams
    constraints: Constraints
    stress_loss_limit: float = 0.18

    def __post_init__(self) -> None:
        codes = [t.control_code for t in self.thresholds]
        if len(codes) != len(set(codes)):
            raise ValueError("duplicate control_code in policy")

    def threshold(self, control_code: str) -> Threshold:
        for t in self.thresholds:
            if t.control_code == control_code:
                return t
        raise KeyError(f"no threshold configured for {control_code}")

    def has(self, control_code: str) -> bool:
        return any(t.control_code == control_code for t in self.thresholds)

    @property
    def hard_codes(self) -> tuple[str, ...]:
        return tuple(t.control_code for t in self.thresholds if t.is_hard)

    # Convenience passthroughs used across the engines.
    @property
    def ewma_lambda(self) -> float:
        return self.model.ewma_lambda

    @property
    def var_confidence(self) -> float:
        return self.model.var_confidence

    @property
    def trading_days_per_year(self) -> int:
        return self.model.trading_days_per_year

    @property
    def risk_free_rate(self) -> float:
        return self.model.risk_free_rate

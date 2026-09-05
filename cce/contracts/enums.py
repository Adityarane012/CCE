"""Enumerations shared across every CCE module.

All are ``str`` enums so they serialise straight to JSON and compare cleanly
against values read back from SQLite CHECK-constrained columns.

Spec: docs/06-DATA-CONTRACTS.md section 2.
"""

from __future__ import annotations

from enum import Enum

__all__ = [
    "Actor",
    "BreakerCategory",
    "CandidateRole",
    "Comparator",
    "ControlStatus",
    "DataProvider",
    "ExpectedReturnMethod",
    "HumanAction",
    "PortfolioOrigin",
    "RiskState",
    "Scope",
    "SolverStatus",
    "Strategy",
    "StressStatus",
    "TriggerType",
    "VaRMethod",
    "ValidationStatus",
]


class RiskState(str, Enum):
    """Traffic-light state of a single control, or of the whole portfolio.

    Portfolio state is the MOST SEVERE individual control state. There is no
    averaging and no "mostly green" — a control that can be outvoted is not a
    control (docs/07-RISK-POLICY.md section 1).
    """

    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"

    @property
    def severity(self) -> int:
        """Ordinal severity, for ``max()`` aggregation. GREEN=0, RED=2."""
        return {"GREEN": 0, "AMBER": 1, "RED": 2}[self.value]


class ControlStatus(str, Enum):
    """Verdict of the independent control engine on a candidate."""

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_VALIDATED = "NOT_VALIDATED"  # validation could not complete


class StressStatus(str, Enum):
    """Outcome of stress validation.

    ``NOT_RUN`` and ``ERROR`` are NEVER equivalent to ``PASSED``. Absence of
    evidence is not evidence of safety (INV-10).
    """

    PASSED = "PASSED"
    FAILED = "FAILED"
    NOT_RUN = "NOT_RUN"
    ERROR = "ERROR"


class SolverStatus(str, Enum):
    """Optimizer solver outcome."""

    OPTIMAL = "OPTIMAL"
    OPTIMAL_INACCURATE = "OPTIMAL_INACCURATE"
    INFEASIBLE = "INFEASIBLE"
    UNBOUNDED = "UNBOUNDED"
    SOLVER_ERROR = "SOLVER_ERROR"

    @property
    def usable(self) -> bool:
        """Only OPTIMAL permits weights to leave the optimizer (INV-2).

        ``OPTIMAL_INACCURATE`` is deliberately excluded: a near-solution to a
        risk-constrained problem may violate the constraints.
        """
        return self is SolverStatus.OPTIMAL


class Strategy(str, Enum):
    """Optimization strategy. MAX_SHARPE is the default (FR-050)."""

    MAX_SHARPE = "MAX_SHARPE"
    MIN_VOLATILITY = "MIN_VOLATILITY"
    TARGET_RETURN = "TARGET_RETURN"
    CVAR_MIN = "CVAR_MIN"
    HRP = "HRP"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"


class ExpectedReturnMethod(str, Enum):
    """How expected returns were estimated.

    Whatever the method, the result is displayed as a "Model Estimate"
    (FR-062) — never as a fact.
    """

    HISTORICAL = "HISTORICAL"
    EWMA = "EWMA"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"


class VaRMethod(str, Enum):
    """VaR estimation method. HISTORICAL is primary; PARAMETRIC is for
    comparison, not authority (docs/08-FINANCIAL-METHODS.md section 7.2)."""

    HISTORICAL = "HISTORICAL"
    PARAMETRIC = "PARAMETRIC"
    MONTE_CARLO = "MONTE_CARLO"


class CandidateRole(str, Enum):
    """What a candidate allocation represents.

    CURRENT, OPTIMAL_UNCONSTRAINED and SAFE_CONSTRAINED are three distinct
    things and are never merged in the UI (INV-9).
    """

    CURRENT = "CURRENT"
    OPTIMAL_UNCONSTRAINED = "OPTIMAL_UNCONSTRAINED"  # for Safe vs Optimal
    SAFE_CONSTRAINED = "SAFE_CONSTRAINED"
    RECOVERY_MAX_SHARPE = "RECOVERY_MAX_SHARPE"
    RECOVERY_MIN_RISK = "RECOVERY_MIN_RISK"
    RECOVERY_DEFENSIVE = "RECOVERY_DEFENSIVE"
    ALTERNATIVE = "ALTERNATIVE"

    @property
    def is_recovery(self) -> bool:
        return self.value.startswith("RECOVERY_")


class HumanAction(str, Enum):
    """The four actions a risk manager may take (FR-115)."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"
    KEEP_CURRENT = "KEEP_CURRENT"
    OVERRIDE = "OVERRIDE"


class TriggerType(str, Enum):
    """What caused a decision cycle to start."""

    USER_REQUEST = "USER_REQUEST"
    SCHEDULED = "SCHEDULED"
    RISK_DETERIORATION = "RISK_DETERIORATION"
    STRESS_SCENARIO = "STRESS_SCENARIO"
    DATA_INTEGRITY = "DATA_INTEGRITY"
    MANUAL_REVIEW = "MANUAL_REVIEW"


class BreakerCategory(str, Enum):
    """Why the circuit breaker tripped (docs/07-RISK-POLICY.md section 6)."""

    RISK = "RISK"
    CONSTRAINT = "CONSTRAINT"
    DATA = "DATA"
    MODEL = "MODEL"
    STRESS = "STRESS"


class Actor(str, Enum):
    """Who acted, for the Decision Replay timeline.

    The three-way distinction is the entire point of the replay page.
    """

    MACHINE = "MACHINE"  # system computation
    CONTROL = "CONTROL"  # control-engine judgement
    HUMAN = "HUMAN"


class DataProvider(str, Enum):
    """Which provider produced a market snapshot.

    CACHED_FALLBACK means live retrieval failed; it MUST be surfaced in the UI.
    """

    JUGAAD = "JUGAAD"
    CACHED = "CACHED"
    CACHED_FALLBACK = "CACHED_FALLBACK"


class ValidationStatus(str, Enum):
    """Data validation outcome.

    INVALID data MUST NOT be used for risk computation (INV-5). DEGRADED data
    may be used but must be visibly labelled (NFR-043).
    """

    VALID = "VALID"
    DEGRADED = "DEGRADED"
    INVALID = "INVALID"


class Comparator(str, Enum):
    """Direction in which a threshold is breached.

    GT: breach when the observed value EXCEEDS the band (volatility, CVaR).
    LT: breach when it falls BELOW the band (liquidity, cash).

    Getting this backwards silently inverts a safety control, so both
    directions are tested explicitly.
    """

    GT = "GT"
    GTE = "GTE"
    LT = "LT"
    LTE = "LTE"


class Scope(str, Enum):
    """What a control applies to."""

    PORTFOLIO = "PORTFOLIO"
    ASSET = "ASSET"
    SECTOR = "SECTOR"


class PortfolioOrigin(str, Enum):
    """How a portfolio state came to exist."""

    SEED = "SEED"
    SIMULATED_REBALANCE = "SIMULATED_REBALANCE"
    MANUAL = "MANUAL"

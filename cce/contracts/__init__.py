"""Typed contracts — the seams between CCE modules.

Pure data. No I/O, no business logic, no imports from anywhere else in ``cce``
(docs/02-ARCHITECTURE.md section 2, enforced by tests/test_architecture.py).

Modules communicate through these objects, never through bare dicts. A dict
crossing a module boundary makes the seam untypeable and lets fields drift
silently (NFR-021).
"""

from __future__ import annotations

from .control import Alert, Candidate, ControlResult, StressResult
from .decision import (
    DecisionEvent,
    DecisionRecord,
    Explanation,
    HumanActionRecord,
    NarratedExplanation,
    SafeAllocation,
)
from .enums import (
    Actor,
    BreakerCategory,
    CandidateRole,
    Comparator,
    ControlStatus,
    DataProvider,
    ExpectedReturnMethod,
    HumanAction,
    PortfolioOrigin,
    RiskState,
    Scope,
    SolverStatus,
    Strategy,
    StressStatus,
    TriggerType,
    ValidationStatus,
    VaRMethod,
)
from .market import (
    Asset,
    MarketData,
    Universe,
    ValidationFinding,
    ValidationReport,
)
from .optimization import Constraints, OptimizationResult
from .policy import ModelParams, Policy, Threshold
from .portfolio import (
    PAISE_PER_CRORE,
    PAISE_PER_RUPEE,
    WEIGHT_TOLERANCE,
    PortfolioState,
    Position,
)
from .risk import Breach, RiskChange, RiskSnapshot

__all__ = [
    # enums
    "Actor", "BreakerCategory", "CandidateRole", "Comparator", "ControlStatus",
    "DataProvider", "ExpectedReturnMethod", "HumanAction", "PortfolioOrigin",
    "RiskState", "Scope", "SolverStatus", "Strategy", "StressStatus",
    "TriggerType", "ValidationStatus", "VaRMethod",
    # market
    "Asset", "Universe", "MarketData", "ValidationFinding", "ValidationReport",
    # portfolio
    "Position", "PortfolioState", "WEIGHT_TOLERANCE", "PAISE_PER_RUPEE",
    "PAISE_PER_CRORE",
    # risk
    "Breach", "RiskSnapshot", "RiskChange",
    # optimization / control
    "Constraints", "OptimizationResult", "ControlResult", "StressResult",
    "Candidate", "Alert",
    # policy
    "Threshold", "ModelParams", "Policy",
    # decision
    "Explanation", "NarratedExplanation", "HumanActionRecord", "DecisionEvent",
    "SafeAllocation", "DecisionRecord",
]

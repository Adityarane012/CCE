"""Typed contracts — the seams between CCE modules.

Pure data. No I/O, no business logic, no imports from anywhere else in ``cce``
(docs/02-ARCHITECTURE.md section 2, enforced by tests/test_architecture.py).

Modules communicate through these objects, never through bare dicts. A dict
crossing a module boundary makes the seam untypeable and lets fields drift
silently (NFR-021).
"""

from __future__ import annotations

from .backtest import BacktestConfig, StrategyMetrics
from .control import (
    LIQUIDITY_KEY,
    Alert,
    Candidate,
    ControlResult,
    Scenario,
    StressResult,
)
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
from .optimization import Constraints, OptimizationResult, View
from .policy import ModelParams, Policy, Threshold
from .portfolio import (
    PAISE_PER_CRORE,
    PAISE_PER_RUPEE,
    WEIGHT_TOLERANCE,
    PortfolioState,
    Position,
)
from .risk import (
    Breach,
    ChangeAttribution,
    ChangeDriver,
    RiskChange,
    RiskSnapshot,
)

__all__ = [  # noqa: RUF022 - grouped by contract family, not alphabetically
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
    "Breach", "RiskSnapshot", "RiskChange", "ChangeAttribution", "ChangeDriver",
    # optimization / control
    "Constraints", "OptimizationResult", "ControlResult", "StressResult", "View",
    "Candidate", "Alert", "Scenario", "LIQUIDITY_KEY",
    # policy
    "Threshold", "ModelParams", "Policy",
    # decision
    "Explanation", "NarratedExplanation", "HumanActionRecord", "DecisionEvent",
    "SafeAllocation", "DecisionRecord",
    # backtest
    "BacktestConfig", "StrategyMetrics",
]

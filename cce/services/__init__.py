"""The service layer — the only API the UI may call.

Spec: docs/02-ARCHITECTURE.md section 2, docs/06-DATA-CONTRACTS.md section 9.

This is L4: the only layer that touches both the engines and the repository.
Phases 5-7 built the control, breaker and stress engines as pure functions
that construct ``Alert`` and ``DecisionEvent`` objects and write nothing; this
layer is where those objects are persisted. If something in ``cce/controls/``
or ``cce/stress/`` ever wants to import ``cce.audit``, the work belongs here.

Three guarantees the UI inherits by having no other way in:

1. :meth:`OptimizationService.propose` always runs optimize -> independently
   validate -> stress as ONE unit. No public callable optimizes without
   validating, so the control engine cannot be skipped by accident.
2. :meth:`ApprovalService.approve` re-checks ``eligible_for_approval``
   server-side and re-validates against CURRENT market data. A disabled
   button is convenience, not enforcement (INV-2, EC-7.1).
3. Every state-changing method writes its audit record inside the same
   transaction as the change (INV-6, EC-7.3).
"""

from __future__ import annotations

from .approval_service import STALE_MESSAGE, ApprovalService
from .backtest_service import BacktestService
from .context import ServiceContext
from .optimization_service import DecisionCycle, OptimizationService
from .policy_service import PolicyService
from .portfolio_service import PortfolioService
from .replay_service import ReplayService
from .risk_service import RiskService
from .stress_service import StressService

__all__ = [
    "STALE_MESSAGE",
    "ApprovalService",
    "BacktestService",
    "DecisionCycle",
    "OptimizationService",
    "PolicyService",
    "PortfolioService",
    "ReplayService",
    "RiskService",
    "ServiceContext",
    "StressService",
]

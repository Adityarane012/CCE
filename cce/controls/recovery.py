"""Recovery candidate generation.

Spec: docs/02-ARCHITECTURE.md section 7, docs/IMPLEMENTATION-PLAN.md Phase 6.
"""

from __future__ import annotations

import logging

from ..contracts import (
    Candidate,
    CandidateRole,
    MarketData,
    OptimizationResult,
    Policy,
    Universe,
)
from .validation import validate

logger = logging.getLogger(__name__)

__all__ = ["generate_recovery_candidates"]


def generate_recovery_candidates(
    optimizations: dict[CandidateRole, OptimizationResult],
    universe: Universe,
    market_data: MarketData,
    current_weights: dict[str, float],
    policy: Policy,
    *,
    total_value_paise: int = 0,
) -> tuple[Candidate, ...]:
    """Generate independently validated recovery candidates.

    The service layer runs the optimizers and provides the results to avoid
    ``cce/controls/`` importing ``cce/optimizer/`` (INV-2). This module
    constructs the Candidate objects and independently re-derives their risk.

    A recovery that fails validation is STILL RETURNED with its failure reasons
    (EC-5.1). It is never dropped silently, nor marked approvable.
    """
    candidates = []

    for role in (
        CandidateRole.RECOVERY_MAX_SHARPE,
        CandidateRole.RECOVERY_MIN_RISK,
        CandidateRole.RECOVERY_DEFENSIVE,
    ):
        opt = optimizations.get(role)
        if opt is None:
            continue

        weights = opt.weights or {}
        solver_ok = opt.solver_status.usable

        control = validate(
            weights,
            universe,
            market_data,
            current_weights,
            policy,
            total_value_paise=total_value_paise,
            solver_ok=solver_ok,
        )

        candidates.append(Candidate(
            role=role,
            optimization=opt,
            control=control,
            stress=(),
        ))

    return tuple(candidates)

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
    SafeAllocation,
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
    worst_stress_loss: dict[CandidateRole, float | None] | None = None,
    data_staleness_days: float | None = None,
    data_completeness: float | None = None,
    last_safe_allocation: SafeAllocation | None = None,
) -> tuple[Candidate, ...]:
    """Generate independently validated recovery candidates.

    The service layer runs the optimizers and provides the results to avoid
    ``cce/controls/`` importing ``cce/optimizer/`` (INV-2). This module
    constructs the Candidate objects and independently re-derives their risk.

    A recovery that fails validation is STILL RETURNED with its failure reasons
    (EC-5.1). It is never dropped silently, nor marked approvable.

    ``worst_stress_loss`` is keyed BY ROLE because each candidate holds
    different weights and therefore faces a different worst scenario. It, and
    the two data-quality readings, are measured by the service and passed in:
    this package can no more run the stress engine than it can import the
    optimizer.

    **They are not optional in practice.** ``STRESS_LOSS_MAX``,
    ``DATA_FRESHNESS`` and ``DATA_COMPLETENESS`` are HARD controls, and
    validating without them leaves all three unevaluated — which correctly
    yields NOT_VALIDATED, making every recovery candidate unapprovable. The
    circuit breaker would then trip and offer a risk manager three options,
    none of which could be chosen. They default to ``None`` only so the
    failure is a visible NOT_VALIDATED rather than a TypeError.
    """
    worst_stress_loss = worst_stress_loss or {}
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
            worst_stress_loss=worst_stress_loss.get(role),
            data_staleness_days=data_staleness_days,
            data_completeness=data_completeness,
            last_safe_allocation=last_safe_allocation,
        )

        candidates.append(Candidate(
            role=role,
            optimization=opt,
            control=control,
            stress=(),
        ))

    return tuple(candidates)

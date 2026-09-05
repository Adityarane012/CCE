"""Independent candidate validation — the product's central mechanism.

Spec: docs/02-ARCHITECTURE.md section 5, docs/03-TRD.md FR-070..FR-085,
INV-2, INV-3.

**THIS MODULE MUST NOT IMPORT ``cce.optimizer``.** It is enforced by
``tests/test_architecture.py``, and it is the structural form of the product's
central claim: the component that proposes an allocation cannot be the
component that approves it.

It receives a plain weight vector and RE-DERIVES every metric it needs from
``cce.risk``. It never reads a number the optimizer reported about its own
output.

Why that matters: if the validator trusted ``OptimizationResult.cvar_95``, an
optimizer bug or a numerically optimistic solver would propagate straight
through the safety gate. Independent re-derivation turns an optimizer bug into
a **rejection** — the safe direction to fail.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import pandas as pd

from ..contracts import (
    ControlResult,
    ControlStatus,
    MarketData,
    Policy,
    SafeAllocation,
    Universe,
)
from ..exceptions import CovarianceError
from ..portfolio import transaction_cost_paise
from ..risk import RiskInputs, compute_risk_snapshot
from .state_machine import ClassificationResult, classify

logger = logging.getLogger(__name__)

__all__ = ["validate", "validate_weights"]


def validate(
    candidate_weights: dict[str, float],
    universe: Universe,
    market_data: MarketData,
    current_weights: dict[str, float],
    policy: Policy,
    *,
    total_value_paise: int = 0,
    worst_stress_loss: float | None = None,
    solver_ok: bool | None = None,
    data_staleness_days: float | None = None,
    data_completeness: float | None = None,
    last_safe_allocation: SafeAllocation | None = None,
) -> ControlResult:
    """Re-derive every metric and judge the candidate.

    Note the signature: it takes **weights**, not an ``OptimizationResult``.
    There is deliberately no way to hand this function the optimizer's own
    opinion of its output.

    ``worst_stress_loss`` and ``solver_ok`` are passed as plain values by the
    service layer, so this module never imports the stress engine or the
    optimizer either.

    Returns ``NOT_VALIDATED`` — never ``PASSED`` — when a hard control could
    not be evaluated. Absence of evidence is not evidence of safety.
    """
    now = datetime.now(timezone.utc)

    # ---- re-derive, independently -----------------------------------------
    try:
        snapshot, cov_report = compute_risk_snapshot(RiskInputs(
            weights=candidate_weights,
            universe=universe,
            market_data=market_data,
            risk_free_rate=policy.risk_free_rate,
            ewma_lambda=policy.ewma_lambda,
            var_confidence=policy.var_confidence,
            trading_days=policy.trading_days_per_year,
            min_observations=policy.model.min_return_observations,
            current_weights=current_weights,
            total_value_paise=total_value_paise,
        ))
    except CovarianceError as exc:
        # An unrepairable covariance is a hard MODEL breach, not an outage.
        # Fail toward rejection (INV-4).
        return _model_failure(
            candidate_weights, universe, market_data, current_weights, policy,
            reason=str(exc), now=now, last_safe=last_safe_allocation,
        )
    except ValueError as exc:
        # A malformed weight vector cannot describe a portfolio at all.
        return _model_failure(
            candidate_weights, universe, market_data, current_weights, policy,
            reason=f"candidate is not a valid allocation: {exc}", now=now,
            last_safe=last_safe_allocation,
        )

    txn_ratio = None
    if total_value_paise > 0:
        cost = transaction_cost_paise(
            candidate_weights, current_weights, universe, total_value_paise
        )
        txn_ratio = cost / total_value_paise

    result = classify(
        snapshot=snapshot,
        weights=candidate_weights,
        universe=universe,
        policy=policy,
        transaction_cost_ratio=txn_ratio,
        worst_stress_loss=worst_stress_loss,
        solver_ok=solver_ok,
        covariance_repaired=cov_report.repaired,
        covariance_note=cov_report.message,
        data_staleness_days=data_staleness_days,
        data_completeness=data_completeness,
    )

    return _to_control_result(result, snapshot, now, last_safe_allocation)


def _to_control_result(
    result: ClassificationResult,
    snapshot,
    now: datetime,
    last_safe: SafeAllocation | None,
) -> ControlResult:
    """Turn a classification into a verdict.

    Three outcomes, and the middle one is the easy mistake:

    - hard breach            -> FAILED, breaker active
    - hard control unevaluated -> NOT_VALIDATED, breaker active
    - otherwise              -> PASSED (AMBER warnings do not block)
    """
    hard = result.hard_breaches

    if hard:
        status, passed = ControlStatus.FAILED, False
    elif not result.fully_evaluated:
        logger.warning(
            "hard control(s) could not be evaluated: %s",
            ", ".join(result.unevaluated_hard),
        )
        status, passed = ControlStatus.NOT_VALIDATED, False
    else:
        status, passed = ControlStatus.PASSED, True

    classified = replace_state(snapshot, result)

    return ControlResult(
        status=status,
        passed=passed,
        findings=result.breaches,
        hard_breaches=hard,
        warnings=result.warnings,
        circuit_breaker_active=not passed,
        breaker_category=result.breaker_category,
        recomputed=classified,
        last_safe_allocation=last_safe,
        evaluated_at=now,
    )


def replace_state(snapshot, result: ClassificationResult):
    """Attach the classification to the snapshot.

    The risk engine returns an UNCLASSIFIED snapshot by design (INV-11);
    this is where it acquires a state.
    """
    from dataclasses import replace
    return replace(snapshot, risk_state=result.state, breaches=result.breaches)


def _model_failure(
    candidate_weights: dict[str, float],
    universe: Universe,
    market_data: MarketData,
    current_weights: dict[str, float],
    policy: Policy,
    reason: str,
    now: datetime,
    last_safe: SafeAllocation | None,
) -> ControlResult:
    """A candidate whose risk could not be computed at all.

    Reported as NOT_VALIDATED with a RED MODEL breach — never as PASSED, and
    never as a silent exception the caller might swallow.
    """
    from ..contracts import (
        Breach,
        BreakerCategory,
        Comparator,
        RiskState,
        Scope,
        VaRMethod,
    )
    from ..contracts.risk import RiskSnapshot

    logger.warning("candidate could not be evaluated: %s", reason)
    breach = Breach(
        control_code="MODEL_COVARIANCE", control_label="Model validity",
        severity=RiskState.RED, is_hard=True, observed=0.0, threshold=1.0,
        comparator=Comparator.LT, scope=Scope.PORTFOLIO.value,
        message=f"Candidate could not be evaluated: {reason}",
    )
    empty = RiskSnapshot(
        timestamp=now, as_of_date=market_data.as_of_date,
        historical_volatility=None, ewma_volatility=None,
        portfolio_volatility=None, expected_return=None,
        expected_return_method=None, sharpe=None, var_95=None, cvar_95=None,
        var_method=VaRMethod.HISTORICAL, current_drawdown=None,
        max_drawdown=None, liquidity_ratio=None, turnover_from_current=None,
        risk_state=RiskState.RED, breaches=(breach,),
        degraded=True, degraded_reason=reason,
    )
    return ControlResult(
        status=ControlStatus.NOT_VALIDATED, passed=False, findings=(breach,),
        hard_breaches=(breach,), warnings=(), circuit_breaker_active=True,
        breaker_category=BreakerCategory.MODEL, recomputed=empty,
        last_safe_allocation=last_safe, evaluated_at=now,
    )


def validate_weights(
    candidate_weights: dict[str, float],
    universe: Universe,
    returns: pd.DataFrame,
    current_weights: dict[str, float],
    policy: Policy,
    **kwargs,
) -> ControlResult:
    """Convenience wrapper matching the signature in docs/02 section 5.

    Builds a minimal :class:`MarketData` around a returns frame.
    """
    from datetime import date

    from ..contracts import DataProvider
    from ..contracts import MarketData as MD
    
    prices = (1.0 + returns).cumprod() * 100.0
    
    if len(returns) > 0:
        last = returns.index[-1]
        as_of_date = last if isinstance(last, date) else getattr(last, "date", lambda: date.today())()
    else:
        as_of_date = date.today()

    md = MD(
        prices=prices, returns=returns,
        as_of_date=as_of_date,
        provider=DataProvider.CACHED, universe_hash="", data_hash="",
    )
    return validate(
        candidate_weights, universe, md, current_weights, policy, **kwargs
    )

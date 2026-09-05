"""Circuit breaker and recovery tests.

Spec: docs/IMPLEMENTATION-PLAN.md Phase 6, INV-4, EC-5.1, EC-5.2.
"""

from __future__ import annotations

from datetime import datetime, timezone
import pytest

from cce.contracts import (
    Breach, BreakerCategory, Candidate, CandidateRole, Comparator,
    ControlResult, ControlStatus, OptimizationResult, RiskState, SafeAllocation,
    Scope, SolverStatus, Strategy, ExpectedReturnMethod,
)
from cce.contracts.risk import RiskSnapshot
from cce.controls.circuit_breaker import evaluate_breaker
from cce.controls.recovery import generate_recovery_candidates


@pytest.fixture
def now() -> datetime:
    return datetime(2026, 8, 31, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def safe_allocation(now) -> SafeAllocation:
    return SafeAllocation(
        safe_allocation_id=1,
        approved_at=now,
        weights={"NIFTY50": 0.5, "CASH": 0.5},
        decision_id=100,
        policy_version_id=1,
        approved_by="system",
    )


@pytest.fixture(scope="module")
def env():
    from datetime import date
    from cce.config import load_policy, load_universe
    from cce.data import CachedDataProvider, DEFAULT_CACHE_DIR, build_market_data
    from cce.contracts import DataProvider
    u, pol = load_universe(), load_policy()
    p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
        u, date(2000, 1, 1), date(2030, 1, 1)
    )
    md = build_market_data(p, u, DataProvider.CACHED, as_of=date(2026, 8, 31))
    return u, pol, md


@pytest.fixture
def empty_snapshot():
    from unittest.mock import MagicMock
    mock = MagicMock(spec=RiskSnapshot)
    mock.risk_state = RiskState.GREEN
    mock.breaches = ()
    return mock


def test_breaker_does_not_trip_on_passed_candidate(safe_allocation, empty_snapshot):
    opt = OptimizationResult(
        strategy=Strategy.MAX_SHARPE,
        expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL,
        weights={"NIFTY50": 0.5, "CASH": 0.5},
    )
    control = ControlResult(
        status=ControlStatus.PASSED,
        passed=True,
        findings=(),
        hard_breaches=(),
        warnings=(),
        circuit_breaker_active=False,
        breaker_category=None,
        recomputed=empty_snapshot,
    )
    candidate = Candidate(role=CandidateRole.CURRENT, optimization=opt, control=control)
    
    outcome = evaluate_breaker(candidate, safe_allocation)
    
    assert not outcome.tripped
    assert outcome.alert is None
    assert outcome.events == ()


def test_breaker_trips_on_hard_red_breach(safe_allocation, empty_snapshot):
    breach = Breach(
        control_code="CONC_SECTOR_MAX",
        control_label="Sector max",
        severity=RiskState.RED,
        is_hard=True,
        observed=0.5,
        threshold=0.3,
        comparator=Comparator.GT,
        scope="BANKING",
        message="Too much banking",
    )
    opt = OptimizationResult(
        strategy=Strategy.MAX_SHARPE,
        expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL,
        weights={"BANKNIFTY": 0.5, "CASH": 0.5},
    )
    control = ControlResult(
        status=ControlStatus.FAILED,
        passed=False,
        findings=(breach,),
        hard_breaches=(breach,),
        warnings=(),
        circuit_breaker_active=True,
        breaker_category=BreakerCategory.CONSTRAINT,
        recomputed=empty_snapshot,
    )
    candidate = Candidate(role=CandidateRole.OPTIMAL_UNCONSTRAINED, optimization=opt, control=control)
    
    outcome = evaluate_breaker(candidate, safe_allocation)
    
    assert outcome.tripped
    assert outcome.category is BreakerCategory.CONSTRAINT
    assert outcome.alert is not None
    assert outcome.alert.severity == "RED"
    assert "Too much banking" in outcome.alert.message
    
    # 1 trip event + 1 preserve event
    assert len(outcome.events) == 2
    assert outcome.events[0].event_code == "BREAKER_TRIPPED"
    assert outcome.events[1].event_code == "SAFE_ALLOCATION_PRESERVED"


def test_breaker_preserves_last_approved_safe_allocation(safe_allocation, empty_snapshot):
    """INV-4: The preserved allocation must be returned untouched."""
    breach = Breach(
        control_code="RISK_CVAR_95", control_label="CVaR", severity=RiskState.RED,
        is_hard=True, observed=0.1, threshold=0.08, comparator=Comparator.GT,
        scope=Scope.PORTFOLIO.value, message="CVaR breach",
    )
    control = ControlResult(
        status=ControlStatus.FAILED, passed=False, findings=(breach,),
        hard_breaches=(breach,), warnings=(), circuit_breaker_active=True,
        breaker_category=BreakerCategory.RISK, recomputed=empty_snapshot,
    )
    candidate = Candidate(
        role=CandidateRole.CURRENT,
        optimization=OptimizationResult(
            strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
            solver_status=SolverStatus.OPTIMAL, weights={}
        ),
        control=control,
    )
    
    outcome = evaluate_breaker(candidate, safe_allocation)
    
    assert outcome.tripped
    assert outcome.preserved_allocation is safe_allocation
    # It must be the exact same object, not a mutation
    assert id(outcome.preserved_allocation) == id(safe_allocation)


def test_optimizer_exception_preserves_last_safe(safe_allocation, empty_snapshot):
    """INV-4: Optimizer failure trips breaker and preserves last safe."""
    control = ControlResult(
        status=ControlStatus.NOT_VALIDATED, passed=False, findings=(),
        hard_breaches=(), warnings=(), circuit_breaker_active=True,
        breaker_category=BreakerCategory.MODEL, recomputed=empty_snapshot,
    )
    candidate = Candidate(
        role=CandidateRole.CURRENT,
        optimization=OptimizationResult(
            strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
            solver_status=SolverStatus.SOLVER_ERROR, weights=None,
        ),
        control=control,
    )
    
    outcome = evaluate_breaker(candidate, safe_allocation)
    
    assert outcome.tripped
    assert outcome.category is BreakerCategory.MODEL
    assert outcome.preserved_allocation is safe_allocation


def test_no_safe_allocation_reports_explicit_message(empty_snapshot):
    """EC-5.2: If genuinely absent, block the preserve path with an explicit message."""
    control = ControlResult(
        status=ControlStatus.NOT_VALIDATED, passed=False, findings=(),
        hard_breaches=(), warnings=(), circuit_breaker_active=True,
        breaker_category=BreakerCategory.MODEL, recomputed=empty_snapshot,
    )
    candidate = Candidate(
        role=CandidateRole.CURRENT,
        optimization=OptimizationResult(
            strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
            solver_status=SolverStatus.SOLVER_ERROR, weights=None,
        ),
        control=control,
    )
    
    outcome = evaluate_breaker(candidate, None)
    
    assert outcome.tripped
    assert outcome.preserved_allocation is None
    
    assert len(outcome.events) == 2
    assert outcome.events[1].event_code == "NO_SAFE_ALLOCATION"
    assert "No prior safe allocation exists" in outcome.events[1].summary


def test_recovery_candidates_are_each_independently_validated(env):
    """Recovery generation returns up to 3 candidates, correctly validated."""
    u, pol, md = env
    
    opt_ms = OptimizationResult(
        strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL, weights={"NIFTY50": 0.5, "CASH": 0.5},
    )
    opt_mr = OptimizationResult(
        strategy=Strategy.MIN_VOLATILITY, expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL, weights={"CASH": 1.0},
    )
    
    optimizations = {
        CandidateRole.RECOVERY_MAX_SHARPE: opt_ms,
        CandidateRole.RECOVERY_MIN_RISK: opt_mr,
    }
    
    candidates = generate_recovery_candidates(
        optimizations, u, md, {"NIFTY50": 0.5, "CASH": 0.5}, pol, total_value_paise=10_000_000_000
    )
    
    assert len(candidates) == 2
    
    roles = [c.role for c in candidates]
    assert CandidateRole.RECOVERY_MAX_SHARPE in roles
    assert CandidateRole.RECOVERY_MIN_RISK in roles
    
    # Each must have a control result
    for c in candidates:
        assert c.control is not None
        assert isinstance(c.control, ControlResult)
        assert c.control.recomputed is not None


def test_all_recoveries_failing_yields_no_eligible_candidate(env):
    """EC-5.1: If all three fail, none are eligible."""
    u, pol, md = env
    
    # Bad weights that fail constraint (max weight is 0.3 for NIFTY50, this is 1.0)
    opt = OptimizationResult(
        strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL, weights={"NIFTY50": 1.0},
    )
    
    optimizations = {
        CandidateRole.RECOVERY_MAX_SHARPE: opt,
        CandidateRole.RECOVERY_MIN_RISK: opt,
        CandidateRole.RECOVERY_DEFENSIVE: opt,
    }
    
    candidates = generate_recovery_candidates(
        optimizations, u, md, {"NIFTY50": 0.5, "CASH": 0.5}, pol, total_value_paise=10_000_000_000
    )
    
    assert len(candidates) == 3
    # None should be eligible
    for c in candidates:
        assert not c.eligible_for_approval
        assert not c.control.passed


def test_recovery_that_fails_is_still_returned_with_reasons(env):
    """EC-5.1: Failed recoveries are returned with rejection reasons."""
    u, pol, md = env
    
    opt = OptimizationResult(
        strategy=Strategy.MAX_SHARPE, expected_return_method=ExpectedReturnMethod.HISTORICAL,
        solver_status=SolverStatus.OPTIMAL, weights={"NIFTY50": 1.0},
    )
    
    optimizations = {CandidateRole.RECOVERY_MAX_SHARPE: opt}
    
    candidates = generate_recovery_candidates(
        optimizations, u, md, {"NIFTY50": 0.5, "CASH": 0.5}, pol, total_value_paise=10_000_000_000
    )
    
    assert len(candidates) == 1
    c = candidates[0]
    assert not c.eligible_for_approval
    # Rejection reasons must be populated
    assert len(c.rejection_reasons) > 0
    assert any("CONC_ASSET_MAX" in r or "Asset" in r for r in c.rejection_reasons)

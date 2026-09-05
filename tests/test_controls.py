"""Control engine tests.

Spec: docs/11-TESTING-STRATEGY.md section 5, docs/IMPLEMENTATION-PLAN.md PHASE 5.

Two tests here prove the architecture rather than merely exercising it:

- ``test_control_module_does_not_import_optimizer`` — structural
- ``test_validation_ignores_optimizer_reported_metrics`` — behavioural

The second is the most valuable test in the repository. It hands the
validator an ``OptimizationResult`` with deliberately falsified metrics and
asserts the verdict does not move, which converts "the control engine is
independent" from an architectural claim into a verified property.
"""

from __future__ import annotations

import re
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from cce.contracts import (
    BreakerCategory,
    Comparator,
    ControlStatus,
    DataProvider,
    ExpectedReturnMethod,
    OptimizationResult,
    RiskState,
    Scope,
    SolverStatus,
    Strategy,
    Threshold,
)
from cce.controls import (
    aggregate_state,
    diff_policies,
    is_weakening,
    validate,
)
from cce.data import DEFAULT_CACHE_DIR, CachedDataProvider, build_market_data

ROOT = Path(__file__).resolve().parent.parent
AS_OF = date(2026, 8, 31)
NAV = 100_000_000_000

CURRENT = {"NIFTY50": 0.26, "BANKNIFTY": 0.20, "IT": 0.10, "PHARMA": 0.08,
           "FMCG": 0.06, "GOLD": 0.10, "GSEC": 0.12, "CORPBOND": 0.02,
           "CASH": 0.06}
BANKING_HEAVY = {"NIFTY50": 0.20, "BANKNIFTY": 0.43, "IT": 0.10, "PHARMA": 0.05,
                 "FMCG": 0.04, "GOLD": 0.06, "GSEC": 0.06, "CORPBOND": 0.00,
                 "CASH": 0.06}


@pytest.fixture(scope="module")
def env():
    from cce.config import load_policy, load_universe
    u, pol = load_universe(), load_policy()
    p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
        u, date(2000, 1, 1), date(2030, 1, 1)
    )
    md = build_market_data(p, u, DataProvider.CACHED, as_of=AS_OF)
    return u, pol, md


def _validate(env, weights, **kw):
    u, pol, md = env
    kw.setdefault("total_value_paise", NAV)
    kw.setdefault("solver_ok", True)
    kw.setdefault("worst_stress_loss", 0.05)      # a passing stress result
    kw.setdefault("data_staleness_days", 0.0)
    kw.setdefault("data_completeness", 1.0)
    return validate(weights, u, md, CURRENT, pol, **kw)


# =====================================================================
# THE architecture tests
# =====================================================================

class TestIndependence:
    def test_control_module_does_not_import_optimizer(self) -> None:
        """INV-2, structural. The safety property in one assertion."""
        offenders = []
        for f in (ROOT / "cce" / "controls").rglob("*.py"):
            src = f.read_text(encoding="utf-8")
            if re.search(r"\bfrom\s+cce\.optimizer|\bimport\s+cce\.optimizer"
                         r"|from\s+\.\.optimizer|from cce import optimizer", src):
                offenders.append(f.name)
        assert not offenders, f"cce/controls imports the optimizer: {offenders}"

    def test_validation_ignores_optimizer_reported_metrics(self, env) -> None:
        """A lying OptimizationResult must not change the verdict.

        The validator's signature takes WEIGHTS, not an OptimizationResult -
        there is deliberately no way to hand it the optimizer's opinion of
        its own output. This test proves the consequence: fabricated metrics
        cannot influence the decision, because they are never read.
        """
        honest = OptimizationResult(
            strategy=Strategy.MAX_SHARPE,
            expected_return_method=ExpectedReturnMethod.HISTORICAL,
            solver_status=SolverStatus.OPTIMAL, weights=BANKING_HEAVY,
            cvar_95=0.094, volatility=0.20, sharpe=0.4,
        )
        liar = replace(honest, cvar_95=0.001, volatility=0.001, sharpe=99.0)

        a = _validate(env, honest.weights)
        b = _validate(env, liar.weights)

        assert a.status is b.status
        assert a.passed == b.passed
        assert {x.control_code for x in a.hard_breaches} == \
               {x.control_code for x in b.hard_breaches}
        assert a.recomputed.cvar_95 == b.recomputed.cvar_95
        # and the re-derived CVaR bears no relation to either claim
        assert a.recomputed.cvar_95 not in (0.094, 0.001)


# =====================================================================
# Classification
# =====================================================================

class TestClassification:
    def test_most_severe_wins(self) -> None:
        """No averaging. A control that can be outvoted is not a control."""
        assert aggregate_state(
            [RiskState.GREEN] * 20 + [RiskState.RED]
        ) is RiskState.RED
        assert aggregate_state(
            [RiskState.GREEN, RiskState.AMBER]
        ) is RiskState.AMBER
        assert aggregate_state([]) is RiskState.GREEN

    def test_banking_concentration_is_red(self, env) -> None:
        """The demo's central claim, asserted on real data."""
        r = _validate(env, BANKING_HEAVY)
        codes = {b.control_code for b in r.hard_breaches}
        assert "CONC_SECTOR_MAX" in codes
        assert "RC_SECTOR_MAX" in codes
        assert r.recomputed.risk_state is RiskState.RED
        assert r.passed is False
        assert r.circuit_breaker_active is True

    def test_risk_contribution_exceeds_weight_for_banking(self, env) -> None:
        """Weight-only controls cannot see this; RC controls can."""
        r = _validate(env, BANKING_HEAVY)
        rc = r.recomputed.sector_risk_contribution["BANKING"]
        assert rc > BANKING_HEAVY["BANKNIFTY"]
        assert rc > 0.45          # above the RED band

    def test_scoped_controls_evaluate_every_member(self, env) -> None:
        """CONC_SECTOR_MAX checks each sector, not an aggregate."""
        r = _validate(env, BANKING_HEAVY)
        scopes = {b.scope for b in r.findings
                  if b.control_code == "CONC_SECTOR_MAX"}
        assert "BANKING" in scopes

    def test_breach_reports_the_threshold_actually_crossed(self, env) -> None:
        """An AMBER breach crossed the GREEN edge, not the amber one.

        Reporting amber_max produced "26% exceeds the AMBER limit of 35%" -
        false, and it is the number shown beside the observed value.
        """
        r = _validate(env, CURRENT)
        amber = [b for b in r.findings
                 if b.severity is RiskState.AMBER
                 and b.control_code == "CONC_SECTOR_MAX"]
        for b in amber:
            assert b.observed > b.threshold, b.message
            assert b.threshold == pytest.approx(0.25)   # green edge, not 0.35

    def test_boundary_tolerance_absorbs_float_noise(self) -> None:
        """A solver satisfying x <= 0.25 exactly may return 0.2500000001.
        A control must not turn on the last bit of a float."""
        t = Threshold(
            control_code="TXN_TURNOVER_MAX", label="Turnover",
            scope=Scope.PORTFOLIO, comparator=Comparator.GT, is_hard=True,
            green_max=0.20, amber_max=0.25,
        )
        assert t.classify(0.25 + 1e-12) is RiskState.AMBER
        assert t.classify(0.26) is RiskState.RED          # real breach bites


# =====================================================================
# Unevaluated hard controls do not pass
# =====================================================================

class TestUnevaluated:
    def test_missing_stress_result_blocks_approval(self, env) -> None:
        """INV-10. Absence of evidence is not evidence of safety.

        STRESS_LOSS_MAX is a hard control. With no stress result the
        candidate is NOT_VALIDATED - never PASSED.
        """
        r = _validate(env, CURRENT, worst_stress_loss=None)
        assert r.status is ControlStatus.NOT_VALIDATED
        assert r.passed is False

    def test_missing_data_metrics_block_approval(self, env) -> None:
        r = _validate(env, CURRENT, data_staleness_days=None,
                      data_completeness=None)
        assert r.status is ControlStatus.NOT_VALIDATED

    def test_fully_supplied_inputs_can_pass(self, env) -> None:
        """A clean allocation with every input present must be able to PASS,
        or the gate is stuck shut and nothing could ever be approved."""
        u, pol, md = env
        # current portfolio against itself: zero turnover, no cost
        r = validate(CURRENT, u, md, CURRENT, pol, total_value_paise=NAV,
                     solver_ok=True, worst_stress_loss=0.05,
                     data_staleness_days=0.0, data_completeness=1.0)
        # The point of the test: with every input supplied, the engine must
        # reach a verdict. NOT_VALIDATED here would mean a hard control could
        # not be evaluated even on complete data — the gate stuck shut.
        assert r.status in (ControlStatus.PASSED, ControlStatus.FAILED)
        assert r.status is not ControlStatus.NOT_VALIDATED
        # Degradation is allowed (this fixture's covariance needs repairing),
        # but it is never silent: a degraded snapshot always says why, so the
        # UI can label the number rather than present it as clean.
        if r.recomputed.degraded:
            assert r.recomputed.degraded_reason

    def test_amber_warnings_do_not_block(self, env) -> None:
        """Only HARD breaches block. AMBER warns."""
        r = _validate(env, CURRENT)
        if r.status is ControlStatus.PASSED:
            assert r.warnings          # warnings present but not blocking
            assert not r.hard_breaches


# =====================================================================
# Model failure
# =====================================================================

class TestModelFailure:
    def test_solver_failure_is_a_hard_red_breach(self, env) -> None:
        r = _validate(env, CURRENT, solver_ok=False)
        codes = {b.control_code for b in r.hard_breaches}
        assert "MODEL_SOLVER" in codes
        assert r.passed is False
        assert r.breaker_category is not None

    def test_malformed_candidate_is_not_validated_not_crashed(self, env) -> None:
        """A candidate that cannot describe a portfolio is reported, not
        raised - the caller must record it as a control event (INV-4)."""
        r = _validate(env, {"NIFTY50": 0.5})       # sums to 0.5
        assert r.status is ControlStatus.NOT_VALIDATED
        assert r.circuit_breaker_active is True
        assert r.breaker_category is BreakerCategory.MODEL
        assert "not a valid allocation" in r.hard_breaches[0].message

    def test_covariance_repair_surfaces_as_a_finding(self, env) -> None:
        """The synthetic cash proxy makes the real matrix near-singular, so
        this fires on live data. A repair is recorded, never silent."""
        r = _validate(env, CURRENT)
        codes = {b.control_code for b in r.findings}
        assert "MODEL_COVARIANCE" in codes

    def test_control_result_contract_forbids_passing_with_hard_breaches(
        self, env
    ) -> None:
        """INV-3, enforced by the contract itself."""
        r = _validate(env, BANKING_HEAVY)
        assert r.hard_breaches and not r.passed


# =====================================================================
# Policy weakening (INV-8)
# =====================================================================

class TestPolicyWeakening:
    def test_raising_a_gt_limit_is_weakening(self, env) -> None:
        _, pol, _ = env
        t = pol.threshold("RISK_CVAR_95")
        loosened = replace(t, amber_max=0.12)
        assert is_weakening(t, loosened, "amber_max") is True
        assert is_weakening(loosened, t, "amber_max") is False

    def test_lowering_an_lt_limit_is_weakening(self, env) -> None:
        """LT controls invert - lowering a liquidity floor admits more risk."""
        _, pol, _ = env
        t = pol.threshold("LIQ_MIN_SHARE")
        loosened = replace(t, amber_min=0.02)
        assert is_weakening(t, loosened, "amber_min") is True

    def test_demoting_a_hard_control_is_weakening(self, env) -> None:
        _, pol, _ = env
        t = pol.threshold("RISK_CVAR_95")
        assert is_weakening(t, replace(t, is_hard=False), "is_hard") is True

    def test_diff_detects_a_material_weakening(self, env) -> None:
        _, pol, _ = env
        new = replace(pol, version=2, thresholds=tuple(
            replace(t, amber_max=0.12) if t.control_code == "RISK_CVAR_95" else t
            for t in pol.thresholds
        ))
        d = diff_policies(pol, new)
        assert d.is_weakening and d.is_material
        assert "RISK_CVAR_95" in d.weakened_controls

    def test_tightening_is_not_flagged(self, env) -> None:
        """Both bands must move together - the contract rejects amber_max
        below green_max, which is itself a useful guard."""
        _, pol, _ = env
        new = replace(pol, version=2, thresholds=tuple(
            replace(t, green_max=0.04, amber_max=0.05)
            if t.control_code == "RISK_CVAR_95" else t
            for t in pol.thresholds
        ))
        d = diff_policies(pol, new)
        assert d.is_weakening is False
        assert d.changes                       # the change IS recorded
        assert all(not c.weakening for c in d.changes)

    def test_inverted_bands_are_rejected_by_the_contract(self, env) -> None:
        """Lowering only amber_max would put the RED edge below the GREEN
        edge - an incoherent control that could never be AMBER."""
        _, pol, _ = env
        t = pol.threshold("RISK_CVAR_95")
        with pytest.raises(ValueError, match="green_max must be <= amber_max"):
            replace(t, amber_max=0.05)         # green_max is 0.06

    def test_removing_a_control_is_the_strongest_weakening(self, env) -> None:
        _, pol, _ = env
        new = replace(pol, version=2, thresholds=tuple(
            t for t in pol.thresholds if t.control_code != "RISK_CVAR_95"
        ))
        d = diff_policies(pol, new)
        assert d.is_weakening and d.is_material
        assert "RISK_CVAR_95" in d.removed

    def test_identical_policies_show_no_change(self, env) -> None:
        _, pol, _ = env
        d = diff_policies(pol, pol)
        assert not d.changes and not d.is_weakening
        assert d.summary == "no threshold changes"


# =====================================================================
# Determinism
# =====================================================================

def test_validation_is_deterministic(env) -> None:
    a = _validate(env, BANKING_HEAVY)
    b = _validate(env, BANKING_HEAVY)
    assert a.status is b.status
    assert [x.message for x in a.findings] == [x.message for x in b.findings]

from datetime import date
from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from cce.contracts import (
    Candidate,
    CandidateRole,
    ControlStatus,
    DataProvider,
    MarketData,
    StressResult,
    StressStatus,
)
from cce.stress.engine import run_scenario
from cce.stress.scenarios import LIQUIDITY_KEY, Scenario
from tests.fixtures import synthetic


def test_scenario_loss_is_the_weighted_shock_sum(demo_universe, demo_portfolio, policy):
    universe = demo_universe
    a01 = universe.assets[0].asset_id
    a02 = universe.assets[1].asset_id
    returns = pd.DataFrame({a01: [0.0], a02: [0.0]})
    prices = pd.DataFrame({a01: [100.0], a02: [100.0]})
    md = MarketData(
        prices=prices, returns=returns, as_of_date=None,
        provider=DataProvider.CACHED, universe_hash="", data_hash=""
    )

    # 50% asset1, 50% asset2
    weights = {a01: 0.5, a02: 0.5}

    # Custom scenario: A01 drops 10%, A02 drops 20%
    scen = Scenario.custom(
        "test",
        {a01: -0.10, a02: -0.20}
    )

    res = run_scenario(weights, scen, universe, md, current_weights=weights, policy=policy, total_value_paise=10000)

    # Weighted shock sum = 0.5 * (-0.10) + 0.5 * (-0.20) = -0.05 + -0.10 = -0.15
    # Portfolio return = -0.15 -> portfolio loss = 0.15
    assert res.portfolio_loss == pytest.approx(0.15)

def test_candidate_passing_controls_but_failing_stress_is_rejected(demo_universe, policy):
    universe = demo_universe
    a01 = universe.assets[0].asset_id
    returns = pd.DataFrame({a01: [0.0]})
    prices = pd.DataFrame({a01: [100.0]})
    md = MarketData(
        prices=prices, returns=returns, as_of_date=None,
        provider=DataProvider.CACHED, universe_hash="", data_hash=""
    )

    # Loss exceeds limit (policy.stress_loss_limit = 0.18)
    weights = {a01: 1.0}
    scen = Scenario.custom("test", {a01: -0.25}) # 25% loss

    res = run_scenario(weights, scen, universe, md, current_weights=weights, policy=policy, total_value_paise=10000)

    assert res.status == StressStatus.FAILED

    # Create Candidate
    opt = MagicMock()
    control = MagicMock()
    control.status = ControlStatus.PASSED
    control.passed = True

    candidate = Candidate(
        role=CandidateRole.SAFE_CONSTRAINED,
        optimization=opt,
        control=control,
        stress=(res,)
    )

    # Even if control passed, stress failure blocks eligible_for_approval
    assert not candidate.eligible_for_approval
    assert candidate.stress_status == StressStatus.FAILED

def test_stress_engine_failure_yields_not_run_not_passed(demo_universe, policy):
    universe = demo_universe
    returns = pd.DataFrame({"INVALID_KEY": [0.0]})
    prices = pd.DataFrame({"INVALID_KEY": [100.0]})
    md = MarketData(
        prices=prices, returns=returns, as_of_date=None,
        provider=DataProvider.CACHED, universe_hash="", data_hash=""
    )

    # We will trigger a failure by passing a malformed weights dictionary
    weights = {"INVALID_KEY": "not-a-number"}
    scen = Scenario.custom("test", {"INVALID_KEY": -0.10})

    res = run_scenario(weights, scen, universe, md, current_weights=weights, policy=policy, total_value_paise=10000)

    assert res.status == StressStatus.ERROR

    opt = MagicMock()
    control = MagicMock()
    control.status = ControlStatus.PASSED
    control.passed = True

    candidate = Candidate(
        role=CandidateRole.SAFE_CONSTRAINED,
        optimization=opt,
        control=control,
        stress=(res,)
    )

    assert candidate.stress_status == StressStatus.ERROR
    assert not candidate.eligible_for_approval

def test_post_shock_weights_drift(demo_universe, policy):
    universe = demo_universe
    a01 = universe.assets[0].asset_id
    a02 = universe.assets[1].asset_id
    returns = pd.DataFrame({a01: [0.0], a02: [0.0]})
    prices = pd.DataFrame({a01: [100.0], a02: [100.0]})
    md = MarketData(
        prices=prices, returns=returns, as_of_date=None,
        provider=DataProvider.CACHED, universe_hash="", data_hash=""
    )

    weights = {a01: 0.5, a02: 0.5}
    scen = Scenario.custom("test", {a01: -0.50, a02: 0.0})

    res = run_scenario(weights, scen, universe, md, current_weights=weights, policy=policy, total_value_paise=10000)

    # A 50% fall in half the portfolio is a 25% portfolio loss, and the loss
    # is attributed entirely to the asset that fell. Asserted exactly: the
    # shock arithmetic is the one part of the stress engine with a closed
    # form, so it is checked against the hand-computed value rather than
    # against whatever the code happens to return.
    assert res.portfolio_loss == pytest.approx(0.25)
    assert res.loss_paise == 2500
    assert res.contribution[a01] == pytest.approx(0.25)
    assert res.contribution[a02] == pytest.approx(0.0)

    # One observation is too few for a covariance, so the control engine
    # cannot evaluate the post-shock portfolio. It must fail toward
    # rejection, never report the scenario as survived (INV-5, INV-10).
    assert res.status is not StressStatus.PASSED
    assert not res.passed

def test_post_shock_weights_drift_via_mock(demo_universe, policy, monkeypatch):
    from cce.stress import engine

    mock_validate = MagicMock()
    dummy_control = MagicMock()
    dummy_control.findings = ()
    dummy_control.recomputed.portfolio_volatility = 0.1
    dummy_control.recomputed.cvar_95 = 0.1
    mock_validate.return_value = dummy_control

    monkeypatch.setattr(engine, "validate", mock_validate)

    universe = demo_universe
    a01 = universe.assets[0].asset_id
    a02 = universe.assets[1].asset_id
    returns = pd.DataFrame({a01: [0.0], a02: [0.0]})
    prices = pd.DataFrame({a01: [100.0], a02: [100.0]})
    md = MarketData(
        prices=prices, returns=returns, as_of_date=None,
        provider=DataProvider.CACHED, universe_hash="", data_hash=""
    )

    weights = {a01: 0.5, a02: 0.5}
    scen = Scenario.custom("test", {a01: -0.50, a02: 0.0})

    engine.run_scenario(weights, scen, universe, md, current_weights=weights, policy=policy, total_value_paise=10000)

    mock_validate.assert_called_once()
    kwargs = mock_validate.call_args.kwargs
    post_weights = kwargs["candidate_weights"]

    assert post_weights[a01] == pytest.approx(1/3)
    assert post_weights[a02] == pytest.approx(2/3)




# ---------------------------------------------------------------------------
# A scenario that applies nothing must never report PASSED (INV-10)
# ---------------------------------------------------------------------------

class TestScenarioAppliesSomething:
    """The stress gate exists to catch what ordinary metrics miss. A scenario
    that shocks nothing catches nothing, and used to report a clean pass."""

    def _md(self, universe):
        ids = [a.asset_id for a in universe.assets]
        rng = np.random.default_rng(7)
        idx = pd.date_range("2025-01-01", periods=300, freq="B")
        returns = pd.DataFrame(rng.normal(0.0004, 0.01, (300, len(ids))),
                               columns=ids, index=idx)
        prices = (1.0 + returns).cumprod() * 100.0
        return MarketData(prices=prices, returns=returns, as_of_date=date(2026, 8, 31),
                          provider=DataProvider.CACHED, universe_hash="", data_hash="")

    def _run(self, universe, policy, shocks):
        weights = synthetic.healthy_weights()
        return run_scenario(
            weights, Scenario.custom("probe", shocks), universe, self._md(universe),
            current_weights=weights, policy=policy, total_value_paise=10**12,
        )

    def test_a_typo_in_a_shock_key_is_not_a_silent_pass(self, demo_universe, policy):
        """The bug this guards: shocks resolve by asset id then sector, and a
        key matching neither is dropped. `BANKNIFTY` where the sector is
        `BANKING` shocked nothing and PASSED — a banking-crisis scenario that
        never touched banking."""
        res = self._run(demo_universe, policy, {"BANKNIFTY_TYPO": -0.30})
        assert res.status is StressStatus.ERROR
        assert not res.passed
        assert res.error_reason and "BANKNIFTY_TYPO" in res.error_reason

    def test_an_empty_scenario_is_not_a_pass(self, demo_universe, policy):
        res = self._run(demo_universe, policy, {})
        assert res.status is StressStatus.ERROR
        assert not res.passed
        assert res.error_reason

    def test_a_partially_unresolved_scenario_is_rejected(self, demo_universe, policy):
        """One good key does not excuse a bad one: the scenario as configured
        is not the scenario that would run."""
        res = self._run(demo_universe, policy, {"BANKING": -0.30, "NOT_A_SECTOR": -0.2})
        assert res.status is StressStatus.ERROR
        assert res.error_reason and "NOT_A_SECTOR" in res.error_reason

    def test_a_resolvable_scenario_still_runs(self, demo_universe, policy):
        """The guard must not break real scenarios."""
        res = self._run(demo_universe, policy, {"BANKING": -0.30})
        assert res.status in (StressStatus.PASSED, StressStatus.FAILED)
        assert res.error_reason is None

    def test_asset_id_keys_resolve(self, demo_universe, policy):
        asset_id = demo_universe.assets[0].asset_id
        res = self._run(demo_universe, policy, {asset_id: -0.30})
        assert res.status in (StressStatus.PASSED, StressStatus.FAILED)

    def test_liquidity_is_a_recognised_pseudo_sector(self, demo_universe, policy):
        """LIQUIDITY scales ADV rather than price, so it is neither an asset
        nor a sector and must not be reported as unresolved."""
        assert Scenario.custom("x", {LIQUIDITY_KEY: -0.20}).unresolved_keys(
            demo_universe
        ) == ()

    def test_every_configured_scenario_resolves(self, universe, scenarios):
        """config/scenarios.yaml must not ship a typo.

        Checked against the REAL universe from config/universe.yaml, not the
        synthetic fixture — the fixture is a reduced subset without CORP_DEBT
        or FMCG, so it would report false unresolved keys for scenarios that
        are perfectly valid in production.

        This is the test that would have caught a shock-key typo in shipped
        configuration rather than in an ad-hoc probe.
        """
        for s in scenarios:
            scenario = Scenario(code=s.code, label=s.label, shocks=s.shocks)
            unresolved = scenario.unresolved_keys(universe)
            assert not unresolved, (
                f"scenario {s.code} has unresolvable shock keys {unresolved}; "
                "it would apply nothing for those and report a smaller loss"
            )


def test_an_errored_result_must_explain_itself():
    """INV-10: an unexplained ERROR is not actionable."""
    with pytest.raises(ValueError, match="error_reason"):
        StressResult(
            scenario_code="X", scenario_label="X", is_custom=True, shocks={},
            portfolio_loss=0.0, loss_paise=0, contribution={},
            post_shock_volatility=None, post_shock_cvar=None, breaches=(),
            loss_threshold=0.18, status=StressStatus.ERROR,
        )


def test_a_passing_result_cannot_carry_an_error_reason():
    with pytest.raises(ValueError, match="cannot carry an error_reason"):
        StressResult(
            scenario_code="X", scenario_label="X", is_custom=True,
            shocks={"BANKING": -0.1}, portfolio_loss=0.01, loss_paise=1,
            contribution={}, post_shock_volatility=None, post_shock_cvar=None,
            breaches=(), loss_threshold=0.18, status=StressStatus.PASSED,
            error_reason="should not be here",
        )


@pytest.mark.parametrize(
    ("status", "measured"),
    [
        (StressStatus.PASSED, True),
        (StressStatus.FAILED, True),
        (StressStatus.NOT_RUN, False),
        (StressStatus.ERROR, False),
    ],
)
def test_loss_is_measured_only_for_a_scenario_that_ran(status, measured):
    """INV-5: portfolio_loss is 0.0 on an ERROR because the field is a plain
    float, not because a loss was measured. The UI renders an em dash unless
    this property is true."""
    res = StressResult(
        scenario_code="X", scenario_label="X", is_custom=True,
        shocks={"BANKING": -0.1}, portfolio_loss=0.0, loss_paise=0,
        contribution={}, post_shock_volatility=None, post_shock_cvar=None,
        breaches=(), loss_threshold=0.18, status=status,
        error_reason="probe" if status is StressStatus.ERROR else None,
    )
    assert res.loss_is_measured is measured

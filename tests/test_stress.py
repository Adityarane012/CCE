from unittest.mock import MagicMock

import pandas as pd
import pytest

from cce.contracts import (
    Candidate,
    CandidateRole,
    ControlStatus,
    DataProvider,
    MarketData,
    StressStatus,
)
from cce.stress.engine import run_scenario
from cce.stress.scenarios import Scenario


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
    # Validation returns but we only check weight drift logic internally.

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



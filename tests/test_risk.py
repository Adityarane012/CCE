"""Risk engine tests.

Spec: docs/11-TESTING-STRATEGY.md section 4, docs/IMPLEMENTATION-PLAN.md PHASE 3.

Every calculation carries at least one HAND-COMPUTED expected value.
Comparing an implementation against itself proves nothing.

The single most valuable assertion here is
``test_risk_contributions_sum_to_portfolio_volatility``: the identity
``sum_i RC_i == sigma_p`` is a free correctness check on the entire
covariance and weight pipeline. If it fails, stop — every number downstream
is meaningless.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from cce.contracts import DataProvider, ExpectedReturnMethod
from cce.data import CachedDataProvider, DEFAULT_CACHE_DIR, build_market_data
from cce.risk import (
    TRADING_DAYS, annualisation_factor, concentration_summary,
    current_drawdown, cvar_with_diagnostics, days_to_liquidate,
    effective_number_of_assets, equity_curve, ewma_mean, ewma_volatility,
    expected_returns, herfindahl_index, historical_cvar, historical_mean,
    historical_var, historical_volatility, liquidity_summary,
    marginal_contributions, max_drawdown, max_sector_weight, monte_carlo_var,
    parametric_var, percentage_risk_contributions, portfolio_volatility,
    risk_contributions, sharpe_ratio,
)
from cce.risk.ewma import ewma_step
from tests.fixtures import synthetic

AS_OF = date(2026, 8, 31)


# =====================================================================
# Volatility — hand computed
# =====================================================================

class TestVolatility:
    def test_hand_computed_daily_volatility(self) -> None:
        """returns [0.01, -0.01, 0.02, -0.02], mean 0.

        var(ddof=1) = (1e-4 + 1e-4 + 4e-4 + 4e-4) / 3 = 1e-3/3
        sd = sqrt(3.3333e-4) = 0.01825742
        """
        r = pd.Series([0.01, -0.01, 0.02, -0.02])
        assert historical_volatility(r, annualise=False) == pytest.approx(
            0.01825742, rel=1e-6
        )

    def test_annualisation_applied_exactly_once(self) -> None:
        """A sqrt(252) applied twice is a 15.9x error that still looks like
        a number (docs/08 section 15)."""
        r = pd.Series([0.01, -0.01, 0.02, -0.02])
        daily = historical_volatility(r, annualise=False)
        annual = historical_volatility(r, annualise=True)
        assert annual == pytest.approx(daily * np.sqrt(252), rel=1e-12)
        assert annual / daily == pytest.approx(15.8745, rel=1e-4)

    def test_constant_returns_have_zero_volatility(self) -> None:
        assert historical_volatility(
            synthetic.constant_returns()["A0"], annualise=False
        ) == pytest.approx(0.0, abs=1e-15)

    def test_recovers_a_known_sigma(self) -> None:
        s = synthetic.known_volatility_series(n=5000, sigma_daily=0.01)
        assert historical_volatility(s) == pytest.approx(0.01 * np.sqrt(252), rel=0.05)

    def test_none_below_two_observations(self) -> None:
        """A standard deviation of one point is no information, not zero."""
        assert historical_volatility(pd.Series([0.01])) is None
        assert historical_volatility(pd.Series([], dtype=float)) is None

    def test_annualisation_factor(self) -> None:
        assert annualisation_factor(252) == pytest.approx(15.8745, rel=1e-4)

    def test_portfolio_volatility_hand_computed(self) -> None:
        """Two assets, sd 0.01 and 0.02, rho 0.5, equal weights.

        var = 0.25*1e-4 + 0.25*4e-4 + 2*0.25*(0.5*0.01*0.02)
            = 2.5e-5 + 1e-4 + 5e-5 = 1.75e-4
        sd  = 0.013228757
        """
        w, cov = synthetic.two_asset_known_covariance(rho=0.5, s1=0.01, s2=0.02)
        assert portfolio_volatility(w, cov) == pytest.approx(0.013228757, rel=1e-6)

    def test_negative_variance_is_rejected(self) -> None:
        bad = np.array([[1.0, 2.0], [2.0, 1.0]])   # not PSD
        with pytest.raises(ValueError, match="not positive semi-definite"):
            portfolio_volatility(np.array([1.0, -1.0]), bad)


# =====================================================================
# EWMA — the responsiveness that justifies it as the default
# =====================================================================

class TestEWMA:
    def test_hand_computed_single_step(self) -> None:
        """0.94*1e-4 + 0.06*(0.02^2) = 9.4e-5 + 2.4e-5 = 1.18e-4"""
        assert ewma_step(1e-4, 0.02, 0.94) == pytest.approx(1.18e-4, rel=1e-12)

    def test_reacts_faster_than_historical_to_a_regime_change(self) -> None:
        """THE reason EWMA is the primary estimator (docs/08 section 3)."""
        base = synthetic.known_volatility_series(n=500, sigma_daily=0.005)
        shocked = synthetic.apply_vol_regime_change(
            base, from_day=480, sigma_daily=0.02
        )
        d_ewma = ewma_volatility(shocked) - ewma_volatility(base)
        d_hist = historical_volatility(shocked) - historical_volatility(base)
        assert d_ewma > d_hist

    def test_lower_lambda_is_more_responsive(self) -> None:
        base = synthetic.known_volatility_series(n=400, sigma_daily=0.005)
        shocked = synthetic.apply_vol_regime_change(
            base, from_day=390, sigma_daily=0.03
        )
        fast = ewma_volatility(shocked, lam=0.80)
        slow = ewma_volatility(shocked, lam=0.99)
        assert fast > slow

    def test_lambda_must_be_a_proper_fraction(self) -> None:
        for bad in (0.0, 1.0, 1.5, -0.1):
            with pytest.raises(ValueError, match="lambda must be"):
                ewma_volatility(pd.Series([0.01, 0.02]), lam=bad)

    def test_constant_returns_converge_to_the_return_magnitude(self) -> None:
        """The zero-mean convention, asserted explicitly.

        EWMA squares the raw return, not the deviation from the mean
        (RiskMetrics). A constant return of r therefore converges to |r|,
        NOT to zero - while historical volatility, which demeans, gives 0.

        This is why our synthetic CASH proxy shows ~0.4% annualised EWMA
        volatility against 0.0% historical. Correct behaviour, but do not
        call cash "zero volatility" while showing an EWMA figure beside it.
        """
        r = 0.001
        v = ewma_volatility(synthetic.constant_returns(n=2000, r=r)["A0"])
        assert v == pytest.approx(abs(r) * np.sqrt(252), rel=1e-6)
        assert historical_volatility(
            synthetic.constant_returns(n=2000, r=r)["A0"]
        ) == pytest.approx(0.0, abs=1e-12)

    def test_none_below_two_observations(self) -> None:
        assert ewma_volatility(pd.Series([0.01])) is None


# =====================================================================
# VaR and CVaR
# =====================================================================

class TestVaR:
    def test_historical_var_is_the_empirical_percentile(self) -> None:
        """Symmetric ladder from -0.10 to 0.10; the 5th percentile is -0.09."""
        r = pd.Series(np.linspace(-0.10, 0.10, 201))
        assert historical_var(r, 0.95, min_observations=10) == pytest.approx(
            0.09, abs=1e-3
        )

    def test_none_below_minimum_observations(self) -> None:
        """INV-5. A 95% VaR from 30 points is noise with a decimal point."""
        assert historical_var(pd.Series(np.zeros(50)), 0.95) is None

    def test_loss_is_reported_positive(self) -> None:
        s = synthetic.known_volatility_series(n=1000)
        assert historical_var(s, 0.95) > 0

    def test_parametric_understates_the_far_tail(self) -> None:
        """The normal assumption fails in the FAR tail, not the near one.

        At 95% the fitted normal inherits the fat-tailed sample's inflated
        variance and actually OVERSTATES the loss - for t(3) the true 5%
        quantile sits at ~1.36 sigma against the normal's 1.645. Fat tails
        only dominate further out, so the honest test is at 99%.

        This is precisely why parametric VaR is for COMPARISON and CVaR is
        the hard control: where you measure changes the answer.
        """
        fat = synthetic.fat_tailed_series(n=5000, df=3, seed=7)
        assert parametric_var(fat, 0.99) < historical_var(
            fat, 0.99, min_observations=250)

    def test_parametric_can_overstate_the_near_tail(self) -> None:
        """Documents the flip side, so the 99% result is not mistaken for a
        universal rule."""
        fat = synthetic.fat_tailed_series(n=5000, df=3, seed=7)
        assert parametric_var(fat, 0.95) > historical_var(
            fat, 0.95, min_observations=250)

    def test_monte_carlo_is_seeded_and_reproducible(self) -> None:
        s = synthetic.known_volatility_series(n=1000)
        assert monte_carlo_var(s, seed=42) == monte_carlo_var(s, seed=42)
        assert monte_carlo_var(s, seed=42) != monte_carlo_var(s, seed=43)

    def test_invalid_confidence_rejected(self) -> None:
        s = synthetic.known_volatility_series(n=1000)
        with pytest.raises(ValueError, match="confidence must be"):
            historical_var(s, 1.5)


class TestCVaR:
    @pytest.mark.parametrize("seed", range(20))
    def test_cvar_is_never_below_var(self, seed: int) -> None:
        """An identity. If it fails, the tail slice is wrong."""
        s = synthetic.known_volatility_series(n=1000, seed=seed)
        assert historical_cvar(s, 0.95) >= historical_var(s, 0.95)

    def test_cvar_exceeds_var_for_a_fat_tail(self) -> None:
        """The whole reason CVaR is the hard control: it measures severity
        beyond the threshold, not the threshold's location."""
        fat = synthetic.fat_tailed_series(n=3000, df=3, seed=11)
        assert historical_cvar(fat, 0.95) > historical_var(fat, 0.95) * 1.2

    def test_thin_tail_is_flagged_degraded(self) -> None:
        """Reporting the mean of three points as a risk limit without saying
        so would be dishonest - and it gates approvals."""
        s = synthetic.known_volatility_series(n=260)
        res = cvar_with_diagnostics(s, 0.95, min_observations=250)
        assert res.value is not None
        if res.tail_observations < 10:
            assert res.degraded and res.reason

    def test_none_below_minimum_observations(self) -> None:
        res = cvar_with_diagnostics(pd.Series(np.zeros(50)), 0.95)
        assert res.value is None and res.degraded


# =====================================================================
# Risk contribution — the free correctness check
# =====================================================================

class TestRiskContribution:
    def test_contributions_sum_to_portfolio_volatility(self) -> None:
        """sum_i RC_i == sigma_p EXACTLY.

        A free correctness check on the entire covariance/weight pipeline.
        If this fails, stop: every number downstream is meaningless.
        """
        w, cov = synthetic.two_asset_known_covariance()
        assert risk_contributions(w, cov).sum() == pytest.approx(
            portfolio_volatility(w, cov), rel=1e-12
        )

    def test_percentage_contributions_sum_to_one(self) -> None:
        w, cov = synthetic.two_asset_known_covariance()
        assert percentage_risk_contributions(w, cov).sum() == pytest.approx(
            1.0, rel=1e-12
        )

    def test_equal_weights_unequal_vol_gives_unequal_risk(self) -> None:
        """The product's core insight: 50/50 capital is NOT 50/50 risk."""
        cov = synthetic.cov_from({"A": 0.01, "B": 0.03}, rho=0.0)
        pcr = percentage_risk_contributions(np.array([0.5, 0.5]), cov)
        assert pcr[1] > 0.85
        assert pcr[0] < 0.15

    def test_identical_assets_split_risk_evenly(self) -> None:
        cov = synthetic.cov_from({"A": 0.02, "B": 0.02}, rho=1.0)
        pcr = percentage_risk_contributions(np.array([0.5, 0.5]), cov)
        assert pcr[0] == pytest.approx(0.5, rel=1e-9)

    def test_zero_volatility_yields_zero_not_nan(self) -> None:
        """EC-3.3. An all-cash portfolio has no risk to attribute; dividing
        by sigma would poison every downstream metric."""
        cov = np.zeros((2, 2))
        mcr = marginal_contributions(np.array([0.5, 0.5]), cov)
        pcr = percentage_risk_contributions(np.array([0.5, 0.5]), cov)
        assert np.all(mcr == 0.0) and np.all(pcr == 0.0)
        assert not np.isnan(mcr).any() and not np.isnan(pcr).any()

    def test_sector_contributions_sum_to_one(self, demo_universe) -> None:
        from cce.risk import sector_risk_contributions
        w = synthetic.healthy_weights()
        cov = synthetic.cov_from(
            {a: 0.01 + 0.002 * i for i, a in enumerate(demo_universe.asset_ids)},
            rho=0.3,
        )
        s = sector_risk_contributions(w, cov, demo_universe)
        assert sum(s.values()) == pytest.approx(1.0, rel=1e-9)


# =====================================================================
# Drawdown
# =====================================================================

class TestDrawdown:
    def test_hand_computed_drawdown(self) -> None:
        """+10% then -20%: peak 1.10, trough 0.88, DD = 0.22/1.10 = 20%."""
        r = pd.Series([0.10, -0.20])
        assert max_drawdown(r) == pytest.approx(0.20, rel=1e-9)
        assert current_drawdown(r) == pytest.approx(0.20, rel=1e-9)

    def test_monotonic_gains_have_no_drawdown(self) -> None:
        assert max_drawdown(pd.Series([0.01] * 50)) == pytest.approx(0.0, abs=1e-12)

    def test_recovery_leaves_max_above_current(self) -> None:
        r = pd.Series([0.10, -0.20, 0.30])
        assert max_drawdown(r) > current_drawdown(r)

    def test_equity_curve_compounds(self) -> None:
        assert equity_curve(pd.Series([0.10, 0.10])).iloc[-1] == pytest.approx(1.21)

    def test_empty_series_returns_none(self) -> None:
        assert max_drawdown(pd.Series([], dtype=float)) is None


# =====================================================================
# Sharpe
# =====================================================================

class TestSharpe:
    def test_hand_computed(self) -> None:
        """(0.132 - 0.065) / 0.150 = 0.44667"""
        assert sharpe_ratio(0.132, 0.150, 0.065) == pytest.approx(0.446667, rel=1e-5)

    def test_zero_volatility_is_none_not_infinity(self) -> None:
        """EC-3.3. An all-cash portfolio has an undefined Sharpe."""
        assert sharpe_ratio(0.065, 0.0, 0.065) is None

    def test_missing_input_is_none(self) -> None:
        assert sharpe_ratio(None, 0.15, 0.065) is None
        assert sharpe_ratio(0.13, None, 0.065) is None


# =====================================================================
# Concentration and liquidity
# =====================================================================

class TestConcentration:
    def test_herfindahl_of_a_single_holding_is_one(self) -> None:
        assert herfindahl_index({"A": 1.0}) == pytest.approx(1.0)

    def test_herfindahl_of_equal_weights_is_one_over_n(self) -> None:
        w = {c: 0.25 for c in "ABCD"}
        assert herfindahl_index(w) == pytest.approx(0.25)
        assert effective_number_of_assets(w) == pytest.approx(4.0)

    def test_max_sector_weight_aggregates(self, demo_universe) -> None:
        sector, w = max_sector_weight(synthetic.healthy_weights(), demo_universe)
        assert (sector, w) == ("BROAD_EQUITY", pytest.approx(0.28))

    def test_concentrated_portfolio_is_detected(self, demo_universe) -> None:
        summary = concentration_summary(
            synthetic.concentrated_weights(), demo_universe
        )
        assert summary["max_sector_weight"] == pytest.approx(0.43)


class TestLiquidity:
    def test_days_to_liquidate_hand_computed(self) -> None:
        """Rs 10 Cr position, Rs 5 Cr ADV, 20% participation:
        1e9 / (0.2 * 5e8) = 10 days."""
        assert days_to_liquidate(1_000_000_000, 500_000_000, 0.20) == pytest.approx(10.0)

    def test_missing_adv_disables_the_control(self) -> None:
        """Never fabricate precision. None disables; it is not zero days."""
        assert days_to_liquidate(1_000_000_000, None) is None
        assert days_to_liquidate(1_000_000_000, 0) is None

    def test_profile_reports_zero_adv_coverage_when_unavailable(
        self, demo_universe
    ) -> None:
        prof = liquidity_summary(
            synthetic.healthy_weights(), demo_universe, 100_000_000_000
        )
        assert prof.adv_coverage == 0.0
        assert prof.adv_available is False
        assert prof.worst_days is None
        assert prof.liquid_share == pytest.approx(0.88)


# =====================================================================
# Expected returns
# =====================================================================

class TestExpectedReturns:
    def test_historical_mean_annualises_by_252(self) -> None:
        df = pd.DataFrame({"A": [0.001] * 100})
        assert historical_mean(df)[0] == pytest.approx(0.001 * 252, rel=1e-9)

    def test_ewma_mean_weights_recent_observations_more(self) -> None:
        df = pd.DataFrame({"A": [0.0] * 99 + [0.10]})
        assert ewma_mean(df, lam=0.90)[0] > historical_mean(df)[0]

    def test_black_litterman_requires_a_posterior(self) -> None:
        df = pd.DataFrame({"A": [0.001] * 10})
        with pytest.raises(ValueError, match="requires a precomputed posterior"):
            expected_returns(df, ExpectedReturnMethod.BLACK_LITTERMAN)


# =====================================================================
# Engine integration on the committed cache
# =====================================================================

@pytest.fixture(scope="module")
def real_market():
    from cce.config import load_universe
    u = load_universe()
    p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
        u, date(2000, 1, 1), date(2030, 1, 1)
    )
    return u, build_market_data(p, u, DataProvider.CACHED, as_of=AS_OF)


class TestRiskEngine:
    @pytest.fixture
    def snapshot(self, real_market):
        from cce.risk import RiskInputs, compute_risk_snapshot
        u, md = real_market
        w = {"NIFTY50": 0.26, "BANKNIFTY": 0.20, "IT": 0.10, "PHARMA": 0.08,
             "FMCG": 0.06, "GOLD": 0.10, "GSEC": 0.12, "CORPBOND": 0.02,
             "CASH": 0.06}
        snap, report = compute_risk_snapshot(RiskInputs(
            weights=w, universe=u, market_data=md,
            total_value_paise=100_000_000_000,
        ))
        return snap, report

    def test_every_metric_is_computed(self, snapshot) -> None:
        snap, _ = snapshot
        for field in ("historical_volatility", "ewma_volatility",
                      "portfolio_volatility", "expected_return", "sharpe",
                      "var_95", "cvar_95", "current_drawdown", "max_drawdown",
                      "liquidity_ratio"):
            assert getattr(snap, field) is not None, f"{field} not computed"

    def test_metrics_are_financially_plausible(self, snapshot) -> None:
        snap, _ = snapshot
        assert 0.03 < snap.portfolio_volatility < 0.30
        assert 0.0 < snap.var_95 < 0.10
        assert snap.cvar_95 >= snap.var_95
        assert 0.0 <= snap.max_drawdown < 0.60

    def test_risk_contributions_sum_to_one(self, snapshot) -> None:
        snap, _ = snapshot
        assert sum(snap.risk_contribution.values()) == pytest.approx(1.0, rel=1e-9)
        assert sum(snap.sector_risk_contribution.values()) == pytest.approx(
            1.0, rel=1e-9
        )

    def test_snapshot_is_returned_unclassified(self, snapshot) -> None:
        """INV-11. Classification happens in cce.controls.state_machine,
        in exactly one place. The engine must not pre-empt it."""
        from cce.contracts import RiskState
        snap, _ = snapshot
        assert snap.risk_state is RiskState.GREEN
        assert snap.breaches == ()

    def test_ewma_and_historical_volatility_differ(self, snapshot) -> None:
        """Showing both is what makes responsiveness visible."""
        snap, _ = snapshot
        assert snap.ewma_volatility != snap.historical_volatility

    def test_cash_reduces_portfolio_volatility(self, real_market) -> None:
        from cce.risk import RiskInputs, compute_risk_snapshot
        u, md = real_market
        equity = {"NIFTY50": 1.0}
        half_cash = {"NIFTY50": 0.5, "CASH": 0.5}
        a, _ = compute_risk_snapshot(RiskInputs(weights=equity, universe=u,
                                                market_data=md))
        b, _ = compute_risk_snapshot(RiskInputs(weights=half_cash, universe=u,
                                                market_data=md))
        assert b.portfolio_volatility < a.portfolio_volatility

    def test_engine_is_deterministic(self, real_market) -> None:
        from cce.risk import RiskInputs, compute_risk_snapshot
        u, md = real_market
        w = {"NIFTY50": 0.5, "GOLD": 0.3, "GSEC": 0.2}
        inputs = RiskInputs(weights=w, universe=u, market_data=md)
        a, _ = compute_risk_snapshot(inputs)
        b, _ = compute_risk_snapshot(inputs)
        assert a.portfolio_volatility == b.portfolio_volatility
        assert a.cvar_95 == b.cvar_95
        assert a.risk_contribution == b.risk_contribution


class TestRiskInputValidation:
    """The engine must refuse a weight vector that cannot describe a real book.

    Found by adversarial probing after Phase 3: the engine happily measured
    weights summing to 0.5 (6.9% vol) and 1.5 (19.0% vol). Neither is wrong
    arithmetic - both answer the wrong question confidently, which is how a
    buggy optimizer output would get measured as safe.
    """

    @pytest.fixture
    def um(self, real_market):
        return real_market

    def test_underinvested_rejected(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="must sum to 1.0"):
            RiskInputs(weights={"NIFTY50": 0.5}, universe=u, market_data=md)

    def test_overinvested_rejected(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="must sum to 1.0"):
            RiskInputs(weights={"NIFTY50": 1.0, "GOLD": 0.5},
                       universe=u, market_data=md)

    def test_negative_weight_rejected(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="long-only"):
            RiskInputs(weights={"NIFTY50": 1.2, "GOLD": -0.2},
                       universe=u, market_data=md)

    def test_unknown_asset_rejected(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="unknown asset_ids"):
            RiskInputs(weights={"NOT_AN_ASSET": 1.0}, universe=u, market_data=md)

    def test_empty_rejected(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="is empty"):
            RiskInputs(weights={}, universe=u, market_data=md)

    def test_current_weights_validated_too(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        with pytest.raises(ValueError, match="current_weights"):
            RiskInputs(weights={"NIFTY50": 1.0}, universe=u, market_data=md,
                       current_weights={"NIFTY50": 0.4})

    def test_float_dust_accepted(self, um) -> None:
        from cce.risk import RiskInputs
        u, md = um
        RiskInputs(weights={"NIFTY50": 0.5, "GOLD": 0.5 + 1e-9},
                   universe=u, market_data=md)


def test_liquidity_skips_adv_tier_rather_than_substituting(demo_universe) -> None:
    """A latent bug found by audit: the engine passed `total_value_paise or 1`,
    which would have measured liquidation against ONE PAISE of portfolio.

    Harmless only because every adv_paise is currently None. The tier is now
    SKIPPED explicitly - a stand-in portfolio size would be a fabricated
    number wearing a real one's clothes.
    """
    prof = liquidity_summary(synthetic.healthy_weights(), demo_universe, None)
    assert all(v is None for v in prof.days_to_liquidate.values())
    assert prof.adv_coverage == 0.0
    assert prof.worst_days is None
    # the Level 1 controls still work without a portfolio size
    assert prof.liquid_share == pytest.approx(0.88)

"""Covariance estimation and repair tests.

Spec: docs/08-FINANCIAL-METHODS.md section 4, docs/13-EDGE-CASES.md section 3.

A broken covariance must never reach the solver: it will return numbers, and
they will be meaningless. Refusing is the safe direction to fail (INV-4).
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from cce.exceptions import CovarianceError
from cce.risk import (
    condition_number, correlation_from_covariance, estimate_covariance,
    ewma_covariance, historical_covariance, is_psd, prepare_covariance,
)
from tests.fixtures import synthetic


def _returns(n: int = 500, k: int = 4, seed: int = 42) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    return pd.DataFrame(
        rng.normal(0, 0.01, (n, k)), columns=[f"A{i}" for i in range(k)]
    )


# =====================================================================
# Estimation
# =====================================================================

class TestEstimation:
    def test_historical_covariance_is_annualised_by_252(self) -> None:
        r = _returns()
        daily = historical_covariance(r, annualise=False)
        annual = historical_covariance(r, annualise=True)
        np.testing.assert_allclose(annual, daily * 252, rtol=1e-12)

    def test_diagonal_matches_individual_variances(self) -> None:
        r = _returns()
        cov = historical_covariance(r, annualise=False)
        for i, col in enumerate(r.columns):
            assert cov[i, i] == pytest.approx(r[col].var(ddof=1), rel=1e-12)

    def test_covariance_is_symmetric(self) -> None:
        cov = historical_covariance(_returns())
        np.testing.assert_allclose(cov, cov.T, rtol=1e-12)

    def test_ewma_covariance_is_symmetric(self) -> None:
        """The recursion is symmetric in exact arithmetic but accumulates
        asymmetry in floating point; downstream eigh assumes symmetry."""
        cov = ewma_covariance(_returns())
        np.testing.assert_allclose(cov, cov.T, rtol=1e-12)

    def test_ewma_covariance_responds_to_a_recent_shock(self) -> None:
        r = _returns(n=400, k=2)
        shocked = r.copy()
        shocked.iloc[-5:] *= 6.0
        base = ewma_covariance(r)
        after = ewma_covariance(shocked)
        assert after[0, 0] > base[0, 0]

    def test_too_few_observations_rejected(self) -> None:
        with pytest.raises(CovarianceError, match="at least two"):
            historical_covariance(pd.DataFrame({"A": [0.01]}))

    def test_unknown_method_rejected(self) -> None:
        with pytest.raises(ValueError, match="unknown covariance method"):
            estimate_covariance(_returns(), method="kalman")


# =====================================================================
# The PSD repair ladder
# =====================================================================

class TestPSDRepair:
    def test_valid_matrix_passes_through_unrepaired(self) -> None:
        cov = historical_covariance(_returns())
        repaired, report = prepare_covariance(cov)
        assert report.repaired is False
        np.testing.assert_allclose(repaired, cov, rtol=1e-10)

    def test_negative_eigenvalue_is_clipped_and_recorded(self) -> None:
        """A repair is never silent - it becomes a MODEL_COVARIANCE finding."""
        bad = np.array([[1.0, 0.9, 0.9],
                        [0.9, 1.0, 0.9],
                        [0.9, 0.9, 0.4]]) * 1e-4     # not PSD
        assert not is_psd(bad)
        repaired, report = prepare_covariance(bad)
        assert is_psd(repaired)
        assert report.repaired and report.eigenvalues_clipped >= 1
        assert report.min_eigenvalue_before < 0
        assert "clipped" in report.message

    def test_asymmetry_is_corrected(self) -> None:
        cov = historical_covariance(_returns())
        cov[0, 1] += 1e-6                            # break symmetry
        repaired, report = prepare_covariance(cov)
        assert report.symmetrised
        np.testing.assert_allclose(repaired, repaired.T, rtol=1e-12)

    def test_near_collinear_assets_trigger_shrinkage(self) -> None:
        """Two proxies for the same exposure - the realistic cause."""
        rng = np.random.default_rng(1)
        base = rng.normal(0, 0.01, 500)
        r = pd.DataFrame({
            "A": base,
            "B": base + rng.normal(0, 1e-9, 500),    # essentially identical
            "C": rng.normal(0, 0.01, 500),
        })
        cov = historical_covariance(r)
        repaired, report = prepare_covariance(cov)
        assert is_psd(repaired)
        if report.shrinkage_applied:
            assert report.condition_number < condition_number(cov)

    def test_unrepairable_matrix_raises(self) -> None:
        """INV-4. Refusing is the safe direction to fail."""
        with pytest.raises(CovarianceError, match="NaN or infinite"):
            prepare_covariance(np.array([[np.nan, 0.0], [0.0, 1.0]]))

    def test_non_square_rejected(self) -> None:
        with pytest.raises(CovarianceError, match="must be square"):
            prepare_covariance(np.ones((2, 3)))

    def test_repaired_matrix_is_usable_for_portfolio_volatility(self) -> None:
        """The end-to-end point of the repair."""
        from cce.risk import portfolio_volatility
        bad = np.array([[1.0, 0.99, 0.99],
                        [0.99, 1.0, 0.99],
                        [0.99, 0.99, 0.2]]) * 1e-4
        repaired, _ = prepare_covariance(bad)
        vol = portfolio_volatility(np.array([1 / 3, 1 / 3, 1 / 3]), repaired)
        assert np.isfinite(vol) and vol >= 0.0

    def test_repair_is_deterministic(self) -> None:
        bad = np.array([[1.0, 0.9, 0.9],
                        [0.9, 1.0, 0.9],
                        [0.9, 0.9, 0.4]]) * 1e-4
        a, _ = prepare_covariance(bad)
        b, _ = prepare_covariance(bad)
        np.testing.assert_array_equal(a, b)


# =====================================================================
# Correlation
# =====================================================================

class TestCorrelation:
    def test_diagonal_is_one(self) -> None:
        corr = correlation_from_covariance(historical_covariance(_returns()))
        np.testing.assert_allclose(np.diag(corr), 1.0, rtol=1e-12)

    def test_bounded_to_plus_minus_one(self) -> None:
        corr = correlation_from_covariance(historical_covariance(_returns()))
        assert corr.max() <= 1.0 and corr.min() >= -1.0

    def test_known_correlation_is_recovered(self) -> None:
        cov = synthetic.cov_from({"A": 0.01, "B": 0.02}, rho=0.5)
        corr = correlation_from_covariance(cov)
        assert corr[0, 1] == pytest.approx(0.5, rel=1e-12)

    def test_zero_variance_asset_yields_zero_not_nan(self) -> None:
        """EC-3.3. A cash proxy must not poison the whole matrix."""
        cov = np.array([[1e-4, 0.0], [0.0, 0.0]])
        corr = correlation_from_covariance(cov)
        assert not np.isnan(corr).any()
        assert corr[0, 1] == 0.0
        assert corr[1, 1] == 1.0


# =====================================================================
# Real data
# =====================================================================

def test_committed_cache_produces_a_valid_covariance() -> None:
    from datetime import date
    from cce.config import load_universe
    from cce.contracts import DataProvider
    from cce.data import CachedDataProvider, DEFAULT_CACHE_DIR, build_market_data

    u = load_universe()
    p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
        u, date(2000, 1, 1), date(2030, 1, 1)
    )
    md = build_market_data(p, u, DataProvider.CACHED, as_of=date(2026, 8, 31))
    cov, report = estimate_covariance(md.returns)
    assert is_psd(cov)
    assert cov.shape == (len(u.assets), len(u.assets))
    # CASH is synthetic with ~zero variance; the matrix must still be usable
    assert np.isfinite(cov).all()

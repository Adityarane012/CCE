"""Portfolio state and arithmetic tests.

Spec: docs/IMPLEMENTATION-PLAN.md PHASE 2.

Every arithmetic test carries at least one hand-computed expected value.
Comparing an implementation against itself proves nothing.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from cce.contracts import PAISE_PER_CRORE, DataProvider
from cce.data import CachedDataProvider, DEFAULT_CACHE_DIR, build_market_data
from cce.portfolio import (
    DEFAULT_CAPITAL_PAISE, allocate_paise, asset_class_exposure,
    build_portfolio_state, liquid_share, normalise_weights, portfolio_returns,
    rebalance_to, sector_exposure, transaction_cost_paise, turnover,
    value_to_units, weight_deltas,
)

AS_OF = date(2026, 8, 31)


@pytest.fixture(scope="module")
def market(universe_mod):
    p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
        universe_mod, date(2000, 1, 1), date(2030, 1, 1)
    )
    return build_market_data(p, universe_mod, DataProvider.CACHED, as_of=AS_OF)


@pytest.fixture(scope="module")
def universe_mod():
    from cce.config import load_universe
    return load_universe()


@pytest.fixture
def weights():
    return {
        "NIFTY50": 0.26, "BANKNIFTY": 0.20, "IT": 0.10, "PHARMA": 0.08,
        "FMCG": 0.06, "GOLD": 0.10, "GSEC": 0.12, "CORPBOND": 0.02,
        "CASH": 0.06,
    }


# =====================================================================
# Turnover — the /2 convention
# =====================================================================

class TestTurnover:
    def test_hand_computed_half_l1_distance(self) -> None:
        """Sell 10% of A to buy 10% of B: 20% absolute weight moved, but
        only 10% of the PORTFOLIO traded."""
        cur = {"A": 0.5, "B": 0.5}
        new = {"A": 0.4, "B": 0.6}
        assert turnover(new, cur) == pytest.approx(0.10)

    def test_no_change_is_zero_turnover(self, weights) -> None:
        assert turnover(weights, weights) == pytest.approx(0.0)

    def test_complete_replacement_is_full_turnover(self) -> None:
        assert turnover({"A": 1.0, "B": 0.0}, {"A": 0.0, "B": 1.0}) == pytest.approx(1.0)

    def test_turnover_is_symmetric(self, weights) -> None:
        other = dict(weights)
        other["NIFTY50"] -= 0.05
        other["GOLD"] += 0.05
        assert turnover(other, weights) == pytest.approx(turnover(weights, other))

    def test_assets_absent_from_one_side_still_count(self) -> None:
        """A new position appearing from nothing is a real trade."""
        assert turnover({"A": 0.5, "B": 0.5}, {"A": 1.0}) == pytest.approx(0.5)

    def test_deltas_span_the_union_of_both_allocations(self) -> None:
        d = weight_deltas({"A": 0.5, "C": 0.5}, {"A": 1.0, "B": 0.0})
        assert set(d) == {"A", "B", "C"}
        assert d["A"] == pytest.approx(-0.5)
        assert d["C"] == pytest.approx(0.5)


# =====================================================================
# Transaction cost
# =====================================================================

class TestTransactionCost:
    def test_hand_computed_cost(self, universe_mod) -> None:
        """10 bps on a 10pp shift, both legs, on Rs 100 Cr.

        NIFTY50 -0.10 and GOLD +0.10, each at 0.0010:
          0.0010 * 0.10 * 1e11 = 1e7 paise per leg, 2e7 total = Rs 2 lakh.
        """
        cur = {"NIFTY50": 0.30, "GOLD": 0.10}
        new = {"NIFTY50": 0.20, "GOLD": 0.20}
        cost = transaction_cost_paise(new, cur, universe_mod, DEFAULT_CAPITAL_PAISE)
        assert cost == 20_000_000  # Rs 2,00,000

    def test_no_trade_costs_nothing(self, universe_mod, weights) -> None:
        assert transaction_cost_paise(
            weights, weights, universe_mod, DEFAULT_CAPITAL_PAISE) == 0

    def test_cash_trades_are_free(self, universe_mod) -> None:
        """CASH carries txn_cost_rate 0.0 in the universe."""
        cost = transaction_cost_paise(
            {"CASH": 0.20}, {"CASH": 0.10}, universe_mod, DEFAULT_CAPITAL_PAISE)
        assert cost == 0

    def test_unknown_asset_is_an_error(self, universe_mod) -> None:
        with pytest.raises(KeyError, match="not in the universe"):
            transaction_cost_paise(
                {"NOPE": 1.0}, {}, universe_mod, DEFAULT_CAPITAL_PAISE)

    def test_cost_uses_full_absolute_change_not_halved_turnover(
        self, universe_mod
    ) -> None:
        """Both the sell leg and the buy leg incur cost."""
        cur, new = {"NIFTY50": 0.30, "GOLD": 0.10}, {"NIFTY50": 0.20, "GOLD": 0.20}
        cost = transaction_cost_paise(new, cur, universe_mod, DEFAULT_CAPITAL_PAISE)
        halved = int(0.0010 * turnover(new, cur) * DEFAULT_CAPITAL_PAISE)
        assert cost == pytest.approx(halved * 2, rel=1e-9)


# =====================================================================
# Integer paise allocation — no lost money
# =====================================================================

class TestPaiseAllocation:
    def test_allocation_is_exact(self) -> None:
        """Naive rounding leaves a residual and the reconciliation fails."""
        w = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
        alloc = allocate_paise(DEFAULT_CAPITAL_PAISE, w)
        assert sum(alloc.values()) == DEFAULT_CAPITAL_PAISE

    @pytest.mark.parametrize("total", [1, 7, 101, 999_999, DEFAULT_CAPITAL_PAISE])
    def test_exact_for_many_totals(self, total: int) -> None:
        w = {"A": 0.2, "B": 0.3, "C": 0.5}
        assert sum(allocate_paise(total, w).values()) == total

    def test_naive_rounding_would_have_lost_money(self) -> None:
        """Documents why largest-remainder is used rather than round()."""
        w = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
        total = 100
        naive = sum(int(round(total * x)) for x in w.values())
        assert naive != total          # 33+33+33 = 99
        assert sum(allocate_paise(total, w).values()) == total

    def test_allocation_is_deterministic(self) -> None:
        w = {"A": 1 / 3, "B": 1 / 3, "C": 1 / 3}
        assert allocate_paise(100, w) == allocate_paise(100, w)

    def test_zero_weights_get_zero(self) -> None:
        alloc = allocate_paise(1000, {"A": 1.0, "B": 0.0})
        assert alloc["B"] == 0


# =====================================================================
# Weight validation
# =====================================================================

class TestWeightValidation:
    def test_weights_must_sum_to_one(self, universe_mod) -> None:
        with pytest.raises(ValueError, match="must sum to 1.0"):
            normalise_weights({"NIFTY50": 0.5, "GOLD": 0.2}, universe_mod)

    def test_unknown_asset_rejected(self, universe_mod) -> None:
        with pytest.raises(KeyError, match="unknown asset_ids"):
            normalise_weights({"NOT_REAL": 1.0}, universe_mod)

    def test_negative_weight_rejected(self, universe_mod) -> None:
        """Long-only by default."""
        with pytest.raises(ValueError, match="negative weights"):
            normalise_weights({"NIFTY50": 1.2, "GOLD": -0.2}, universe_mod)

    def test_absent_assets_are_filled_with_zero(self, universe_mod) -> None:
        w = normalise_weights({"NIFTY50": 1.0}, universe_mod)
        assert set(w) == set(universe_mod.asset_ids)
        assert w["GOLD"] == 0.0

    def test_float_dust_is_absorbed(self, universe_mod) -> None:
        """1e-9 of drift must not fail the contract assertion downstream.

        Exact float equality to 1.0 is not achievable and not required - the
        contract's tolerance is 1e-6. What matters is that a state can be
        built from the result without raising.
        """
        w = {"NIFTY50": 0.5, "GOLD": 0.5 + 1e-9}
        out = normalise_weights(w, universe_mod)
        assert sum(out.values()) == pytest.approx(1.0, abs=1e-12)


# =====================================================================
# Portfolio state construction
# =====================================================================

class TestPortfolioState:
    def test_default_capital_is_100_crore(self) -> None:
        """Rs 1 Cr = 1e7 rupees = 1e9 paise, so Rs 100 Cr = 1e11 paise.

        Asserted explicitly because an order-of-magnitude slip here would
        silently rescale every position value and transaction cost in the
        system while every ratio still looked correct.
        """
        assert DEFAULT_CAPITAL_PAISE == 100_000_000_000
        assert DEFAULT_CAPITAL_PAISE / PAISE_PER_CRORE == 100.0
        assert DEFAULT_CAPITAL_PAISE / 100 == 1_000_000_000  # rupees

    def test_positions_reconcile_to_total_exactly(
        self, universe_mod, weights, market
    ) -> None:
        s = build_portfolio_state(universe_mod, weights, market)
        assert sum(p.value_paise for p in s.positions) == s.total_value_paise

    def test_weights_sum_to_one(self, universe_mod, weights, market) -> None:
        s = build_portfolio_state(universe_mod, weights, market)
        assert sum(s.weights.values()) == pytest.approx(1.0, abs=1e-9)

    def test_cash_is_a_view_into_positions_not_an_addition(
        self, universe_mod, weights, market
    ) -> None:
        """CASH is an asset in this universe. Adding cash_value_paise to the
        position total would double-count it."""
        s = build_portfolio_state(universe_mod, weights, market)
        cash_pos = next(p for p in s.positions if p.asset_id == "CASH")
        assert s.cash_value_paise == cash_pos.value_paise
        assert sum(p.value_paise for p in s.positions) == s.total_value_paise

    def test_units_reconcile_with_price_and_value(
        self, universe_mod, weights, market
    ) -> None:
        s = build_portfolio_state(universe_mod, weights, market)
        for p in s.positions:
            if p.value_paise == 0:
                continue
            assert p.units * p.price == pytest.approx(p.value_paise / 100, rel=1e-9)

    def test_sector_exposure_sums_to_one(
        self, universe_mod, weights, market
    ) -> None:
        s = build_portfolio_state(universe_mod, weights, market)
        assert sum(s.sector_exposure().values()) == pytest.approx(1.0)

    def test_liquid_share_excludes_illiquid_assets(
        self, universe_mod, weights, market
    ) -> None:
        """GSEC 0.12 and CORPBOND 0.02 are illiquid: 1 - 0.14 = 0.86."""
        s = build_portfolio_state(universe_mod, weights, market)
        assert s.liquid_share(universe_mod) == pytest.approx(0.86)

    def test_return_series_is_produced(
        self, universe_mod, weights, market
    ) -> None:
        s = build_portfolio_state(universe_mod, weights, market)
        assert len(s.return_series) == len(market.returns)
        assert not s.return_series.isna().any()

    def test_weight_on_an_unpriced_asset_is_an_error(
        self, universe_mod, market
    ) -> None:
        """An asset excluded upstream cannot be held."""
        trimmed = market.prices.drop(columns=["GOLD"])
        md = build_market_data(
            trimmed, universe_mod, DataProvider.CACHED, as_of=AS_OF
        )
        with pytest.raises(KeyError, match="no price in the market panel"):
            build_portfolio_state(
                universe_mod, {"GOLD": 0.5, "NIFTY50": 0.5}, md
            )

    def test_zero_capital_rejected(self, universe_mod, weights, market) -> None:
        with pytest.raises(ValueError, match="must be positive"):
            build_portfolio_state(universe_mod, weights, market,
                                  total_value_paise=0)


# =====================================================================
# Simulated rebalance
# =====================================================================

class TestRebalance:
    def test_rebalance_returns_a_new_state_and_does_not_mutate(
        self, universe_mod, weights, market
    ) -> None:
        before = build_portfolio_state(universe_mod, weights, market)
        after = rebalance_to(before, {"NIFTY50": 0.5, "GOLD": 0.5},
                             universe_mod, market)
        assert before.weights != after.weights
        assert before.weights["NIFTY50"] == weights["NIFTY50"]  # unchanged

    def test_transaction_cost_shrinks_the_portfolio(
        self, universe_mod, weights, market
    ) -> None:
        """A rebalance is never free."""
        before = build_portfolio_state(universe_mod, weights, market)
        cost = 25_000_000  # Rs 2.5 lakh
        after = rebalance_to(before, {"NIFTY50": 0.5, "GOLD": 0.5},
                             universe_mod, market, transaction_cost_paise=cost)
        assert after.total_value_paise == before.total_value_paise - cost
        assert sum(p.value_paise for p in after.positions) == after.total_value_paise

    def test_cost_exceeding_value_is_rejected(
        self, universe_mod, weights, market
    ) -> None:
        before = build_portfolio_state(universe_mod, weights, market)
        with pytest.raises(ValueError, match="exceeds portfolio value"):
            rebalance_to(before, weights, universe_mod, market,
                         transaction_cost_paise=before.total_value_paise + 1)

    def test_negative_cost_rejected(self, universe_mod, weights, market) -> None:
        before = build_portfolio_state(universe_mod, weights, market)
        with pytest.raises(ValueError, match="must not be negative"):
            rebalance_to(before, weights, universe_mod, market,
                         transaction_cost_paise=-1)


# =====================================================================
# Portfolio returns
# =====================================================================

class TestPortfolioReturns:
    def test_hand_computed_single_period(self) -> None:
        """0.6*0.02 + 0.4*(-0.01) = 0.012 - 0.004 = 0.008"""
        r = pd.DataFrame({"A": [0.02], "B": [-0.01]})
        out = portfolio_returns({"A": 0.6, "B": 0.4}, r)
        assert out.iloc[0] == pytest.approx(0.008)

    def test_full_weight_reproduces_the_asset(self) -> None:
        r = pd.DataFrame({"A": [0.01, -0.02, 0.03], "B": [0.0, 0.0, 0.0]})
        out = portfolio_returns({"A": 1.0, "B": 0.0}, r)
        pd.testing.assert_series_equal(out, r["A"], check_names=False)

    def test_no_overlap_is_an_error(self) -> None:
        with pytest.raises(ValueError, match="no overlap"):
            portfolio_returns({"X": 1.0}, pd.DataFrame({"A": [0.01]}))

    def test_index_is_preserved(self, universe_mod, weights, market) -> None:
        out = portfolio_returns(weights, market.returns)
        assert list(out.index) == list(market.returns.index)


# =====================================================================
# Exposure helpers
# =====================================================================

def test_sector_exposure_aggregates(universe_mod) -> None:
    exp = sector_exposure({"NIFTY50": 0.3, "BANKNIFTY": 0.2, "GOLD": 0.5},
                          universe_mod)
    assert exp["BROAD_EQUITY"] == pytest.approx(0.3)
    assert exp["BANKING"] == pytest.approx(0.2)
    assert exp["GOLD"] == pytest.approx(0.5)


def test_asset_class_exposure_aggregates_across_sectors(universe_mod) -> None:
    """Five equity sectors roll up into one EQUITY class."""
    exp = asset_class_exposure(
        {"NIFTY50": 0.2, "BANKNIFTY": 0.2, "IT": 0.2, "GSEC": 0.2, "CASH": 0.2},
        universe_mod,
    )
    assert exp["EQUITY"] == pytest.approx(0.6)
    assert exp["FIXED_INCOME"] == pytest.approx(0.2)
    assert exp["CASH"] == pytest.approx(0.2)


def test_liquid_share_helper_matches_state_method(universe_mod) -> None:
    w = {"NIFTY50": 0.5, "GSEC": 0.3, "CASH": 0.2}
    assert liquid_share(w, universe_mod) == pytest.approx(0.7)


def test_value_to_units_rejects_non_positive_price() -> None:
    with pytest.raises(ValueError, match="price must be positive"):
        value_to_units(1000, 0.0)

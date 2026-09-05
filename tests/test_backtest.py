"""Walk-forward backtest.

Spec: docs/08-FINANCIAL-METHODS.md section 14,
docs/IMPLEMENTATION-PLAN.md PHASE 12.

One test carries this whole phase: ``test_rebalance_uses_only_prior_data``.
Look-ahead is the single bug that would invalidate every number a backtest
produces, and it does not announce itself — the leaked curve looks BETTER,
which is exactly why it survives review.
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from cce.backtest import (
    BacktestConfig,
    compare,
    compute_metrics,
    estimation_window,
    rebalance_dates,
    run_backtest,
)
from tests.fixtures import synthetic


@pytest.fixture(scope="module")
def panel():
    """Three years of daily returns for the demo universe."""
    universe = synthetic.demo_universe()
    ids = [a.asset_id for a in universe.assets]
    rng = np.random.default_rng(11)
    idx = pd.bdate_range(end=pd.Timestamp("2026-08-31"), periods=780)
    frame = pd.DataFrame(
        rng.normal(0.0004, 0.010, (len(idx), len(ids))), columns=ids, index=idx
    )
    return universe, frame


@pytest.fixture
def config():
    return BacktestConfig(
        start=date(2025, 1, 1), end=date(2026, 8, 31),
        rebalance="MONTHLY", min_window=250,
    )


def equal_weight_proposer(window: pd.DataFrame, current: dict[str, float]):
    """A proposer whose answer depends ONLY on the window it is shown.

    Deliberately data-dependent: it returns weights proportional to inverse
    volatility over the window. If any future data reaches the window, these
    weights change — which is what makes the look-ahead test meaningful. A
    constant proposer would pass the test while proving nothing.
    """
    vol = window.std(ddof=1)
    inv = 1.0 / vol.replace(0.0, np.nan)
    inv = inv.fillna(0.0)
    total = inv.sum()
    if total <= 0:
        return None
    return {a: float(v / total) for a, v in inv.items()}


def always_passes(weights, window, current):
    return True, []


def always_fails(weights, window, current):
    return False, ["FORCED_BREACH"]


# ---------------------------------------------------------------------------
# INV-7 — the test that carries the phase
# ---------------------------------------------------------------------------

def test_rebalance_uses_only_prior_data(panel, config):
    """INV-7. Shift every future return; every decision must be identical.

    The mechanism: run the backtest twice. In the second run every return
    from a chosen date onward is shifted by a large constant. A decision
    taken BEFORE that date cannot legitimately change — if any does, the
    estimation window is reaching forward in time.

    The proposer is recorded on both runs, so this compares the actual
    weights that were asked for, not just the final equity curve. A curve
    can coincide by luck; a full decision sequence cannot.
    """
    universe, returns = panel
    decisions_a: list[dict] = []
    decisions_b: list[dict] = []

    def record(store):
        def _propose(window, current):
            weights = equal_weight_proposer(window, current)
            store.append((window.index[-1], weights))
            return weights
        return _propose

    run_backtest(
        returns, universe, None, config, record(decisions_a), always_passes
    )

    # Contaminate the future: every return from the midpoint onward.
    cut = returns.index[len(returns) // 2]
    poisoned = returns.copy()
    poisoned.loc[poisoned.index >= cut] += 0.05

    run_backtest(
        poisoned, universe, None, config, record(decisions_b), always_passes
    )

    before_a = [(t, w) for t, w in decisions_a if t < cut]
    before_b = [(t, w) for t, w in decisions_b if t < cut]

    assert before_a, "no decisions were taken before the contamination point"
    assert len(before_a) == len(before_b)

    for (ta, wa), (tb, wb) in zip(before_a, before_b, strict=True):
        assert ta == tb
        for asset in wa:
            assert wa[asset] == pytest.approx(wb[asset], abs=1e-12), (
                f"decision at {ta} changed when FUTURE data moved — the "
                f"estimation window is leaking (INV-7)"
            )


def test_a_one_day_leak_is_detected(panel, config):
    """INV-7, sharpened to the leak that actually happens.

    The broad shift above catches gross leakage but NOT an off-by-one: with
    an inclusive ``.loc[:t]`` bound the window gains exactly one day, and if
    the contamination starts mid-panel every decision before it is still
    clean. The test passes and the bug ships.

    So this contaminates from a REBALANCE DATE onward and checks the decision
    taken AT that date. A correct window excludes it entirely, so the weights
    cannot move. An inclusive bound sees the poisoned row and they do.

    Verified by injecting the bug: flipping ``<`` to ``<=`` in
    ``estimation_window`` makes this fail.
    """
    universe, returns = panel

    # Derived exactly as run_backtest derives them — range-filtered FIRST.
    # Computing them over the whole panel gives a different list, and the
    # call index then points at a different decision than intended.
    in_range = returns.loc[
        (returns.index >= pd.Timestamp(config.start))
        & (returns.index <= pd.Timestamp(config.end))
    ]
    dates = [
        d for d in rebalance_dates(in_range.index, config.rebalance)
        if len(estimation_window(returns, d)) >= config.min_window
    ]
    target = dates[len(dates) // 2]
    position = dates.index(target)

    def decision_at(frame):
        """The weights proposed on the ``position``-th rebalance.

        Indexed by CALL ORDER, not by the window's last date. Keying on the
        window would defeat the test: an inclusive bound changes that very
        date, so the lookup would quietly select a different, uncontaminated
        decision and the leak would pass unnoticed. (It did, the first time
        this was written.)
        """
        seen: list[dict] = []

        def _propose(window, current):
            weights = equal_weight_proposer(window, current)
            seen.append(weights)
            return weights

        run_backtest(frame, universe, None, config, _propose, always_passes)
        return seen[position] if position < len(seen) else None

    clean = decision_at(returns)

    poisoned = returns.copy()
    poisoned.loc[poisoned.index >= target] += 0.20   # only from `target` on

    leaked = decision_at(poisoned)

    assert clean is not None and leaked is not None
    for asset in clean:
        assert clean[asset] == pytest.approx(leaked[asset], abs=1e-12), (
            f"the decision at {target} moved when only data AT AND AFTER that "
            f"date changed — the window includes the rebalance date (INV-7)"
        )


def test_the_estimation_window_excludes_the_rebalance_date(panel):
    """The rebalance date's own return is an OUTCOME, not evidence.

    ``.loc[:t]`` in pandas includes ``t``. That one inclusive bound would
    leak a day of the future into every decision, and nothing downstream
    would look wrong.
    """
    _universe, returns = panel
    t = returns.index[400]
    window = estimation_window(returns, t)

    assert t not in window.index
    assert window.index.max() < t
    assert len(window) == 400


def test_the_window_grows_as_the_walk_advances(panel):
    _universe, returns = panel
    early = estimation_window(returns, returns.index[300])
    late = estimation_window(returns, returns.index[600])
    assert len(late) > len(early)


def test_rebalance_dates_come_from_the_observed_calendar(panel):
    """A month-end that was a market holiday is not a rebalance date."""
    _universe, returns = panel
    dates = rebalance_dates(returns.index, "MONTHLY")
    assert dates
    assert all(d in returns.index for d in dates), (
        "a rebalance date is not a trading day in the panel"
    )
    assert dates == sorted(dates)


def test_weekly_rebalancing_produces_more_dates_than_monthly(panel):
    _universe, returns = panel
    weekly = rebalance_dates(returns.index, "WEEKLY")
    monthly = rebalance_dates(returns.index, "MONTHLY")
    assert len(weekly) > len(monthly)


# ---------------------------------------------------------------------------
# The three-way comparison
# ---------------------------------------------------------------------------

def test_all_three_strategies_run_on_identical_data(panel, config):
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    assert set(run.strategies) == {
        "BUY_AND_HOLD", "UNCONTROLLED_OPTIMIZER", "CCE_CONTROLLED"
    }
    for strategy in run.strategies.values():
        assert len(strategy.equity_curve) == len(run.rebalance_dates)


def test_buy_and_hold_never_trades(panel, config):
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    bah = run.get("BUY_AND_HOLD")
    assert bah.rebalances == 0
    assert bah.transaction_cost_paise == 0
    assert not bah.turnovers


def test_the_controlled_strategy_holds_when_validation_fails(panel, config):
    """The whole comparison in one assertion.

    With validation always failing, the controlled strategy must never adopt
    a proposal — it holds the last allocation that passed. The uncontrolled
    one adopts every recommendation regardless, which is the behaviour the
    control layer exists to prevent.
    """
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_fails
    )
    controlled = run.get("CCE_CONTROLLED")
    uncontrolled = run.get("UNCONTROLLED_OPTIMIZER")

    assert controlled.rebalances == 0, "the controlled strategy adopted a failure"
    assert controlled.holds > 0
    assert controlled.breaker_activations > 0
    assert uncontrolled.rebalances > 0, "the uncontrolled strategy did not trade"
    assert uncontrolled.policy_breaches > 0


def test_the_controlled_strategy_adopts_when_validation_passes(panel, config):
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    controlled = run.get("CCE_CONTROLLED")
    assert controlled.rebalances > 0
    assert controlled.holds == 0
    assert controlled.breaker_activations == 0


def test_a_rebalance_is_never_free(panel, config):
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    unc = run.get("UNCONTROLLED_OPTIMIZER")
    assert unc.transaction_cost_paise > 0
    assert all(t >= 0 for t in unc.turnovers)


def test_a_proposer_that_returns_nothing_leaves_the_book_alone(panel, config):
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, lambda w, c: None, always_passes
    )
    for strategy in run.strategies.values():
        assert strategy.rebalances == 0


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def test_metrics_report_governance_alongside_return(panel, config):
    """The breach count and breaker activations carry equal weight to return.

    The question is not "did it make more money" but "did it improve the
    return/risk balance while reducing policy breaches and drawdowns".
    """
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_fails
    )
    metrics = compare(run)

    assert set(metrics) == set(run.strategies)
    controlled = metrics["CCE_CONTROLLED"]
    assert controlled.policy_breach_count == 0
    assert controlled.breaker_activations > 0
    assert metrics["UNCONTROLLED_OPTIMIZER"].policy_breach_count > 0


def test_metrics_are_none_rather_than_zero_when_uncomputable(panel):
    """INV-5 in the backtest: too few observations is not a zero result."""
    from cce.backtest import StrategyRun

    empty = StrategyRun(
        name="X", equity_curve=pd.Series(dtype=float), weights_history=[],
        turnovers=[], transaction_cost_paise=0, policy_breaches=0,
        breaker_activations=0, rebalances=0,
    )
    m = compute_metrics(empty)
    assert m.cumulative_return is None
    assert m.volatility is None
    assert m.sharpe is None
    assert m.avg_turnover is None


def test_annualisation_uses_the_observed_cadence(panel, config):
    """A monthly curve annualised as if daily inflates volatility ~4.6x."""
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    m = compute_metrics(run.get("BUY_AND_HOLD"))
    assert m.volatility is not None
    assert 0.0 < m.volatility < 1.0, (
        f"volatility {m.volatility} is implausible for a monthly series — "
        "the annualisation factor is probably wrong"
    )


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

def test_an_impossible_window_is_refused(panel):
    """Never silently produce a backtest with no valid decision point."""
    universe, returns = panel
    with pytest.raises(ValueError, match="prior observations"):
        run_backtest(
            returns, universe, None,
            BacktestConfig(
                start=date(2025, 1, 1), end=date(2026, 8, 31),
                min_window=10_000,
            ),
            equal_weight_proposer, always_passes,
        )


def test_an_empty_range_is_refused(panel):
    universe, returns = panel
    with pytest.raises(ValueError, match="no returns"):
        run_backtest(
            returns, universe, None,
            BacktestConfig(start=date(1990, 1, 1), end=date(1990, 12, 31)),
            equal_weight_proposer, always_passes,
        )


def test_config_rejects_a_bad_cadence():
    with pytest.raises(ValueError, match="MONTHLY or WEEKLY"):
        BacktestConfig(
            start=date(2025, 1, 1), end=date(2026, 1, 1), rebalance="DAILY"
        )


def test_config_rejects_an_inverted_range():
    with pytest.raises(ValueError, match="end must be after start"):
        BacktestConfig(start=date(2026, 1, 1), end=date(2025, 1, 1))


def test_drawdown_is_computed_from_returns_not_levels(panel, config):
    """max_drawdown builds its own cumulative series, so it takes RETURNS.

    Handing it the equity curve reports 0.0% for every strategy — silently,
    and on one of the two metrics the whole comparison turns on. Caught by
    printing the table and noticing three identical zeros.
    """
    universe, returns = panel
    run = run_backtest(
        returns, universe, None, config, equal_weight_proposer, always_passes
    )
    metrics = compute_metrics(run.get("BUY_AND_HOLD"))
    assert metrics.max_drawdown is not None
    assert metrics.max_drawdown > 0.0, (
        "a two-year equity curve with zero drawdown means levels were passed "
        "where returns were expected"
    )

"""Page 6 — Backtesting.

Spec: docs/09-UI-SPEC.md section 9, docs/08-FINANCIAL-METHODS.md section 14.

The page exists to answer one question honestly: **what did the control layer
cost, and what did it buy?** On a single sample the controlled strategy will
usually earn LESS than the uncontrolled optimizer. That is not a result to
hide behind a chart — it is the result, and the caption says so in the same
visual weight as the return column.

Breach and breaker counts sit in the same table as return, not in a footnote.
A strategy that earned more by breaching policy twenty-seven times did not
"outperform"; it ran a different, riskier mandate.
"""

from __future__ import annotations

from datetime import date

import streamlit as st

from cce.contracts import BacktestConfig
from ui.components.charts import STRATEGY_LABELS, drawdown_curves, equity_curves
from ui.components.format import DASH, crore, pct, ratio
from ui.state import Services

#: Order is deliberate: the naive baseline, then the tempting one, then ours.
#: A reader scanning top to bottom meets the uncontrolled optimizer's higher
#: return BEFORE the controlled row, which is the honest way round.
STRATEGY_ORDER = ("BUY_AND_HOLD", "UNCONTROLLED_OPTIMIZER", "CCE_CONTROLLED")

_LOOK_AHEAD_NOTE = """
**No look-ahead bias.** At each rebalance date `t` the estimation window is
everything strictly *before* `t` — the rebalance date's own return belongs to
the outcome period, never to the estimate that produced the trade. Rebalance
dates come from the observed trading calendar, so a month-end that fell on a
market holiday is not a trading day here either. This is invariant INV-7, and
`tests/test_invariants.py` verifies it by shifting every future return and
asserting that no earlier decision moves.
"""


def render(svc: Services) -> None:
    st.header("Backtesting — controlled vs uncontrolled")
    st.caption(
        "The same data, the same optimizer, the same dates. The only "
        "difference is whether an independent control engine may reject a "
        "proposal."
    )

    try:
        first, last = svc.backtest.available_range()
    except Exception as exc:  # noqa: BLE001 - a missing panel is not a crash
        st.error(f"Market data could not be read: {exc}", icon="⚠")
        return

    config = _controls(first, last)
    if config is None:
        return

    if st.button("Run backtest", type="primary"):
        _execute(svc, config)

    stored = st.session_state.get("cce_backtest")
    if stored is None:
        st.info(
            "Choose a range and run the backtest. A walk-forward run "
            "re-optimizes at every rebalance date, so it takes a moment.",
            icon="ℹ",
        )
    else:
        _results(svc, stored)

    # Shown whether or not a run has happened. The construction is what makes
    # the numbers admissible, so a reader should be able to check it BEFORE
    # deciding whether to trust a result — not only after one appears.
    st.markdown(_LOOK_AHEAD_NOTE)
    st.caption(
        f"A dash ({DASH}) means the metric was not computed, never that it "
        "was zero. Past results from a single historical sample are not a "
        "forecast; this is a decision-support prototype."
    )


def _controls(first: date, last: date) -> BacktestConfig | None:
    """Date range, cadence and minimum window.

    Bounded by what the loaded panel actually covers: a range the data cannot
    support is unselectable rather than an error after the run.
    """
    c1, c2, c3 = st.columns([2, 1, 1])

    with c1:
        chosen = st.date_input(
            "Backtest range",
            value=(max(first, _two_years_before(last)), last),
            min_value=first,
            max_value=last,
            help=f"The loaded panel covers {first} to {last}.",
        )
    with c2:
        cadence = st.selectbox("Rebalance", ["MONTHLY", "WEEKLY"], index=0)
    with c3:
        min_window = st.number_input(
            "Minimum window (days)", min_value=60, max_value=750, value=250,
            step=10,
            help=(
                "A rebalance date with fewer prior observations than this is "
                "skipped rather than decided on a thin estimate."
            ),
        )

    if not isinstance(chosen, tuple) or len(chosen) != 2:
        st.info("Select both a start and an end date.", icon="ℹ")
        return None

    start, end = chosen
    if end <= start:
        st.warning("The end date must be after the start date.", icon="⚠")
        return None

    return BacktestConfig(
        start=start, end=end, rebalance=cadence, min_window=int(min_window)
    )


def _two_years_before(day: date) -> date:
    """Two years back, clamped for a 29 February start."""
    try:
        return day.replace(year=day.year - 2)
    except ValueError:
        return day.replace(year=day.year - 2, day=28)


def _execute(svc: Services, config: BacktestConfig) -> None:
    """Run and store. Failures are shown, never swallowed into an empty page."""
    st.session_state["cce_backtest"] = None
    try:
        with st.spinner("Walking forward — re-optimizing at each rebalance…"):
            run = svc.backtest.run(config)
            st.session_state["cce_backtest"] = {
                "metrics": svc.backtest.compare(run),
                "curves": svc.backtest.equity_curves(run),
                "drawdowns": svc.backtest.drawdowns(run),
                "rebalances": len(run.rebalance_dates),
                "config": config,
            }
    except ValueError as exc:
        st.error(f"The backtest could not run: {exc}", icon="⚠")
    except Exception as exc:  # noqa: BLE001 - surfaced, not hidden
        st.error(f"The backtest failed: {exc}", icon="⚠")


def _results(svc: Services, stored: dict) -> None:
    metrics = stored["metrics"]
    config = stored["config"]

    st.caption(
        f"{config.start} → {config.end} · {config.rebalance.lower()} · "
        f"{stored['rebalances']} rebalance dates · minimum window "
        f"{config.min_window} observations"
    )

    st.plotly_chart(
        equity_curves(stored["curves"]), use_container_width=True,
        key="bt_equity",
    )
    st.plotly_chart(
        drawdown_curves(stored["drawdowns"]), use_container_width=True,
        key="bt_drawdown",
    )

    rows = []
    for name in STRATEGY_ORDER:
        m = metrics.get(name)
        if m is None:
            continue
        rows.append({
            "Strategy": STRATEGY_LABELS.get(name, name),
            "Return": pct(m.cumulative_return),
            "Annualised": pct(m.annualised_return),
            "Volatility": pct(m.volatility),
            "Sharpe": ratio(m.sharpe),
            "Max drawdown": pct(m.max_drawdown),
            "Avg turnover": pct(m.avg_turnover),
            "Txn cost": crore(m.total_txn_cost_paise),
            "Policy breaches": m.policy_breach_count,
            "Holds": m.holds if name == "CCE_CONTROLLED" else DASH,
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    _honest_reading(metrics)


def _honest_reading(metrics: dict) -> None:
    """State the trade-off in words, including when it went against us.

    Written from the measured numbers rather than asserted: if the controlled
    strategy did NOT reduce drawdown on this sample, the caption says that.
    Dressing a lower return as a win by omission is the specific failure
    docs/09 section 9 forbids.
    """
    ctrl = metrics.get("CCE_CONTROLLED")
    unc = metrics.get("UNCONTROLLED_OPTIMIZER")
    if ctrl is None or unc is None:
        return

    def gap(a: float | None, b: float | None) -> str:
        if a is None or b is None:
            return DASH
        return f"{(a - b) * 100:+.1f}pp"

    st.markdown(
        f"**The trade-off on this sample.** The controlled strategy returned "
        f"{pct(ctrl.cumulative_return)} against the uncontrolled optimizer's "
        f"{pct(unc.cumulative_return)} "
        f"({gap(ctrl.cumulative_return, unc.cumulative_return)}), with a "
        f"maximum drawdown of {pct(ctrl.max_drawdown)} against "
        f"{pct(unc.max_drawdown)} "
        f"({gap(ctrl.max_drawdown, unc.max_drawdown)}) and "
        f"{ctrl.policy_breach_count} policy breaches against "
        f"{unc.policy_breach_count}. It held its previous allocation "
        f"{ctrl.holds} times rather than adopt a proposal that failed "
        f"validation."
    )

    if _worse_on_both(ctrl, unc):
        st.warning(
            "On this sample the control layer reduced neither drawdown nor "
            "breaches. That is a real outcome for this window, not a bug — "
            "report it as measured.",
            icon="⚠",
        )


def _worse_on_both(ctrl, unc) -> bool:
    deeper = (
        ctrl.max_drawdown is not None
        and unc.max_drawdown is not None
        and ctrl.max_drawdown >= unc.max_drawdown
    )
    return deeper and ctrl.policy_breach_count >= unc.policy_breach_count

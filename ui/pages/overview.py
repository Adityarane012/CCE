"""Page 1 — Executive Overview. The judge-facing home page.

Spec: docs/09-UI-SPEC.md section 4.

Must communicate the entire product in seconds: what state the portfolio is
in, which controls are breached with observed vs threshold, and what the
system did about it.

The action block is NEVER empty. In GREEN it says optimization is available;
in RED it says what was rejected and what is available instead. A blank panel
during a demo reads as a crash (EC-9).
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import RiskState
from ui.components.format import arrow, crore, pct, ratio
from ui.components.indicators import (
    cached_fallback_banner,
    degraded_marker,
    model_estimate,
    state_chip,
)
from ui.components.what_changed import render_what_changed
from ui.state import Services, session


def render(svc: Services) -> None:
    st.header("CCE — Capital Control Engine")
    st.caption("₹100 Cr institutional demo portfolio · Indian market data")

    cached_fallback_banner(svc.ctx.market_data.provider.value)

    try:
        state = svc.state()
        snapshot = svc.snapshot(state)
    except Exception as exc:  # noqa: BLE001 - never show a traceback on the hero page
        st.error(
            f"Portfolio state could not be loaded: {exc}", icon="⚠"
        )
        return

    previous = session().get("last_snapshot")
    prev_weights = session().get("last_weights") or state.weights
    session()["last_snapshot"] = snapshot
    session()["last_weights"] = dict(state.weights)

    _state_banner(snapshot)
    _metrics(snapshot, state, previous)
    _breaches(snapshot)
    render_what_changed(svc, previous, snapshot, prev_weights, state.weights)
    _action_block(snapshot)


def _state_banner(snapshot) -> None:
    st.markdown(
        f"### RISK STATE: {state_chip(snapshot.risk_state)}",
        unsafe_allow_html=True,
    )
    if snapshot.risk_state is RiskState.RED:
        st.error(
            "Circuit breaker would activate on this state. Hard controls are "
            "breached.", icon="⛔",
        )
    degraded_marker(snapshot.degraded_reason)
    st.divider()


def _metrics(snapshot, state, previous) -> None:
    c1, c2, c3, c4 = st.columns(4)

    c1.metric("Portfolio value", crore(state.total_value_paise))

    c2.metric(
        "Expected return", pct(snapshot.expected_return),
        help="A model estimate, not a forecast.",
    )
    with c2:
        model_estimate()

    # Only show a delta when the DISPLAYED values differ. Comparing the raw
    # floats is not enough: 7.548% and 7.551% both render as "7.5%", and the
    # badge then read "from 7.5%" beside a headline of "7.5%" — onto which
    # Streamlit prepends its own arrow, so a metric that had not visibly moved
    # appeared to have risen.
    prev_vol = previous.ewma_volatility if previous else None
    shown, prev_shown = pct(snapshot.ewma_volatility), pct(prev_vol)
    moved = prev_vol is not None and prev_shown != shown
    c3.metric(
        "EWMA volatility", shown,
        delta=(
            f"{arrow(prev_vol, snapshot.ewma_volatility)} from {prev_shown}"
            if moved else None
        ),
        delta_color="off",
    )

    c4.metric("Sharpe", ratio(snapshot.sharpe))

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Historical volatility", pct(snapshot.historical_volatility))
    d2.metric("95% VaR", pct(snapshot.var_95))
    d3.metric("95% CVaR", pct(snapshot.cvar_95))
    d4.metric("Liquid share", pct(snapshot.liquidity_ratio))


def _breaches(snapshot) -> None:
    st.subheader("Controls")
    if not snapshot.breaches:
        st.success("No breaches. Every configured control is within policy.", icon="✅")
        return

    ordered = sorted(
        snapshot.breaches, key=lambda b: -b.severity.severity
    )
    rows = [
        {
            "State": b.severity.value,
            "Control": b.control_label,
            "Scope": b.scope,
            "Observed": pct(b.observed),
            "Threshold": pct(b.threshold),
            "Hard": "Hard" if b.is_hard else "Soft",
        }
        for b in ordered
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "Every row shows the observed value against the threshold it crossed "
        "— never a bare colour."
    )


def _action_block(snapshot) -> None:
    st.subheader("Recommended action")
    hard = snapshot.hard_breaches

    if hard:
        st.error(
            f"**{len(hard)} hard control(s) breached.** An uncontrolled "
            "optimizer output would be rejected. Open the Optimizer to see "
            "Safe vs Optimal and the validated alternatives.",
            icon="⛔",
        )
    elif snapshot.risk_state is RiskState.AMBER:
        st.warning(
            "Approaching a policy limit. Optimization is available and any "
            "proposal will still be independently validated.", icon="⚠",
        )
    else:
        st.success(
            "No breaches. Optimization available.", icon="✅",
        )

    st.caption(
        "Use the sidebar to open **Optimizer** (Safe vs Optimal), "
        "**Risk Control Center**, or **Decision Replay**."
    )

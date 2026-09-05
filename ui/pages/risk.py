"""Page 3 — Risk Control Center. Every control against its threshold.

Spec: docs/09-UI-SPEC.md section 6.

Sorted RED first, then AMBER, then GREEN. A risk manager scanning this table
should hit the problems before the reassurance.
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import RiskState
from ui.components.format import DASH, pct
from ui.components.indicators import degraded_marker, state_chip
from ui.components.what_changed import render_what_changed
from ui.state import Services, session


def render(svc: Services) -> None:
    st.header("Risk Control Center")
    st.caption(
        "Every configured control, re-derived independently of the optimizer."
    )

    try:
        state = svc.state()
        snapshot = svc.snapshot(state)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Risk could not be computed: {exc}", icon="⚠")
        return

    st.markdown(
        f"**Portfolio state:** {state_chip(snapshot.risk_state)}",
        unsafe_allow_html=True,
    )
    st.caption(
        "The portfolio state is the MOST SEVERE individual control state. "
        "There is no averaging — a control that can be outvoted is not a "
        "control."
    )
    degraded_marker(snapshot.degraded_reason)

    previous = session().get("last_snapshot")
    prev_weights = session().get("last_weights") or state.weights
    render_what_changed(svc, previous, snapshot, prev_weights, state.weights)

    _breaker_panel(snapshot)
    _control_table(snapshot)
    _metric_detail(snapshot)


def _breaker_panel(snapshot) -> None:
    st.subheader("Circuit breaker")
    hard = snapshot.hard_breaches
    if hard:
        st.error(
            f"**Would be ACTIVE.** {len(hard)} hard control(s) at RED: "
            + ", ".join(b.control_code for b in hard),
            icon="⛔",
        )
        st.caption(
            "On activation the Last Approved Safe Allocation is preserved "
            "and recovery candidates are generated. Nothing is adopted "
            "automatically."
        )
    else:
        st.success("Inactive — no hard control at RED.", icon="✅")


def _control_table(snapshot) -> None:
    st.subheader("Controls")
    if not snapshot.breaches:
        st.success(
            "Every configured control evaluated within policy.", icon="✅"
        )
        return

    order = {RiskState.RED: 0, RiskState.AMBER: 1, RiskState.GREEN: 2}
    rows = [
        {
            "State": b.severity.value,
            "Control": b.control_label,
            "Code": b.control_code,
            "Scope": b.scope,
            "Observed": pct(b.observed),
            "Threshold": pct(b.threshold),
            "Hard?": "Hard" if b.is_hard else "Soft",
        }
        for b in sorted(snapshot.breaches, key=lambda b: order[b.severity])
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("**Why each was raised**")
    for b in sorted(snapshot.breaches, key=lambda b: order[b.severity]):
        st.markdown(f"- {b.message}")


def _metric_detail(snapshot) -> None:
    st.subheader("Measured metrics")
    st.caption(
        f"A dash ({DASH}) means NOT COMPUTED — typically too few "
        "observations. It never means zero."
    )
    rows = [
        ("Historical volatility (annualised)", pct(snapshot.historical_volatility)),
        ("EWMA volatility (annualised)", pct(snapshot.ewma_volatility)),
        ("Portfolio volatility (from covariance)", pct(snapshot.portfolio_volatility)),
        ("95% VaR (1-day)", pct(snapshot.var_95)),
        ("95% CVaR (1-day)", pct(snapshot.cvar_95)),
        ("Current drawdown", pct(snapshot.current_drawdown)),
        ("Maximum drawdown", pct(snapshot.max_drawdown)),
        ("Liquid share", pct(snapshot.liquidity_ratio)),
        ("Turnover from current", pct(snapshot.turnover_from_current)),
    ]
    st.dataframe(
        [{"Metric": k, "Value": v} for k, v in rows],
        use_container_width=True, hide_index=True,
    )
    st.caption(
        "Losses are positive: a 1.4% CVaR is a 1.4% expected tail loss. "
        "CVaR ≥ VaR always — the contract refuses to construct a snapshot "
        "where it is not."
    )

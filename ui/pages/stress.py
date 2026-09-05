"""Page 5 — Stress Lab.

Spec: docs/09-UI-SPEC.md section 8.

A scenario that did not run is never shown as one the portfolio survived.
``loss_is_measured`` gates the loss figure: an ERROR or unrun scenario still
carries ``0.0`` because the field is a plain float, and rendering that as
"0.0% loss" would report a scenario the book never faced as one it passed
(INV-5, INV-10).
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import StressStatus
from ui.components.format import DASH, crore, pct
from ui.components.indicators import stress_label
from ui.state import Services


def render(svc: Services) -> None:
    st.header("Stress Lab")
    st.caption(
        "Configured scenarios applied to the current book. A scenario that "
        "could not run is reported as such, never as one that passed."
    )

    try:
        state = svc.state()
        scenarios = svc.stress.list_scenarios()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Scenarios could not be loaded: {exc}", icon="⚠")
        return

    if not scenarios:
        st.info("No scenarios are configured.", icon="ℹ")
        return

    codes = st.multiselect(
        "Scenarios", [s.code for s in scenarios],
        default=[s.code for s in scenarios],
        format_func=lambda c: next(s.label for s in scenarios if s.code == c),
    )

    if st.button("Run stress suite", type="primary"):
        _run(svc, state, tuple(codes))

    _custom(svc, state)


def _run(svc, state, codes) -> None:
    if not codes:
        st.warning(
            "No scenarios selected. An empty suite tests nothing, so it is "
            "not run.", icon="⚠",
        )
        return

    with st.spinner("Applying scenarios…"):
        results = svc.stress.run(
            state.weights, codes, total_value_paise=state.total_value_paise
        )

    worst = svc.stress.worst_loss(results)
    c1, c2, c3 = st.columns(3)
    c1.metric("Scenarios run", str(len(results)))
    c2.metric(
        "Worst measured loss", pct(worst),
        help="None if no scenario produced a usable verdict.",
    )
    c3.metric("Loss limit", pct(svc.ctx.policy.stress_loss_limit))

    rows = []
    for r in results:
        rows.append({
            "Scenario": r.scenario_label,
            "Status": r.status.value,
            "Loss": pct(r.portfolio_loss) if r.loss_is_measured else DASH,
            "Loss (₹)": crore(r.loss_paise) if r.loss_is_measured else DASH,
            "Limit": pct(r.loss_threshold),
            "Post-shock volatility": pct(r.post_shock_volatility),
            "Post-shock CVaR": pct(r.post_shock_cvar),
        })
    st.dataframe(rows, use_container_width=True, hide_index=True)

    for r in results:
        if r.status is StressStatus.ERROR:
            st.error(
                f"**{r.scenario_label}** — {r.error_reason}", icon="⚠"
            )
        elif r.status is StressStatus.FAILED:
            st.warning(
                f"**{r.scenario_label}** — loss {pct(r.portfolio_loss)} "
                f"exceeds the {pct(r.loss_threshold)} limit.", icon="⚠",
            )

    st.caption(
        f"A dash ({DASH}) in the loss column means the scenario produced no "
        "verdict. It is not a zero loss."
    )


def _custom(svc, state) -> None:
    with st.expander("Custom scenario"):
        st.caption(
            "Shock a sector or an asset. A key matching neither is reported "
            "as an error — a scenario that shocks nothing tests nothing."
        )
        sectors = sorted({a.sector for a in svc.ctx.universe.assets})
        target = st.selectbox("Sector", sectors)
        shock = st.slider(
            "Shock (%)", min_value=-60, max_value=20, value=-30, step=5
        )
        if st.button("Run custom scenario"):
            result = svc.stress.run_custom(
                state.weights, {target: shock / 100.0},
                label=f"{target} {shock}%",
                total_value_paise=state.total_value_paise,
            )
            st.markdown(f"**{stress_label(result.status)}**")
            if result.loss_is_measured:
                st.metric("Portfolio loss", pct(result.portfolio_loss))
                st.metric("Loss in rupees", crore(result.loss_paise))
            else:
                st.error(result.error_reason or "No verdict produced.", icon="⚠")

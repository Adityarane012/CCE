"""Page 2 — Portfolio & Exposure.

Spec: docs/09-UI-SPEC.md section 5.

The weight-vs-risk-contribution chart is the one to get right. It renders the
product's central insight visually: two bars per asset that ought to track
each other, and visibly do not. A 24% position carrying 41% of portfolio risk
is invisible to any weight-based limit, and that gap is the reason a risk
contribution control exists at all.
"""

from __future__ import annotations

import streamlit as st

from ui.components.charts import (
    allocation_donut,
    sector_vs_cap,
    weight_vs_risk_contribution,
)
from ui.components.format import DASH, crore, pct, weight
from ui.state import Services


def render(svc: Services) -> None:
    st.header("Portfolio & Exposure")
    st.caption("Where the capital sits, and where the risk actually is.")

    try:
        state = svc.state()
        snapshot = svc.snapshot(state)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Portfolio could not be loaded: {exc}", icon="⚠")
        return

    if not state.weights:
        st.info("The portfolio holds no positions.", icon="ℹ")
        return

    _headline(state, snapshot)
    _weight_vs_rc(state, snapshot)
    _exposure(svc, state, snapshot)
    _positions(state, snapshot)


def _headline(state, snapshot) -> None:
    c1, c2, c3 = st.columns(3)
    c1.metric("Portfolio value", crore(state.total_value_paise))
    c2.metric("Cash", crore(state.cash_value_paise))
    c3.metric("Liquid share", pct(snapshot.liquidity_ratio))


def _weight_vs_rc(state, snapshot) -> None:
    st.subheader("Weight vs risk contribution")
    rc = snapshot.risk_contribution
    if not rc:
        st.info(
            "Risk contribution was not computed for this panel, so the "
            "comparison cannot be drawn. It is not being shown as zero.",
            icon="ℹ",
        )
        return

    st.plotly_chart(
        weight_vs_risk_contribution(state.weights, rc),
        use_container_width=True,
    )
    st.caption(
        "Blue is share of CAPITAL; red is share of RISK. Where red runs "
        "ahead of blue, the position carries more risk than its size "
        "suggests — which a weight-based limit alone cannot see."
    )

    widest = max(
        ((a, rc.get(a, 0.0) - state.weights.get(a, 0.0)) for a in state.weights),
        key=lambda kv: kv[1], default=None,
    )
    if widest and widest[1] > 0:
        asset, gap = widest
        st.info(
            f"**{asset}** carries {pct(rc.get(asset))} of portfolio risk on "
            f"{weight(state.weights.get(asset))} of capital — a gap of "
            f"{gap * 100:+.1f}pp.",
            icon="🔍",
        )


def _exposure(svc, state, snapshot) -> None:
    c1, c2 = st.columns([1, 1])

    with c1:
        st.subheader("Allocation")
        st.plotly_chart(allocation_donut(state.weights), use_container_width=True)

    with c2:
        st.subheader("Sector exposure vs cap")
        exposure = snapshot.sector_exposure or state.sector_exposure()
        caps = svc.ctx.policy.constraints.sector_max
        if exposure:
            st.plotly_chart(
                sector_vs_cap(exposure, caps), use_container_width=True
            )
        else:
            st.info("Sector exposure was not computed.", icon="ℹ")


def _positions(state, snapshot) -> None:
    st.subheader("Positions")
    rc = snapshot.risk_contribution
    rows = [
        {
            "Asset": p.asset_id,
            "Sector": p.sector,
            "Class": p.asset_class,
            "Units": f"{p.units:,.0f}",
            "Value": crore(p.value_paise),
            "Weight": weight(p.weight),
            "Risk contribution": pct(rc.get(p.asset_id)) if rc else DASH,
        }
        for p in sorted(state.positions, key=lambda p: p.weight, reverse=True)
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    conc = snapshot.concentration
    if conc:
        st.subheader("Concentration")
        cols = st.columns(len(conc))
        for col, (name, value) in zip(cols, sorted(conc.items()), strict=True):
            col.metric(name.replace("_", " ").title(), _concentration(name, value))


#: Concentration figures that are COUNTS, not fractions. Everything else in
#: `concentration_summary` is a weight share.
_COUNTS = {"effective_assets"}


def _concentration(name: str, value: float | None) -> str:
    """Format one concentration figure in its own units.

    ``effective_assets`` is 1/HHI — "this book behaves like 5.3 equal
    positions". Formatting it with ``pct()`` alongside the weight shares
    rendered it as **529.3%**, which is not a quantity that exists. Every
    other key in the summary really is a fraction.
    """
    if value is None:
        return DASH
    if name in _COUNTS:
        return f"{value:.1f}"
    return pct(value)

"""The "What Changed?" panel.

Spec: docs/09-UI-SPEC.md section 10.

Shown on the Overview and the Risk Control Center whenever a previous
snapshot exists.

The panel's job is to separate ALLOCATION DRIFT from a VOLATILITY REGIME
CHANGE. Those call for opposite responses — rebalance, or reassess — and a
reader shown only "volatility is up" has to guess which happened.

The interpretation sentence is rendered by the deterministic narrator from
the attribution the service computed. It is not assembled here and not
written by an LLM, so two pages showing the same numbers cannot disagree
about what they mean.
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import ChangeDriver
from cce.decisions import render_change_interpretation

from .format import pct

__all__ = ["render_what_changed"]

_DRIVER_LABEL = {
    ChangeDriver.REGIME: "Market regime — the book was not traded",
    ChangeDriver.ALLOCATION: "Allocation — the book was traded",
    ChangeDriver.BOTH: "Allocation and market regime",
    ChangeDriver.NONE: "No material change",
}


def render_what_changed(svc, previous, current, prev_weights, curr_weights) -> None:
    """Draw the panel, or say plainly that there is nothing to compare."""
    st.subheader("What changed?")

    if previous is None:
        st.caption(
            "No previous reading in this session yet — there is nothing to "
            "compare against. Re-run after the next optimization."
        )
        return

    attribution = svc.risk.attribute(
        previous, current, prev_weights, curr_weights
    )

    if attribution.driver is ChangeDriver.NONE:
        st.info("No material change since the previous reading.", icon="ℹ")
        return

    st.markdown(f"**Primary driver:** {_DRIVER_LABEL[attribution.driver]}")

    if attribution.metrics:
        st.dataframe(
            [
                {
                    "Metric": c.metric,
                    "Before": pct(c.from_value),
                    "After": pct(c.to_value),
                    "Change": f"{c.delta * 100:+.1f}pp",
                }
                for c in attribution.metrics
            ],
            use_container_width=True, hide_index=True,
        )

    if attribution.contributors:
        st.markdown("**Risk contribution by sector**")
        st.dataframe(
            [
                {
                    "Sector": c.scope,
                    "Before": pct(c.from_value),
                    "After": pct(c.to_value),
                    "Change": f"{c.delta * 100:+.1f}pp",
                }
                for c in attribution.contributors
            ],
            use_container_width=True, hide_index=True,
        )

    st.markdown("**Interpretation**")
    st.info(render_change_interpretation(attribution), icon="🔍")
    st.caption(
        f"Largest weight shift {pct(attribution.max_weight_shift)} against a "
        f"{pct(attribution.weight_shift_threshold)} materiality floor. "
        "The floor keeps rounding drift from being reported as a rebalance."
    )

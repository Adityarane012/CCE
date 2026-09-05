"""Page 8 — Policy / Settings.

Spec: docs/09-UI-SPEC.md sections 12 and 13.

Read-only here plus the weakening PREVIEW. Applying a change is possible
through PolicyService, but the flow that matters for the demo is showing what
a change WOULD do before it is made (FR-084): a loosened hard limit is named,
and the service refuses it without an acknowledgement and a reason regardless
of what this page allows (INV-8).
"""

from __future__ import annotations

import streamlit as st

from ui.components.format import pct
from ui.state import Services


def render(svc: Services) -> None:
    st.header("Policy & Settings")
    st.caption(
        "Thresholds are configuration, not code. Every change inserts a new "
        "version with attribution — nothing is edited in place."
    )

    policy = svc.policy.get_current()
    c1, c2, c3 = st.columns(3)
    c1.metric("Policy version", str(policy.version))
    c2.metric("Label", policy.label)
    c3.metric("Stress loss limit", pct(policy.stress_loss_limit))

    st.subheader("Thresholds")
    st.caption("[DEMO-CONFIG] — every value below comes from config/policy.yaml.")
    rows = [
        {
            "Control": t.control_code,
            "Label": t.label,
            "Scope": t.scope.value,
            "Direction": t.comparator.value,
            "Green": pct(t.green_max) if t.green_max is not None else pct(t.green_min),
            "Amber": pct(t.amber_max) if t.amber_max is not None else pct(t.amber_min),
            "Hard?": "Hard" if t.is_hard else "Soft",
        }
        for t in policy.thresholds
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)
    st.caption(
        "GT controls breach when the value EXCEEDS the band (volatility, "
        "CVaR). LT controls breach when it falls BELOW (liquidity, cash). "
        "A boundary value belongs to the less severe band."
    )

    _preview(svc, policy)
    _model(policy)


def _preview(svc, policy) -> None:
    st.subheader("Preview a threshold change")
    st.caption(
        "Shows whether a change would WEAKEN a hard control, before it is "
        "applied (FR-084)."
    )
    codes = [t.control_code for t in policy.thresholds]
    code = st.selectbox("Control", codes)
    threshold = policy.threshold(code)

    field = st.selectbox(
        "Band",
        [f for f in ("green_max", "amber_max", "green_min", "amber_min")
         if getattr(threshold, f) is not None],
    )
    current = float(getattr(threshold, field))
    proposed = st.number_input(
        "Proposed value", value=current, step=0.01, format="%.4f"
    )

    if st.button("Preview change"):
        try:
            preview = svc.policy.preview_change({code: {field: proposed}})
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc), icon="⚠")
            return

        if not preview.changes:
            st.info("No effective change.", icon="ℹ")
            return
        for change in preview.changes:
            st.markdown(f"- {change.message}")
        if preview.is_weakening:
            st.error(
                "**This loosens a hard control.** Applying it requires an "
                "explicit acknowledgement and a recorded reason. Controls "
                f"affected: {', '.join(preview.weakened_controls)}.",
                icon="⛔",
            )
        else:
            st.success("This tightens the policy. No acknowledgement needed.", icon="✅")


def _model(policy) -> None:
    with st.expander("Model parameters"):
        m = policy.model
        st.dataframe(
            [
                {"Parameter": "EWMA lambda", "Value": f"{m.ewma_lambda}"},
                {"Parameter": "VaR confidence", "Value": pct(m.var_confidence)},
                {"Parameter": "Trading days / year", "Value": str(m.trading_days_per_year)},
                {"Parameter": "Risk-free rate", "Value": pct(m.risk_free_rate)},
                {"Parameter": "Min observations", "Value": str(m.min_return_observations)},
                {"Parameter": "Random seed", "Value": str(m.random_seed)},
            ],
            use_container_width=True, hide_index=True,
        )

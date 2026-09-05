"""Page 7 — Decision Replay. The audit timeline.

Spec: docs/09-UI-SPEC.md section 11.

Every row was persisted. Nothing here is recomputed (INV-6), and the
three-way MACHINE / CONTROL / HUMAN distinction is the point of the page: the
system computed, the control engine judged, a person decided.
"""

from __future__ import annotations

import streamlit as st

from ui.components.format import DASH, pct, time_only, timestamp
from ui.state import Services


def render(svc: Services) -> None:
    st.header("Decision Replay")
    st.caption(
        "Reconstructed from persisted events only — never recomputed. "
        "An empty timeline means nothing was recorded, not that nothing "
        "happened."
    )

    try:
        decisions = svc.replay.list_decisions(limit=50)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Decision history could not be read: {exc}", icon="⚠")
        return

    if not decisions:
        st.info(
            "No decisions recorded yet. Run an optimization from the "
            "Optimizer page to create one.", icon="ℹ",
        )
        return

    labels = {
        d.decision_id: (
            f"#{d.decision_id} · {timestamp(d.created_at)} · "
            f"{d.trigger_type} · {d.control_status}"
            + (f" · {d.human_action}" if d.human_action else " · open")
        )
        for d in decisions
    }
    chosen = st.selectbox(
        "Decision", list(labels), format_func=lambda k: labels[k]
    )

    _detail(svc, chosen)


def _detail(svc, decision_id: int) -> None:
    try:
        stored = svc.replay.get_decision(decision_id)
        timeline = svc.replay.get_timeline(decision_id)
    except LookupError:
        st.error(f"Decision {decision_id} could not be found.", icon="⚠")
        return

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Control status", stored.control_status)
    c2.metric("Breaker", "ACTIVE" if stored.circuit_breaker_active else "inactive")
    c3.metric("Policy version", str(stored.policy_version_id))
    c4.metric("Market snapshot", str(stored.snapshot_id))

    st.subheader("Timeline")
    if not timeline:
        st.warning(
            "No events were recorded for this decision.", icon="⚠"
        )
    else:
        rows = [
            {
                "#": r.sequence_no,
                "Time": time_only(r.event.occurred_at),
                "Actor": r.actor_label,
                "Event": r.event_code,
                "Summary": r.summary,
            }
            for r in timeline
        ]
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.caption(
            "**System** computed it, **Control engine** judged it, "
            "**Risk manager** decided it. That distinction is the page."
        )

    _candidates(stored)
    _human_action(stored)
    _explanation(stored)


def _candidates(stored) -> None:
    if not stored.candidates:
        return
    st.subheader("Candidates considered")
    rows = [
        {
            "Role": c.role,
            "Strategy": c.strategy,
            "Control": c.control_status,
            "Stress": c.stress_status,
            "Approvable": "Yes" if c.eligible_for_approval else "No",
            "Sharpe": f"{c.sharpe:.2f}" if c.sharpe is not None else DASH,
            "CVaR": pct(c.cvar_95),
            "Turnover": pct(c.turnover),
        }
        for c in stored.candidates
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)

    for c in stored.candidates:
        if c.findings:
            with st.expander(f"{c.role} — {len(c.findings)} control finding(s)"):
                for b in c.findings:
                    st.markdown(f"- {b.message}")


def _human_action(stored) -> None:
    st.subheader("Human action")
    action = stored.human_action
    if action is None:
        st.info("This decision is still open — no human has acted.", icon="ℹ")
        return
    st.markdown(
        f"**{action.action}** by `{action.user_identity}` "
        f"({action.user_role}) at {timestamp(action.created_at)}"
    )
    if action.comment:
        st.caption(f"Comment: {action.comment}")
    if action.is_override:
        st.warning(
            f"**Override.** Reason: {action.override_reason}. "
            f"Controls overridden: {', '.join(action.overridden_controls)}.",
            icon="⚠",
        )


def _explanation(stored) -> None:
    if not stored.template_text:
        return
    st.subheader("Explanation")
    st.markdown(stored.template_text)
    if stored.llm_text:
        with st.expander("LLM narration (display only)"):
            st.markdown(stored.llm_text)
            st.caption(
                "Generated prose. It is never parsed back into any decision, "
                "metric or state (INV-1)."
            )

"""Page 4 — Optimizer. The three-column Safe vs Optimal comparison.

Spec: docs/09-UI-SPEC.md section 7.

This page is the product. Three columns that are always three DISTINCT things
(INV-9), and the rejected column is shown rather than hidden — it is the
argument. A dashboard that displayed only the safe allocation would be a
dashboard claiming its optimizer never proposes anything dangerous.

The Approve button reads ``candidate.eligible_for_approval``. It does not
reimplement the condition, and disabling it is convenience: the service
re-checks server-side and raises (INV-2).
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import (
    Candidate,
    CandidateRole,
    ExpectedReturnMethod,
    HumanAction,
    HumanActionRecord,
    Strategy,
    View,
)
from cce.exceptions import CCEError
from ui.components.format import DASH, crore, pct, ratio, weight
from ui.components.indicators import (
    control_label,
    model_estimate,
    state_chip,
    stress_label,
)
from ui.state import Services, clear_cycle, session

_ACTOR_ID = "demo_risk_manager"
_ACTOR_ROLE = "RISK_MANAGER"


def _actor(action: HumanAction, **kw) -> HumanActionRecord:
    from datetime import UTC, datetime

    from cce.services import ServiceContext  # noqa: F401  (typing only)

    return HumanActionRecord(
        action=action, user_identity=_ACTOR_ID, user_role=_ACTOR_ROLE,
        timestamp=datetime.now(UTC), **kw,
    )


def render(svc: Services) -> None:
    st.header("Optimizer")
    st.caption(
        "The optimizer proposes. An independent control engine disposes. "
        "Both answers are shown."
    )

    state = svc.state()
    s = session()

    with st.sidebar:
        st.subheader("Optimization inputs")
        strategy = st.selectbox(
            "Strategy",
            [
                Strategy.MAX_SHARPE,
                Strategy.MIN_VOLATILITY,
                Strategy.CVAR_MIN,
                Strategy.HRP,
                Strategy.TARGET_RETURN,
                Strategy.BLACK_LITTERMAN,
            ],
            format_func=lambda x: x.value.replace("_", " ").title(),
        )
        target_return = None
        if strategy is Strategy.TARGET_RETURN:
            target_return = st.slider(
                "Required return", 0.05, 0.25, 0.12, 0.01, format="%.2f",
                help="Minimum acceptable expected return. If unreachable under "
                     "the policy, the optimizer reports why rather than "
                     "relaxing a constraint.",
            )
        views = _view_entry(svc) if strategy is Strategy.BLACK_LITTERMAN else ()
        if strategy is Strategy.HRP:
            st.caption(
                "HRP uses no expected returns and no matrix inversion — it is "
                "robust where mean-variance is fragile. Its allocation is then "
                "projected onto the policy constraints like any other."
            )
        er_method = st.selectbox(
            "Expected-return method",
            [ExpectedReturnMethod.HISTORICAL, ExpectedReturnMethod.EWMA],
            format_func=lambda x: x.value.title(),
        )
        st.caption(
            "Expected returns are model estimates whatever the method. "
            "They are the least reliable inputs here."
        )
        if st.button("Run optimization", type="primary", use_container_width=True):
            _run(svc, state, strategy, er_method, target_return, views)

    if s["error"]:
        st.error(s["error"], icon="⚠")

    cycle = s["cycle"]
    if cycle is None:
        st.info(
            "No proposal yet. Choose a strategy in the sidebar and select "
            "**Run optimization** to generate one.",
            icon="ℹ",
        )
        _current_only(svc, state)
        return

    _three_columns(svc, state, cycle)
    _explanation(svc, cycle)
    _recovery(svc, state, cycle)
    _trade_list(svc, state, cycle)


def _view_entry(svc):
    """Black-Litterman view entry, in the words a person uses.

    "IT will outperform broad equity by 2%, and I am 60% confident" becomes
    one row of P, one entry of Q and one diagonal entry of Omega. The view
    shifts expected returns and nothing else — the sector cap it might want
    to breach is applied afterwards, unchanged.
    """
    assets = sorted(a.asset_id for a in svc.ctx.universe.assets)
    st.markdown("**Your view**")
    asset = st.selectbox("Asset", assets, key="bl_asset")
    versus = st.selectbox(
        "Will outperform", ["(the market overall)", *assets], key="bl_versus"
    )
    outperformance = st.slider(
        "By", -0.10, 0.10, 0.02, 0.005, format="%.3f", key="bl_by"
    )
    confidence = st.slider("Confidence", 0.1, 1.0, 0.6, 0.1, key="bl_conf")
    st.caption(
        "A view moves the expected returns the optimizer sees. It cannot "
        "move a control."
    )
    return (
        View(
            asset=asset,
            versus=None if versus.startswith("(") else versus,
            outperformance=outperformance,
            confidence=confidence,
        ),
    )


# ---------------------------------------------------------------------------

def _run(svc, state, strategy, er_method, target_return=None, views=()) -> None:
    s = session()
    try:
        with st.spinner("Optimizing, validating independently, stress testing…"):
            s["cycle"] = svc.optimization.run_cycle(
                state, strategy=strategy, er_method=er_method,
                target_return=target_return, views=views,
                trigger_detail=f"{strategy.value} requested from the dashboard",
            )
        s["error"] = None
    except CCEError as exc:
        s["cycle"] = None
        s["error"] = f"Optimization could not complete: {exc}"
    except Exception as exc:  # noqa: BLE001 - a dashboard must not show a traceback
        s["cycle"] = None
        s["error"] = f"Unexpected failure during optimization: {exc}"


def _metrics(cand: Candidate | None, state) -> dict[str, str]:
    """The comparison rows. Every one may legitimately be unavailable."""
    if cand is None or cand.optimization.weights is None:
        return {}
    o = cand.optimization
    return {
        "Expected return": pct(o.expected_return),
        "Sharpe": ratio(o.sharpe),
        "Volatility": pct(o.volatility),
        "95% CVaR": pct(o.cvar_95),
        "Turnover": pct(o.turnover),
        "Txn cost": crore(o.transaction_cost_paise),
    }


def _current_only(svc, state) -> None:
    snapshot = svc.snapshot(state)
    st.subheader("Current allocation")
    c1, c2, c3 = st.columns(3)
    c1.metric("Portfolio value", crore(state.total_value_paise))
    c2.metric("Volatility", pct(snapshot.portfolio_volatility))
    c3.metric("95% CVaR", pct(snapshot.cvar_95))


def _three_columns(svc, state, cycle) -> None:
    current = svc.snapshot(state)
    optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
    safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)

    st.subheader("Safe vs Optimal")
    col_cur, col_opt, col_safe = st.columns(3)

    with col_cur:
        st.markdown("#### CURRENT")
        st.caption("What the book holds today")
        st.metric("Expected return", pct(current.expected_return))
        model_estimate()
        st.metric("Sharpe", ratio(current.sharpe))
        st.metric("Volatility", pct(current.portfolio_volatility))
        st.metric("95% CVaR", pct(current.cvar_95))
        st.metric("Turnover", DASH)
        st.metric("Txn cost", DASH)
        st.markdown(state_chip(current.risk_state), unsafe_allow_html=True)

    with col_opt:
        st.markdown("#### OPTIMAL")
        st.caption("Unconstrained — policy limits removed")
        _candidate_column(optimal, state)

    with col_safe:
        st.markdown("#### SAFE")
        st.caption("Risk-controlled — every policy limit applied")
        _candidate_column(safe, state)
        _approval_controls(svc, state, cycle, safe)


def _candidate_column(cand: Candidate | None, state) -> None:
    if cand is None:
        st.info("Not generated.", icon="ℹ")
        return
    if cand.optimization.weights is None:
        st.warning(
            f"No allocation produced — solver status "
            f"{cand.optimization.solver_status.value}.",
            icon="⚠",
        )
        for note in cand.optimization.diagnostics.get("conflicts", []) or []:
            st.caption(f"• {note}")
        return

    rows = _metrics(cand, state)
    st.metric("Expected return", rows["Expected return"])
    model_estimate()
    st.metric("Sharpe", rows["Sharpe"])
    st.metric("Volatility", rows["Volatility"])
    st.metric("95% CVaR", rows["95% CVaR"])
    st.metric("Turnover", rows["Turnover"])
    st.metric("Txn cost", rows["Txn cost"])

    st.markdown(f"**{control_label(cand.control.status if cand.control else None)}**")
    st.markdown(f"**{stress_label(cand.stress_status)}**")

    reasons = cand.rejection_reasons
    if reasons:
        st.markdown("**Rejected because:**")
        for r in reasons:
            st.markdown(f"- {r}")
    elif cand.eligible_for_approval:
        st.success(
            "Passed every hard control and stress validation.", icon="✅"
        )


def _approval_controls(svc, state, cycle, safe: Candidate | None) -> None:
    if safe is None:
        return
    st.divider()
    eligible = safe.eligible_for_approval

    if st.button(
        "Approve Safe allocation", type="primary", disabled=not eligible,
        use_container_width=True, key="approve_safe",
    ):
        _act(svc, state, cycle, safe, HumanAction.APPROVE)

    c1, c2 = st.columns(2)
    if c1.button("Reject", use_container_width=True, key="reject"):
        _act(svc, state, cycle, safe, HumanAction.REJECT)
    if c2.button("Keep current", use_container_width=True, key="keep"):
        _act(svc, state, cycle, safe, HumanAction.KEEP_CURRENT)

    if not eligible:
        st.caption(
            "Approve is unavailable because this allocation did not pass. "
            "The button is a convenience — the service refuses server-side."
        )
        _override(svc, state, cycle, safe)


def _override(svc, state, cycle, cand: Candidate) -> None:
    """FR-117: a RED allocation never gets a one-click approval."""
    with st.expander("Request Controlled Override"):
        st.warning(
            "You are about to adopt an allocation the control engine "
            "rejected. This is recorded permanently against your name.",
            icon="⚠",
        )
        controls = [b.control_code for b in (cand.control.hard_breaches if cand.control else ())]
        st.markdown("**Controls being overridden:**")
        for code in controls or ["(none recorded)"]:
            st.markdown(f"- `{code}`")

        reason = st.text_area("Reason (required)", key="override_reason")
        confirmed = st.checkbox(
            "I confirm I am overriding the controls listed above",
            key="override_confirm",
        )
        ready = bool(reason.strip()) and confirmed and controls
        if st.button("Override and adopt", disabled=not ready, key="override_go"):
            _act(
                svc, state, cycle, cand, HumanAction.OVERRIDE,
                is_override=True, override_reason=reason.strip(),
                overridden_controls=tuple(controls),
                confirmation_token=f"UI-{cycle.decision_id}",
            )


def _act(svc, state, cycle, cand, action: HumanAction, **kw) -> None:
    s = session()
    try:
        actor = _actor(action, **kw)
        if action is HumanAction.APPROVE:
            svc.approval.approve(cycle.decision_id, cand, actor, state)
            s["approved"] = cand.role.value
            st.success("Approved. Simulated rebalance recorded.", icon="✅")
        elif action is HumanAction.OVERRIDE:
            svc.approval.override(cycle.decision_id, cand, actor, state)
            s["approved"] = cand.role.value
            st.success("Override recorded and allocation adopted.", icon="✅")
        elif action is HumanAction.REJECT:
            svc.approval.reject(cycle.decision_id, actor)
            st.info("Rejected. The portfolio has not been changed.", icon="ℹ")
        else:
            svc.approval.keep_current(cycle.decision_id, actor)
            st.info(
                "Keeping the current allocation. The Last Approved Safe "
                "Allocation is unchanged.", icon="ℹ",
            )
        clear_cycle()
        st.cache_resource.clear()
        st.rerun()
    except CCEError as exc:
        s["error"] = str(exc)
        st.error(str(exc), icon="⚠")


def _explanation(svc, cycle) -> None:
    """The decision, in prose (FR-140..FR-142).

    Written by the deterministic narrator from the structured Explanation.
    Complete with no LLM present and no API key configured — the LLM, when
    there is one, replaces this text for DISPLAY and never the decision
    behind it (INV-1).
    """
    try:
        stored = svc.replay.get_decision(cycle.decision_id)
    except LookupError:
        return
    if not stored.template_text:
        return

    st.divider()
    st.subheader("What the system decided, and why")
    st.markdown(stored.template_text)
    st.caption(
        "Generated from the structured decision record. Nothing here states "
        "a fact the record does not contain."
    )


def _recovery(svc, state, cycle) -> None:
    recovery = [c for c in cycle.candidates if c.role.is_recovery]
    if not recovery:
        return

    st.divider()
    st.subheader("Circuit breaker active — recovery allocations")
    st.caption(
        "The Last Approved Safe Allocation is preserved. These are "
        "independently validated alternatives."
    )

    eligible = [c for c in recovery if c.eligible_for_approval]
    rejected = [c for c in recovery if not c.eligible_for_approval]

    if eligible:
        for col, cand in zip(st.columns(len(eligible)), eligible, strict=True):
            with col:
                st.markdown(f"**{cand.role.value.replace('_', ' ').title()}**")
                st.metric("Sharpe", ratio(cand.optimization.sharpe))
                st.metric("95% CVaR", pct(cand.optimization.cvar_95))
                st.markdown("● ELIGIBLE")
                if st.button(
                    "Approve", key=f"approve_{cand.role.value}",
                    use_container_width=True,
                ):
                    _act(svc, state, cycle, cand, HumanAction.APPROVE)

    if rejected:
        with st.expander(f"Attempted and rejected ({len(rejected)})"):
            st.caption(
                "Shown rather than dropped: that CCE generated and then "
                "rejected these is evidence the control layer is real."
            )
            for cand in rejected:
                st.markdown(f"**{cand.role.value.replace('_', ' ').title()}**")
                for r in cand.rejection_reasons or ["No allocation produced."]:
                    st.markdown(f"- {r}")


def _trade_list(svc, state, cycle) -> None:
    safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)
    if safe is None or safe.optimization.weights is None:
        return
    st.divider()
    st.subheader("Recommended trades")
    target = safe.optimization.weights
    rows = []
    for asset_id in sorted(set(state.weights) | set(target)):
        now = state.weights.get(asset_id, 0.0)
        then = target.get(asset_id, 0.0)
        if abs(then - now) < 1e-9:
            continue
        rows.append({
            "Asset": asset_id,
            "Current": weight(now),
            "Target": weight(then),
            "Change": f"{(then - now) * 100:+.1f}pp",
        })
    if rows:
        st.dataframe(rows, use_container_width=True, hide_index=True)
    else:
        st.caption("No trades required — the proposal matches the current book.")

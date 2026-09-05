"""The append-only decision store.

Spec: docs/05-BACKEND-SCHEMA.md section 6.

The only sanctioned database surface in CCE. There is deliberately no
``update_decision``, no ``delete_decision`` and no ``execute_sql``; the single
permitted mutation is :meth:`AuditRepository.close_decision_with_human_action`,
guarded with ``WHERE human_action IS NULL`` so a second write cannot succeed
(INV-6).

Every write is parameterised, and every write that fails raises
:class:`AuditWriteError`. A write is never reported as succeeding when it did
not (EC-7.3) — an audit trail that quietly loses rows is worse than no audit
trail, because it is trusted.
"""

from __future__ import annotations

import logging
import sqlite3
from collections.abc import Sequence
from datetime import datetime

from cce.clock import utc_now
from cce.contracts import (
    Alert,
    Breach,
    Candidate,
    ControlStatus,
    DecisionEvent,
    Explanation,
    HumanActionRecord,
    Policy,
    PortfolioOrigin,
    PortfolioState,
    RiskChange,
    RiskSnapshot,
    SafeAllocation,
    StressResult,
    StressStatus,
)
from cce.exceptions import AuditWriteError, DecisionAlreadyClosed

from . import queries
from .database import transaction
from .models import (
    DecisionContext,
    DecisionSummary,
    MarketSnapshotMeta,
    PolicyChangeMeta,
    StoredDecision,
)
from .serialization import breaches_to_json, dumps, policy_to_json, positions_to_json

logger = logging.getLogger(__name__)

__all__ = [
    "AuditRepository",
    "AuditWriteError",
    "DecisionContext",
    "MarketSnapshotMeta",
    "PolicyChangeMeta",
]


# Re-exported so callers may import it from the repository they use, but
# defined ONCE in cce.exceptions. Two classes of the same name meant a service
# catching cce.exceptions.AuditWriteError did not catch what the repository
# actually raised — the failure mode is silence exactly where FR-125 requires
# a visible failure.


def _now() -> datetime:
    """Timezone-aware wall clock. Audit rows never carry a naive timestamp."""
    return utc_now()


def _risk_change_dict(rc: RiskChange | None) -> dict | None:
    """Serialise a RiskChange, including its derived delta."""
    if rc is None:
        return None
    return {
        "metric": rc.metric,
        "from_value": rc.from_value,
        "to_value": rc.to_value,
        "delta": rc.delta,
        "scope": rc.scope,
    }


class AuditRepository:
    """Append-only persistence for the decision loop."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ------------------------------------------------------------------
    # writes
    # ------------------------------------------------------------------

    def record_policy_version(self, policy: Policy, meta: PolicyChangeMeta) -> int:
        """Persist a policy version in full (INV-8).

        The complete Policy is serialised, not a summary of it. Every risk
        verdict is only interpretable against the thresholds actually in force
        at the time, so a policy row that cannot be read back into a Policy is
        not an audit record.
        """
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO policy_versions (
                        created_at, created_by, created_by_role, source, policy_json,
                        parent_version_id, change_summary, is_weakening,
                        weakening_ack_by, weakening_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (meta.created_at or _now()).isoformat(),
                        meta.created_by,
                        meta.created_by_role,
                        meta.source,
                        policy_to_json(policy),
                        meta.parent_version_id,
                        meta.change_summary,
                        int(meta.is_weakening),
                        meta.weakening_ack_by,
                        meta.weakening_reason,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record policy version: {e}") from e

    def record_market_snapshot(self, snap: MarketSnapshotMeta) -> int:
        """Persist market-data provenance."""
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO market_snapshots (
                        captured_at, as_of_date, provider, universe_hash, data_hash,
                        row_count, asset_count, validation_status, validation_json,
                        cache_path
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snap.captured_at.isoformat(),
                        snap.as_of_date,
                        snap.provider,
                        snap.universe_hash,
                        snap.data_hash,
                        snap.row_count,
                        snap.asset_count,
                        snap.validation_status,
                        snap.validation_json,
                        snap.cache_path,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record market snapshot: {e}") from e

    def record_portfolio_state(
        self,
        state: PortfolioState,
        origin: PortfolioOrigin,
        snapshot_id: int,
        source_decision_id: int | None = None,
    ) -> int:
        """Persist a portfolio state.

        ``snapshot_id`` is a required NOT NULL foreign key: a portfolio state
        is only meaningful against the market data that priced it.
        """
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO portfolio_states (
                        portfolio_id, created_at, as_of_date, total_value_paise,
                        cash_value_paise, positions_json, weights_json, origin,
                        source_decision_id, snapshot_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        state.portfolio_id,
                        state.timestamp.isoformat(),
                        state.as_of_date.isoformat(),
                        state.total_value_paise,
                        state.cash_value_paise,
                        positions_to_json(state.positions),
                        dumps(state.weights),
                        origin.value,
                        source_decision_id,
                        snapshot_id,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record portfolio state: {e}") from e

    def record_risk_snapshot(
        self,
        snapshot: RiskSnapshot,
        portfolio_state_id: int,
        snapshot_id: int,
        policy_version_id: int,
    ) -> int:
        """Persist a risk snapshot.

        ``None`` metrics are stored as SQL NULL and read back as ``None``.
        They are never written as ``0.0`` — "not computed" and "no risk" are
        different facts, and conflating them is exactly the false safety
        signal INV-5 exists to prevent.
        """
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO risk_snapshots (
                        created_at, portfolio_state_id, snapshot_id, policy_version_id,
                        historical_volatility, ewma_volatility, portfolio_volatility,
                        expected_return, expected_return_method, sharpe, var_95,
                        cvar_95, var_method, current_drawdown, max_drawdown,
                        liquidity_ratio, turnover_from_current,
                        risk_contribution_json, sector_exposure_json,
                        sector_risk_contrib_json, concentration_json, risk_state,
                        breaches_json, degraded, degraded_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                              ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        snapshot.timestamp.isoformat(),
                        portfolio_state_id,
                        snapshot_id,
                        policy_version_id,
                        snapshot.historical_volatility,
                        snapshot.ewma_volatility,
                        snapshot.portfolio_volatility,
                        snapshot.expected_return,
                        snapshot.expected_return_method.value
                        if snapshot.expected_return_method
                        else None,
                        snapshot.sharpe,
                        snapshot.var_95,
                        snapshot.cvar_95,
                        snapshot.var_method.value if snapshot.var_method else None,
                        snapshot.current_drawdown,
                        snapshot.max_drawdown,
                        snapshot.liquidity_ratio,
                        snapshot.turnover_from_current,
                        dumps(snapshot.risk_contribution),
                        dumps(snapshot.sector_exposure),
                        dumps(snapshot.sector_risk_contribution),
                        dumps(snapshot.concentration),
                        snapshot.risk_state.value,
                        breaches_to_json(snapshot.breaches),
                        int(snapshot.degraded),
                        snapshot.degraded_reason,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record risk snapshot: {e}") from e

    def open_decision(self, ctx: DecisionContext) -> int:
        """Open a decision record. Closed later, exactly once, by a human."""
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO decision_records (
                        event_uid, created_at, trigger_type, trigger_detail,
                        snapshot_id, policy_version_id, portfolio_state_before,
                        risk_snapshot_before, optimizer_strategy,
                        expected_return_method, solver_status, control_status,
                        circuit_breaker_active, breaker_trigger_category,
                        recommended_candidate_id
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ctx.event_uid,
                        ctx.created_at.isoformat(),
                        ctx.trigger_type,
                        ctx.trigger_detail,
                        ctx.snapshot_id,
                        ctx.policy_version_id,
                        ctx.portfolio_state_before,
                        ctx.risk_snapshot_before,
                        ctx.optimizer_strategy,
                        ctx.expected_return_method,
                        ctx.solver_status,
                        ctx.control_status,
                        int(ctx.circuit_breaker_active),
                        ctx.breaker_trigger_category,
                        ctx.recommended_candidate_id,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to open decision: {e}") from e

    def record_candidate(
        self, decision_id: int, cand: Candidate, created_at: datetime | None = None
    ) -> int:
        """Persist one candidate allocation and every verdict on it.

        The metric columns come from ``cand.optimization`` and are the
        optimizer's ADVISORY self-report (FR-072). They are stored so the
        audit trail shows what the optimizer claimed next to what the control
        engine independently found — not because they are trusted.

        ``eligible_for_approval`` is taken from the contract property, which
        already requires control PASSED and stress PASSED. It is re-asserted
        here rather than recomputed: a second implementation of the approval
        gate is a bug waiting to diverge (INV-2, INV-10).
        """
        opt = cand.optimization
        eligible = cand.eligible_for_approval

        if eligible and not (
            cand.control is not None
            and cand.control.status is ControlStatus.PASSED
            and cand.stress_status is StressStatus.PASSED
        ):  # pragma: no cover - defends the invariant against contract drift
            raise AuditWriteError(
                "refusing to persist eligible_for_approval=1 without both "
                "control PASSED and stress PASSED (INV-2, INV-10)"
            )

        control_status = (
            cand.control.status.value
            if cand.control is not None
            else ControlStatus.NOT_VALIDATED.value
        )
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO candidate_allocations (
                        decision_id, created_at, candidate_role, strategy,
                        weights_json, expected_return, volatility, sharpe, var_95,
                        cvar_95, turnover, transaction_cost_paise, solver_status,
                        control_status, stress_status, eligible_for_approval
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        (created_at or _now()).isoformat(),
                        cand.role.value,
                        opt.strategy.value,
                        dumps(opt.weights or {}),
                        opt.expected_return,
                        opt.volatility,
                        opt.sharpe,
                        opt.var_95,
                        opt.cvar_95,
                        opt.turnover,
                        opt.transaction_cost_paise,
                        opt.solver_status.value,
                        control_status,
                        cand.stress_status.value,
                        int(eligible),
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record candidate: {e}") from e

    def record_explanation(
        self,
        decision_id: int,
        expl: Explanation,
        template_text: str,
        llm_text: str | None = None,
        llm_model: str | None = None,
        llm_error: str | None = None,
    ) -> int:
        """Persist the structured explanation and its prose.

        ``structured_json`` is the source of truth (FR-141). ``llm_text`` is
        stored as display text only; nothing ever parses it back into a
        decision, a metric or any state (INV-1).
        """
        structured_json = dumps(
            {
                "trigger": expl.trigger,
                "risk_change": _risk_change_dict(expl.risk_change),
                "main_contributors": [
                    _risk_change_dict(rc) for rc in expl.main_contributors
                ],
                "optimizer": expl.optimizer.value if expl.optimizer else None,
                "candidate_summary": expl.candidate_summary,
                "control_result": expl.control_result,
                "reasons": list(expl.reasons),
                "stress_summary": list(expl.stress_summary),
                "action": expl.action,
                "expected_improvement": expl.expected_improvement,
            }
        )
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO explanations (
                        decision_id, created_at, structured_json, template_text,
                        llm_used, llm_model, llm_text, llm_error
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        _now().isoformat(),
                        structured_json,
                        template_text,
                        int(llm_text is not None),
                        llm_model,
                        llm_text,
                        llm_error,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record explanation: {e}") from e

    # ------------------------------------------------------------------
    # the single guarded transition
    # ------------------------------------------------------------------

    def close_decision_with_human_action(
        self,
        decision_id: int,
        action: HumanActionRecord,
        portfolio_state_after: int | None,
        candidate_id: int | None = None,
    ) -> int:
        """Close a decision with a human action. Fails if already closed.

        Two writes in one transaction: the guarded UPDATE on
        ``decision_records``, and the full attribution row in
        ``human_actions``. The UPDATE alone would record only *what* was
        decided; INV-6 requires *who* decided it and why — including the
        override reason and the specific controls overridden (FR-118).

        Returns the ``human_actions`` row id.
        """
        try:
            with transaction(self.conn):
                row = self.conn.execute(
                    "SELECT human_action FROM decision_records WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()
                if row is None:
                    raise AuditWriteError(f"decision {decision_id} does not exist")
                if row["human_action"] is not None:
                    raise DecisionAlreadyClosed(
                        f"decision {decision_id} already closed with a human action "
                        f"({row['human_action']}); records are append-only (INV-6)"
                    )

                updated = self.conn.execute(
                    """
                    UPDATE decision_records
                       SET human_action = ?, portfolio_state_after = ?
                     WHERE decision_id = ? AND human_action IS NULL
                    """,
                    (action.action.value, portfolio_state_after, decision_id),
                )
                if updated.rowcount != 1:
                    raise AuditWriteError(
                        f"guarded update matched {updated.rowcount} rows for decision "
                        f"{decision_id}; refusing to report success"
                    )

                cur = self.conn.execute(
                    """
                    INSERT INTO human_actions (
                        decision_id, candidate_id, created_at, action, user_identity,
                        user_role, comment, is_override, override_reason,
                        overridden_controls_json, confirmation_token
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        candidate_id,
                        action.timestamp.isoformat(),
                        action.action.value,
                        action.user_identity,
                        action.user_role,
                        action.comment,
                        int(action.is_override),
                        action.override_reason,
                        dumps(list(action.overridden_controls)),
                        action.confirmation_token,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to close decision {decision_id}: {e}") from e


    def record_control_findings(
        self,
        decision_id: int,
        findings: Sequence[Breach],
        candidate_id: int | None = None,
        created_at: datetime | None = None,
    ) -> int:
        """Persist the control engine's findings for one candidate.

        Every finding carries its observed value AND its threshold, so the UI
        can show "43.0% > 35.0%" rather than "constraints violated" (FR-174).
        A finding written without them cannot be explained later.

        All findings are written in one transaction: a partial set would
        misrepresent the verdict. Returns the number of rows written.
        """
        if not findings:
            return 0
        stamp = (created_at or _now()).isoformat()
        try:
            with transaction(self.conn):
                self.conn.executemany(
                    """
                    INSERT INTO control_findings (
                        decision_id, candidate_id, created_at, control_code,
                        control_label, severity, is_hard, observed_value,
                        threshold_value, comparator, scope, message
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            decision_id,
                            candidate_id,
                            stamp,
                            b.control_code,
                            b.control_label,
                            b.severity.value,
                            int(b.is_hard),
                            b.observed,
                            b.threshold,
                            b.comparator.value,
                            b.scope,
                            b.message,
                        )
                        for b in findings
                    ],
                )
            return len(findings)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record control findings: {e}") from e

    def record_stress_results(
        self,
        decision_id: int,
        results: Sequence[StressResult],
        candidate_id: int | None = None,
        created_at: datetime | None = None,
    ) -> int:
        """Persist stress-scenario outcomes for one candidate.

        Both ``passed`` and the full ``status`` are stored. NOT_RUN and ERROR
        are never equivalent to PASSED, and after an incident the difference
        between "the portfolio failed the scenario" and "the stress engine
        errored" is exactly what someone needs from the audit trail (INV-10).

        Returns the number of rows written.
        """
        if not results:
            return 0
        stamp = (created_at or _now()).isoformat()
        try:
            with transaction(self.conn):
                self.conn.executemany(
                    """
                    INSERT INTO stress_results (
                        decision_id, candidate_id, created_at, scenario_code,
                        scenario_label, is_custom, shocks_json, portfolio_loss,
                        loss_paise, contribution_json, post_shock_vol,
                        post_shock_cvar, breaches_json, passed, loss_threshold,
                        status, error_reason
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            decision_id,
                            candidate_id,
                            stamp,
                            r.scenario_code,
                            r.scenario_label,
                            int(r.is_custom),
                            dumps(r.shocks),
                            r.portfolio_loss,
                            r.loss_paise,
                            dumps(r.contribution),
                            r.post_shock_volatility,
                            r.post_shock_cvar,
                            breaches_to_json(r.breaches),
                            int(r.status is StressStatus.PASSED),
                            r.loss_threshold,
                            r.status.value,
                            r.error_reason,
                        )
                        for r in results
                    ],
                )
            return len(results)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record stress results: {e}") from e

    def record_event(self, decision_id: int, event: DecisionEvent) -> int:
        """Append one row to the decision timeline.

        ``sequence_no`` is unique per decision, enforced by the schema. A
        duplicate is a bug in the caller's ordering, not something to
        overwrite — replay orders by this column, never by wall clock.
        """
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO decision_events (
                        decision_id, sequence_no, occurred_at, actor, event_code,
                        summary, detail_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        decision_id,
                        event.sequence_no,
                        event.occurred_at.isoformat(),
                        event.actor.value,
                        event.event_code,
                        event.summary,
                        dumps(event.detail) if event.detail is not None else None,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.IntegrityError as e:
            raise AuditWriteError(
                f"decision {decision_id} already has an event at sequence "
                f"{event.sequence_no}: {e}"
            ) from e
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to record event: {e}") from e

    def raise_alert(self, alert: Alert, decision_id: int | None = None) -> int:
        """Persist an alert raised by the engines.

        The engines CONSTRUCT alerts and perform no I/O; persistence happens
        here, at the edge.
        """
        try:
            with transaction(self.conn):
                cur = self.conn.execute(
                    """
                    INSERT INTO alerts (
                        created_at, decision_id, severity, category, title, message
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        alert.created_at.isoformat(),
                        decision_id,
                        alert.severity,
                        alert.category.value,
                        alert.title,
                        alert.message,
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to raise alert: {e}") from e

    def promote_safe_allocation(
        self,
        decision_id: int,
        candidate_id: int,
        portfolio_state_id: int,
        portfolio_id: str = "DEMO_100CR",
        approved_at: datetime | None = None,
    ) -> int:
        """Record a new Last Approved Safe Allocation.

        Only a candidate the control engine passed AND stress validation
        passed may be promoted, unless it was approved through an explicit,
        recorded override. That is re-checked against the PERSISTED candidate
        row rather than trusting the caller: the approval gate is enforced
        server-side, and a disabled button is convenience, not enforcement
        (INV-2, INV-10).

        ``approved_by`` and ``via_override`` are read from the decision's
        recorded human action, so a promotion cannot claim an approver the
        audit trail does not have (INV-6).

        Raises:
            AuditWriteError: If the candidate is not eligible and was not
                approved via a recorded override, or if the decision has no
                recorded human action.
        """
        try:
            with transaction(self.conn):
                cand = self.conn.execute(
                    """
                    SELECT eligible_for_approval, control_status, stress_status,
                           weights_json, decision_id
                      FROM candidate_allocations
                     WHERE candidate_id = ?
                    """,
                    (candidate_id,),
                ).fetchone()
                if cand is None:
                    raise AuditWriteError(f"candidate {candidate_id} does not exist")
                if int(cand["decision_id"]) != decision_id:
                    owner = cand["decision_id"]
                    raise AuditWriteError(
                        f"candidate {candidate_id} belongs to decision {owner}, "
                        f"not {decision_id}"
                    )

                human = self.conn.execute(
                    """
                    SELECT user_identity, is_override
                      FROM human_actions
                     WHERE decision_id = ?
                     ORDER BY action_id ASC LIMIT 1
                    """,
                    (decision_id,),
                ).fetchone()
                if human is None:
                    raise AuditWriteError(
                        f"decision {decision_id} has no recorded human action; an "
                        "allocation is never promoted without one (INV-6)"
                    )

                via_override = bool(human["is_override"])
                if not cand["eligible_for_approval"] and not via_override:
                    control, stress = cand["control_status"], cand["stress_status"]
                    raise AuditWriteError(
                        f"candidate {candidate_id} is not eligible for approval "
                        f"(control {control}, stress {stress}) and was not approved "
                        "through a recorded override (INV-2, INV-10)"
                    )

                decision = self.conn.execute(
                    "SELECT policy_version_id FROM decision_records "
                    "WHERE decision_id = ?",
                    (decision_id,),
                ).fetchone()

                cur = self.conn.execute(
                    """
                    INSERT INTO safe_allocations (
                        portfolio_id, approved_at, decision_id, candidate_id,
                        portfolio_state_id, weights_json, policy_version_id,
                        approved_by, via_override
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        portfolio_id,
                        (approved_at or _now()).isoformat(),
                        decision_id,
                        candidate_id,
                        portfolio_state_id,
                        cand["weights_json"],
                        decision["policy_version_id"],
                        human["user_identity"],
                        int(via_override),
                    ),
                )
                return int(cur.lastrowid or 0)
        except sqlite3.Error as e:
            raise AuditWriteError(f"failed to promote safe allocation: {e}") from e

    # ------------------------------------------------------------------
    # reads
    #
    # Thin delegations to cce.audit.queries. The repository stays the single
    # sanctioned surface; the SQL lives next to the read models it builds.
    # ------------------------------------------------------------------

    def get_last_safe_allocation(self, portfolio_id: str) -> SafeAllocation | None:
        """The Last Approved Safe Allocation, or ``None`` if there is none."""
        return queries.get_last_safe_allocation(self.conn, portfolio_id)

    def get_decision(self, decision_id: int) -> StoredDecision:
        """One complete decision, exactly as persisted."""
        return queries.get_decision(self.conn, decision_id)

    def get_replay_timeline(self, decision_id: int) -> list[DecisionEvent]:
        """The decision timeline, from persisted events only (INV-6)."""
        return queries.get_replay_timeline(self.conn, decision_id)

    def list_decisions(self, limit: int = 50, offset: int = 0) -> list[DecisionSummary]:
        """Decision history, newest first."""
        return queries.list_decisions(self.conn, limit, offset)

    def get_current_policy(self) -> Policy:
        """The most recent policy version."""
        return queries.get_current_policy(self.conn)

    def get_policy_version(self, policy_version_id: int) -> Policy:
        """The policy in force for a given version id (INV-8)."""
        return queries.get_policy_version(self.conn, policy_version_id)

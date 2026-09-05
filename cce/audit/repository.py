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

import json
import logging
import sqlite3
from dataclasses import dataclass
from datetime import datetime

from cce.contracts import (
    Candidate,
    ControlStatus,
    Explanation,
    HumanActionRecord,
    Policy,
    PortfolioOrigin,
    PortfolioState,
    RiskChange,
    RiskSnapshot,
    SafeAllocation,
    StressStatus,
)

from .database import transaction
from .serialization import breaches_to_json, dumps, policy_to_json, positions_to_json

logger = logging.getLogger(__name__)

__all__ = [
    "AuditRepository",
    "AuditWriteError",
    "DecisionContext",
    "MarketSnapshotMeta",
    "PolicyChangeMeta",
]


class AuditWriteError(Exception):
    """An audit write failed, or would have broken an append-only guarantee."""


def _now() -> datetime:
    """Timezone-aware wall clock. Audit rows never carry a naive timestamp."""
    return datetime.now().astimezone()


def _parse_dt(raw: str) -> datetime:
    """Parse a persisted timestamp.

    Stored timestamps are ISO-8601, but SQLite's own ``datetime('now')``
    produces a space-separated form with no zone, so both are accepted.
    """
    text = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text.replace(" ", "T"))


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


@dataclass(frozen=True)
class PolicyChangeMeta:
    """Attribution for a policy version (INV-8).

    A weakening change — any hard limit loosened — must carry who acknowledged
    it and why. That is the entire point of versioning thresholds rather than
    editing them.
    """

    created_by: str
    created_by_role: str
    source: str  # FILE | UI_EDIT | SEED
    created_at: datetime | None = None
    parent_version_id: int | None = None
    change_summary: str | None = None
    is_weakening: bool = False
    weakening_ack_by: str | None = None
    weakening_reason: str | None = None

    def __post_init__(self) -> None:
        if self.source not in {"FILE", "UI_EDIT", "SEED"}:
            raise ValueError(
                f"source must be FILE, UI_EDIT or SEED; got {self.source!r}"
            )
        if self.is_weakening and not (self.weakening_ack_by and self.weakening_reason):
            raise ValueError(
                "a weakening policy change requires weakening_ack_by and "
                "weakening_reason (INV-8)"
            )


@dataclass(frozen=True)
class MarketSnapshotMeta:
    """Provenance for one market-data panel."""

    captured_at: datetime
    as_of_date: str
    provider: str
    universe_hash: str
    data_hash: str
    row_count: int
    asset_count: int
    validation_status: str
    validation_json: str
    cache_path: str | None = None


@dataclass(frozen=True)
class DecisionContext:
    """Everything known when a decision cycle opens."""

    event_uid: str
    created_at: datetime
    trigger_type: str
    trigger_detail: str | None
    snapshot_id: int
    policy_version_id: int
    portfolio_state_before: int
    risk_snapshot_before: int
    control_status: str
    circuit_breaker_active: bool
    breaker_trigger_category: str | None = None
    optimizer_strategy: str | None = None
    expected_return_method: str | None = None
    solver_status: str | None = None
    recommended_candidate_id: int | None = None


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
                    raise AuditWriteError(
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

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def get_last_safe_allocation(self, portfolio_id: str) -> SafeAllocation | None:
        """The Last Approved Safe Allocation, or ``None`` if there is none.

        ``None`` means no allocation has ever been approved for this
        portfolio. The caller preserves the current allocation rather than
        inventing one (INV-4).
        """
        row = self.conn.execute(
            """
            SELECT safe_allocation_id, approved_at, weights_json, decision_id,
                   policy_version_id, approved_by, via_override
              FROM safe_allocations
             WHERE portfolio_id = ?
             ORDER BY approved_at DESC, safe_allocation_id DESC
             LIMIT 1
            """,
            (portfolio_id,),
        ).fetchone()
        if row is None:
            return None

        return SafeAllocation(
            safe_allocation_id=int(row["safe_allocation_id"]),
            approved_at=_parse_dt(row["approved_at"]),
            weights={k: float(v) for k, v in json.loads(row["weights_json"]).items()},
            decision_id=int(row["decision_id"]),
            policy_version_id=int(row["policy_version_id"]),
            approved_by=row["approved_by"],
            via_override=bool(row["via_override"]),
        )

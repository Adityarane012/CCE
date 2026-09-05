"""Reads against the decision store.

Spec: docs/05-BACKEND-SCHEMA.md section 6.

Plain functions over a connection, so each one is testable on its own and
``repository.py`` stays the single sanctioned surface rather than a single
enormous module. :class:`~cce.audit.repository.AuditRepository` delegates
here; nothing outside ``cce/audit/`` calls these directly.

Every function reads what was persisted and stops there. None of them
recompute a metric, re-derive a verdict, or fill a missing column with a
default — a read that quietly recalculates is not a record of what happened
(INV-6), and a ``None`` that becomes ``0.0`` on the way out is the false
safety signal INV-5 exists to prevent.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from cce.contracts import Actor, DecisionEvent, Policy, SafeAllocation, StressStatus

from .models import (
    DecisionSummary,
    StoredCandidate,
    StoredDecision,
    StoredHumanAction,
    StoredStressResult,
)
from .serialization import breaches_from_json, loads_or_none, policy_from_json

__all__ = [
    "get_current_policy",
    "get_decision",
    "get_last_safe_allocation",
    "get_policy_version",
    "get_replay_timeline",
    "list_decisions",
]


def parse_dt(raw: str) -> datetime:
    """Parse a persisted timestamp.

    Stored timestamps are ISO-8601, but SQLite's own ``datetime('now')``
    yields a space-separated form with no zone, so both are accepted.
    """
    text = raw.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return datetime.fromisoformat(text.replace(" ", "T"))


def _weights(raw: str) -> dict[str, float]:
    return {k: float(v) for k, v in json.loads(raw).items()}


# ---------------------------------------------------------------------------
# policy
# ---------------------------------------------------------------------------

def get_current_policy(conn: sqlite3.Connection) -> Policy:
    """The most recent policy version.

    Raises:
        LookupError: If no policy version exists. The seed guarantees one, so
            its absence means the database was not migrated — better to say
            so than to fall back to a default policy nobody configured.
    """
    row = conn.execute(
        "SELECT policy_json FROM policy_versions "
        "ORDER BY policy_version_id DESC LIMIT 1"
    ).fetchone()
    if row is None:
        raise LookupError(
            "no policy version in the database; run migrations before use"
        )
    return policy_from_json(row["policy_json"])


def get_policy_version(conn: sqlite3.Connection, policy_version_id: int) -> Policy:
    """The policy that was in force for a given version id.

    A risk verdict is only interpretable against the thresholds actually
    applied to it, so replay reads the version the decision recorded rather
    than whatever is current (INV-8).
    """
    row = conn.execute(
        "SELECT policy_json FROM policy_versions WHERE policy_version_id = ?",
        (policy_version_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"no policy version {policy_version_id}")
    return policy_from_json(row["policy_json"])


# ---------------------------------------------------------------------------
# safe allocations
# ---------------------------------------------------------------------------

def get_last_safe_allocation(
    conn: sqlite3.Connection, portfolio_id: str
) -> SafeAllocation | None:
    """The Last Approved Safe Allocation, or ``None`` if there is none.

    ``None`` means no allocation has ever been approved for this portfolio.
    The caller preserves the current allocation rather than inventing one
    (INV-4).
    """
    row = conn.execute(
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
        approved_at=parse_dt(row["approved_at"]),
        weights=_weights(row["weights_json"]),
        decision_id=int(row["decision_id"]),
        policy_version_id=int(row["policy_version_id"]),
        approved_by=row["approved_by"],
        via_override=bool(row["via_override"]),
    )


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------

def list_decisions(
    conn: sqlite3.Connection, limit: int = 50, offset: int = 0
) -> list[DecisionSummary]:
    """Decision history, newest first."""
    rows = conn.execute(
        """
        SELECT decision_id, event_uid, created_at, trigger_type, control_status,
               circuit_breaker_active, breaker_trigger_category, human_action
          FROM decision_records
         ORDER BY created_at DESC, decision_id DESC
         LIMIT ? OFFSET ?
        """,
        (limit, offset),
    ).fetchall()
    return [
        DecisionSummary(
            decision_id=int(r["decision_id"]),
            event_uid=r["event_uid"],
            created_at=parse_dt(r["created_at"]),
            trigger_type=r["trigger_type"],
            control_status=r["control_status"],
            circuit_breaker_active=bool(r["circuit_breaker_active"]),
            breaker_trigger_category=r["breaker_trigger_category"],
            human_action=r["human_action"],
        )
        for r in rows
    ]


def get_replay_timeline(
    conn: sqlite3.Connection, decision_id: int
) -> list[DecisionEvent]:
    """The decision timeline, from persisted events only.

    Ordered by ``sequence_no``, never by wall clock: two events written in the
    same millisecond must still replay in the order they occurred.

    An empty list means no events were recorded for this decision. It does not
    mean nothing happened, and the caller must not paper over it by
    reconstructing a plausible timeline (INV-6).
    """
    rows = conn.execute(
        """
        SELECT sequence_no, occurred_at, actor, event_code, summary, detail_json
          FROM decision_events
         WHERE decision_id = ?
         ORDER BY sequence_no ASC
        """,
        (decision_id,),
    ).fetchall()
    return [
        DecisionEvent(
            sequence_no=int(r["sequence_no"]),
            occurred_at=parse_dt(r["occurred_at"]),
            actor=Actor(r["actor"]),
            event_code=r["event_code"],
            summary=r["summary"],
            detail=loads_or_none(r["detail_json"]),
        )
        for r in rows
    ]


def _stress_for(conn: sqlite3.Connection, candidate_id: int) -> tuple[StoredStressResult, ...]:
    rows = conn.execute(
        "SELECT * FROM stress_results WHERE candidate_id = ? "
        "ORDER BY stress_result_id ASC",
        (candidate_id,),
    ).fetchall()
    return tuple(
        StoredStressResult(
            scenario_code=r["scenario_code"],
            scenario_label=r["scenario_label"],
            is_custom=bool(r["is_custom"]),
            portfolio_loss=float(r["portfolio_loss"]),
            loss_paise=int(r["loss_paise"]),
            loss_threshold=float(r["loss_threshold"]),
            passed=bool(r["passed"]),
            status=StressStatus(r["status"]),
            post_shock_volatility=r["post_shock_vol"],
            post_shock_cvar=r["post_shock_cvar"],
            shocks=loads_or_none(r["shocks_json"]) or {},
            contribution=loads_or_none(r["contribution_json"]) or {},
            breaches=breaches_from_json(r["breaches_json"]),
        )
        for r in rows
    )


def _findings_for(conn: sqlite3.Connection, candidate_id: int):
    rows = conn.execute(
        """
        SELECT control_code, control_label, severity, is_hard, observed_value,
               threshold_value, comparator, scope, message
          FROM control_findings
         WHERE candidate_id = ?
         ORDER BY finding_id ASC
        """,
        (candidate_id,),
    ).fetchall()
    return breaches_from_json(
        json.dumps(
            [
                {
                    "control_code": r["control_code"],
                    "control_label": r["control_label"],
                    "severity": r["severity"],
                    "is_hard": bool(r["is_hard"]),
                    "observed": r["observed_value"],
                    "threshold": r["threshold_value"],
                    "comparator": r["comparator"],
                    "scope": r["scope"],
                    "message": r["message"],
                }
                for r in rows
            ]
        )
    )


def _candidates_for(
    conn: sqlite3.Connection, decision_id: int
) -> tuple[StoredCandidate, ...]:
    rows = conn.execute(
        "SELECT * FROM candidate_allocations WHERE decision_id = ? "
        "ORDER BY candidate_id ASC",
        (decision_id,),
    ).fetchall()
    return tuple(
        StoredCandidate(
            candidate_id=int(r["candidate_id"]),
            decision_id=int(r["decision_id"]),
            created_at=parse_dt(r["created_at"]),
            role=r["candidate_role"],
            strategy=r["strategy"],
            weights=_weights(r["weights_json"]),
            solver_status=r["solver_status"],
            control_status=r["control_status"],
            stress_status=r["stress_status"],
            eligible_for_approval=bool(r["eligible_for_approval"]),
            expected_return=r["expected_return"],
            volatility=r["volatility"],
            sharpe=r["sharpe"],
            var_95=r["var_95"],
            cvar_95=r["cvar_95"],
            turnover=r["turnover"],
            transaction_cost_paise=r["transaction_cost_paise"],
            findings=_findings_for(conn, int(r["candidate_id"])),
            stress=_stress_for(conn, int(r["candidate_id"])),
        )
        for r in rows
    )


def _human_action_for(
    conn: sqlite3.Connection, decision_id: int
) -> StoredHumanAction | None:
    row = conn.execute(
        "SELECT * FROM human_actions WHERE decision_id = ? "
        "ORDER BY action_id ASC LIMIT 1",
        (decision_id,),
    ).fetchone()
    if row is None:
        return None
    return StoredHumanAction(
        action_id=int(row["action_id"]),
        created_at=parse_dt(row["created_at"]),
        action=row["action"],
        user_identity=row["user_identity"],
        user_role=row["user_role"],
        candidate_id=row["candidate_id"],
        comment=row["comment"],
        is_override=bool(row["is_override"]),
        override_reason=row["override_reason"],
        overridden_controls=tuple(loads_or_none(row["overridden_controls_json"]) or ()),
        confirmation_token=row["confirmation_token"],
    )


def get_decision(conn: sqlite3.Connection, decision_id: int) -> StoredDecision:
    """One complete decision, exactly as persisted.

    Raises:
        LookupError: If the decision does not exist.
    """
    row = conn.execute(
        "SELECT * FROM decision_records WHERE decision_id = ?", (decision_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"no decision {decision_id}")

    expl = conn.execute(
        "SELECT structured_json, template_text, llm_text FROM explanations "
        "WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()

    return StoredDecision(
        decision_id=int(row["decision_id"]),
        event_uid=row["event_uid"],
        created_at=parse_dt(row["created_at"]),
        trigger_type=row["trigger_type"],
        trigger_detail=row["trigger_detail"],
        snapshot_id=int(row["snapshot_id"]),
        policy_version_id=int(row["policy_version_id"]),
        portfolio_state_before=int(row["portfolio_state_before"]),
        risk_snapshot_before=int(row["risk_snapshot_before"]),
        control_status=row["control_status"],
        circuit_breaker_active=bool(row["circuit_breaker_active"]),
        breaker_trigger_category=row["breaker_trigger_category"],
        optimizer_strategy=row["optimizer_strategy"],
        expected_return_method=row["expected_return_method"],
        solver_status=row["solver_status"],
        recommended_candidate_id=row["recommended_candidate_id"],
        portfolio_state_after=row["portfolio_state_after"],
        candidates=_candidates_for(conn, decision_id),
        events=tuple(get_replay_timeline(conn, decision_id)),
        human_action=_human_action_for(conn, decision_id),
        template_text=expl["template_text"] if expl else None,
        llm_text=expl["llm_text"] if expl else None,
        structured_explanation=loads_or_none(expl["structured_json"]) if expl else None,
    )

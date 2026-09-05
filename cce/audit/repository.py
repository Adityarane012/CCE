import json
import logging
from dataclasses import dataclass

from ..contracts import (
    Candidate,
    Explanation,
    HumanActionRecord,
    Policy,
    PortfolioState,
    RiskSnapshot,
    SafeAllocation,
)

logger = logging.getLogger(__name__)

class AuditWriteError(Exception):
    """Raised when an audit write fails to maintain the append-only or invariant constraints."""


@dataclass
class PolicyChangeMeta:
    created_by: str
    created_by_role: str
    source: str
    change_summary: str | None = None
    is_weakening: bool = False
    weakening_ack_by: str | None = None
    weakening_reason: str | None = None


@dataclass
class MarketSnapshotMeta:
    captured_at: str
    as_of_date: str
    provider: str
    universe_hash: str
    data_hash: str
    row_count: int
    asset_count: int
    validation_status: str
    validation_json: str
    cache_path: str | None = None


@dataclass
class DecisionContext:
    event_uid: str
    created_at: str
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


@dataclass
class Alert:
    created_at: str
    decision_id: int | None
    severity: str
    category: str
    title: str
    message: str


class AuditRepository:
    def __init__(self, conn):
        self.conn = conn

    def record_policy_version(self, policy: Policy, meta: PolicyChangeMeta) -> int:
        cur = self.conn.cursor()
        try:
            # Need to convert Policy to json (mock implementation for now)
            # as it relies on specific formatting not yet fully serialized here.
            # We'll assume a dummy json for now or an existing dict struct.
            policy_json = "{}"
            cur.execute("""
                INSERT INTO policy_versions (
                    created_at, created_by, created_by_role, source, policy_json,
                    change_summary, is_weakening, weakening_ack_by, weakening_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                "2026-08-31T00:00:00Z", meta.created_by, meta.created_by_role, meta.source,
                policy_json, meta.change_summary, 1 if meta.is_weakening else 0,
                meta.weakening_ack_by, meta.weakening_reason
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record policy version: {e}")

    def record_market_snapshot(self, snap: MarketSnapshotMeta) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute("""
                INSERT INTO market_snapshots (
                    captured_at, as_of_date, provider, universe_hash, data_hash,
                    row_count, asset_count, validation_status, validation_json, cache_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snap.captured_at, snap.as_of_date, snap.provider, snap.universe_hash,
                snap.data_hash, snap.row_count, snap.asset_count, snap.validation_status,
                snap.validation_json, snap.cache_path
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record market snapshot: {e}")

    def record_portfolio_state(self, state: PortfolioState, origin: str) -> int:
        cur = self.conn.cursor()
        try:
            positions_json = json.dumps([p.__dict__ for p in state.positions])
            weights_json = json.dumps(state.weights)
            cur.execute("""
                INSERT INTO portfolio_states (
                    portfolio_id, created_at, as_of_date, total_value_paise, cash_value_paise,
                    positions_json, weights_json, origin, source_decision_id, snapshot_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            """, (
                state.portfolio_id, state.timestamp.isoformat(), state.as_of_date.isoformat(),
                state.total_value_paise, state.cash_value_paise, positions_json, weights_json,
                origin, 1 # dummy snapshot_id, typically fetched from context
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record portfolio state: {e}")

    def open_decision(self, ctx: DecisionContext) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute("""
                INSERT INTO decision_records (
                    event_uid, created_at, trigger_type, trigger_detail, snapshot_id,
                    policy_version_id, portfolio_state_before, risk_snapshot_before,
                    control_status, circuit_breaker_active, breaker_trigger_category,
                    optimizer_strategy, expected_return_method, solver_status,
                    recommended_candidate_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                ctx.event_uid, ctx.created_at, ctx.trigger_type, ctx.trigger_detail,
                ctx.snapshot_id, ctx.policy_version_id, ctx.portfolio_state_before,
                ctx.risk_snapshot_before, ctx.control_status,
                1 if ctx.circuit_breaker_active else 0, ctx.breaker_trigger_category,
                ctx.optimizer_strategy, ctx.expected_return_method, ctx.solver_status,
                ctx.recommended_candidate_id
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to open decision: {e}")

    def close_decision_with_human_action(self, decision_id: int, action: HumanActionRecord, portfolio_state_after: int | None) -> None:
        cur = self.conn.cursor()
        try:
            # First, check if already closed
            cur.execute("SELECT human_action FROM decision_records WHERE decision_id = ?", (decision_id,))
            row = cur.fetchone()
            if not row:
                raise ValueError("Decision record not found.")
            if row[0] is not None:
                raise AuditWriteError("Decision already closed with a human action.")
                
            cur.execute("""
                UPDATE decision_records
                SET human_action = ?, portfolio_state_after = ?
                WHERE decision_id = ? AND human_action IS NULL
            """, (action.action.name, portfolio_state_after, decision_id))
            
            if cur.rowcount == 0:
                raise AuditWriteError("Failed to close decision. Action was already taken or decision not found.")
                
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Error closing decision: {e}")

    def record_risk_snapshot(self, snapshot: RiskSnapshot, portfolio_state_id: int, snapshot_id: int, policy_version_id: int) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute("""
                INSERT INTO risk_snapshots (
                    created_at, portfolio_state_id, snapshot_id, policy_version_id,
                    historical_volatility, ewma_volatility, portfolio_volatility,
                    expected_return, expected_return_method, sharpe, var_95, cvar_95,
                    var_method, current_drawdown, max_drawdown, liquidity_ratio,
                    turnover_from_current, risk_contribution_json, sector_exposure_json,
                    sector_risk_contrib_json, concentration_json, risk_state,
                    breaches_json, degraded, degraded_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.timestamp.isoformat(), portfolio_state_id, snapshot_id, policy_version_id,
                snapshot.historical_volatility, snapshot.ewma_volatility, snapshot.portfolio_volatility,
                snapshot.expected_return, snapshot.expected_return_method.name if snapshot.expected_return_method else None,
                snapshot.sharpe, snapshot.var_95, snapshot.cvar_95, snapshot.var_method.name if snapshot.var_method else None,
                snapshot.current_drawdown, snapshot.max_drawdown, snapshot.liquidity_ratio,
                snapshot.turnover_from_current, 
                json.dumps(snapshot.risk_contribution) if snapshot.risk_contribution else None,
                json.dumps(snapshot.sector_exposure) if snapshot.sector_exposure else None,
                json.dumps(snapshot.sector_risk_contrib) if snapshot.sector_risk_contrib else None,
                json.dumps(snapshot.concentration) if snapshot.concentration else None,
                snapshot.risk_state.name,
                json.dumps([b.__dict__ for b in snapshot.breaches]) if snapshot.breaches else "[]",
                1 if snapshot.degraded else 0,
                snapshot.degraded_reason
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record risk snapshot: {e}")

    def record_candidate(self, decision_id: int, cand: Candidate) -> int:
        cur = self.conn.cursor()
        try:
            cur.execute("""
                INSERT INTO candidate_allocations (
                    decision_id, created_at, candidate_role, strategy, weights_json,
                    expected_return, volatility, sharpe, var_95, cvar_95, turnover,
                    transaction_cost_paise, solver_status, control_status, stress_status,
                    eligible_for_approval
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                decision_id, cand.created_at.isoformat(), cand.role.name, cand.strategy.name,
                json.dumps(cand.weights), cand.expected_return, cand.volatility, cand.sharpe,
                cand.var_95, cand.cvar_95, cand.turnover, cand.transaction_cost_paise,
                cand.solver_status.name, cand.control_status.name, cand.stress_status.name,
                1 if cand.eligible_for_approval else 0
            ))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record candidate: {e}")

    def record_explanation(self, decision_id: int, expl: Explanation, template_text: str) -> int:
        cur = self.conn.cursor()
        try:
            # We serialize expl to json directly
            structured_json = json.dumps({
                "trigger": expl.trigger,
                "risk_change": expl.risk_change.__dict__ if expl.risk_change else None,
                "main_contributors": [rc.__dict__ for rc in expl.main_contributors],
                "optimizer": expl.optimizer.name if expl.optimizer else None,
                "candidate_summary": expl.candidate_summary,
                "control_result": expl.control_result,
                "reasons": expl.reasons,
                "stress_summary": expl.stress_summary,
                "action": expl.action,
                "expected_improvement": expl.expected_improvement
            })
            cur.execute("""
                INSERT INTO explanations (
                    decision_id, created_at, structured_json, template_text,
                    llm_used, llm_model, llm_text, llm_error
                ) VALUES (?, datetime('now'), ?, ?, 0, NULL, NULL, NULL)
            """, (decision_id, structured_json, template_text))
            self.conn.commit()
            return cur.lastrowid
        except Exception as e:
            self.conn.rollback()
            raise AuditWriteError(f"Failed to record explanation: {e}")

    def get_last_safe_allocation(self, portfolio_id: str) -> SafeAllocation | None:
        cur = self.conn.cursor()
        cur.execute("""
            SELECT * FROM safe_allocations
            WHERE portfolio_id = ?
            ORDER BY approved_at DESC
            LIMIT 1;
        """, (portfolio_id,))
        row = cur.fetchone()
        if not row:
            return None
        # In a real app we'd construct the dataclass exactly
        return SafeAllocation(
            safe_allocation_id=row["safe_allocation_id"],
            approved_at=row["approved_at"],  # parse datetime
            weights=json.loads(row["weights_json"]),
            decision_id=row["decision_id"],
            policy_version_id=row["policy_version_id"],
            approved_by=row["approved_by"],
            via_override=bool(row["via_override"])
        )

"""Human approval, and the simulated rebalance that follows it.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/13-EDGE-CASES.md section 7.

Three things this module enforces, none of which the UI is trusted to do:

1. **Eligibility is re-checked server-side** (INV-2). A disabled Approve
   button is a convenience. This is the enforcement.
2. **The candidate is re-validated against CURRENT market data** (EC-7.1).
   A recommendation generated ten minutes ago was judged against a panel that
   may have moved; approving on that verdict approves a conclusion nobody
   drew about today.
3. **The state change and its audit record commit together** (INV-6, EC-7.3).
   A portfolio updated without its record is worse than no change at all, so
   everything runs in one transaction and a failure leaves the book untouched.

No broker. No orders. The rebalance is simulated (FR-120).
"""

from __future__ import annotations

import logging

from cce.audit import (
    EVENT_HUMAN_ACTION,
    EVENT_SAFE_ALLOCATION_PROMOTED,
    EVENT_SAFE_ALLOCATION_RETAINED,
    make_event,
)
from cce.contracts import (
    Candidate,
    HumanAction,
    HumanActionRecord,
    PortfolioOrigin,
    PortfolioState,
)
from cce.exceptions import ApprovalNotPermitted
from cce.portfolio import rebalance_to, transaction_cost_paise

from .context import ServiceContext
from .optimization_service import OptimizationService

logger = logging.getLogger(__name__)

__all__ = ["ApprovalService"]

STALE_MESSAGE = (
    "Market conditions have changed since this recommendation was generated. "
    "Re-run the optimization."
)


class ApprovalService:
    """The only path from a candidate to a changed portfolio."""

    def __init__(
        self, ctx: ServiceContext, optimization: OptimizationService | None = None
    ) -> None:
        self._ctx = ctx
        self._optimization = optimization or OptimizationService(ctx)

    # ------------------------------------------------------------------
    # the four human actions (FR-115)
    # ------------------------------------------------------------------

    def approve(
        self,
        decision_id: int,
        candidate: Candidate,
        actor: HumanActionRecord,
        state: PortfolioState,
    ) -> PortfolioState:
        """Approve a candidate and simulate the rebalance.

        Raises:
            ApprovalNotPermitted: If the candidate is not eligible, or is no
                longer eligible against current data.
            DecisionAlreadyClosed: If a human already acted on this decision.
        """
        if actor.action is not HumanAction.APPROVE:
            raise ApprovalNotPermitted(
                f"approve() requires action APPROVE, got {actor.action.value}"
            )
        self._require_eligible(candidate)
        self._require_fresh(candidate, state)
        return self._adopt(decision_id, candidate, actor, state, via_override=False)

    def override(
        self,
        decision_id: int,
        candidate: Candidate,
        actor: HumanActionRecord,
        state: PortfolioState,
    ) -> PortfolioState:
        """Adopt a candidate the control engine rejected.

        Permitted, and recorded as an override with its reason and the
        specific controls overridden — ``HumanActionRecord.__post_init__``
        refuses to construct one without them (FR-118, EC-7.4).

        Eligibility is deliberately NOT re-checked: overriding is the act of
        proceeding despite the verdict. Staleness still is, because approving
        against a panel that has moved is a different mistake, and one nobody
        intended to make.
        """
        if not actor.is_override or actor.action is not HumanAction.OVERRIDE:
            raise ApprovalNotPermitted(
                "override() requires a HumanActionRecord with action OVERRIDE "
                "and is_override=True"
            )
        self._require_fresh(candidate, state)
        return self._adopt(decision_id, candidate, actor, state, via_override=True)

    def reject(self, decision_id: int, actor: HumanActionRecord) -> None:
        """Reject the proposal. The portfolio is not changed."""
        self._close_without_change(decision_id, actor)

    def keep_current(self, decision_id: int, actor: HumanActionRecord) -> None:
        """Keep the current allocation. The portfolio is not changed."""
        self._close_without_change(decision_id, actor)

    # ------------------------------------------------------------------
    # enforcement
    # ------------------------------------------------------------------

    def _require_eligible(self, candidate: Candidate) -> None:
        """INV-2, server-side. The reasons are specific, never generic."""
        if candidate.eligible_for_approval:
            return
        reasons = candidate.rejection_reasons
        detail = "; ".join(reasons) if reasons else (
            f"control {candidate.control.status.value if candidate.control else 'NOT_VALIDATED'}, "
            f"stress {candidate.stress_status.value}"
        )
        raise ApprovalNotPermitted(
            f"candidate {candidate.role.value} is not eligible for approval: {detail}"
        )

    def _require_fresh(self, candidate: Candidate, state: PortfolioState) -> None:
        """EC-7.1: re-judge against CURRENT data before adopting.

        The candidate's own ``control`` was computed when it was proposed.
        This re-runs the independent validation on today's panel and refuses
        if the verdict has changed for the worse. An allocation that passed
        yesterday is not thereby safe today, and the audit trail must not
        record that it was.
        """
        weights = candidate.optimization.weights
        if weights is None:
            raise ApprovalNotPermitted(
                f"candidate {candidate.role.value} carries no weights; there is "
                "nothing to adopt"
            )

        rejudged = self._optimization.propose_from_weights(weights, state, candidate.role)
        if candidate.eligible_for_approval and not rejudged.eligible_for_approval:
            reasons = "; ".join(rejudged.rejection_reasons)
            logger.warning(
                "candidate %s went stale before approval: %s",
                candidate.role.value, reasons,
            )
            raise ApprovalNotPermitted(
                f"{STALE_MESSAGE} ({reasons})" if reasons else STALE_MESSAGE
            )

    # ------------------------------------------------------------------
    # the state change
    # ------------------------------------------------------------------

    def _adopt(
        self,
        decision_id: int,
        candidate: Candidate,
        actor: HumanActionRecord,
        state: PortfolioState,
        via_override: bool,
    ) -> PortfolioState:
        """Simulated rebalance, recorded in the same transaction (INV-6).

        Order matters: the new state is written first so the decision can
        reference it, the decision is closed second (which is the guarded
        transition), and the allocation is promoted last — promotion reads the
        human action, so it must come after. All inside one transaction, so a
        failure anywhere leaves the portfolio exactly as it was (EC-7.3).
        """
        weights = candidate.optimization.weights
        if weights is None:                       # pragma: no cover - guarded above
            raise ApprovalNotPermitted("candidate carries no weights")

        cost = transaction_cost_paise(
            weights, state.weights, self._ctx.universe, state.total_value_paise
        )
        new_state = rebalance_to(
            state, weights, self._ctx.universe, self._ctx.market_data,
            transaction_cost_paise=cost,
        )

        repo = self._ctx.repo
        candidate_id = self._candidate_id(decision_id, candidate)

        with self._ctx.repo.atomic():
            state_id = repo.record_portfolio_state(
                new_state, PortfolioOrigin.SIMULATED_REBALANCE,
                self._ctx.snapshot_id, source_decision_id=decision_id,
            )
            repo.close_decision_with_human_action(
                decision_id, actor, portfolio_state_after=state_id,
                candidate_id=candidate_id,
            )
            repo.promote_safe_allocation(
                decision_id, candidate_id, state_id,
                portfolio_id=self._ctx.portfolio_id,
            )
            seq = self._next_sequence(decision_id)
            repo.record_event(decision_id, make_event(
                seq, EVENT_HUMAN_ACTION,
                f"{actor.user_identity} chose {actor.action.value}"
                + (" (override)" if via_override else ""),
                detail={"role": candidate.role.value, "via_override": via_override},
            ))
            repo.record_event(decision_id, make_event(
                seq + 1, EVENT_SAFE_ALLOCATION_PROMOTED,
                "Last Approved Safe Allocation updated",
                detail={"candidate_id": candidate_id},
            ))

        return new_state

    def _close_without_change(
        self, decision_id: int, actor: HumanActionRecord
    ) -> None:
        """Record the decision. The portfolio is untouched.

        ``portfolio_state_after`` stays NULL — nothing was adopted, and
        pointing it at the unchanged current state would read as a rebalance
        that happened to produce the same weights.
        """
        with self._ctx.repo.atomic():
            self._ctx.repo.close_decision_with_human_action(
                decision_id, actor, portfolio_state_after=None,
            )
            seq = self._next_sequence(decision_id)
            self._ctx.repo.record_event(decision_id, make_event(
                seq, EVENT_HUMAN_ACTION,
                f"{actor.user_identity} chose {actor.action.value}",
            ))
            self._ctx.repo.record_event(decision_id, make_event(
                seq + 1, EVENT_SAFE_ALLOCATION_RETAINED,
                "Last Approved Safe Allocation retained unchanged",
            ))

    # ------------------------------------------------------------------
    # helpers
    # ------------------------------------------------------------------

    def _candidate_id(self, decision_id: int, candidate: Candidate) -> int:
        cid = self._ctx.repo.get_candidate_id(decision_id, candidate.role.value)
        if cid is None:
            raise ApprovalNotPermitted(
                f"decision {decision_id} has no persisted {candidate.role.value} "
                "candidate; it cannot be approved"
            )
        return cid

    def _next_sequence(self, decision_id: int) -> int:
        return self._ctx.repo.next_event_sequence(decision_id)

"""Proposal, independent validation and stress testing as one unit.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/04-WORKFLOW.md.

**There is no public path here that optimizes without validating.** That is
the whole point of the method boundary: the UI cannot skip the control engine
because no callable exists that would let it. ``_optimize`` is private and
returns an ``OptimizationResult`` that never leaves this module unvalidated.

This module is also where the engines meet persistence. Phases 5-7 built them
as pure functions that construct ``Alert`` and ``DecisionEvent`` objects and
write nothing; :meth:`OptimizationService.run_cycle` is what actually records
them. If a control or stress module ever needs to import ``cce.audit``, the
work belongs here instead.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace

import numpy as np

from cce.audit import (
    EVENT_BREAKER_TRIPPED,
    EVENT_CANDIDATE_PROPOSED,
    EVENT_CONTROL_REJECTED,
    EVENT_CONTROL_VALIDATED,
    EVENT_RECOVERY_GENERATED,
    EVENT_RISK_COMPUTED,
    EVENT_SAFE_ALLOCATION_RETAINED,
    EVENT_STRESS_COMPLETED,
    EVENT_TRIGGER_RECEIVED,
    DecisionContext,
    make_event,
)
from cce.clock import utc_now
from cce.contracts import (
    Candidate,
    CandidateRole,
    Constraints,
    ControlStatus,
    ExpectedReturnMethod,
    NarratedExplanation,
    OptimizationResult,
    PortfolioState,
    RiskChange,
    SolverStatus,
    Strategy,
    TriggerType,
)
from cce.controls import evaluate_breaker, generate_recovery_candidates, validate
from cce.decisions import build_explanation
from cce.decisions.llm import narrate
from cce.optimizer import (
    CVaROptimizer,
    HRPOptimizer,
    MaxSharpeOptimizer,
    MinVolatilityOptimizer,
    OptimizerInputs,
    TargetReturnOptimizer,
    View,
    black_litterman,
    failed_result,
)
from cce.risk import estimate_covariance, expected_returns

from .context import ServiceContext
from .stress_service import StressService

logger = logging.getLogger(__name__)

__all__ = ["DecisionCycle", "OptimizationService"]


@dataclass(frozen=True)
class DecisionCycle:
    """One persisted decision cycle: what was proposed and what was decided."""

    decision_id: int
    candidates: tuple[Candidate, ...]
    candidate_ids: dict[str, int]          # CandidateRole.value -> candidate_id
    breaker_tripped: bool
    recommended_role: CandidateRole | None

    def candidate(self, role: CandidateRole) -> Candidate | None:
        for c in self.candidates:
            if c.role is role:
                return c
        return None


class OptimizationService:
    """Proposes allocations and has them independently judged."""

    def __init__(self, ctx: ServiceContext, stress: StressService | None = None) -> None:
        self._ctx = ctx
        self._stress = stress or StressService(ctx)

    # ------------------------------------------------------------------
    # the one unit of work
    # ------------------------------------------------------------------

    def propose(
        self,
        state: PortfolioState,
        strategy: Strategy = Strategy.MAX_SHARPE,
        er_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL,
        overrides: Constraints | None = None,
        role: CandidateRole = CandidateRole.SAFE_CONSTRAINED,
        target_return: float | None = None,
        views: tuple[View, ...] = (),
    ) -> Candidate:
        """Optimize, then independently validate, then stress test.

        One unit of work, always in that order. The validation step does NOT
        receive the ``OptimizationResult`` — it is handed the weight vector
        and re-derives every metric from raw returns, so an optimizer that
        reports an optimistic CVaR cannot talk its way through the gate
        (FR-072, INV-2).
        """
        opt = self._optimize(
            strategy, er_method, overrides, state,
            target_return=target_return, views=views,
        )
        return self._judge(opt, state, role)

    def propose_from_weights(
        self,
        weights: dict[str, float],
        state: PortfolioState,
        role: CandidateRole = CandidateRole.SAFE_CONSTRAINED,
    ) -> Candidate:
        """Judge an EXISTING allocation against current data.

        Same validate-then-stress unit as :meth:`propose`, without the
        optimizer: used to re-check a candidate before approving it, since
        the verdict attached to it was reached against whatever panel was
        current when it was proposed (EC-7.1).

        The synthesised ``OptimizationResult`` carries no advisory metrics.
        They would be the earlier proposal's numbers, and nothing here
        recomputes them — the control engine derives its own, which is the
        only opinion that matters (FR-072).
        """
        opt = OptimizationResult(
            strategy=Strategy.MAX_SHARPE,
            expected_return_method=ExpectedReturnMethod.HISTORICAL,
            solver_status=SolverStatus.OPTIMAL,
            weights=dict(weights),
        )
        return self._judge(opt, state, role)

    def propose_safe_and_optimal(
        self,
        state: PortfolioState,
        strategy: Strategy = Strategy.MAX_SHARPE,
        er_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL,
        target_return: float | None = None,
        views: tuple[View, ...] = (),
    ) -> tuple[Candidate, Candidate]:
        """``(optimal_unconstrained, safe_constrained)`` for the Safe vs Optimal view.

        Both are judged. The unconstrained optimum is expected to fail, and it
        is returned anyway — showing the allocation that was rejected, beside
        the one that was not, is the product's central claim. It is never
        silently replaced by the safe one (INV-9).
        """
        unconstrained = self._judge(
            self._optimize_unconstrained(er_method, state),
            state, CandidateRole.OPTIMAL_UNCONSTRAINED,
        )
        safe = self.propose(
            state, strategy, er_method, role=CandidateRole.SAFE_CONSTRAINED,
            target_return=target_return, views=views,
        )
        return unconstrained, safe

    def generate_recovery_candidates(
        self, state: PortfolioState, er_method: ExpectedReturnMethod =
        ExpectedReturnMethod.HISTORICAL,
    ) -> tuple[Candidate, ...]:
        """Up to three defensive alternatives, each independently validated.

        The optimizers run HERE and their results are handed to
        ``cce.controls``, so the control package never imports the optimizer
        (INV-2). A recovery that fails validation is still returned, with its
        reasons — never dropped, never marked approvable (EC-5.1).
        """
        inputs = self._inputs(er_method, state)
        optimizations: dict[CandidateRole, OptimizationResult] = {}

        optimizations[CandidateRole.RECOVERY_MAX_SHARPE] = MaxSharpeOptimizer().solve(
            inputs
        )
        optimizations[CandidateRole.RECOVERY_MIN_RISK] = (
            MinVolatilityOptimizer().solve(inputs)
        )
        defensive = replace(
            inputs,
            constraints=replace(
                inputs.constraints,
                max_turnover=min(
                    inputs.constraints.max_turnover,
                    self._ctx.policy.recovery_max_turnover,
                ),
            ),
        )
        optimizations[CandidateRole.RECOVERY_DEFENSIVE] = (
            MinVolatilityOptimizer().solve(defensive)
        )

        candidates = generate_recovery_candidates(
            optimizations, self._ctx.universe, self._ctx.market_data,
            state.weights, self._ctx.policy,
            total_value_paise=state.total_value_paise,
        )
        # controls/ cannot run the stress engine either; attach it here.
        return tuple(self._with_stress(c, state) for c in candidates)

    # ------------------------------------------------------------------
    # persistence — the engines construct, this records
    # ------------------------------------------------------------------

    def run_cycle(
        self,
        state: PortfolioState,
        trigger: TriggerType = TriggerType.USER_REQUEST,
        trigger_detail: str | None = None,
        strategy: Strategy = Strategy.MAX_SHARPE,
        er_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL,
        target_return: float | None = None,
        views: tuple[View, ...] = (),
    ) -> DecisionCycle:
        """Run a full decision cycle and record it.

        Detect -> optimize -> validate -> stress -> breaker -> persist. Every
        write happens inside ONE transaction: a decision record without its
        candidates, or a tripped breaker without its alert, is a worse
        artefact than no record at all (INV-6).
        """
        unconstrained, safe = self.propose_safe_and_optimal(
            state, strategy, er_method,
            target_return=target_return, views=views,
        )
        last_safe = self._ctx.repo.get_last_safe_allocation(self._ctx.portfolio_id)

        recovery: tuple[Candidate, ...] = ()
        if not safe.eligible_for_approval:
            recovery = self.generate_recovery_candidates(state, er_method)

        outcome = evaluate_breaker(safe, last_safe, recovery_candidates=recovery)

        recommended = self._recommend(safe, recovery)
        candidates = (unconstrained, safe, *recovery)

        with self._ctx.repo.atomic():
            decision_id = self._ctx.repo.open_decision(DecisionContext(
                event_uid=str(uuid.uuid4()),
                created_at=utc_now(),
                trigger_type=trigger.value,
                trigger_detail=trigger_detail,
                snapshot_id=self._ctx.snapshot_id,
                policy_version_id=self._ctx.policy_version_id,
                portfolio_state_before=self._state_id(state),
                risk_snapshot_before=self._risk_snapshot_id(safe, state),
                control_status=(
                    safe.control.status.value if safe.control
                    else ControlStatus.NOT_VALIDATED.value
                ),
                circuit_breaker_active=outcome.tripped,
                breaker_trigger_category=(
                    outcome.category.value if outcome.category else None
                ),
                optimizer_strategy=strategy.value,
                expected_return_method=er_method.value,
                solver_status=safe.optimization.solver_status.value,
            ))

            candidate_ids: dict[str, int] = {}
            for cand in candidates:
                cid = self._ctx.repo.record_candidate(decision_id, cand)
                candidate_ids[cand.role.value] = cid
                if cand.control is not None:
                    self._ctx.repo.record_control_findings(
                        decision_id, list(cand.control.findings), cid
                    )
                if cand.stress:
                    self._ctx.repo.record_stress_results(
                        decision_id, list(cand.stress), cid
                    )

            if outcome.alert is not None:
                self._ctx.repo.raise_alert(outcome.alert, decision_id)

            for event in self._events(safe, outcome, recovery, trigger_detail):
                self._ctx.repo.record_event(decision_id, event)

            narrated = self._explain(
                safe, unconstrained, outcome, recovery, strategy, trigger_detail
            )
            self._ctx.repo.record_explanation(
                decision_id, narrated.structured, narrated.template_text,
                llm_text=narrated.llm_text, llm_model=narrated.llm_model,
                llm_error=narrated.llm_error,
            )

            if recommended is not None:
                recommended_id = candidate_ids.get(recommended.value)
                if recommended_id is not None:
                    self._ctx.repo.attach_recommendation(decision_id, recommended_id)

        return DecisionCycle(
            decision_id=decision_id,
            candidates=candidates,
            candidate_ids=candidate_ids,
            breaker_tripped=outcome.tripped,
            recommended_role=recommended,
        )

    # ------------------------------------------------------------------
    # internals — deliberately private
    # ------------------------------------------------------------------

    def _inputs(
        self, er_method: ExpectedReturnMethod, state: PortfolioState,
        overrides: Constraints | None = None,
        views: tuple[View, ...] = (),
    ) -> OptimizerInputs:
        returns = self._ctx.market_data.returns
        cov, _ = estimate_covariance(returns)
        mu = expected_returns(
            returns, er_method,
            lam=self._ctx.policy.ewma_lambda,
            trading_days=self._ctx.policy.trading_days_per_year,
        )
        if views:
            # The view shifts mu. It does NOT touch `constraints` below, which
            # is the whole point: a user who believes IT will outperform can
            # move the proposal, not the sector cap.
            asset_ids = tuple(returns.columns)
            posterior = black_litterman(
                cov,
                np.array([state.weights.get(a, 0.0) for a in asset_ids]),
                views, asset_ids,
            )
            if posterior.fell_back:
                logger.warning(
                    "Black-Litterman fell back to the equilibrium prior: %s",
                    posterior.note,
                )
            mu = posterior.expected_returns
            self._last_bl = posterior
        return OptimizerInputs(
            universe=self._ctx.universe,
            returns=returns,
            expected_returns=mu,
            covariance=cov,
            constraints=overrides or self._ctx.policy.constraints,
            current_weights=state.weights,
            risk_free_rate=self._ctx.policy.risk_free_rate,
            total_value_paise=state.total_value_paise,
            return_method=er_method,
            var_confidence=self._ctx.policy.var_confidence,
            min_observations=self._ctx.policy.model.min_return_observations,
        )

    def _optimize(
        self, strategy: Strategy, er_method: ExpectedReturnMethod,
        overrides: Constraints | None, state: PortfolioState,
        target_return: float | None = None,
        views: tuple[View, ...] = (),
    ) -> OptimizationResult:
        inputs = self._inputs(er_method, state, overrides, views=views)
        optimizer = self._optimizer_for(strategy, target_return)
        if optimizer is None:
            return failed_result(
                strategy, er_method, SolverStatus.SOLVER_ERROR,
                f"{strategy.value} is not available", 0,
            )
        return optimizer.solve(inputs)

    def _optimizer_for(self, strategy: Strategy, target_return: float | None):
        """The optimizer for a strategy, or None if it cannot be built.

        BLACK_LITTERMAN is not a separate optimizer: a view changes expected
        returns and the CONSTRAINED max-Sharpe problem is then solved as
        usual. That is the boundary the feature exists to respect — a view
        moves the proposal, it never bypasses a control.
        """
        if strategy in (Strategy.MAX_SHARPE, Strategy.BLACK_LITTERMAN):
            return MaxSharpeOptimizer()
        if strategy is Strategy.MIN_VOLATILITY:
            return MinVolatilityOptimizer()
        if strategy is Strategy.CVAR_MIN:
            return CVaROptimizer()
        if strategy is Strategy.HRP:
            return HRPOptimizer()
        if strategy is Strategy.TARGET_RETURN:
            # A return target is not optional for this strategy, and there is
            # no sensible default: picking one would silently optimize for a
            # goal nobody set.
            if target_return is None:
                return None
            return TargetReturnOptimizer(target_return=target_return)
        # Every Strategy member is handled above, so this is unreachable
        # today. It stays as the landing point for a member added later —
        # a new strategy should fail loudly as "not available" rather than
        # fall through to whichever branch happens to match first.
        return None  # type: ignore[unreachable]

    def _optimize_unconstrained(
        self, er_method: ExpectedReturnMethod, state: PortfolioState
    ) -> OptimizationResult:
        """The optimum with policy limits removed — the 'Optimal' column.

        Only the long-only and fully-invested constraints survive: without
        them the result is not an allocation at all. Every risk limit is
        dropped deliberately, because the comparison is the product.
        """
        inputs = self._inputs(er_method, state)
        unconstrained = Constraints(
            min_weights={a.asset_id: 0.0 for a in self._ctx.universe.assets},
            max_weights={a.asset_id: 1.0 for a in self._ctx.universe.assets},
            sector_max={}, asset_class_max={},
            min_liquid_share=0.0, min_cash_share=0.0, max_turnover=1.0,
            long_only=True, include_txn_cost=False,
        )
        return MaxSharpeOptimizer().solve(replace(inputs, constraints=unconstrained))

    def _judge(
        self, opt: OptimizationResult, state: PortfolioState, role: CandidateRole
    ) -> Candidate:
        """Stress, then validate independently. Never one without the other.

        Stress runs FIRST, which reads backwards against "optimize ->
        validate -> stress" but is what that sequence requires:
        ``STRESS_LOSS_MAX`` is a HARD control, and the control engine cannot
        evaluate it without the worst measured scenario loss. Validating
        first left that control unevaluated, which correctly produced
        NOT_VALIDATED — so every candidate, however healthy, was refused. The
        gate was stuck shut.

        The two steps are still one indivisible unit; only their internal
        order differs from the prose.
        """
        if not opt.succeeded or opt.weights is None:
            # A failed solve is still a candidate: the UI must show WHY there
            # is no proposal rather than an empty panel (INV-4).
            return Candidate(role=role, optimization=opt, control=None, stress=())

        stress = self._stress.run(
            opt.weights, total_value_paise=state.total_value_paise
        )
        stale_days, completeness = self._data_metrics()

        control = validate(
            opt.weights, self._ctx.universe, self._ctx.market_data,
            state.weights, self._ctx.policy,
            total_value_paise=state.total_value_paise,
            solver_ok=opt.succeeded,
            worst_stress_loss=self._stress.worst_loss(stress),
            data_staleness_days=stale_days,
            data_completeness=completeness,
            last_safe_allocation=self._ctx.repo.get_last_safe_allocation(
                self._ctx.portfolio_id
            ),
        )
        return Candidate(role=role, optimization=opt, control=control, stress=stress)

    def _data_metrics(self) -> tuple[float | None, float | None]:
        """Staleness and completeness of the panel behind this decision.

        Measured, not classified — the bands live in ``cce/controls/``
        (INV-11). ``None`` propagates as "not evaluated", which the control
        engine treats as NOT_VALIDATED rather than as a clean reading.
        """
        from cce.data.validation import panel_metrics

        return panel_metrics(
            self._ctx.market_data.prices, self._ctx.market_data.as_of_date
        )

    def _with_stress(self, candidate: Candidate, state: PortfolioState) -> Candidate:
        """Attach stress results to a candidate built elsewhere.

        Used for recovery candidates, which ``cce/controls/`` constructs and
        validates without being able to run the stress engine itself.
        """
        if candidate.optimization.weights is None:
            return candidate
        results = self._stress.run(
            candidate.optimization.weights,
            total_value_paise=state.total_value_paise,
        )
        return replace(candidate, stress=results)

    def _recommend(
        self, safe: Candidate, recovery: tuple[Candidate, ...]
    ) -> CandidateRole | None:
        """The candidate to put in front of the human, or None.

        ``None`` is a real answer: when nothing is approvable the system
        recommends nothing rather than promoting the least-bad option
        (Rule 2).
        """
        if safe.eligible_for_approval:
            return safe.role
        for cand in recovery:
            if cand.eligible_for_approval:
                return cand.role
        return None


    def _explain(
        self,
        safe: Candidate,
        unconstrained: Candidate,
        outcome,
        recovery: tuple[Candidate, ...],
        strategy: Strategy,
        trigger_detail: str | None,
    ) -> NarratedExplanation:
        """Build the structured Explanation and render it to prose.

        The Explanation is the SOURCE OF TRUTH for all narrative output
        (FR-141): nothing downstream may state a fact it does not contain.
        Every field here comes from a value an engine already computed — this
        assembles, it does not derive.

        The prose comes from :func:`cce.decisions.llm.narrate`, which uses
        the LLM when one is configured and the deterministic narrator
        otherwise. The narrator is the SHIPPING DEFAULT (FR-142): the prose is
        complete with no API key, and no failure in the narration layer can
        leave a decision unexplained.
        """
        recomputed = safe.control.recomputed if safe.control else None

        # The controls that actually moved, worst first — the "why", not
        # every finding.
        #
        # MODEL_* and DATA_* are excluded deliberately. They are validity and
        # integrity controls whose observed value is a flag, not a rate, so
        # rendering one as a movement produces "Covariance validity rose from
        # 0.0% to 100.0%" — true, meaningless, and the first line a reader
        # sees. Their failures still appear in `reasons`, which is where a
        # model problem belongs.
        contributors: list[RiskChange] = []
        if safe.control is not None:
            movable = [
                b for b in safe.control.findings
                if not b.control_code.startswith(("MODEL_", "DATA_"))
            ]
            for breach in sorted(
                movable, key=lambda b: b.observed - b.threshold, reverse=True
            )[:3]:
                contributors.append(RiskChange(
                    metric=breach.control_label,
                    from_value=breach.threshold,
                    to_value=breach.observed,
                    scope=breach.scope,
                ))

        if safe.eligible_for_approval:
            action = (
                "Proposal passed independent validation and stress testing. "
                "Awaiting human approval — nothing is adopted automatically."
            )
        elif outcome.tripped:
            action = (
                "Circuit breaker tripped. The Last Approved Safe Allocation is "
                "retained"
                + (f" and {len(recovery)} recovery allocation(s) were generated."
                   if recovery else " and no recovery allocation qualified.")
            )
        else:
            action = (
                "Proposal rejected by the independent control engine. The "
                "current allocation is unchanged."
            )

        improvement = None
        if (
            safe.eligible_for_approval
            and safe.optimization.sharpe is not None
            and recomputed is not None
            and recomputed.sharpe is not None
        ):
            improvement = (
                f"Sharpe {recomputed.sharpe:.2f} on the proposal, against "
                f"{unconstrained.optimization.sharpe:.2f} for the "
                "unconstrained optimum that was rejected."
                if unconstrained.optimization.sharpe is not None else None
            )

        expl = build_explanation(
            trigger=trigger_detail or "Decision cycle requested",
            risk_change=None,
            main_contributors=tuple(contributors),
            optimizer=strategy,
            candidate_summary=dict(safe.optimization.weights or {}),
            control_status=(
                safe.control.status if safe.control else ControlStatus.NOT_VALIDATED
            ),
            reasons=safe.rejection_reasons or (
                ("Every hard control and every stress scenario passed.",)
                if safe.eligible_for_approval else ()
            ),
            stress_summary=tuple(
                f"{s.scenario_label}: "
                + (
                    f"loss {s.portfolio_loss:.1%} against a "
                    f"{s.loss_threshold:.1%} limit"
                    if s.loss_is_measured
                    else f"no verdict ({s.error_reason})"
                )
                for s in safe.stress
            ),
            action=action,
            expected_improvement=improvement,
        )
        return narrate(expl)

    def _events(self, safe, outcome, recovery, trigger_detail):
        seq = 0

        def nxt(code, summary, **detail):
            nonlocal seq
            seq += 1
            return make_event(seq, code, summary, detail=detail or None)

        events = [nxt(EVENT_TRIGGER_RECEIVED,
                      trigger_detail or "Decision cycle requested")]

        recomputed = safe.control.recomputed if safe.control else None
        if recomputed is not None and recomputed.portfolio_volatility is not None:
            events.append(nxt(
                EVENT_RISK_COMPUTED,
                f"Volatility {recomputed.portfolio_volatility:.2%}"
                + (f", CVaR {recomputed.cvar_95:.2%}"
                   if recomputed.cvar_95 is not None else ""),
            ))

        if safe.optimization.weights is not None:
            events.append(nxt(
                EVENT_CANDIDATE_PROPOSED,
                f"{safe.optimization.strategy.value} proposed a constrained allocation",
            ))

        if safe.control is not None:
            if safe.control.passed:
                events.append(nxt(EVENT_CONTROL_VALIDATED,
                                  "Independent validation passed"))
            else:
                reasons = "; ".join(b.message for b in safe.control.hard_breaches)
                events.append(nxt(
                    EVENT_CONTROL_REJECTED,
                    reasons or "Independent validation did not pass",
                ))

        if safe.stress:
            events.append(nxt(
                EVENT_STRESS_COMPLETED,
                f"Stress suite: {safe.stress_status.value.lower()} "
                f"across {len(safe.stress)} scenario(s)",
            ))

        if outcome.tripped:
            events.append(nxt(
                EVENT_BREAKER_TRIPPED,
                f"Circuit breaker tripped on "
                f"{outcome.category.value if outcome.category else 'UNKNOWN'}",
            ))
            events.append(nxt(EVENT_SAFE_ALLOCATION_RETAINED,
                              "Last Approved Safe Allocation retained"))
        if recovery:
            events.append(nxt(
                EVENT_RECOVERY_GENERATED,
                f"{len(recovery)} recovery candidate(s) generated",
            ))
        return events

    def _state_id(self, state: PortfolioState) -> int:
        latest = self._ctx.repo.get_latest_portfolio_state(state.portfolio_id)
        if latest is None:
            raise LookupError(f"no persisted portfolio state for {state.portfolio_id}")
        return latest[0]

    def _risk_snapshot_id(self, safe: Candidate, state: PortfolioState) -> int:
        """Persist the control engine's own recomputed snapshot, and use it.

        The decision references the risk that was actually measured for it,
        not a snapshot from an earlier cycle.
        """
        if safe.control is None:
            latest = self._ctx.repo.get_latest_risk_snapshot_id()
            if latest is None:
                raise LookupError("no risk snapshot recorded")
            return latest
        return self._ctx.repo.record_risk_snapshot(
            safe.control.recomputed, self._state_id(state),
            self._ctx.snapshot_id, self._ctx.policy_version_id,
        )

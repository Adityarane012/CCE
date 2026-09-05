"""Service layer: orchestration, approval gating and simulated rebalance.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/13-EDGE-CASES.md section 7,
docs/IMPLEMENTATION-PLAN.md PHASE 9.

The four tests the plan names are here, plus the ones that matter for the
guarantees the UI inherits by having no other way in:

- there is NO public path that optimizes without validating
- approval is gated SERVER-SIDE, against CURRENT data
- a failure mid-approval leaves the portfolio untouched
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cce.audit import AuditRepository, get_connection, run_migrations
from cce.config import load_universe
from cce.contracts import (
    CandidateRole,
    ChangeDriver,
    ControlStatus,
    DataProvider,
    HumanAction,
    HumanActionRecord,
    MarketData,
    SolverStatus,
    Strategy,
    StressStatus,
)
from cce.data import load_market_data
from cce.exceptions import ApprovalNotPermitted, DecisionAlreadyClosed, PolicyError
from cce.services import (
    STALE_MESSAGE,
    ApprovalService,
    OptimizationService,
    PolicyService,
    PortfolioService,
    ReplayService,
    RiskService,
    ServiceContext,
    StressService,
)

AS_OF = date(2026, 8, 31)


# ---------------------------------------------------------------------------
# fixtures — market data is loaded once; each test gets a fresh database
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def loaded():
    universe = load_universe()
    market_data, report = load_market_data(universe, end=AS_OF)
    return universe, market_data, report


@pytest.fixture
def ctx(loaded, tmp_path: Path):
    universe, market_data, report = loaded
    db = tmp_path / "services.db"
    run_migrations(db)
    repo = AuditRepository(get_connection(db))
    context = ServiceContext(
        universe=universe, policy=repo.get_current_policy(),
        market_data=market_data, validation=report, repo=repo, snapshot_id=1,
    )
    yield context
    context.close()


@pytest.fixture
def state(ctx):
    return PortfolioService(ctx).get_current_state()


@pytest.fixture
def cycle(ctx, state):
    return OptimizationService(ctx).run_cycle(state)


def an_actor(action: HumanAction = HumanAction.APPROVE) -> HumanActionRecord:
    return HumanActionRecord(
        action=action, user_identity="demo_risk_manager",
        user_role="RISK_MANAGER", timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
    )


def an_override() -> HumanActionRecord:
    return HumanActionRecord(
        action=HumanAction.OVERRIDE, user_identity="demo_risk_manager",
        user_role="RISK_MANAGER", timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
        is_override=True, override_reason="Board-approved exception",
        overridden_controls=("CONC_SECTOR_MAX",), confirmation_token="CONFIRM-1",
    )


def _count_states(ctx) -> int:
    """Tests may reach the connection; production code may not."""
    return ctx.repo.conn.execute(
        "SELECT COUNT(*) AS c FROM portfolio_states"
    ).fetchone()["c"]


def turbulent(market_data: MarketData, factor: float = 9.0) -> MarketData:
    """The same panel with volatility scaled up.

    Used to make a previously-passing candidate fail against 'current' data
    without hand-writing a second panel that might differ in other ways.
    """
    returns = market_data.returns * factor
    prices = (1.0 + returns).cumprod() * 100.0
    return MarketData(
        prices=prices, returns=returns, as_of_date=market_data.as_of_date,
        provider=DataProvider.CACHED, universe_hash="", data_hash="",
    )


# ---------------------------------------------------------------------------
# propose: one indivisible unit
# ---------------------------------------------------------------------------

class TestProposeAlwaysValidates:

    def test_propose_always_validates(self, ctx, state):
        """The named Phase 9 test: no proposal escapes unjudged."""
        candidate = OptimizationService(ctx).propose(state)
        assert candidate.control is not None, "propose returned an unvalidated candidate"
        assert candidate.stress, "propose returned a candidate with no stress results"
        assert candidate.control.status in (
            ControlStatus.PASSED, ControlStatus.FAILED, ControlStatus.NOT_VALIDATED
        )

    def test_there_is_no_public_path_that_optimizes_without_validating(self, ctx):
        """The guarantee is structural, not a matter of discipline.

        Every public method returns a Candidate — which carries a verdict —
        or a DecisionCycle of them. Nothing public hands back a bare
        OptimizationResult, so the UI has no way to obtain one and skip the
        control engine.
        """
        service = OptimizationService(ctx)
        public = [
            n for n in dir(service)
            if not n.startswith("_") and callable(getattr(service, n))
        ]
        import inspect

        for name in public:
            ret = inspect.signature(getattr(service, name)).return_annotation
            assert "OptimizationResult" not in str(ret), (
                f"{name} exposes a raw OptimizationResult; the UI could then "
                "act on an unvalidated proposal (INV-2)"
            )

    def test_a_healthy_portfolio_reaches_an_approvable_candidate(self, ctx, state):
        """The gate must be able to open, or nothing could ever be approved.

        This is the test that caught the ordering defect: validating before
        running stress left STRESS_LOSS_MAX — a hard control — unevaluated,
        so every candidate came back NOT_VALIDATED however healthy it was.
        """
        candidate = OptimizationService(ctx).propose(state)
        assert candidate.control.status is not ControlStatus.NOT_VALIDATED, (
            "a hard control could not be evaluated on clean data; the gate is "
            "stuck shut"
        )

    def test_safe_and_optimal_stay_distinct(self, ctx, state):
        """INV-9: the rejected optimum is shown, never replaced by the safe one."""
        optimal, safe = OptimizationService(ctx).propose_safe_and_optimal(state)
        assert optimal.role is CandidateRole.OPTIMAL_UNCONSTRAINED
        assert safe.role is CandidateRole.SAFE_CONSTRAINED
        assert optimal.optimization.weights != safe.optimization.weights
        # the unconstrained optimum is returned even though it fails
        assert not optimal.eligible_for_approval

    def test_a_failed_solve_still_returns_a_candidate(self, ctx, state):
        """INV-4: the UI must show WHY there is no proposal, not an empty panel.

        TARGET_RETURN with no target is a genuine "cannot be built" case:
        there is no sensible default target, and inventing one would optimize
        for a goal nobody set.
        """
        service = OptimizationService(ctx)
        candidate = service.propose(state, strategy=Strategy.TARGET_RETURN)
        assert candidate.optimization.weights is None
        assert not candidate.eligible_for_approval
        assert candidate.optimization.solver_status is not SolverStatus.OPTIMAL

    @pytest.mark.parametrize("strategy", [
        Strategy.MAX_SHARPE, Strategy.MIN_VOLATILITY,
        Strategy.CVAR_MIN, Strategy.HRP,
    ])
    def test_every_strategy_is_reachable_and_validated(self, ctx, state, strategy):
        """PHASE 11: the alternatives are wired through, and still judged."""
        candidate = OptimizationService(ctx).propose(state, strategy=strategy)
        assert candidate.optimization.weights is not None, (
            f"{strategy.value} produced no allocation"
        )
        assert candidate.control is not None, (
            f"{strategy.value} escaped independent validation"
        )
        assert candidate.stress, f"{strategy.value} escaped stress testing"

    def test_a_black_litterman_view_moves_the_proposal(self, ctx, state):
        """A view changes expected returns. It never bypasses a control."""
        from cce.optimizer import View

        service = OptimizationService(ctx)
        base = service.propose(state, strategy=Strategy.MAX_SHARPE)
        with_view = service.propose(
            state, strategy=Strategy.BLACK_LITTERMAN,
            views=(View(asset="IT", versus="NIFTY50", outperformance=0.05,
                        confidence=0.8),),
        )
        assert with_view.optimization.weights is not None
        assert with_view.control is not None, "a view skipped validation"
        assert with_view.optimization.weights != base.optimization.weights, (
            "the view did not move the proposal at all"
        )


# ---------------------------------------------------------------------------
# run_cycle: the engines meet persistence
# ---------------------------------------------------------------------------

class TestDecisionCycle:

    def test_a_cycle_persists_every_part_of_the_decision(self, ctx, cycle):
        """INV-6: the record is complete, or it is not a record."""
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        assert stored.candidates, "no candidates persisted"
        assert stored.events, "no timeline persisted"
        assert stored.trigger_type
        assert stored.policy_version_id == 1
        roles = {c.role for c in stored.candidates}
        assert "SAFE_CONSTRAINED" in roles
        assert "OPTIMAL_UNCONSTRAINED" in roles

    def test_candidate_metrics_and_verdicts_are_both_recorded(self, ctx, cycle):
        """The optimizer's claim sits beside the control engine's finding."""
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        safe = next(c for c in stored.candidates if c.role == "SAFE_CONSTRAINED")
        assert safe.weights
        assert safe.control_status in ("PASSED", "FAILED", "NOT_VALIDATED")
        assert safe.stress, "stress results were not persisted against the candidate"

    def test_the_timeline_separates_machine_control_and_human(self, ctx, cycle):
        rows = ReplayService(ctx).get_timeline(cycle.decision_id)
        assert rows
        labels = {r.actor_label for r in rows}
        assert "System" in labels
        assert "Control engine" in labels
        assert [r.sequence_no for r in rows] == sorted(r.sequence_no for r in rows)

    def test_a_rejected_cycle_generates_recovery_candidates(self, ctx, state):
        """EC-5.1: alternatives appear when the proposal cannot be approved."""
        rough = ctx.with_market_data(turbulent(ctx.market_data), ctx.validation)
        result = OptimizationService(rough).run_cycle(state)
        safe = result.candidate(CandidateRole.SAFE_CONSTRAINED)
        if safe is not None and safe.eligible_for_approval:
            pytest.skip("shocked panel still passes; nothing to recover from")
        assert any(c.role.is_recovery for c in result.candidates)
        # and a recovery that fails is still returned, never dropped
        assert result.recommended_role is None or result.recommended_role.is_recovery


# ---------------------------------------------------------------------------
# approval — the enforcement
# ---------------------------------------------------------------------------

class TestApproval:

    def test_approval_of_a_failed_candidate_raises(self, ctx, state, cycle):
        """INV-2, the named Phase 9 test. Server-side, not the button."""
        optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
        assert not optimal.eligible_for_approval
        with pytest.raises(ApprovalNotPermitted, match="not eligible"):
            ApprovalService(ctx).approve(
                cycle.decision_id, optimal, an_actor(), state
            )

    def test_the_refusal_names_the_specific_control(self, ctx, state, cycle):
        """FR-174: never a generic "constraints violated"."""
        optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
        with pytest.raises(ApprovalNotPermitted) as exc:
            ApprovalService(ctx).approve(cycle.decision_id, optimal, an_actor(), state)
        assert "%" in str(exc.value) or "exceeds" in str(exc.value)

    def test_stale_candidate_approval_is_refused(self, ctx, state, cycle):
        """EC-7.1: re-judged against CURRENT data, not the verdict it carries.

        The candidate passed when it was proposed. The panel then moves. The
        stored verdict still says PASSED, and approving on it would approve a
        conclusion nobody drew about today's market.
        """
        safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)
        if not safe.eligible_for_approval:
            pytest.skip("candidate was not approvable to begin with")

        moved = ctx.with_market_data(turbulent(ctx.market_data), ctx.validation)
        with pytest.raises(ApprovalNotPermitted) as exc:
            ApprovalService(moved).approve(
                cycle.decision_id, safe, an_actor(), state
            )
        assert STALE_MESSAGE.split(".")[0] in str(exc.value)

    def test_override_without_reason_raises(self):
        """EC-7.4: enforced by the contract, before any service sees it."""
        with pytest.raises(ValueError, match="override requires a reason"):
            HumanActionRecord(
                action=HumanAction.OVERRIDE, user_identity="u",
                user_role="RISK_MANAGER", timestamp=datetime.now(UTC),
                is_override=True,
            )

    def test_override_adopts_a_rejected_candidate_and_records_why(
        self, ctx, state, cycle
    ):
        """FR-118: permitted, and permanently attributed."""
        optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
        ApprovalService(ctx).override(
            cycle.decision_id, optimal, an_override(), state
        )
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        assert stored.human_action is not None
        assert stored.human_action.is_override
        assert stored.human_action.override_reason
        assert stored.human_action.overridden_controls
        safe_alloc = PortfolioService(ctx).get_last_safe_allocation()
        assert safe_alloc.via_override is True

    def test_override_requires_an_override_record(self, ctx, state, cycle):
        """A plain APPROVE cannot be smuggled through the override path."""
        optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
        with pytest.raises(ApprovalNotPermitted, match="requires a HumanActionRecord"):
            ApprovalService(ctx).override(
                cycle.decision_id, optimal, an_actor(), state
            )

    def test_approval_rebalances_and_promotes(self, ctx, state, cycle):
        safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)
        if not safe.eligible_for_approval:
            pytest.skip("nothing approvable in this cycle")

        before = PortfolioService(ctx).get_last_safe_allocation()
        new_state = ApprovalService(ctx).approve(
            cycle.decision_id, safe, an_actor(), state
        )
        after = PortfolioService(ctx).get_last_safe_allocation()

        assert new_state.weights == pytest.approx(safe.optimization.weights)
        assert after.weights != before.weights
        assert after.decision_id == cycle.decision_id
        assert after.approved_by == "demo_risk_manager"
        # a rebalance is never free (FR-120)
        assert new_state.total_value_paise <= state.total_value_paise

    def test_double_approval_raises(self, ctx, state, cycle):
        """EC-7.2."""
        safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)
        if not safe.eligible_for_approval:
            pytest.skip("nothing approvable in this cycle")
        app = ApprovalService(ctx)
        app.approve(cycle.decision_id, safe, an_actor(), state)
        with pytest.raises(DecisionAlreadyClosed):
            app.approve(cycle.decision_id, safe, an_actor(), state)

    def test_reject_closes_without_changing_the_portfolio(self, ctx, cycle):
        before = PortfolioService(ctx).get_last_safe_allocation()
        ApprovalService(ctx).reject(cycle.decision_id, an_actor(HumanAction.REJECT))

        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        assert stored.human_action.action == "REJECT"
        assert stored.portfolio_state_after is None, (
            "a rejection must not point at a portfolio state; nothing was adopted"
        )
        assert PortfolioService(ctx).get_last_safe_allocation() == before

    def test_keep_current_preserves_the_last_approved_allocation(self, ctx, cycle):
        """INV-4."""
        before = PortfolioService(ctx).get_last_safe_allocation()
        ApprovalService(ctx).keep_current(
            cycle.decision_id, an_actor(HumanAction.KEEP_CURRENT)
        )
        assert PortfolioService(ctx).get_last_safe_allocation() == before

    def test_a_failed_write_leaves_the_portfolio_unchanged(
        self, ctx, state, cycle, monkeypatch
    ):
        """EC-7.3: the state change and its record commit together, or neither.

        The promotion is made to fail AFTER the new portfolio state has been
        written. Without one transaction around both, the book would be
        rebalanced with no record that anyone approved it — a state change
        that lost its audit trail, which is worse than no change at all.
        """
        safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)
        if not safe.eligible_for_approval:
            pytest.skip("nothing approvable in this cycle")

        before_safe = PortfolioService(ctx).get_last_safe_allocation()
        before_states = _count_states(ctx)

        def boom(*args, **kwargs):
            raise RuntimeError("disk full")

        monkeypatch.setattr(ctx.repo, "promote_safe_allocation", boom)

        with pytest.raises(RuntimeError, match="disk full"):
            ApprovalService(ctx).approve(cycle.decision_id, safe, an_actor(), state)

        assert PortfolioService(ctx).get_last_safe_allocation() == before_safe
        after_states = _count_states(ctx)
        assert after_states == before_states, "a portfolio state survived a failed approval"
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        assert stored.human_action is None, "the decision was closed by a failed approval"


# ---------------------------------------------------------------------------
# the remaining services
# ---------------------------------------------------------------------------

class TestPortfolioAndRisk:

    def test_current_state_is_priced_on_current_data(self, ctx, state):
        assert state.total_value_paise > 0
        assert sum(state.weights.values()) == pytest.approx(1.0)

    def test_risk_snapshot_is_unclassified(self, ctx, state):
        """INV-11: the risk engine measures; only cce/controls classifies."""
        snapshot = RiskService(ctx).get_snapshot(state)
        assert snapshot.breaches == ()
        assert snapshot.portfolio_volatility is not None

    def test_what_changed_omits_metrics_that_were_not_computed(self, ctx, state):
        """INV-5: 'not computed' is never reported as a move to zero."""
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        previous = replace(current, ewma_volatility=None, cvar_95=0.02)
        changes = service.what_changed(previous, current)
        metrics = {c.metric for c in changes}
        assert "EWMA volatility" not in metrics
        assert "95% CVaR" in metrics

    def test_what_changed_reports_direction(self, ctx, state):
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        # both tail metrics move together: CVaR < VaR is unconstructible,
        # and rightly so — the contract refuses a broken tail slice.
        previous = replace(
            current,
            var_95=(current.var_95 or 0.01) / 2,
            cvar_95=(current.cvar_95 or 0.02) / 2,
        )
        change = next(c for c in service.what_changed(previous, current)
                      if c.metric == "95% CVaR")
        assert change.delta > 0


class TestStressService:

    def test_running_all_configured_scenarios(self, ctx, state):
        results = StressService(ctx).run(
            state.weights, total_value_paise=state.total_value_paise
        )
        assert len(results) == len(StressService(ctx).list_scenarios())
        assert all(r.scenario_code for r in results)

    def test_an_unknown_scenario_code_errors_rather_than_shortening_the_suite(
        self, ctx, state
    ):
        """INV-10: a shorter suite that passes looks like a longer one that passes."""
        results = StressService(ctx).run(state.weights, ("NOT_A_SCENARIO",))
        assert len(results) == 1
        assert results[0].status is StressStatus.ERROR
        assert "NOT_A_SCENARIO" in results[0].error_reason

    def test_worst_loss_is_none_when_nothing_was_measured(self, ctx, state):
        service = StressService(ctx)
        results = service.run(state.weights, ("NOT_A_SCENARIO",))
        assert service.worst_loss(results) is None, (
            "an unrun suite must not report a zero worst loss"
        )

    def test_a_custom_scenario_with_an_unknown_key_errors(self, ctx, state):
        result = StressService(ctx).run_custom(state.weights, {"NOT_A_SECTOR": -0.3})
        assert result.status is StressStatus.ERROR
        assert "NOT_A_SECTOR" in result.error_reason


class TestPolicyService:

    def test_preview_reports_a_weakening_before_it_is_applied(self, ctx):
        """FR-084."""
        preview = PolicyService(ctx).preview_change(
            {"RISK_VOL_ANNUAL": {"amber_max": 0.30}}
        )
        assert preview.is_weakening
        assert "RISK_VOL_ANNUAL" in preview.weakened_controls

    def test_a_weakening_change_without_acknowledgement_is_refused(self, ctx):
        """INV-8: enforced here, not only in the UI."""
        with pytest.raises(PolicyError, match="loosens a hard limit"):
            PolicyService(ctx).apply_change(
                {"RISK_VOL_ANNUAL": {"amber_max": 0.30}}, an_actor()
            )

    def test_a_weakening_change_with_acknowledgement_creates_a_version(self, ctx):
        service = PolicyService(ctx)
        before = ctx.policy_version_id
        service.apply_change({"RISK_VOL_ANNUAL": {"amber_max": 0.30}}, an_override())
        assert ctx.policy_version_id > before
        row = ctx.repo.conn.execute(
            "SELECT is_weakening, weakening_reason FROM policy_versions "
            "ORDER BY policy_version_id DESC LIMIT 1"
        ).fetchone()
        assert row["is_weakening"] == 1
        assert row["weakening_reason"]

    def test_a_tightening_change_needs_no_acknowledgement(self, ctx):
        service = PolicyService(ctx)
        # both bands move together: green_max must stay <= amber_max
        service.apply_change(
            {"RISK_VOL_ANNUAL": {"green_max": 0.08, "amber_max": 0.10}}, an_actor()
        )
        assert service.get_current().threshold("RISK_VOL_ANNUAL").amber_max == 0.10

    def test_an_unknown_control_is_refused(self, ctx):
        with pytest.raises(PolicyError, match="no such control"):
            PolicyService(ctx).preview_change({"NOT_A_CONTROL": {"amber_max": 0.1}})

    def test_an_incoherent_band_is_refused_as_a_policy_error(self, ctx):
        """green_max above amber_max would invert the control silently."""
        with pytest.raises(PolicyError, match="RISK_VOL_ANNUAL"):
            PolicyService(ctx).preview_change({"RISK_VOL_ANNUAL": {"amber_max": 0.01}})

    def test_an_earlier_version_is_still_readable(self, ctx):
        """INV-8: a verdict is only interpretable against the policy applied."""
        original = PolicyService(ctx).get_current()
        PolicyService(ctx).apply_change(
            {"RISK_VOL_ANNUAL": {"green_max": 0.08, "amber_max": 0.10}}, an_actor()
        )
        assert PolicyService(ctx).get_version(1) == original


class TestReplayService:

    def test_decisions_are_listed_newest_first(self, ctx, state, cycle):
        OptimizationService(ctx).run_cycle(state)
        rows = ReplayService(ctx).list_decisions()
        assert len(rows) >= 2
        assert rows[0].created_at >= rows[-1].created_at

    def test_an_unrecorded_decision_has_an_empty_timeline(self, ctx):
        """INV-6: empty means nothing was recorded, not that nothing happened."""
        assert ReplayService(ctx).get_timeline(1) == ()


class TestDecisionExplanation:
    """FR-140..FR-142: every decision carries a structured explanation and
    complete prose, with no LLM present."""

    def test_a_cycle_records_an_explanation(self, ctx, cycle):
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        assert stored.structured_explanation is not None, (
            "the decision has no structured explanation (FR-140)"
        )
        assert stored.template_text, (
            "the decision has no deterministic prose (FR-142)"
        )
        assert stored.llm_text is None, "no LLM is configured in tests"

    def test_the_explanation_carries_all_nine_fields(self, ctx, cycle):
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        expl = stored.structured_explanation
        for field in (
            "trigger", "risk_change", "main_contributors", "optimizer",
            "candidate_summary", "control_result", "reasons",
            "stress_summary", "action",
        ):
            assert field in expl, f"Explanation is missing {field} (FR-140)"

    def test_the_prose_states_the_verdict_and_the_action(self, ctx, cycle):
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        text = stored.template_text
        assert "**Control verdict.**" in text
        assert "**Action.**" in text
        assert "Model Estimate" in text, (
            "expected returns must be labelled wherever they appear (FR-062)"
        )

    def test_validity_controls_are_not_rendered_as_movements(self, ctx, cycle):
        """A flag is not a rate.

        MODEL_COVARIANCE observed=0/threshold=1 rendered as "Covariance
        validity rose from 0.0% to 100.0%" — true, meaningless, and the first
        line a reader saw. Model and data findings belong in `reasons`.
        """
        stored = ReplayService(ctx).get_decision(cycle.decision_id)
        for rc in stored.structured_explanation["main_contributors"]:
            assert "validity" not in rc["metric"].lower(), (
                f"a validity control leaked into main_contributors: {rc}"
            )


class TestTheDemoPortfolioIsWhatEveryDocumentClaims:
    """The headline number is ₹100 Cr in every document and on the dashboard.

    The seed once said 1e12 paise — ₹1,000 Cr, ten times over. Nothing caught
    it: no test asserted the demo's own size, and ₹1,000 Cr is a perfectly
    plausible figure for an institutional book. It was found by printing the
    value in a pre-demo drill.
    """

    def test_the_portfolio_is_one_hundred_crore(self, ctx):
        from cce.portfolio import DEFAULT_CAPITAL_PAISE

        state = PortfolioService(ctx).get_current_state()
        assert state.total_value_paise == DEFAULT_CAPITAL_PAISE
        assert state.total_value_crore == pytest.approx(100.0)

    def test_positions_reconcile_to_the_capital_exactly(self, ctx):
        """To the paise. Largest-remainder, not per-position rounding."""
        state = PortfolioService(ctx).get_current_state()
        assert sum(p.value_paise for p in state.positions) == state.total_value_paise

    def test_the_seed_weights_sum_to_one(self, ctx):
        state = PortfolioService(ctx).get_current_state()
        assert sum(state.weights.values()) == pytest.approx(1.0)


class TestWhatChanged:
    """docs/09-UI-SPEC.md section 10: separate allocation drift from a
    volatility regime change.

    They call for opposite responses — rebalance, or reassess — and a panel
    reporting only "volatility is up" leaves the reader to guess which.
    """

    def test_what_changed_isolates_allocation_from_regime(self, ctx, state):
        """The demo case: weights untouched, risk contribution moves.

        Banking allocation unchanged at 24% while its risk contribution goes
        27% -> 41%. The driver must be named as REGIME, not allocation.
        """
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        previous = replace(
            current,
            ewma_volatility=(current.ewma_volatility or 0.10) / 2,
            sector_risk_contribution={
                k: v / 2 for k, v in current.sector_risk_contribution.items()
            },
        )
        attribution = service.attribute(
            previous, current, state.weights, state.weights  # identical weights
        )
        assert attribution.driver is ChangeDriver.REGIME
        assert not attribution.allocation_moved
        assert attribution.max_weight_shift == 0.0

    def test_a_traded_book_is_attributed_to_allocation(self, ctx, state):
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        previous = replace(
            current, ewma_volatility=(current.ewma_volatility or 0.10) / 2
        )
        moved = dict(state.weights)
        first, second = sorted(moved)[:2]
        moved[first] = moved[first] + 0.10
        moved[second] = moved[second] - 0.10

        attribution = service.attribute(previous, current, state.weights, moved)
        assert attribution.driver in (ChangeDriver.ALLOCATION, ChangeDriver.BOTH)
        assert attribution.allocation_moved
        assert attribution.max_weight_shift == pytest.approx(0.10)

    def test_rounding_drift_is_not_reported_as_a_rebalance(self, ctx, state):
        """The materiality floor. A 0.3% drift is not a trade."""
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        previous = replace(
            current, ewma_volatility=(current.ewma_volatility or 0.10) / 2
        )
        drifted = dict(state.weights)
        first = sorted(drifted)[0]
        drifted[first] = drifted[first] + 0.003

        attribution = service.attribute(previous, current, state.weights, drifted)
        assert not attribution.allocation_moved
        assert attribution.driver is ChangeDriver.REGIME

    def test_no_change_is_reported_as_none(self, ctx, state):
        service = RiskService(ctx)
        current = service.get_snapshot(state)
        attribution = service.attribute(
            current, current, state.weights, state.weights
        )
        assert attribution.driver is ChangeDriver.NONE

    def test_the_interpretation_comes_from_the_narrator(self, ctx, state):
        """Not assembled in the UI, and not written by an LLM."""
        from cce.decisions import render_change_interpretation

        service = RiskService(ctx)
        current = service.get_snapshot(state)
        previous = replace(
            current, ewma_volatility=(current.ewma_volatility or 0.10) / 2
        )
        attribution = service.attribute(
            previous, current, state.weights, state.weights
        )
        text = render_change_interpretation(attribution)
        assert "did not materially change" in text
        assert text == render_change_interpretation(attribution)  # deterministic


class TestRecoveryCandidatesAreApprovable:
    """A recovery set nobody may approve is not a recovery set.

    The circuit breaker exists so a human can choose a safer allocation. If
    every recovery candidate comes back NOT_VALIDATED, the breaker trips and
    the demo — and the product — dead-ends at the one moment it is supposed
    to help.

    This is the SAME defect that was fixed on the main propose path: STRESS
    _LOSS_MAX is a hard control, and validating without the worst measured
    scenario loss leaves it unevaluated, which correctly yields NOT_VALIDATED.
    The recovery path attached stress results only AFTER validation had
    already run blind, so the gate was stuck shut there too.
    """

    def test_a_healthy_recovery_candidate_can_be_approved(self, ctx, state):
        from cce.services import OptimizationService

        svc = OptimizationService(ctx)
        recovery = svc.generate_recovery_candidates(state)

        assert recovery, "no recovery candidates were generated at all"
        assert any(c.eligible_for_approval for c in recovery), (
            "every recovery candidate is unapprovable — the circuit breaker "
            "would leave a risk manager with no action to take:\n"
            + "\n".join(
                f"  {c.role.value}: {c.control.status.value if c.control else '?'}"
                for c in recovery
            )
        )

    def test_every_recovery_candidate_was_stress_tested(self, ctx, state):
        """Validation must SEE the stress result, not merely be handed one later.

        Asserted on the control findings rather than on ``candidate.stress``:
        attaching stress results for display while validating blind is
        exactly the bug, and it leaves ``stress`` populated.
        """
        from cce.services import OptimizationService

        svc = OptimizationService(ctx)
        for candidate in svc.generate_recovery_candidates(state):
            if candidate.control is None:
                continue
            assert candidate.stress, f"{candidate.role.value} has no stress results"
            evaluated = {b.control_code for b in candidate.control.findings}
            assert candidate.control.status.value != "NOT_VALIDATED", (
                f"{candidate.role.value} was not fully validated; "
                f"findings evaluated: {sorted(evaluated)}"
            )

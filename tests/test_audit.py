"""Audit persistence, explanation and narration.

Spec: docs/05-BACKEND-SCHEMA.md, docs/11-TESTING-STRATEGY.md section 8.

Several tests here exist because the first implementation of this layer was
written against an imagined contract rather than the real one and still passed
a green suite: it read ``Candidate.weights`` (which lives on
``Candidate.optimization``) and ``RiskChange.value_from`` (really
``from_value``). Both crash on first call. The rule those defects imply is
that every repository method must be EXERCISED with a real contract object,
not merely defined — so each writer below is actually invoked.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from cce.audit.database import get_connection, run_migrations, transaction
from cce.audit.events import (
    EVENT_BREAKER_TRIPPED,
    EVENT_CONTROL_REJECTED,
    EVENT_HUMAN_ACTION,
    EVENT_RISK_COMPUTED,
    EVENT_SHOCK_DETECTED,
    EVENT_TRIGGER_RECEIVED,
    make_event,
)
from cce.audit.repository import (
    AuditRepository,
    AuditWriteError,
    DecisionContext,
    MarketSnapshotMeta,
    PolicyChangeMeta,
)
from cce.audit.serialization import policy_from_json, policy_to_json
from cce.contracts import (
    Actor,
    Alert,
    Breach,
    BreakerCategory,
    Candidate,
    CandidateRole,
    Comparator,
    ControlResult,
    ControlStatus,
    ExpectedReturnMethod,
    HumanAction,
    HumanActionRecord,
    OptimizationResult,
    PortfolioOrigin,
    RiskChange,
    RiskSnapshot,
    RiskState,
    SolverStatus,
    Strategy,
    StressResult,
    StressStatus,
    VaRMethod,
)
from cce.decisions.explanation import build_explanation
from cce.decisions.narrator import build_narrated_explanation, render_narrative
from cce.decisions.replay import reconstruct_timeline

WEIGHTS = {"NIFTY50": 0.30, "GSEC": 0.40, "GOLD": 0.20, "CASH": 0.10}


# ---------------------------------------------------------------------------
# fixtures and builders
# ---------------------------------------------------------------------------

@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "cce_test.db"


@pytest.fixture
def conn(db_path: Path):
    run_migrations(db_path)
    connection = get_connection(db_path)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn) -> AuditRepository:
    return AuditRepository(conn)


def a_risk_snapshot(**overrides) -> RiskSnapshot:
    """A populated RiskSnapshot. Every optional field deliberately set."""
    defaults = {
        "timestamp": datetime(2026, 8, 31, 9, 30, tzinfo=UTC),
        "as_of_date": date(2026, 8, 31),
        "historical_volatility": 0.0971,
        "ewma_volatility": 0.1043,
        "portfolio_volatility": 0.0971,
        "expected_return": 0.1120,
        "expected_return_method": ExpectedReturnMethod.HISTORICAL,
        "sharpe": 0.48,
        "var_95": 0.0093,
        "cvar_95": 0.0138,
        "var_method": VaRMethod.HISTORICAL,
        "current_drawdown": 0.021,
        "max_drawdown": 0.084,
        "liquidity_ratio": 0.62,
        "turnover_from_current": 0.11,
        "risk_contribution": {"NIFTY50": 0.55, "GSEC": 0.15, "GOLD": 0.28, "CASH": 0.02},
        "sector_exposure": {"BROAD_EQUITY": 0.30, "GSEC": 0.40, "GOLD": 0.20, "CASH": 0.10},
        "sector_risk_contribution": {"BROAD_EQUITY": 0.55, "GOLD": 0.28},
        "concentration": {"max_asset": 0.40, "max_sector": 0.40},
        "risk_state": RiskState.GREEN,
        "breaches": (),
        "degraded": False,
        "degraded_reason": None,
    }
    defaults.update(overrides)
    return RiskSnapshot(**defaults)  # type: ignore[arg-type]


def a_breach() -> Breach:
    return Breach(
        control_code="CONC_SECTOR_MAX",
        control_label="Sector concentration",
        severity=RiskState.RED,
        is_hard=True,
        observed=0.43,
        threshold=0.35,
        comparator=Comparator.GT,
        scope="BANKING",
        message="BANKING at 43.0% exceeds the sector limit of 35.0%",
    )


def an_optimization(**overrides) -> OptimizationResult:
    defaults = {
        "strategy": Strategy.MAX_SHARPE,
        "expected_return_method": ExpectedReturnMethod.HISTORICAL,
        "solver_status": SolverStatus.OPTIMAL,
        "weights": dict(WEIGHTS),
        "expected_return": 0.1120,
        "volatility": 0.0971,
        "sharpe": 0.48,
        "var_95": 0.0093,
        "cvar_95": 0.0138,
        "turnover": 0.11,
        "transaction_cost_paise": 1_250_000,
    }
    defaults.update(overrides)
    return OptimizationResult(**defaults)  # type: ignore[arg-type]


def a_control_result(passed: bool = True, **overrides) -> ControlResult:
    breaches = () if passed else (a_breach(),)
    defaults = {
        "status": ControlStatus.PASSED if passed else ControlStatus.FAILED,
        "passed": passed,
        "findings": breaches,
        "hard_breaches": breaches,
        "warnings": (),
        "circuit_breaker_active": not passed,
        "breaker_category": None,
        "recomputed": a_risk_snapshot(),
        "evaluated_at": datetime(2026, 8, 31, 9, 35, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ControlResult(**defaults)  # type: ignore[arg-type]


def a_stress_result(passed: bool = True) -> StressResult:
    return StressResult(
        scenario_code="BANKING_CRISIS",
        scenario_label="Banking crisis",
        is_custom=False,
        shocks={"BANKING": -0.30},
        portfolio_loss=0.072 if passed else 0.221,
        loss_paise=720_000_000 if passed else 2_210_000_000,
        contribution={"NIFTY50": 0.05, "GOLD": 0.02},
        post_shock_volatility=0.1450,
        post_shock_cvar=0.0210,
        breaches=() if passed else (a_breach(),),
        loss_threshold=0.18,
        status=StressStatus.PASSED if passed else StressStatus.FAILED,
    )


def a_candidate(passed: bool = True, role: CandidateRole = CandidateRole.SAFE_CONSTRAINED):
    return Candidate(
        role=role,
        optimization=an_optimization(),
        control=a_control_result(passed=passed),
        stress=(a_stress_result(passed=passed),),
    )


def a_decision(repo: AuditRepository, uid: str = "uid-1") -> int:
    """Open a decision against the seeded snapshot/policy/state rows."""
    return repo.open_decision(
        DecisionContext(
            event_uid=uid,
            created_at=datetime(2026, 8, 31, 9, 40, tzinfo=UTC),
            trigger_type="RISK_DETERIORATION",
            trigger_detail="EWMA volatility crossed the amber band",
            snapshot_id=1,
            policy_version_id=1,
            portfolio_state_before=1,
            risk_snapshot_before=1,
            control_status=ControlStatus.FAILED.value,
            circuit_breaker_active=True,
            breaker_trigger_category="RISK",
            optimizer_strategy=Strategy.MAX_SHARPE.value,
            expected_return_method=ExpectedReturnMethod.HISTORICAL.value,
            solver_status=SolverStatus.OPTIMAL.value,
        )
    )


# ---------------------------------------------------------------------------
# migrations
# ---------------------------------------------------------------------------

def test_database_recreatable_from_migrations(conn, db_path: Path):
    """NFR-015: the database is completely recreatable from scripts."""
    applied = conn.execute("SELECT version FROM schema_migrations ORDER BY version")
    versions = [r["version"] for r in applied.fetchall()]
    assert versions == sorted(versions)
    assert versions, "no migrations recorded"

    # every table in docs/05 section 3 exists
    names = {
        r["name"]
        for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "policy_versions", "market_snapshots", "portfolio_states", "risk_snapshots",
        "decision_records", "candidate_allocations", "control_findings",
        "stress_results", "explanations", "human_actions", "safe_allocations",
        "decision_events", "alerts", "backtest_runs", "backtest_results",
    } <= names

    # the seeds landed
    assert conn.execute(
        "SELECT portfolio_id FROM safe_allocations"
    ).fetchone()["portfolio_id"] == "DEMO_100CR"


def test_migrations_are_idempotent(db_path: Path):
    """Re-running applies nothing and does not raise."""
    first = run_migrations(db_path)
    second = run_migrations(db_path)
    assert first, "first run should apply migrations"
    assert second == [], "second run must apply nothing"


def test_failed_migration_leaves_no_partial_schema(tmp_path: Path, monkeypatch):
    """A migration that fails half way is rolled back whole.

    Without an explicit transaction around the DDL this is exactly what goes
    wrong: sqlite3 autocommits CREATE TABLE, so the tables from the first half
    of a failing script survive while no schema_migrations row is written, and
    the next run tries to create them again.
    """
    from cce.audit import database

    bad = tmp_path / "migrations"
    bad.mkdir()
    (bad / "001_broken.sql").write_text(
        "CREATE TABLE good_table (id INTEGER PRIMARY KEY);\n"
        "CREATE TABLE bad_table (id INTEGER PRIMARY KEY, x REFERENCES nope(id));\n"
        "INSERT INTO bad_table (id, x) VALUES (1, 999);\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(database, "MIGRATIONS_DIR", bad)

    db = tmp_path / "broken.db"
    with pytest.raises(sqlite3.Error):
        database.run_migrations(db)

    with database.get_connection(db) as check:
        tables = {
            r["name"]
            for r in check.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "good_table" not in tables, "partial schema survived a failed migration"


def test_transaction_rolls_back_on_error(conn):
    """The transaction helper undoes everything in the block."""
    before = conn.execute("SELECT COUNT(*) AS c FROM alerts").fetchone()["c"]
    def insert_then_fail() -> None:
        with transaction(conn):
            conn.execute(
                "INSERT INTO alerts (created_at, severity, category, title, message) "
                "VALUES ('2026-08-31', 'INFO', 'DATA', 't', 'm')"
            )
            raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        insert_then_fail()
    after = conn.execute("SELECT COUNT(*) AS c FROM alerts").fetchone()["c"]
    assert after == before


# ---------------------------------------------------------------------------
# policy serialisation (INV-8)
# ---------------------------------------------------------------------------

def test_policy_survives_a_round_trip(policy):
    """INV-8: a persisted policy version must reproduce the policy exactly.

    Storing a placeholder here is worse than storing nothing: the row looks
    like an audit record and cannot answer the only question asked of it —
    which thresholds were in force.
    """
    assert policy_from_json(policy_to_json(policy)) == policy


def test_seeded_policy_reads_back_as_the_configured_policy(conn, policy):
    """The seed row and config/policy.yaml describe the same policy."""
    raw = conn.execute(
        "SELECT policy_json FROM policy_versions WHERE policy_version_id = 1"
    ).fetchone()["policy_json"]
    assert policy_from_json(raw) == policy


def test_record_policy_version_persists_the_whole_policy(repo, conn, policy):
    version_id = repo.record_policy_version(
        policy,
        PolicyChangeMeta(
            created_by="demo_risk_manager",
            created_by_role="RISK_MANAGER",
            source="UI_EDIT",
            parent_version_id=1,
            change_summary="raised the volatility band",
        ),
    )
    raw = conn.execute(
        "SELECT policy_json, created_at FROM policy_versions WHERE policy_version_id = ?",
        (version_id,),
    ).fetchone()
    assert policy_from_json(raw["policy_json"]) == policy
    assert raw["created_at"] != "2026-08-31T00:00:00Z", "timestamp must not be hardcoded"


def test_weakening_policy_change_requires_acknowledgement(policy):
    """INV-8: loosening a hard limit cannot be anonymous."""
    with pytest.raises(ValueError, match="weakening"):
        PolicyChangeMeta(
            created_by="u", created_by_role="RISK_MANAGER", source="UI_EDIT",
            is_weakening=True,
        )


# ---------------------------------------------------------------------------
# writers — each must actually run against a real contract object
# ---------------------------------------------------------------------------

def test_record_market_snapshot(repo, conn):
    snapshot_id = repo.record_market_snapshot(
        MarketSnapshotMeta(
            captured_at=datetime(2026, 8, 31, 18, 0, tzinfo=UTC),
            as_of_date="2026-08-31",
            provider="CACHED",
            universe_hash="uni-hash",
            data_hash="data-hash",
            row_count=676,
            asset_count=9,
            validation_status="VALID",
            validation_json="{}",
        )
    )
    row = conn.execute(
        "SELECT provider, row_count FROM market_snapshots WHERE snapshot_id = ?",
        (snapshot_id,),
    ).fetchone()
    assert row["provider"] == "CACHED"
    assert row["row_count"] == 676


def test_record_portfolio_state(repo, conn, demo_portfolio):
    state_id = repo.record_portfolio_state(demo_portfolio, PortfolioOrigin.SEED, 1)
    row = conn.execute(
        "SELECT snapshot_id, origin, total_value_paise FROM portfolio_states "
        "WHERE portfolio_state_id = ?",
        (state_id,),
    ).fetchone()
    assert row["origin"] == "SEED"
    assert row["snapshot_id"] == 1
    assert row["total_value_paise"] == demo_portfolio.total_value_paise


def test_record_risk_snapshot_persists_every_metric(repo, conn):
    """Covers the sector_risk_contribution field name specifically."""
    snap = a_risk_snapshot()
    rid = repo.record_risk_snapshot(snap, 1, 1, 1)
    row = conn.execute(
        "SELECT * FROM risk_snapshots WHERE risk_snapshot_id = ?", (rid,)
    ).fetchone()
    assert row["ewma_volatility"] == pytest.approx(0.1043)
    assert row["cvar_95"] == pytest.approx(0.0138)
    assert row["var_method"] == "HISTORICAL"
    assert "BROAD_EQUITY" in row["sector_risk_contrib_json"]


def test_uncomputed_metrics_are_stored_as_null_not_zero(repo, conn):
    """INV-5: missing data is not zero risk."""
    snap = a_risk_snapshot(
        ewma_volatility=None, cvar_95=None, var_95=None, liquidity_ratio=None,
        degraded=True, degraded_reason="fewer than 250 observations",
    )
    rid = repo.record_risk_snapshot(snap, 1, 1, 1)
    row = conn.execute(
        "SELECT ewma_volatility, cvar_95, liquidity_ratio, degraded, degraded_reason "
        "FROM risk_snapshots WHERE risk_snapshot_id = ?",
        (rid,),
    ).fetchone()
    assert row["ewma_volatility"] is None
    assert row["cvar_95"] is None
    assert row["liquidity_ratio"] is None
    assert row["degraded"] == 1
    assert row["degraded_reason"]


def test_record_candidate_reads_metrics_from_the_optimization_result(repo, conn):
    """The optimizer's metrics live on Candidate.optimization, not on Candidate.

    This is the test the original implementation lacked: it named thirteen
    attributes that do not exist, and nothing called it.
    """
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=True))

    row = conn.execute(
        "SELECT * FROM candidate_allocations WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    assert row["strategy"] == "MAX_SHARPE"
    assert row["candidate_role"] == "SAFE_CONSTRAINED"
    assert row["sharpe"] == pytest.approx(0.48)
    assert row["cvar_95"] == pytest.approx(0.0138)
    assert row["transaction_cost_paise"] == 1_250_000
    assert row["solver_status"] == "OPTIMAL"
    assert row["control_status"] == "PASSED"
    assert row["stress_status"] == "PASSED"
    assert row["eligible_for_approval"] == 1


def test_rejected_candidate_is_not_eligible_for_approval(repo, conn):
    """INV-2, INV-10: a control or stress failure blocks approval."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    row = conn.execute(
        "SELECT control_status, stress_status, eligible_for_approval "
        "FROM candidate_allocations WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    assert row["control_status"] == "FAILED"
    assert row["stress_status"] == "FAILED"
    assert row["eligible_for_approval"] == 0


def test_unvalidated_candidate_is_not_eligible(repo, conn):
    """INV-10: an unrun control or stress suite is never equivalent to PASSED."""
    decision_id = a_decision(repo)
    unvalidated = Candidate(
        role=CandidateRole.OPTIMAL_UNCONSTRAINED,
        optimization=an_optimization(),
        control=None,
        stress=(),
    )
    candidate_id = repo.record_candidate(decision_id, unvalidated)
    row = conn.execute(
        "SELECT control_status, stress_status, eligible_for_approval "
        "FROM candidate_allocations WHERE candidate_id = ?",
        (candidate_id,),
    ).fetchone()
    assert row["control_status"] == "NOT_VALIDATED"
    assert row["stress_status"] == "NOT_RUN"
    assert row["eligible_for_approval"] == 0


def test_record_explanation_stores_the_structured_object(repo, conn):
    decision_id = a_decision(repo)
    expl = build_explanation(
        trigger="Banking sector shock of -30% applied",
        risk_change=RiskChange(metric="EWMA volatility", from_value=0.0971, to_value=0.1643),
        main_contributors=(
            RiskChange(metric="risk contribution", from_value=0.31, to_value=0.58,
                       scope="BANKING"),
        ),
        optimizer=Strategy.MAX_SHARPE,
        candidate_summary=dict(WEIGHTS),
        control_status=ControlStatus.FAILED,
        reasons=("BANKING at 43.0% exceeds the sector limit of 35.0%",),
        stress_summary=("Banking crisis: loss 22.1% exceeds limit 18.0%",),
        action="Proposal rejected; Last Approved Safe Allocation retained.",
    )
    narrated = build_narrated_explanation(expl)
    eid = repo.record_explanation(decision_id, expl, narrated.template_text)

    row = conn.execute(
        "SELECT structured_json, template_text, llm_used, llm_text "
        "FROM explanations WHERE explanation_id = ?",
        (eid,),
    ).fetchone()
    assert '"from_value":0.0971' in row["structured_json"].replace(" ", "")
    assert row["llm_used"] == 0
    assert row["llm_text"] is None
    assert "Banking" in row["template_text"]


# ---------------------------------------------------------------------------
# the guarded transition (INV-6)
# ---------------------------------------------------------------------------

def test_human_action_can_only_be_recorded_once(repo):
    """EC-7.2: the close transition is guarded."""
    decision_id = a_decision(repo)
    action = HumanActionRecord(
        action=HumanAction.APPROVE,
        user_identity="demo_risk_manager",
        user_role="RISK_MANAGER",
        timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
    )
    repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)

    with pytest.raises(AuditWriteError, match="already closed"):
        repo.close_decision_with_human_action(
            decision_id, action, portfolio_state_after=1
        )


def test_failed_audit_write_is_not_reported_as_success(repo):
    """EC-7.3: a write that did not happen raises."""
    action = HumanActionRecord(
        action=HumanAction.REJECT,
        user_identity="demo_risk_manager",
        user_role="RISK_MANAGER",
        timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
    )
    with pytest.raises(AuditWriteError, match="does not exist"):
        repo.close_decision_with_human_action(9999, action, portfolio_state_after=None)


def test_human_action_records_full_attribution(repo, conn):
    """INV-6: who acted, and why, is part of the audit record.

    The decision_records column stores only the action name. An override that
    loses its reason and the controls it overrode is not auditable (FR-118).
    """
    decision_id = a_decision(repo)
    action = HumanActionRecord(
        action=HumanAction.OVERRIDE,
        user_identity="demo_risk_manager",
        user_role="RISK_MANAGER",
        timestamp=datetime(2026, 8, 31, 10, 5, tzinfo=UTC),
        comment="Accepted for the demo narrative",
        is_override=True,
        override_reason="Board-approved temporary exception",
        overridden_controls=("CONC_SECTOR_MAX", "RC_SECTOR_MAX"),
        confirmation_token="CONFIRM-7731",
    )
    repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)

    row = conn.execute(
        "SELECT * FROM human_actions WHERE decision_id = ?", (decision_id,)
    ).fetchone()
    assert row["user_identity"] == "demo_risk_manager"
    assert row["user_role"] == "RISK_MANAGER"
    assert row["is_override"] == 1
    assert row["override_reason"] == "Board-approved temporary exception"
    assert "CONC_SECTOR_MAX" in row["overridden_controls_json"]
    assert row["confirmation_token"] == "CONFIRM-7731"


def test_a_rejected_close_writes_nothing_at_all(repo, conn):
    """The two writes in the close transition are atomic together."""
    decision_id = a_decision(repo)
    action = HumanActionRecord(
        action=HumanAction.APPROVE,
        user_identity="demo_risk_manager",
        user_role="RISK_MANAGER",
        timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
    )
    repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)
    with pytest.raises(AuditWriteError):
        repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)

    count = conn.execute(
        "SELECT COUNT(*) AS c FROM human_actions WHERE decision_id = ?", (decision_id,)
    ).fetchone()["c"]
    assert count == 1, "the refused second close must not leave an attribution row"


def test_repository_exposes_no_update_or_delete_methods(repo):
    """INV-6: append-only, by construction."""
    for name in dir(repo):
        assert not name.startswith("update_")
        assert not name.startswith("delete_")
    assert not hasattr(repo, "execute_sql")


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def test_get_last_safe_allocation_returns_a_typed_datetime(repo):
    """The seeded Last Approved Safe Allocation is readable."""
    safe = repo.get_last_safe_allocation("DEMO_100CR")
    assert safe is not None
    assert isinstance(safe.approved_at, datetime)
    assert safe.weights["NIFTY50"] == pytest.approx(0.28)
    assert safe.policy_version_id == 1
    assert safe.via_override is False


def test_get_last_safe_allocation_is_none_for_an_unknown_portfolio(repo):
    """INV-4: no safe allocation means None — never a fabricated one."""
    assert repo.get_last_safe_allocation("NO_SUCH_PORTFOLIO") is None


# ---------------------------------------------------------------------------
# narration (FR-142)
# ---------------------------------------------------------------------------

def test_narrator_renders_a_risk_change():
    """The original narrator crashed here: RiskChange has from_value/to_value."""
    expl = build_explanation(
        trigger="Scheduled review",
        risk_change=RiskChange(metric="EWMA volatility", from_value=0.0971, to_value=0.1643),
        main_contributors=(),
        optimizer=Strategy.MAX_SHARPE,
        candidate_summary=dict(WEIGHTS),
        control_status=ControlStatus.FAILED,
        reasons=("BANKING at 43.0% exceeds the sector limit of 35.0%",),
        stress_summary=("Banking crisis: loss 22.1% exceeds limit 18.0%",),
        action="Proposal rejected; Last Approved Safe Allocation retained.",
    )
    text = render_narrative(expl)
    assert "9.71%" in text
    assert "16.43%" in text
    assert "rose" in text
    assert "rejected this allocation" in text
    assert "Model Estimate" in text


def test_narrator_is_complete_with_no_llm_and_no_api_key():
    """FR-142/FR-146: the deterministic narrator is the shipping default."""
    expl = build_explanation(
        trigger="Scheduled review",
        risk_change=None,
        main_contributors=(),
        optimizer=None,
        candidate_summary={},
        control_status=ControlStatus.PASSED,
        reasons=(),
        stress_summary=(),
        action="No change required.",
    )
    narrated = build_narrated_explanation(expl)
    assert narrated.llm_text is None
    assert narrated.display_text == narrated.template_text
    assert narrated.template_text.strip()
    assert "Scheduled review" in narrated.template_text


def test_narrator_is_deterministic():
    """Same Explanation, same prose. Always."""
    expl = build_explanation(
        trigger="t", risk_change=None, main_contributors=(), optimizer=None,
        candidate_summary=dict(WEIGHTS), control_status=ControlStatus.PASSED,
        reasons=("a", "b"), stress_summary=(), action="none",
    )
    assert render_narrative(expl) == render_narrative(expl)


def test_llm_text_is_display_only(repo, conn):
    """INV-1: LLM prose is stored and displayed, never parsed back."""
    decision_id = a_decision(repo)
    expl = build_explanation(
        trigger="t", risk_change=None, main_contributors=(), optimizer=None,
        candidate_summary={}, control_status=ControlStatus.PASSED,
        reasons=(), stress_summary=(), action="none",
    )
    narrated = build_narrated_explanation(
        expl, llm_text="Some generated prose.", llm_model="claude-x"
    )
    repo.record_explanation(
        decision_id, expl, narrated.template_text,
        llm_text=narrated.llm_text, llm_model=narrated.llm_model,
    )
    row = conn.execute(
        "SELECT structured_json, llm_used, llm_text FROM explanations "
        "WHERE decision_id = ?",
        (decision_id,),
    ).fetchone()
    assert row["llm_used"] == 1
    assert row["llm_text"] == "Some generated prose."
    # the authoritative record is untouched by the prose
    assert "Some generated prose." not in row["structured_json"]


# ---------------------------------------------------------------------------
# explanation construction (FR-140)
# ---------------------------------------------------------------------------

def test_explanation_never_carries_an_empty_string():
    """FR-140: a field that does not apply is None, never ''."""
    expl = build_explanation(
        trigger="t", risk_change=None, main_contributors=(), optimizer=None,
        candidate_summary={}, control_status=ControlStatus.PASSED,
        reasons=("", "  ", "real reason"), stress_summary=("",),
        action="none", expected_improvement="   ",
    )
    assert expl.expected_improvement is None
    assert expl.reasons == ("real reason",)
    assert expl.stress_summary == ()


@pytest.mark.parametrize("field", ["trigger", "action"])
def test_explanation_requires_trigger_and_action(field):
    kwargs: dict = {
        "trigger": "t",
        "risk_change": None,
        "main_contributors": (),
        "optimizer": None,
        "candidate_summary": {},
        "control_status": ControlStatus.PASSED,
        "reasons": (),
        "stress_summary": (),
        "action": "a",
    }
    kwargs[field] = "   "
    with pytest.raises(ValueError, match=field):
        build_explanation(**kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# control findings and stress results
# ---------------------------------------------------------------------------

def test_record_control_findings_keeps_observed_and_threshold(repo, conn):
    """FR-174: a finding shows 43.0% > 35.0%, not "constraints violated"."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    written = repo.record_control_findings(decision_id, [a_breach()], candidate_id)
    assert written == 1

    row = conn.execute(
        "SELECT * FROM control_findings WHERE candidate_id = ?", (candidate_id,)
    ).fetchone()
    assert row["control_code"] == "CONC_SECTOR_MAX"
    assert row["observed_value"] == pytest.approx(0.43)
    assert row["threshold_value"] == pytest.approx(0.35)
    assert row["comparator"] == "GT"
    assert row["is_hard"] == 1
    assert row["severity"] == "RED"


def test_record_stress_results_keeps_the_full_status(repo, conn):
    """INV-10: NOT_RUN and ERROR are never equivalent to PASSED."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))

    errored = StressResult(
        scenario_code="BROAD_CRASH",
        scenario_label="Broad crash",
        is_custom=False,
        shocks={"BROAD_EQUITY": -0.25},
        portfolio_loss=0.0,
        loss_paise=0,
        contribution={},
        post_shock_volatility=None,
        post_shock_cvar=None,
        breaches=(),
        loss_threshold=0.18,
        status=StressStatus.ERROR,
    )
    repo.record_stress_results(
        decision_id, [a_stress_result(passed=False), errored], candidate_id
    )

    rows = conn.execute(
        "SELECT scenario_code, passed, status FROM stress_results "
        "WHERE candidate_id = ? ORDER BY stress_result_id",
        (candidate_id,),
    ).fetchall()
    assert [(r["scenario_code"], r["passed"], r["status"]) for r in rows] == [
        ("BANKING_CRISIS", 0, "FAILED"),
        ("BROAD_CRASH", 0, "ERROR"),
    ]


def test_an_errored_stress_run_is_never_stored_as_passed(repo, conn):
    """The passed bit is derived from status, not supplied separately."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    for status in (StressStatus.NOT_RUN, StressStatus.ERROR, StressStatus.FAILED):
        result = StressResult(
            scenario_code=f"S_{status.value}",
            scenario_label=status.value,
            is_custom=False,
            shocks={},
            portfolio_loss=0.0,
            loss_paise=0,
            contribution={},
            post_shock_volatility=None,
            post_shock_cvar=None,
            breaches=(),
            loss_threshold=0.18,
            status=status,
        )
        repo.record_stress_results(decision_id, [result], candidate_id)

    passed_flags = [
        r["passed"]
        for r in conn.execute(
            "SELECT passed FROM stress_results WHERE candidate_id = ? "
            "AND scenario_code LIKE 'S_%'",
            (candidate_id,),
        ).fetchall()
    ]
    assert passed_flags == [0, 0, 0]


def test_empty_findings_and_results_write_nothing(repo):
    decision_id = a_decision(repo)
    assert repo.record_control_findings(decision_id, []) == 0
    assert repo.record_stress_results(decision_id, []) == 0


# ---------------------------------------------------------------------------
# decision events and replay (INV-6)
# ---------------------------------------------------------------------------

def test_record_event_and_replay_in_sequence_order(repo):
    """Replay orders by sequence_no, never by wall clock."""
    decision_id = a_decision(repo)
    # deliberately written out of order, with the LATER event timestamped first
    repo.record_event(decision_id, make_event(
        2, EVENT_CONTROL_REJECTED, "Rejected on sector concentration",
        occurred_at=datetime(2026, 8, 31, 9, 41, tzinfo=UTC),
    ))
    repo.record_event(decision_id, make_event(
        1, EVENT_SHOCK_DETECTED, "Banking shock detected",
        occurred_at=datetime(2026, 8, 31, 9, 41, tzinfo=UTC),
    ))

    timeline = repo.get_replay_timeline(decision_id)
    assert [e.sequence_no for e in timeline] == [1, 2]
    assert timeline[0].event_code == EVENT_SHOCK_DETECTED
    assert timeline[0].actor is Actor.MACHINE
    assert timeline[1].actor is Actor.CONTROL


def test_duplicate_sequence_number_is_refused(repo):
    """The schema enforces one event per sequence_no per decision."""
    decision_id = a_decision(repo)
    repo.record_event(decision_id, make_event(1, EVENT_SHOCK_DETECTED, "first"))
    with pytest.raises(AuditWriteError, match="sequence"):
        repo.record_event(decision_id, make_event(1, EVENT_RISK_COMPUTED, "second"))


def test_event_detail_round_trips(repo):
    decision_id = a_decision(repo)
    repo.record_event(decision_id, make_event(
        1, EVENT_RISK_COMPUTED, "Risk recomputed",
        detail={"ewma_volatility": 0.1643, "sector": "BANKING"},
    ))
    timeline = repo.get_replay_timeline(decision_id)
    assert timeline[0].detail == {"ewma_volatility": 0.1643, "sector": "BANKING"}


def test_make_event_derives_the_actor_from_the_event_code():
    """A control judgement filed as a machine step misrepresents who decided."""
    assert make_event(1, EVENT_SHOCK_DETECTED, "s").actor is Actor.MACHINE
    assert make_event(1, EVENT_BREAKER_TRIPPED, "s").actor is Actor.CONTROL
    assert make_event(1, EVENT_HUMAN_ACTION, "s").actor is Actor.HUMAN


def test_make_event_refuses_to_guess_an_actor():
    with pytest.raises(ValueError, match="unknown event_code"):
        make_event(1, "NOT_A_REAL_CODE", "s")


def test_replay_reconstructs_from_persistence_only(repo):
    """INV-6: the timeline is read, never recomputed."""
    decision_id = a_decision(repo)
    repo.record_event(decision_id, make_event(1, EVENT_TRIGGER_RECEIVED, "Trigger"))
    repo.record_event(decision_id, make_event(2, EVENT_RISK_COMPUTED, "Risk"))
    repo.record_event(decision_id, make_event(3, EVENT_CONTROL_REJECTED, "Rejected"))
    repo.record_event(decision_id, make_event(4, EVENT_HUMAN_ACTION, "Kept current"))

    rows = reconstruct_timeline(repo, decision_id)
    assert [r.sequence_no for r in rows] == [1, 2, 3, 4]
    assert [r.actor_label for r in rows] == [
        "System", "System", "Control engine", "Risk manager"
    ]
    assert rows[2].summary == "Rejected"
    assert rows[0].timestamp_text


def test_replay_of_a_decision_with_no_events_is_empty(repo):
    """An empty timeline is reported as empty, not filled in (Rule 2)."""
    decision_id = a_decision(repo)
    assert reconstruct_timeline(repo, decision_id) == ()


# ---------------------------------------------------------------------------
# alerts
# ---------------------------------------------------------------------------

def test_raise_alert(repo, conn):
    decision_id = a_decision(repo)
    alert_id = repo.raise_alert(
        Alert(
            severity="RED",
            category=BreakerCategory.RISK,
            title="Circuit breaker active",
            message="Sector risk contribution at 58% exceeds the 45% hard limit",
            created_at=datetime(2026, 8, 31, 9, 42, tzinfo=UTC),
        ),
        decision_id=decision_id,
    )
    row = conn.execute(
        "SELECT * FROM alerts WHERE alert_id = ?", (alert_id,)
    ).fetchone()
    assert row["severity"] == "RED"
    assert row["category"] == "RISK"
    assert row["decision_id"] == decision_id
    assert row["acknowledged_at"] is None


# ---------------------------------------------------------------------------
# safe-allocation promotion (INV-2, INV-4, INV-10)
# ---------------------------------------------------------------------------

def _approve(repo, decision_id, override=False):
    action = HumanActionRecord(
        action=HumanAction.OVERRIDE if override else HumanAction.APPROVE,
        user_identity="demo_risk_manager",
        user_role="RISK_MANAGER",
        timestamp=datetime(2026, 8, 31, 10, 0, tzinfo=UTC),
        is_override=override,
        override_reason="Board-approved exception" if override else None,
        overridden_controls=("CONC_SECTOR_MAX",) if override else (),
        confirmation_token="CONFIRM-1" if override else None,
    )
    repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)


def test_promote_safe_allocation_records_the_new_last_approved(repo):
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=True))
    _approve(repo, decision_id)

    repo.promote_safe_allocation(decision_id, candidate_id, portfolio_state_id=1)

    safe = repo.get_last_safe_allocation("DEMO_100CR")
    assert safe is not None
    assert safe.decision_id == decision_id
    assert safe.approved_by == "demo_risk_manager"
    assert safe.via_override is False
    assert safe.weights == pytest.approx(WEIGHTS)


def test_an_ineligible_candidate_cannot_be_promoted(repo):
    """INV-2: an invalid allocation cannot become an approved allocation."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    _approve(repo, decision_id)

    with pytest.raises(AuditWriteError, match="not eligible for approval"):
        repo.promote_safe_allocation(decision_id, candidate_id, portfolio_state_id=1)


def test_the_last_safe_allocation_is_unchanged_by_a_refused_promotion(repo):
    """INV-4: on failure, retain the last approved allocation."""
    before = repo.get_last_safe_allocation("DEMO_100CR")
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    _approve(repo, decision_id)
    with pytest.raises(AuditWriteError):
        repo.promote_safe_allocation(decision_id, candidate_id, portfolio_state_id=1)

    after = repo.get_last_safe_allocation("DEMO_100CR")
    assert after == before


def test_an_ineligible_candidate_can_be_promoted_via_a_recorded_override(repo):
    """FR-118: an override is permitted, and is recorded as an override."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    _approve(repo, decision_id, override=True)

    repo.promote_safe_allocation(decision_id, candidate_id, portfolio_state_id=1)
    safe = repo.get_last_safe_allocation("DEMO_100CR")
    assert safe is not None
    assert safe.via_override is True


def test_promotion_requires_a_recorded_human_action(repo):
    """INV-6: nothing is promoted without a human on the record."""
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=True))
    with pytest.raises(AuditWriteError, match="no recorded human action"):
        repo.promote_safe_allocation(decision_id, candidate_id, portfolio_state_id=1)


def test_promotion_rejects_a_candidate_from_another_decision(repo):
    first = a_decision(repo, uid="uid-a")
    second = a_decision(repo, uid="uid-b")
    candidate_id = repo.record_candidate(first, a_candidate(passed=True))
    _approve(repo, second)
    with pytest.raises(AuditWriteError, match="belongs to decision"):
        repo.promote_safe_allocation(second, candidate_id, portfolio_state_id=1)


# ---------------------------------------------------------------------------
# reads
# ---------------------------------------------------------------------------

def test_get_decision_assembles_everything_that_was_stored(repo):
    decision_id = a_decision(repo)
    candidate_id = repo.record_candidate(decision_id, a_candidate(passed=False))
    repo.record_control_findings(decision_id, [a_breach()], candidate_id)
    repo.record_stress_results(decision_id, [a_stress_result(passed=False)], candidate_id)
    repo.record_event(decision_id, make_event(1, EVENT_SHOCK_DETECTED, "Shock"))
    expl = build_explanation(
        trigger="Banking shock", risk_change=None, main_contributors=(),
        optimizer=Strategy.MAX_SHARPE, candidate_summary=dict(WEIGHTS),
        control_status=ControlStatus.FAILED, reasons=("sector limit",),
        stress_summary=("banking crisis failed",), action="Rejected.",
    )
    repo.record_explanation(decision_id, expl, render_narrative(expl))
    _approve(repo, decision_id, override=True)

    stored = repo.get_decision(decision_id)
    assert stored.event_uid == "uid-1"
    assert stored.control_status == "FAILED"
    assert stored.circuit_breaker_active is True
    assert stored.is_closed

    assert len(stored.candidates) == 1
    cand = stored.candidates[0]
    assert cand.role == "SAFE_CONSTRAINED"
    assert cand.eligible_for_approval is False
    assert cand.weights == pytest.approx(WEIGHTS)
    assert len(cand.findings) == 1
    assert cand.findings[0].control_code == "CONC_SECTOR_MAX"
    assert cand.findings[0].observed == pytest.approx(0.43)
    assert len(cand.stress) == 1
    assert cand.stress[0].status is StressStatus.FAILED

    assert [e.event_code for e in stored.events] == [EVENT_SHOCK_DETECTED]
    assert stored.human_action is not None
    assert stored.human_action.is_override is True
    assert stored.human_action.overridden_controls == ("CONC_SECTOR_MAX",)
    assert stored.template_text and "Banking shock" in stored.template_text
    assert stored.structured_explanation is not None


def test_get_decision_raises_for_an_unknown_id(repo):
    with pytest.raises(LookupError, match="no decision"):
        repo.get_decision(9999)


def test_list_decisions_is_newest_first(repo):
    a_decision(repo, uid="uid-a")
    a_decision(repo, uid="uid-b")
    rows = repo.list_decisions(limit=10)
    # the seeded decision plus the two above
    assert len(rows) == 3
    assert rows[0].created_at >= rows[-1].created_at
    assert all(isinstance(r.created_at, datetime) for r in rows)


def test_list_decisions_paginates(repo):
    a_decision(repo, uid="uid-a")
    a_decision(repo, uid="uid-b")
    first = repo.list_decisions(limit=1, offset=0)
    second = repo.list_decisions(limit=1, offset=1)
    assert len(first) == len(second) == 1
    assert first[0].decision_id != second[0].decision_id


def test_get_current_policy_returns_the_configured_policy(repo, policy):
    assert repo.get_current_policy() == policy


def test_get_policy_version_returns_the_policy_in_force(repo, policy):
    """INV-8: replay reads the version the decision recorded, not the newest."""
    assert repo.get_policy_version(1) == policy


def test_get_current_policy_follows_the_newest_version(repo, policy):
    from dataclasses import replace

    amended = replace(policy, version=2, label="amended")
    repo.record_policy_version(
        amended,
        PolicyChangeMeta(
            created_by="demo_risk_manager", created_by_role="RISK_MANAGER",
            source="UI_EDIT", parent_version_id=1, change_summary="relabelled",
        ),
    )
    assert repo.get_current_policy() == amended
    assert repo.get_policy_version(1) == policy

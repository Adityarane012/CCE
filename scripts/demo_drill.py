"""The pre-demo failure drill.

Spec: docs/IMPLEMENTATION-PLAN.md PHASE 15, docs/13-EDGE-CASES.md section 11.

Run before presenting::

    python scripts/demo_drill.py

Phase 15 is deliberately a HUMAN phase: rehearsing the script aloud, timed,
twice, is not something that can be delegated. This automates only the six
failure drills — the machine-checkable half — so the rehearsal itself starts
from a known-good system rather than from hope.

Each drill answers a question a judge might ask by actually doing it, not by
asserting it in a comment.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
logging.disable(logging.WARNING)

from cce.contracts import (
    CandidateRole,
    HumanAction,
    HumanActionRecord,
    StressStatus,
)
from cce.exceptions import ApprovalNotPermitted, PolicyError
from cce.services import (
    ApprovalService,
    OptimizationService,
    PolicyService,
    PortfolioService,
    ReplayService,
    ServiceContext,
    StressService,
)

PASS, FAIL = "  PASS", "  FAIL"
_results: list[tuple[str, bool, str]] = []


def drill(name: str):
    def wrap(fn):
        def run(*a, **kw):
            try:
                detail = fn(*a, **kw) or ""
                _results.append((name, True, detail))
                print(f"{PASS}  {name}" + (f"\n         {detail}" if detail else ""))
            except AssertionError as exc:
                _results.append((name, False, str(exc)))
                print(f"{FAIL}  {name}\n         {exc}")
            except Exception as exc:  # noqa: BLE001 - a drill must not abort the run
                _results.append((name, False, f"{type(exc).__name__}: {exc}"))
                print(f"{FAIL}  {name}\n         {type(exc).__name__}: {exc}")
        return run
    return wrap


def _actor(action: HumanAction = HumanAction.APPROVE) -> HumanActionRecord:
    return HumanActionRecord(
        action=action, user_identity="demo_risk_manager",
        user_role="RISK_MANAGER", timestamp=datetime.now(UTC),
    )


# ---------------------------------------------------------------------------

@drill("1. Runs with no network — cached provider is the default")
def drill_offline(ctx: ServiceContext) -> str:
    provider = ctx.market_data.provider.value
    assert provider in {"CACHED", "CACHED_FALLBACK"}, (
        f"provider is {provider}; the demo must not need the network"
    )
    rows = len(ctx.market_data.returns)
    assert rows > 250, f"only {rows} sessions loaded"
    return f"{rows} sessions from the committed cache, provider {provider}"


@drill("2. Runs with no API key — deterministic narrator produces full prose")
def drill_no_llm(ctx: ServiceContext, cycle) -> str:
    stored = ReplayService(ctx).get_decision(cycle.decision_id)
    assert stored.template_text, "no prose was generated"
    assert stored.llm_text is None, "an LLM ran; this drill assumes none"
    assert "**Action.**" in stored.template_text, "prose is incomplete"
    return f"{len(stored.template_text)} characters of prose, no LLM"


@drill("3. Database deleted — migrations rebuild to a working state")
def drill_rebuild(tmp: Path) -> str:
    db = tmp / "rebuild.db"
    ctx = ServiceContext.build(db_path=str(db))
    assert db.exists(), "no database was created"
    policy = ctx.policy
    safe = PortfolioService(ctx).get_last_safe_allocation()
    assert safe is not None, "the seed did not create a safe allocation"
    ctx.close()

    db.unlink()
    for suffix in ("-wal", "-shm"):
        Path(str(db) + suffix).unlink(missing_ok=True)
    assert not db.exists(), "database was not removed"

    ctx2 = ServiceContext.build(db_path=str(db))
    assert ctx2.policy.label == policy.label, "policy did not survive the rebuild"
    assert PortfolioService(ctx2).get_last_safe_allocation() is not None
    ctx2.close()
    return "deleted and rebuilt from migrations; policy and seed restored"


@drill("4. Extreme shock (-40% across the book) — handled, never reported safe")
def drill_extreme_shock(ctx: ServiceContext) -> str:
    state = PortfolioService(ctx).get_current_state()
    shocks = {a.sector: -0.40 for a in ctx.universe.assets}
    result = StressService(ctx).run_custom(
        state.weights, shocks, label="Everything -40%",
        total_value_paise=state.total_value_paise,
    )
    assert result.status is not StressStatus.PASSED, (
        "a 40% fall across every sector was reported as survived"
    )
    if result.loss_is_measured:
        assert result.portfolio_loss > result.loss_threshold, (
            f"loss {result.portfolio_loss:.1%} did not exceed the limit"
        )
        return (
            f"loss {result.portfolio_loss:.1%} exceeds the "
            f"{result.loss_threshold:.1%} limit; status {result.status.value}"
        )
    return f"status {result.status.value} — {result.error_reason}"


@drill("5. Approving a rejected candidate — refused, with a legible reason")
def drill_refusal(ctx: ServiceContext, cycle) -> str:
    state = PortfolioService(ctx).get_current_state()
    rejected = next(
        (c for c in cycle.candidates if not c.eligible_for_approval), None
    )
    assert rejected is not None, "no rejected candidate to try"
    try:
        ApprovalService(ctx).approve(
            cycle.decision_id, rejected, _actor(), state
        )
    except ApprovalNotPermitted as exc:
        message = str(exc)
        assert "not eligible" in message, "the refusal does not say why"
        assert any(ch.isdigit() for ch in message), (
            "the refusal names no observed value — it must not be generic"
        )
        return message[:110] + ("…" if len(message) > 110 else "")
    raise AssertionError("a rejected candidate was approved")


@drill("6. Weakening a threshold — refused without a recorded reason")
def drill_weakening(ctx: ServiceContext) -> str:
    service = PolicyService(ctx)
    change = {"RISK_VOL_ANNUAL": {"amber_max": 0.30}}

    preview = service.preview_change(change)
    assert preview.is_weakening, "loosening a hard limit was not flagged"

    try:
        service.apply_change(change, _actor())
    except PolicyError as exc:
        assert "loosens a hard limit" in str(exc)
        return (
            f"preview flags {', '.join(preview.weakened_controls)}; "
            "applying without an acknowledgement is refused"
        )
    raise AssertionError("a hard limit was loosened with no reason recorded")


# ---------------------------------------------------------------------------

def main() -> int:
    print("\nCCE — pre-demo failure drill")
    print("=" * 62)

    tmp = Path(tempfile.mkdtemp(prefix="cce-drill-"))
    try:
        ctx = ServiceContext.build(db_path=str(tmp / "drill.db"))
        state = PortfolioService(ctx).get_current_state()
        cycle = OptimizationService(ctx).run_cycle(
            state, trigger_detail="Pre-demo drill"
        )

        drill_offline(ctx)
        drill_no_llm(ctx, cycle)
        drill_rebuild(tmp)
        drill_extreme_shock(ctx)
        drill_refusal(ctx, cycle)
        drill_weakening(ctx)

        print("=" * 62)
        _summary(ctx, state, cycle)
        ctx.close()
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    failed = [n for n, ok, _ in _results if not ok]
    print()
    if failed:
        print(f"{len(failed)} drill(s) FAILED: {', '.join(failed)}")
        return 1
    print(f"All {len(_results)} drills pass. The system is demo-ready.")
    print("\nThe rehearsal itself is yours: read 14-DEMO-SCRIPT.md aloud,")
    print("timed, twice. Pre-type the shock values.")
    return 0


def _summary(ctx, state, cycle) -> None:
    """What a presenter should confirm on screen before starting."""
    risk = ctx.repo.get_current_policy()
    optimal = cycle.candidate(CandidateRole.OPTIMAL_UNCONSTRAINED)
    safe = cycle.candidate(CandidateRole.SAFE_CONSTRAINED)

    print("\nDemo state")
    print(f"  portfolio        {state.total_value_crore:,.1f} Cr")
    print(f"  policy           {risk.label} (v{risk.version})")
    print(f"  data as of       {ctx.market_data.as_of_date}")
    print(f"  market snapshot  #{ctx.snapshot_id}")
    if optimal is not None:
        print(
            f"  OPTIMAL          eligible={optimal.eligible_for_approval} "
            f"({len(optimal.rejection_reasons)} rejection reason(s))"
        )
    if safe is not None:
        print(f"  SAFE             eligible={safe.eligible_for_approval}")
        if safe.rejection_reasons:
            for r in safe.rejection_reasons[:3]:
                print(f"                   - {r}")


if __name__ == "__main__":
    raise SystemExit(main())

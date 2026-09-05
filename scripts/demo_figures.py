"""Regenerate every figure quoted in docs/14-DEMO-SCRIPT.md.

    ./.venv/Scripts/python.exe scripts/demo_figures.py

`docs/10-RULES.md` section 5.3 forbids speaking a number aloud or putting it
on a slide until a real run on the committed data has produced it. This is
that run. Every figure in the demo script should be traceable to a line of
this output, and a judge who asks *"can you show me that again?"* gets the
same number.

The figures move when the cached panel is refreshed or a threshold changes —
that is the point of regenerating them rather than pasting them once. If this
output and the demo script disagree, **the output wins and the script is
corrected**, never the other way round.

Runs entirely on the committed cache: no network, no API key, and against a
throwaway database so it never touches demo state.
"""

from __future__ import annotations

import logging
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cce.contracts import RiskState, View
from cce.services import (
    OptimizationService,
    PortfolioService,
    RiskService,
    ServiceContext,
    StressService,
)

#: The view that drives the demo's central moment. A portfolio manager
#: believing banking will outperform is an ordinary, defensible thing to
#: believe — which is exactly why it makes an honest trigger. The engine's
#: answer to it is not defensible, and that is the story.
DEMO_VIEW_OUTPERFORMANCE = 0.04
DEMO_VIEW_CONFIDENCE = 0.60

#: The shock Stage 2 of the demo applies by hand. Severe enough to matter,
#: mild enough not to look staged — and MILDER than the built-in
#: BANKING_CRISIS scenario, so a judge cannot say the worst case was cherry
#: picked.
DEMO_SHOCK = {
    "BANKING": -0.18,
    "BROAD_EQUITY": -0.12,
    "IT": -0.08,
    "GOLD": 0.05,
}

RULE = "=" * 70


def main() -> int:
    logging.disable(logging.WARNING)

    db = Path(tempfile.mkdtemp()) / "figures.db"
    ctx = ServiceContext.build(db_path=str(db))
    portfolio = PortfolioService(ctx)
    risk = RiskService(ctx)
    stress = StressService(ctx)
    optimization = OptimizationService(ctx, stress)

    state = portfolio.get_current_state()
    universe = ctx.universe

    print("\nCCE — demo figures, regenerated from the committed cache")
    print(RULE)
    print(f"  data as of      {ctx.market_data.as_of_date}")
    print(f"  provider        {ctx.market_data.provider.value}")
    print(f"  policy          {ctx.policy.label} (v{ctx.policy.version})")
    print(f"  portfolio       {state.total_value_paise / 1e9:.1f} Cr")

    _stage_1(risk, state, universe)
    _stage_2(stress, state)
    _stage_3(optimization, state, universe)
    _stage_4(optimization, state, universe)

    print("\n" + RULE)
    print("Every number above came from this run. If the demo script quotes")
    print("a figure this output does not contain, the script is wrong.")
    print(RULE + "\n")
    return 0


# ---------------------------------------------------------------------------


def _sectors(weights: dict[str, float], universe) -> dict[str, float]:
    out: dict[str, float] = {}
    for asset_id, w in weights.items():
        sector = universe.get(asset_id).sector
        out[sector] = out.get(sector, 0.0) + w
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


def _fmt(mapping: dict[str, float], floor: float = 0.005) -> str:
    """Largest first. A demo line read aloud out of order invites the
    question "why is that one third?" instead of the one you want."""
    ordered = sorted(mapping.items(), key=lambda kv: -kv[1])
    return " · ".join(f"{k} {v * 100:.0f}%" for k, v in ordered if v > floor)


def _stage_1(risk, state, universe) -> None:
    print("\n" + RULE)
    print("STAGE 1 — the book as it stands")
    print(RULE)
    snapshot = risk.get_snapshot(state)
    print(f"  risk state      {snapshot.risk_state.value}")
    print(f"  volatility      {_pct(snapshot.portfolio_volatility)}")
    print(f"  VaR 95 / CVaR   {_pct(snapshot.var_95)} / {_pct(snapshot.cvar_95)}")
    print(f"  allocation      {_fmt(_sectors(state.weights, universe))}")
    print(f"  sector risk     {_fmt(snapshot.sector_risk_contribution)}")
    if snapshot.breaches:
        print("  findings:")
        for breach in snapshot.breaches:
            print(f"    {breach.severity.value:<5} {breach.control_code}: "
                  f"{breach.message}")
    else:
        print("  findings        none — the book is within policy")


def _stage_2(stress, state) -> None:
    """The banking shock, measured rather than asserted."""
    print("\n" + RULE)
    print("STAGE 2 — the banking shock")
    print(RULE)
    scenarios = stress.list_scenarios()
    banking = [
        s for s in scenarios
        if any(k.upper().startswith("BANK") for k in s.shocks)
    ]
    if not banking:
        print("  no banking scenario is configured")
        return

    results = stress.run(
        state.weights,
        tuple(s.code for s in banking),
        total_value_paise=state.total_value_paise,
    )
    for result in results:
        _stress_line(result)

    print("\nthe shock applied by hand on stage:")
    print("    " + " · ".join(
        f"{k} {v * 100:+.0f}%" for k, v in DEMO_SHOCK.items()
    ))
    custom = stress.run_custom(
        state.weights, DEMO_SHOCK, label="Demo banking shock",
        total_value_paise=state.total_value_paise,
    )
    _stress_line(custom)


def _stress_line(result) -> None:
    loss = (
        f"{result.portfolio_loss * 100:.1f}% ({result.loss_paise / 1e9:.1f} Cr)"
        if result.loss_is_measured else "—  (no verdict, NOT a zero loss)"
    )
    print(f"  {result.scenario_label:<34} {result.status.value:<8} {loss}"
          f"   limit {result.loss_threshold * 100:.0f}%")


def _stage_3(optimization, state, universe) -> None:
    """Safe vs Optimal, with and without the view that drives the demo."""
    banking = [
        a.asset_id for a in universe.assets
        if a.sector.upper().startswith("BANK")
    ]
    views = tuple(
        View(
            asset=asset_id,
            versus=None,
            outperformance=DEMO_VIEW_OUTPERFORMANCE,
            confidence=DEMO_VIEW_CONFIDENCE,
        )
        for asset_id in banking
    )

    print("\n" + RULE)
    print("STAGE 3a — Safe vs Optimal, no view (historical means)")
    print(RULE)
    unconstrained, safe = optimization.propose_safe_and_optimal(state)
    _candidate("OPTIMAL — unconstrained", unconstrained, universe)
    _candidate("SAFE — constrained", safe, universe)

    print("\n" + RULE)
    print(
        f"STAGE 3b — the same book, after a stated view: banking outperforms "
        f"by {DEMO_VIEW_OUTPERFORMANCE * 100:.0f}%"
    )
    print(f"           (Black-Litterman, confidence {DEMO_VIEW_CONFIDENCE:.0%}, "
          f"assets {', '.join(banking)})")
    print(RULE)
    _, safe_with_view = optimization.propose_safe_and_optimal(state, views=views)
    _candidate("SAFE — constrained, with the view", safe_with_view, universe)

    print("\n  THE MOMENT: the view is a legitimate opinion, and the optimizer")
    print("  acts on it. The control engine — which never saw the view, and")
    print("  re-derives every metric itself — is what refuses the result.")


def _stage_4(optimization, state, universe) -> None:
    """The recovery set. A breaker that only says "stop" is not a control."""
    print("\n" + RULE)
    print("STAGE 4 — recovery candidates offered after a rejection")
    print(RULE)
    for candidate in optimization.generate_recovery_candidates(state):
        _candidate(candidate.role.value, candidate, universe)
    print("\nA recovery that FAILS validation is still listed, with its")
    print("  reasons. Hiding the attempts that did not work would remove the")
    print("  evidence that the control layer is real (EC-5.1).")


def _candidate(label: str, candidate, universe) -> None:
    result = candidate.optimization
    control = candidate.control
    snapshot = control.recomputed if control else None

    print(f"\n  {label}")
    if not result.weights:
        print(f"    no allocation — solver {result.solver_status.value}")
        return
    print(f"    weights     {_fmt(result.weights)}")
    print(f"    sectors     {_fmt(_sectors(result.weights, universe))}")
    if snapshot:
        print(f"    sector risk {_fmt(snapshot.sector_risk_contribution)}")
        print(f"    state       {snapshot.risk_state.value}   "
              f"vol {_pct(snapshot.portfolio_volatility)}   "
              f"CVaR {_pct(snapshot.cvar_95)}")
    print(f"    approvable  {candidate.eligible_for_approval}")

    # RED first, and NEVER truncate a RED away. A candidate reported RED
    # whose listed reasons are all AMBER reads as a bug in front of a judge —
    # the reason for the state must be visible beside the state.
    findings = sorted(
        control.findings if control else (),
        key=lambda b: (b.severity is not RiskState.RED, not b.is_hard),
    )
    shown = [b for b in findings if b.severity is RiskState.RED][:6]
    shown += [b for b in findings if b.severity is not RiskState.RED][
        : max(0, 6 - len(shown))
    ]
    for breach in shown:
        hard = "hard" if breach.is_hard else "soft"
        print(f"      {breach.severity.value:<5} {hard}  {breach.control_code}: "
              f"{breach.message}")
    if len(findings) > len(shown):
        print(f"      … and {len(findings) - len(shown)} more finding(s)")


def _pct(value: float | None) -> str:
    """A missing metric renders as a dash, never as zero (INV-5)."""
    return "—" if value is None else f"{value * 100:.1f}%"


if __name__ == "__main__":
    raise SystemExit(main())

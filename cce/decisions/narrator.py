"""Deterministic prose rendering of a structured Explanation (FR-142).

This is the SHIPPING DEFAULT, not a placeholder for the LLM. The system
produces complete, demo-quality prose with no API key configured and no
network available. The LLM, when present, replaces this text for display
only — it never replaces this function's role as the guaranteed output.

The narrator states nothing the :class:`Explanation` does not contain
(FR-141). Every number it prints comes from the structured object; it derives
no metric of its own.
"""

from __future__ import annotations

from cce.contracts import Explanation, NarratedExplanation, RiskChange

__all__ = [
    "build_narrated_explanation",
    "render_change_interpretation",
    "render_narrative",
]

# How a control verdict reads in a sentence. Keyed by ControlStatus.value.
_VERDICT: dict[str, str] = {
    "PASSED": "The independent control engine accepted this allocation.",
    "FAILED": "The independent control engine rejected this allocation.",
    "NOT_VALIDATED": (
        "The independent control engine could not complete validation, so the "
        "allocation is not approvable."
    ),
}


def _pct(value: float) -> str:
    """Format a decimal fraction as a percentage. 0.0871 -> '8.71%'."""
    return f"{value * 100:.2f}%"


def _describe_change(rc: RiskChange) -> str:
    """One risk metric's movement, with direction named rather than implied."""
    direction = "rose" if rc.delta > 0 else "fell" if rc.delta < 0 else "held at"
    if rc.delta == 0:
        return f"{rc.metric} held at {_pct(rc.to_value)}"
    return (
        f"{rc.metric} {direction} from {_pct(rc.from_value)} to "
        f"{_pct(rc.to_value)} ({rc.delta:+.2%})"
    )


def render_narrative(expl: Explanation) -> str:
    """Render an :class:`Explanation` to prose. Deterministic and total.

    Given the same Explanation this returns the same string, always. It never
    raises on a sparsely populated Explanation: fields that do not apply are
    omitted rather than rendered as empty headings.
    """
    lines: list[str] = []

    # --- what started this -------------------------------------------------
    lines.append(f"**Trigger.** {expl.trigger}")

    # --- what moved --------------------------------------------------------
    if expl.risk_change is not None:
        scope = expl.risk_change.scope
        where = "" if scope == "PORTFOLIO" else f" for {scope}"
        lines.append(
            f"**What changed.** {_describe_change(expl.risk_change).capitalize()}"
            f"{where}."
        )

    if expl.main_contributors:
        contributors = "; ".join(
            f"{rc.scope} — {_describe_change(rc)}" for rc in expl.main_contributors
        )
        lines.append(f"**Main contributors.** {contributors}.")

    # --- what was proposed -------------------------------------------------
    if expl.optimizer is not None:
        lines.append(
            f"**Proposal.** The optimizer ran a {expl.optimizer.value} strategy. "
            "Expected return is a Model Estimate, not a forecast."
        )

    if expl.candidate_summary:
        weights = ", ".join(
            f"{asset} {weight:.1%}"
            for asset, weight in sorted(
                expl.candidate_summary.items(), key=lambda kv: (-kv[1], kv[0])
            )
        )
        lines.append(f"**Proposed allocation.** {weights}.")

    # --- what the control engine said --------------------------------------
    lines.append(
        "**Control verdict.** "
        + _VERDICT.get(
            expl.control_result,
            f"The independent control engine returned {expl.control_result}.",
        )
    )

    if expl.reasons:
        lines.append("**Reasons.**")
        lines.extend(f"- {reason}" for reason in expl.reasons)

    # --- stress ------------------------------------------------------------
    if expl.stress_summary:
        lines.append("**Stress validation.**")
        lines.extend(f"- {item}" for item in expl.stress_summary)

    # --- outcome -----------------------------------------------------------
    lines.append(f"**Action.** {expl.action}")

    if expl.expected_improvement:
        lines.append(f"**Expected improvement.** {expl.expected_improvement}")

    return "\n".join(lines)


def build_narrated_explanation(
    expl: Explanation,
    llm_text: str | None = None,
    llm_model: str | None = None,
    llm_error: str | None = None,
) -> NarratedExplanation:
    """Wrap an Explanation with its deterministic prose.

    ``template_text`` is always populated. If the LLM is unavailable, failed,
    or was never configured, the caller passes ``llm_text=None`` and the
    narrated explanation is still complete (FR-146).
    """
    return NarratedExplanation(
        structured=expl,
        template_text=render_narrative(expl),
        llm_text=llm_text,
        llm_model=llm_model,
        llm_error=llm_error,
    )


#: One sentence per driver. Deterministic, and the only place this
#: interpretation is written — not in the UI, and not by an LLM
#: (docs/09-UI-SPEC.md section 10).
_DRIVER_PROSE: dict[str, str] = {
    "REGIME": (
        "Allocation did not materially change, but market conditions moved "
        "underneath it — the risk shifted without a trade."
    ),
    "ALLOCATION": (
        "The book was traded, and the risk moved with it."
    ),
    "BOTH": (
        "The book was traded AND market conditions moved. Both contributed, "
        "so a rebalance alone will not account for the change."
    ),
    "NONE": "No material change since the previous reading.",
}


def render_change_interpretation(attribution) -> str:
    """Explain a risk move in one paragraph.

    Deterministic, and derived only from the attribution the service
    computed. The UI renders this string; it never assembles the sentence
    itself, so the interpretation cannot drift between two pages that show
    the same numbers.
    """
    lines = [_DRIVER_PROSE.get(attribution.driver.value, _DRIVER_PROSE["NONE"])]

    headline = attribution.headline
    if headline is not None:
        lines.append(
            f"{headline.metric} moved from {_pct(headline.from_value)} to "
            f"{_pct(headline.to_value)} ({headline.delta:+.2%})."
        )

    worst = attribution.contributors[0] if attribution.contributors else None
    if worst is not None:
        lines.append(
            f"The largest shift in risk contribution was {worst.scope}, "
            f"from {_pct(worst.from_value)} to {_pct(worst.to_value)}."
        )

    if attribution.driver.value == "REGIME" and worst is not None:
        lines.append(
            f"{worst.scope}'s share of the book is unchanged; its share of "
            "the RISK is not."
        )
    return " ".join(lines)

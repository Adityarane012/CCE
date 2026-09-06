"""Construction of the structured Explanation (FR-140).

The :class:`~cce.contracts.decision.Explanation` is the SOURCE OF TRUTH for
all narrative output (FR-141). Nothing downstream — neither the deterministic
narrator nor the LLM — may state a fact this object does not contain.

It is built from values the engines already computed. This module derives no
metric of its own; it is a constructor, not a calculation.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from cce.contracts import (
    Breach,
    ControlStatus,
    Explanation,
    RiskChange,
    Strategy,
)

__all__ = ["build_explanation"]


def _clean(text: str | None) -> str | None:
    """Normalise an optional field.

    A field that does not apply is ``None``, never an empty or whitespace
    string (FR-140). An empty string renders as a blank line in the UI and
    reads as "we had nothing to say" rather than "this does not apply".
    """
    if text is None:
        return None
    stripped = text.strip()
    return stripped or None


def build_explanation(
    trigger: str,
    risk_change: RiskChange | None,
    main_contributors: Iterable[RiskChange],
    optimizer: Strategy | None,
    candidate_summary: Mapping[str, float],
    control_status: ControlStatus,
    reasons: Iterable[str],
    stress_summary: Iterable[str],
    action: str,
    expected_improvement: str | None = None,
    main_exceedances: Iterable[Breach] = (),
) -> Explanation:
    """Assemble the structured Explanation. Deterministic.

    Args:
        trigger: What started this decision cycle. Required, non-empty.
        risk_change: The headline metric movement, or ``None`` if this cycle
            was not triggered by one.
        main_contributors: Per-scope MOVEMENTS behind ``risk_change``.
            Never breaches — a threshold is not a previous value.
        main_exceedances: The controls the candidate breached, worst
            first. Carries observed AND threshold so prose can state
            both without implying the metric moved.
        optimizer: The strategy that produced the proposal, or ``None`` if the
            optimizer did not run.
        candidate_summary: ``{asset_id: weight}`` for the proposed allocation.
        control_status: The independent control engine's verdict.
        reasons: Specific rejection or acceptance reasons, each carrying the
            observed value and the threshold (FR-174). Never generic.
        stress_summary: One line per scenario.
        action: What the system did as a result.
        expected_improvement: What the safe alternative buys, if applicable.

    Raises:
        ValueError: If ``trigger`` or ``action`` is empty. Those two fields
            always apply; a blank one means the caller lost information.
    """
    trigger_text = _clean(trigger)
    action_text = _clean(action)
    if trigger_text is None:
        raise ValueError("trigger is required and must not be empty (FR-140)")
    if action_text is None:
        raise ValueError("action is required and must not be empty (FR-140)")

    return Explanation(
        trigger=trigger_text,
        risk_change=risk_change,
        main_contributors=tuple(main_contributors),
        main_exceedances=tuple(main_exceedances),
        optimizer=optimizer,
        candidate_summary=dict(candidate_summary),
        control_result=control_status.value,
        reasons=tuple(r for r in (_clean(x) for x in reasons) if r is not None),
        stress_summary=tuple(
            s for s in (_clean(x) for x in stress_summary) if s is not None
        ),
        action=action_text,
        expected_improvement=_clean(expected_improvement),
    )

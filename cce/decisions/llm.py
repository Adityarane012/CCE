"""Optional LLM narration. Display text only.

Spec: docs/12-SECURITY.md section 3, docs/10-RULES.md INV-1,
docs/03-TRD.md FR-143..FR-146.

    Deterministic engine -> structured Explanation -> LLM -> display text
                                   ▲                              │
                                   └────── NO PATH BACK ──────────┘

The containment is ARCHITECTURAL, not prompt-based. It holds because this
module returns ``str`` and nothing downstream can turn a string into a weight,
a threshold, an approval or a state — not because the prompt asked the model
nicely. Specifically:

- :func:`narrate` returns a :class:`NarratedExplanation` whose ``structured``
  field is the caller's own object, passed through untouched.
- The model's text is never ``json.loads``-ed, never ``eval``-ed, never
  dispatched on. It is stored in ``explanations.llm_text`` and rendered.
- The prompt contains ONLY the structured Explanation. No market data, no
  file paths, no environment values, no database contents — smaller input is
  both cheaper and a smaller disclosure surface.

Every failure path serves the deterministic narrator. The system works fully
with no API key, and ``CCE_LLM_ENABLED=false`` is a valid shipping
configuration (FR-146).
"""

from __future__ import annotations

import logging
import re
import unicodedata

from cce.config import get_settings
from cce.contracts import Explanation, NarratedExplanation

from .narrator import render_narrative

logger = logging.getLogger(__name__)

__all__ = ["MAX_DISPLAY_CHARS", "MODEL", "narrate", "sanitize_for_display"]

#: Pinned deliberately. A model id is a reproducibility input like any other,
#: and "whatever is newest" is not a version.
MODEL = "claude-opus-5"

#: Prose, not an essay. The structured Explanation is the record; this is a
#: readable gloss on it.
MAX_TOKENS = 700

#: Hard ceiling on what reaches the screen. A model that returns a megabyte
#: should not be able to make the page unusable.
MAX_DISPLAY_CHARS = 4000

_SYSTEM = (
    "You write short, factual briefings for an institutional risk manager.\n"
    "\n"
    "You are given a structured record of a decision that has ALREADY been "
    "made by a deterministic control system. Your only job is to restate it "
    "in clear prose.\n"
    "\n"
    "Rules:\n"
    "- State only what the record contains. Add no numbers, no conclusions, "
    "and no recommendations of your own.\n"
    "- Never suggest a different allocation, threshold or action.\n"
    "- Describe expected returns as model estimates, never as forecasts.\n"
    "- Do not say the portfolio is safe. Say which controls passed.\n"
    "- Plain paragraphs. No markdown, no headings, no bullet lists.\n"
    "- At most 180 words."
)


def _enabled() -> bool:
    settings = get_settings()
    return bool(settings.llm_enabled and settings.llm_api_key)


def sanitize_for_display(text: str) -> str:
    """Make model output safe to render as plain text.

    Strips markup, removes control characters, collapses whitespace and caps
    the length. This is defence in depth: the UI already renders with
    ``unsafe_allow_html=False``, so markup would be shown rather than
    executed. Removing it anyway means a model that emits a ``<script>`` tag
    produces tidy prose rather than visible noise in a demo.
    """
    if not text:
        return ""

    text = re.sub(r"<[^>]{0,200}>", "", text)          # tags, bounded
    text = re.sub(r"[*_`#>]+", "", text)               # markdown emphasis
    text = "".join(
        ch for ch in text
        if ch in "\n\t" or unicodedata.category(ch)[0] != "C"
    )
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if len(text) > MAX_DISPLAY_CHARS:
        text = text[:MAX_DISPLAY_CHARS].rstrip() + "…"
    return text


def _prompt(explanation: Explanation) -> str:
    """The structured record, and nothing else.

    Built field by field rather than by serialising the object, so a field
    added to ``Explanation`` later cannot silently start being transmitted.
    """
    lines = [
        f"Trigger: {explanation.trigger}",
        f"Optimizer: {explanation.optimizer.value if explanation.optimizer else 'none'}",
        f"Control result: {explanation.control_result}",
        f"Action taken: {explanation.action}",
    ]
    if explanation.risk_change is not None:
        rc = explanation.risk_change
        lines.append(
            f"Risk change: {rc.metric} {rc.from_value:.4f} -> {rc.to_value:.4f} "
            f"(scope {rc.scope})"
        )
    for breach in explanation.main_exceedances:
        lines.append(
            f"Limit crossed: {breach.scope} {breach.control_label} "
            f"observed {breach.observed:.4f} against a {breach.threshold:.4f} "
            f"limit (this is a LIMIT, not a previous value)"
        )
    for contributor in explanation.main_contributors:
        lines.append(
            f"Contributor: {contributor.scope} {contributor.metric} "
            f"{contributor.from_value:.4f} -> {contributor.to_value:.4f}"
        )
    if explanation.candidate_summary:
        weights = ", ".join(
            f"{a} {w:.3f}" for a, w in sorted(explanation.candidate_summary.items())
        )
        lines.append(f"Proposed weights: {weights}")
    lines.extend(f"Reason: {r}" for r in explanation.reasons)
    lines.extend(f"Stress: {s}" for s in explanation.stress_summary)
    if explanation.expected_improvement:
        lines.append(f"Expected improvement: {explanation.expected_improvement}")
    return "\n".join(lines)


def narrate(explanation: Explanation) -> NarratedExplanation:
    """Render the explanation, using the LLM when one is configured.

    Always returns a complete :class:`NarratedExplanation`. The deterministic
    ``template_text`` is produced first and unconditionally, so no failure in
    here can leave a decision unexplained — the loop is never blocked by the
    narration layer (FR-146).
    """
    template = render_narrative(explanation)

    if not _enabled():
        return NarratedExplanation(structured=explanation, template_text=template)

    try:
        import anthropic

        client = anthropic.Anthropic(api_key=get_settings().llm_api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            output_config={"effort": "low"},
            system=_SYSTEM,
            messages=[{"role": "user", "content": _prompt(explanation)}],
        )

        if response.stop_reason == "refusal":
            return NarratedExplanation(
                structured=explanation, template_text=template,
                llm_error="model declined to narrate this record",
            )

        text = sanitize_for_display(
            "".join(b.text for b in response.content if b.type == "text")
        )
        if not text:
            return NarratedExplanation(
                structured=explanation, template_text=template,
                llm_error="model returned no usable text",
            )
        return NarratedExplanation(
            structured=explanation, template_text=template,
            llm_text=text, llm_model=MODEL,
        )

    except Exception as exc:  # noqa: BLE001 - narration must never break the loop
        # Deliberately broad. A narration failure is cosmetic; a decision
        # cycle that dies because prose could not be generated is not.
        logger.warning("LLM narration failed (%s); serving the deterministic "
                       "narrator", type(exc).__name__)
        return NarratedExplanation(
            structured=explanation, template_text=template,
            llm_error=f"{type(exc).__name__}: {exc}"[:500],
        )

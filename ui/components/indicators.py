"""Risk-state chips and data-quality markers.

Spec: docs/09-UI-SPEC.md sections 2.1 and 2.2.

**Colour is never the only channel** (FR-176). Every state indicator carries a
text label. That is an accessibility requirement and also a projector
requirement: demo-room colour reproduction is unreliable, and a judge who
cannot tell your amber from your red cannot follow the story.
"""

from __future__ import annotations

import streamlit as st

from cce.contracts import ControlStatus, RiskState, StressStatus

from .format import DASH, MODEL_ESTIMATE

__all__ = [
    "cached_fallback_banner",
    "control_label",
    "degraded_marker",
    "model_estimate",
    "state_chip",
    "state_colour",
    "state_label",
    "stress_label",
]

_PALETTE: dict[str, str] = {
    "GREEN": "#1B873F",
    "AMBER": "#B7791F",
    "RED": "#C53030",
    "NEUTRAL": "#6B7280",
}

_LABEL: dict[str, str] = {
    "GREEN": "GREEN — Within policy",
    "AMBER": "AMBER — Approaching limit",
    "RED": "RED — Policy breach",
}


def state_colour(state: RiskState | None) -> str:
    return _PALETTE["NEUTRAL"] if state is None else _PALETTE[state.value]


def state_label(state: RiskState | None) -> str:
    """The full text label. Always shown next to the colour."""
    return DASH if state is None else _LABEL[state.value]


def state_chip(state: RiskState | None, *, compact: bool = False) -> str:
    """An inline state indicator: filled circle PLUS its text label."""
    if state is None:
        return f"<span style='color:{_PALETTE['NEUTRAL']}'>● {DASH}</span>"
    text = state.value if compact else _LABEL[state.value]
    return (
        f"<span style='color:{state_colour(state)};font-weight:600'>"
        f"● {text}</span>"
    )


def control_label(status: ControlStatus | None) -> str:
    """A control verdict in words a risk manager uses.

    NOT_VALIDATED is spelled out rather than shortened: "could not be
    evaluated" and "failed" call for different responses, and the difference
    disappears if both render as a red dot.
    """
    if status is None:
        return f"● {DASH} Not validated"
    return {
        ControlStatus.PASSED: "● PASSED — within every hard control",
        ControlStatus.FAILED: "● REJECTED — hard control breached",
        ControlStatus.NOT_VALIDATED: (
            "● NOT VALIDATED — a hard control could not be evaluated"
        ),
    }[status]


def stress_label(status: StressStatus | None) -> str:
    """A stress verdict. NOT_RUN and ERROR never read as survival."""
    if status is None:
        return f"● {DASH}"
    return {
        StressStatus.PASSED: "● PASSED — survived every scenario",
        StressStatus.FAILED: "● FAILED — a scenario breached the loss limit",
        StressStatus.NOT_RUN: "● NOT RUN — no scenario was applied",
        StressStatus.ERROR: "● ERROR — the suite could not complete",
    }[status]


def model_estimate(caption: str = "") -> None:
    """The mandatory label beside a forward-looking return (FR-062)."""
    st.caption(f"*{MODEL_ESTIMATE}*{f' — {caption}' if caption else ''}")


def degraded_marker(reason: str | None) -> None:
    """Shown wherever a figure was computed on incomplete data."""
    if reason:
        st.caption(f":orange[⚠ Degraded — {reason}]")


def cached_fallback_banner(provider_value: str) -> None:
    """Persistent banner when live retrieval failed (docs/09 section 2.2).

    CACHED_FALLBACK only. A deliberately frozen demo snapshot is CACHED and
    is stale by construction; warning about it every render would train the
    presenter to ignore the banner that matters.
    """
    if provider_value == "CACHED_FALLBACK":
        st.warning(
            "Using cached market data — live retrieval unavailable. "
            "Figures are computed on the last good panel.",
            icon="⚠",
        )

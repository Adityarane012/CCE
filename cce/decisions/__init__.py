"""Explanation, narration and decision replay.

The structured :class:`~cce.contracts.decision.Explanation` is the SOURCE OF
TRUTH for all narrative output (FR-141). The narrator renders it with
deterministic templates and is the SHIPPING DEFAULT, not a placeholder for the
LLM (FR-142) — the system produces complete, demo-quality prose with no API
key configured.

Replay reconstructs a timeline from persisted events ONLY. It never recomputes
(INV-6), and it reads through the audit repository rather than touching the
database itself.
"""

from __future__ import annotations

from .explanation import build_explanation
from .llm import narrate, sanitize_for_display
from .narrator import build_narrated_explanation, render_narrative
from .replay import TimelineRow, reconstruct_timeline

__all__ = [
    "TimelineRow",
    "build_explanation",
    "build_narrated_explanation",
    "narrate",
    "reconstruct_timeline",
    "render_narrative",
    "sanitize_for_display",
]

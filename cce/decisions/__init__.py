"""Explanation, narration and decision replay.

The structured :class:`~cce.contracts.decision.Explanation` is the SOURCE OF
TRUTH for all narrative output (FR-141). The narrator renders it with
deterministic templates and is the SHIPPING DEFAULT, not a placeholder for the
LLM (FR-142) — the system produces complete, demo-quality prose with no API
key configured.

Replay reconstructs a timeline from persisted events ONLY. It never recomputes
(INV-6).
"""

from __future__ import annotations

from .explanation import build_explanation
from .narrator import build_narrated_explanation, render_narrative
from .replay import reconstruct_timeline

__all__ = [
    "build_explanation",
    "build_narrated_explanation",
    "reconstruct_timeline",
    "render_narrative",
]

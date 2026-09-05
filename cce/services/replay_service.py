"""Decision history and replay.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/09-UI-SPEC.md.

Read-only. Everything returned was persisted; nothing is recomputed (INV-6).
"""

from __future__ import annotations

from cce.audit import DecisionSummary, StoredDecision
from cce.decisions import TimelineRow, reconstruct_timeline

from .context import ServiceContext

__all__ = ["ReplayService"]


class ReplayService:
    """The audit trail, as the UI reads it."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx

    def list_decisions(
        self, limit: int = 50, offset: int = 0
    ) -> tuple[DecisionSummary, ...]:
        """Decision history, newest first."""
        return tuple(self._ctx.repo.list_decisions(limit, offset))

    def get_decision(self, decision_id: int) -> StoredDecision:
        """One complete decision, exactly as stored."""
        return self._ctx.repo.get_decision(decision_id)

    def get_timeline(self, decision_id: int) -> tuple[TimelineRow, ...]:
        """The replay timeline, tagged MACHINE / CONTROL / HUMAN.

        An empty result means no events were recorded — not that nothing
        happened. Nothing here invents a plausible timeline to fill the gap.
        """
        return reconstruct_timeline(self._ctx.repo, decision_id)

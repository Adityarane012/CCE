"""Decision replay.

Spec: docs/04-WORKFLOW.md, docs/09-UI-SPEC.md.

Replay reconstructs what happened from persisted ``decision_events`` and
NOTHING else. It never recomputes a metric, re-runs a control, or infers a
step that was not recorded (INV-6). A recomputed timeline would show what the
system would decide *now*, which is precisely the question replay does not
ask — and it would quietly diverge the moment a threshold changed.

Rows are ordered by ``sequence_no``, never by wall clock: two events written
in the same millisecond must still replay in the order they occurred.

Every row is tagged MACHINE, CONTROL or HUMAN. That three-way distinction —
the system computed, the control engine judged, a person decided — is the
entire point of the page.
"""

from __future__ import annotations

from dataclasses import dataclass

from cce.audit.repository import AuditRepository
from cce.contracts import Actor, DecisionEvent

__all__ = ["TimelineRow", "reconstruct_timeline"]

#: Display label per actor. The control engine is called out by name because
#: "the system rejected it" and "the independent control engine rejected it"
#: are different claims, and only the second one is CCE's.
_ACTOR_LABEL: dict[Actor, str] = {
    Actor.MACHINE: "System",
    Actor.CONTROL: "Control engine",
    Actor.HUMAN: "Risk manager",
}


@dataclass(frozen=True)
class TimelineRow:
    """One display-ready row of the replay timeline."""

    event: DecisionEvent

    @property
    def sequence_no(self) -> int:
        return self.event.sequence_no

    @property
    def actor(self) -> Actor:
        return self.event.actor

    @property
    def actor_label(self) -> str:
        return _ACTOR_LABEL[self.event.actor]

    @property
    def event_code(self) -> str:
        return self.event.event_code

    @property
    def summary(self) -> str:
        return self.event.summary

    @property
    def detail(self) -> dict | None:
        return self.event.detail

    @property
    def timestamp_text(self) -> str:
        """Second precision. Sub-second noise is not information here."""
        return self.event.occurred_at.strftime("%Y-%m-%d %H:%M:%S")


def reconstruct_timeline(
    repo: AuditRepository, decision_id: int
) -> tuple[TimelineRow, ...]:
    """Rebuild one decision's timeline from persistence only.

    Args:
        repo: The audit repository. Replay reads through it rather than
            opening its own connection — ``cce/audit/`` is the only database
            access in the system (docs/02-ARCHITECTURE.md section 2).
        decision_id: The decision to replay.

    Returns:
        Rows in ``sequence_no`` order. An EMPTY tuple means no events were
        recorded for this decision. It does not mean nothing happened, and
        nothing here fabricates a plausible timeline to fill the gap — on
        failure the system does less, never something different (Rule 2).
    """
    return tuple(
        TimelineRow(event) for event in repo.get_replay_timeline(decision_id)
    )

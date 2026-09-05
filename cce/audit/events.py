"""The decision-replay event vocabulary.

Spec: docs/05-BACKEND-SCHEMA.md section 3 (``decision_events``),
docs/04-WORKFLOW.md.

Replay reconstructs a decision from these rows and nothing else (INV-6). It
never recomputes, so whatever is not written here is not recoverable later —
an event that was never recorded did not happen as far as the audit trail is
concerned.

``actor`` is the point of the timeline. MACHINE computed something, CONTROL
judged it, HUMAN decided. Collapsing that three-way distinction would turn
the replay page into a log.
"""

from __future__ import annotations

from datetime import datetime

from cce.contracts import Actor, DecisionEvent

__all__ = [
    "EVENT_ACTORS",
    "EVENT_BREAKER_TRIPPED",
    "EVENT_CANDIDATE_PROPOSED",
    "EVENT_CONTROL_REJECTED",
    "EVENT_CONTROL_VALIDATED",
    "EVENT_DATA_VALIDATED",
    "EVENT_EXPLANATION_BUILT",
    "EVENT_HUMAN_ACTION",
    "EVENT_RECOVERY_GENERATED",
    "EVENT_RISK_COMPUTED",
    "EVENT_SAFE_ALLOCATION_PROMOTED",
    "EVENT_SAFE_ALLOCATION_RETAINED",
    "EVENT_SHOCK_DETECTED",
    "EVENT_STRESS_COMPLETED",
    "EVENT_TRIGGER_RECEIVED",
    "make_event",
]

# --- MACHINE: the system computed something --------------------------------
EVENT_TRIGGER_RECEIVED = "TRIGGER_RECEIVED"
EVENT_DATA_VALIDATED = "DATA_VALIDATED"
EVENT_SHOCK_DETECTED = "SHOCK_DETECTED"
EVENT_RISK_COMPUTED = "RISK_COMPUTED"
EVENT_CANDIDATE_PROPOSED = "CANDIDATE_PROPOSED"
EVENT_RECOVERY_GENERATED = "RECOVERY_GENERATED"
EVENT_EXPLANATION_BUILT = "EXPLANATION_BUILT"

# --- CONTROL: the independent control engine judged ------------------------
EVENT_CONTROL_VALIDATED = "CONTROL_VALIDATED"
EVENT_CONTROL_REJECTED = "CONTROL_REJECTED"
EVENT_BREAKER_TRIPPED = "BREAKER_TRIPPED"
EVENT_STRESS_COMPLETED = "STRESS_COMPLETED"
EVENT_SAFE_ALLOCATION_RETAINED = "SAFE_ALLOCATION_RETAINED"

# --- HUMAN: a person decided -----------------------------------------------
EVENT_HUMAN_ACTION = "HUMAN_ACTION"
EVENT_SAFE_ALLOCATION_PROMOTED = "SAFE_ALLOCATION_PROMOTED"

#: The actor each known event code belongs to.
#:
#: Held here rather than passed in at every call site so a control judgement
#: cannot be recorded as a machine step by a caller in a hurry — that would
#: quietly misattribute the safety decision the replay page exists to show.
EVENT_ACTORS: dict[str, Actor] = {
    EVENT_TRIGGER_RECEIVED: Actor.MACHINE,
    EVENT_DATA_VALIDATED: Actor.MACHINE,
    EVENT_SHOCK_DETECTED: Actor.MACHINE,
    EVENT_RISK_COMPUTED: Actor.MACHINE,
    EVENT_CANDIDATE_PROPOSED: Actor.MACHINE,
    EVENT_RECOVERY_GENERATED: Actor.MACHINE,
    EVENT_EXPLANATION_BUILT: Actor.MACHINE,
    EVENT_CONTROL_VALIDATED: Actor.CONTROL,
    EVENT_CONTROL_REJECTED: Actor.CONTROL,
    EVENT_BREAKER_TRIPPED: Actor.CONTROL,
    EVENT_STRESS_COMPLETED: Actor.CONTROL,
    EVENT_SAFE_ALLOCATION_RETAINED: Actor.CONTROL,
    EVENT_HUMAN_ACTION: Actor.HUMAN,
    EVENT_SAFE_ALLOCATION_PROMOTED: Actor.HUMAN,
}


def make_event(
    sequence_no: int,
    event_code: str,
    summary: str,
    occurred_at: datetime | None = None,
    detail: dict | None = None,
    actor: Actor | None = None,
) -> DecisionEvent:
    """Build one timeline row, with the actor derived from the event code.

    Args:
        sequence_no: Position within this decision. Unique per decision.
        event_code: One of the ``EVENT_*`` constants above.
        summary: One line, display-ready. This is what the replay page shows.
        occurred_at: When it happened. Defaults to now, timezone-aware.
        detail: Structured extras, stored as JSON.
        actor: Override the derived actor. Required for a code not in
            :data:`EVENT_ACTORS`.

    Raises:
        ValueError: If the event code is unknown and no actor was given.
            Guessing an actor is worse than refusing: a control judgement
            filed as a machine step misrepresents who made the call.
    """
    resolved = actor or EVENT_ACTORS.get(event_code)
    if resolved is None:
        raise ValueError(
            f"unknown event_code {event_code!r}; pass an explicit actor or add "
            "it to EVENT_ACTORS"
        )
    return DecisionEvent(
        sequence_no=sequence_no,
        occurred_at=occurred_at or datetime.now().astimezone(),
        actor=resolved,
        event_code=event_code,
        summary=summary,
        detail=detail,
    )

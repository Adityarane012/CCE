"""Append-only decision store.

Spec: docs/05-BACKEND-SCHEMA.md.

This package is the ONLY database access in CCE (docs/02-ARCHITECTURE.md
section 2). No other module opens a connection, and no other module writes
SQL. Everything else goes through :class:`AuditRepository`, and
``tests/test_architecture.py`` enforces that rather than trusting it.

There is deliberately no ``update_decision``, no ``delete_decision`` and no
``execute_sql``. The single permitted mutation is
:meth:`AuditRepository.close_decision_with_human_action`, guarded so a second
write cannot succeed (INV-6).
"""

from __future__ import annotations

from cce.exceptions import AuditWriteError, DecisionAlreadyClosed

from .database import default_db_path, get_connection, run_migrations, transaction
from .events import (
    EVENT_ACTORS,
    EVENT_BREAKER_TRIPPED,
    EVENT_CANDIDATE_PROPOSED,
    EVENT_CONTROL_REJECTED,
    EVENT_CONTROL_VALIDATED,
    EVENT_DATA_VALIDATED,
    EVENT_EXPLANATION_BUILT,
    EVENT_HUMAN_ACTION,
    EVENT_RECOVERY_GENERATED,
    EVENT_RISK_COMPUTED,
    EVENT_SAFE_ALLOCATION_PROMOTED,
    EVENT_SAFE_ALLOCATION_RETAINED,
    EVENT_SHOCK_DETECTED,
    EVENT_STRESS_COMPLETED,
    EVENT_TRIGGER_RECEIVED,
    make_event,
)
from .models import (
    DecisionContext,
    DecisionSummary,
    MarketSnapshotMeta,
    PolicyChangeMeta,
    StoredCandidate,
    StoredDecision,
    StoredHumanAction,
    StoredStressResult,
)
from .repository import AuditRepository

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
    "AuditRepository",
    "AuditWriteError",
    "DecisionAlreadyClosed",
    "DecisionContext",
    "DecisionSummary",
    "MarketSnapshotMeta",
    "PolicyChangeMeta",
    "StoredCandidate",
    "StoredDecision",
    "StoredHumanAction",
    "StoredStressResult",
    "default_db_path",
    "get_connection",
    "make_event",
    "run_migrations",
    "transaction",
]

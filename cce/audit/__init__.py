"""Append-only decision store.

Spec: docs/05-BACKEND-SCHEMA.md.

This package is the ONLY database access in CCE (docs/02-ARCHITECTURE.md
section 2). No other module opens a connection, and no other module writes
SQL. Everything else goes through :class:`AuditRepository`.

There is deliberately no ``update_decision``, no ``delete_decision`` and no
``execute_sql``. The single sanctioned mutation is
:meth:`AuditRepository.close_decision_with_human_action`, guarded so a second
write cannot succeed (INV-6).
"""

from __future__ import annotations

from .database import default_db_path, get_connection, run_migrations, transaction
from .repository import (
    AuditRepository,
    AuditWriteError,
    DecisionContext,
    MarketSnapshotMeta,
    PolicyChangeMeta,
)

__all__ = [
    "AuditRepository",
    "AuditWriteError",
    "DecisionContext",
    "MarketSnapshotMeta",
    "PolicyChangeMeta",
    "default_db_path",
    "get_connection",
    "run_migrations",
    "transaction",
]

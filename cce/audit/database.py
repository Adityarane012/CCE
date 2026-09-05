"""Connection handling and schema migration.

Spec: docs/05-BACKEND-SCHEMA.md sections 2 and 8.

Transactions are EXPLICIT. The connection is opened in autocommit mode
(``isolation_level=None``) and every write goes through :func:`transaction`.

That is not a stylistic preference. Python's sqlite3 module does not open an
implicit transaction for DDL, so a ``CREATE TABLE`` issued under the default
isolation level commits immediately — a migration that fails half way would
leave a partially built schema with no ``schema_migrations`` row and no way
back. Explicit ``BEGIN``/``COMMIT`` puts DDL inside the transaction where it
belongs (NFR-015: the database must be recreatable from scripts).
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path

from cce.config import get_settings

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

__all__ = [
    "MIGRATIONS_DIR",
    "default_db_path",
    "get_connection",
    "run_migrations",
    "transaction",
]


def default_db_path() -> Path:
    """The configured database path.

    Resolved lazily rather than bound at import time: a module-level constant
    would freeze whatever the working directory happened to be, and tests
    point ``CCE_DB_PATH`` at a temporary file.
    """
    return get_settings().db_path


def get_connection(db_path: Path | str | None = None) -> sqlite3.Connection:
    """Open a configured connection.

    ``isolation_level=None`` means autocommit: nothing is held open implicitly
    and every transaction is started explicitly by :func:`transaction`.
    """
    path = Path(db_path) if db_path is not None else default_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    # check_same_thread=False because Streamlit runs every script rerun on a
    # NEW thread while the connection is cached across reruns. Without it the
    # second interaction raises "SQLite objects created in a thread can only be
    # used in that same thread" — the app dies on the first click.
    #
    # Safe here only because every write goes through transaction(), which
    # serialises on a per-connection lock. Cross-thread use of a sqlite3
    # connection is unsafe when concurrent, not when serialised.
    conn = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    conn.row_factory = sqlite3.Row

    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


#: Nesting depth per connection. A repository method opens a transaction of
#: its own, but the service layer must compose several of those into ONE
#: all-or-nothing unit — INV-6 requires a state change and its audit record to
#: commit together, and EC-7.3 requires a failure mid-approval to leave the
#: portfolio unchanged. Without re-entrancy the inner ``BEGIN`` raises
#: "cannot start a transaction within a transaction".
_DEPTH: dict[int, int] = {}

#: One re-entrant lock per connection, guarding both the transaction and the
#: depth counter above. Connections are opened with check_same_thread=False so
#: the Streamlit UI can reuse one across reruns; this is what makes that safe,
#: by serialising the writes rather than merely permitting them.
#:
#: RLock, not Lock: transaction() is re-entrant by design, and a plain lock
#: would deadlock the moment a service composed two repository writes.
_LOCKS: dict[int, threading.RLock] = {}
_LOCKS_GUARD = threading.Lock()


def _lock_for(conn: sqlite3.Connection) -> threading.RLock:
    key = id(conn)
    with _LOCKS_GUARD:
        lock = _LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _LOCKS[key] = lock
        return lock


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a block inside one all-or-nothing transaction. Re-entrant.

    ``BEGIN IMMEDIATE`` takes the write lock up front so two concurrent
    writers fail fast rather than one discovering the conflict at COMMIT.

    Nested uses JOIN the outermost transaction rather than starting their
    own, and only the outermost commits. That is deliberate rather than
    convenient: SAVEPOINTs would let an inner block roll back while the outer
    one commits, which is exactly the partial write — a portfolio updated
    without its audit record — that must never happen.
    """
    key = id(conn)
    with _lock_for(conn):
        depth = _DEPTH.get(key, 0)

        if depth:                   # already inside one; join it
            _DEPTH[key] = depth + 1
            try:
                yield conn
            finally:
                _DEPTH[key] = depth
            return

        conn.execute("BEGIN IMMEDIATE;")
        _DEPTH[key] = 1
        try:
            yield conn
        except BaseException:
            _DEPTH[key] = 0
            conn.execute("ROLLBACK;")
            raise
        _DEPTH[key] = 0
        conn.execute("COMMIT;")


def _applied_migrations(conn: sqlite3.Connection) -> set[int]:
    """Versions already applied. Empty before migration 001 has ever run."""
    try:
        rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    except sqlite3.OperationalError:
        return set()  # schema_migrations is created by 001
    return {int(r["version"]) for r in rows}


def _split_statements(sql: str) -> list[str]:
    """Split a script into complete SQL statements.

    ``sqlite3.complete_statement`` is used rather than splitting on ``;``
    because it understands string literals and comments — the seeded policy
    JSON is one long quoted string and must not be cut in half.

    Splitting is necessary at all because ``executescript`` issues an implicit
    COMMIT before it runs, which would break out of the surrounding
    transaction and defeat the atomicity this module exists to provide.
    """
    statements: list[str] = []
    buf = ""
    for line in sql.splitlines(keepends=True):
        buf += line
        if sqlite3.complete_statement(buf):
            stmt = buf.strip()
            if stmt:
                statements.append(stmt)
            buf = ""
    if buf.strip():
        raise ValueError(f"migration ends with an incomplete statement: {buf.strip()[:80]!r}")
    return statements


def _migration_files() -> list[Path]:
    """Migration scripts in version order."""
    return sorted(
        f
        for f in MIGRATIONS_DIR.iterdir()
        if f.is_file() and f.suffix == ".sql" and f.name[0].isdigit()
    )


def run_migrations(db_path: Path | str | None = None) -> list[int]:
    """Apply every pending migration, each in its own transaction.

    Returns the versions applied by this call (empty when already current).
    A failure rolls the offending migration back whole and re-raises: a
    half-applied schema is never left behind, and never recorded as applied.
    """
    applied_now: list[int] = []

    with closing(get_connection(db_path)) as conn:
        already = _applied_migrations(conn)

        for fpath in _migration_files():
            version = int(fpath.name.split("_")[0])
            if version in already:
                continue

            sql = fpath.read_text(encoding="utf-8")
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            logger.info("applying migration %s", fpath.name)

            try:
                with transaction(conn):
                    for stmt in _split_statements(sql):
                        conn.execute(stmt)
                    conn.execute(
                        "INSERT INTO schema_migrations (version, applied_at, checksum) "
                        "VALUES (?, datetime('now'), ?)",
                        (version, checksum),
                    )
            except Exception:
                logger.exception("migration %s failed and was rolled back", fpath.name)
                raise

            applied_now.append(version)
            logger.info("applied migration %d", version)

    return applied_now

import hashlib
import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path("data/cce.db")
MIGRATIONS_DIR = Path(__file__).parent / "migrations"


def get_connection(db_path: Path | str = DB_PATH) -> sqlite3.Connection:
    """Returns an open, configured connection to the SQLite database."""
    conn = sqlite3.connect(db_path)
    
    # Enable dict-like access
    conn.row_factory = sqlite3.Row
    
    # Required pragmas
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    
    return conn


def _get_applied_migrations(conn: sqlite3.Connection) -> set[int]:
    try:
        cur = conn.execute("SELECT version FROM schema_migrations")
        return {row["version"] for row in cur.fetchall()}
    except sqlite3.OperationalError:
        return set()


def run_migrations(db_path: Path | str = DB_PATH) -> None:
    """Applies all pending migrations in order."""
    if isinstance(db_path, str):
        db_path = Path(db_path)
        
    db_path.parent.mkdir(parents=True, exist_ok=True)
    
    with get_connection(db_path) as conn:
        applied = _get_applied_migrations(conn)
        
        migration_files = sorted([
            f for f in MIGRATIONS_DIR.iterdir()
            if f.is_file() and f.suffix == ".sql" and f.name[0].isdigit()
        ])
        
        for fpath in migration_files:
            version_str = fpath.name.split("_")[0]
            try:
                version = int(version_str)
            except ValueError:
                continue
                
            if version in applied:
                continue
                
            logger.info("Applying migration %s", fpath.name)
            
            with open(fpath, encoding="utf-8") as f:
                sql = f.read()
                
            checksum = hashlib.sha256(sql.encode("utf-8")).hexdigest()
            
            try:
                conn.execute("BEGIN EXCLUSIVE TRANSACTION;")
                conn.executescript(sql)
                
                # Check if schema_migrations exists, if not, wait. Wait, 001 creates it.
                conn.execute(
                    "INSERT INTO schema_migrations (version, applied_at, checksum) VALUES (?, datetime('now'), ?)",
                    (version, checksum)
                )
                conn.commit()
                logger.info("Successfully applied migration %d", version)
            except Exception as e:
                conn.rollback()
                logger.error("Failed to apply migration %s: %s", fpath.name, e)
                raise


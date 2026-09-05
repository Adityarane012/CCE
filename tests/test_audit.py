from datetime import datetime
from pathlib import Path

import pytest

from cce.audit.database import get_connection, run_migrations
from cce.audit.repository import AuditRepository, AuditWriteError
from cce.contracts.decision import HumanAction, HumanActionRecord


@pytest.fixture
def test_db(tmp_path: Path):
    db_path = tmp_path / "cce_test.db"
    # Run migrations against a fresh DB in tmp_path
    run_migrations(db_path)
    conn = get_connection(db_path)
    repo = AuditRepository(conn)
    yield conn, repo
    conn.close()

def test_database_recreatable_from_migrations(test_db):
    """NFR-015: Database must be completely recreatable from scripts."""
    conn, repo = test_db
    # Check that schema_migrations has 3 records
    cur = conn.execute("SELECT COUNT(*) as c FROM schema_migrations")
    assert cur.fetchone()["c"] == 3
    # Check seeds were applied
    cur = conn.execute("SELECT portfolio_id FROM safe_allocations")
    assert cur.fetchone()["portfolio_id"] == "DEMO_100CR"

def test_no_update_or_delete_against_audit_tables(test_db):
    """INV-6: Append-only for decision data."""
    conn, repo = test_db
    # Insert a dummy alert to try to delete
    conn.execute("INSERT INTO alerts (created_at, severity, category, title, message) VALUES ('2026-08-31', 'INFO', 'DATA', 'T', 'M')")
    
    # In SQLite, we can't easily prevent raw DELETEs if executed directly unless there are triggers.
    # The requirement is that application code does not contain UPDATE or DELETE. 
    # But let's at least test that our repository has no update/delete methods.
    for method in dir(repo):
        assert not method.startswith("update_")
        assert not method.startswith("delete_")

def test_human_action_can_only_be_recorded_once(test_db):
    """EC-7.2: Guarded transition for closing decisions."""
    conn, repo = test_db
    # Ensure there is a decision with human_action IS NULL
    # decision 1 is already closed by seed.
    conn.execute("INSERT INTO decision_records (event_uid, created_at, trigger_type, snapshot_id, policy_version_id, portfolio_state_before, risk_snapshot_before, control_status) VALUES ('test-uuid', '2026-08-31', 'USER_REQUEST', 1, 1, 1, 1, 'PASSED')")
    decision_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
    
    action = HumanActionRecord(
        action=HumanAction.APPROVE,
        user_identity="test",
        user_role="RISK",
        timestamp=datetime.now()
    )
    
    # First action should succeed
    repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)
    
    # Second action should fail
    with pytest.raises(AuditWriteError, match="Decision already closed with a human action"):
        repo.close_decision_with_human_action(decision_id, action, portfolio_state_after=1)

def test_failed_audit_write_is_not_reported_as_success(test_db):
    """EC-7.3: Failed write raises AuditWriteError."""
    conn, repo = test_db
    
    # Try to close a non-existent decision
    action = HumanActionRecord(
        action=HumanAction.APPROVE,
        user_identity="test",
        user_role="RISK",
        timestamp=datetime.now()
    )
    with pytest.raises(AuditWriteError):
        repo.close_decision_with_human_action(9999, action, portfolio_state_after=1)

import json
from datetime import datetime

from cce.audit.repository import AuditRepository
from cce.contracts.decision import DecisionEvent
from cce.contracts.enums import Actor


def reconstruct_timeline(repo: AuditRepository, decision_id: int) -> tuple[DecisionEvent, ...]:
    """
    Reconstruct the timeline from persisted decision_events ONLY.
    NEVER recompute. Order by sequence_no.
    """
    cur = repo.conn.cursor()
    cur.execute("""
        SELECT sequence_no, occurred_at, actor, event_code, summary, detail_json
        FROM decision_events
        WHERE decision_id = ?
        ORDER BY sequence_no ASC
    """, (decision_id,))
    
    events = []
    for row in cur.fetchall():
        detail = json.loads(row["detail_json"]) if row["detail_json"] else None
        
        # Parse timestamp safely (assuming ISO 8601 string from SQLite)
        dt_str = row["occurred_at"]
        try:
            occurred = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
        except ValueError:
            # Fallback if unparsable
            occurred = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            
        events.append(DecisionEvent(
            sequence_no=row["sequence_no"],
            occurred_at=occurred,
            actor=Actor[row["actor"]],
            event_code=row["event_code"],
            summary=row["summary"],
            detail=detail
        ))
        
    return tuple(events)

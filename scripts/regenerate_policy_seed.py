"""Regenerate 002_seed_policy_v1.sql from config/policy.yaml.

The seeded ``policy_json`` must be exactly what
``cce.audit.serialization.policy_to_json`` produces, so that
``get_current_policy()`` reads back a Policy equal to ``load_policy()``.
Hand-editing that JSON is how the two drift apart; run this instead.

    python scripts/regenerate_policy_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cce.audit.serialization import policy_from_json, policy_to_json
from cce.config import load_policy

SEED = (
    Path(__file__).resolve().parent.parent
    / "cce" / "audit" / "migrations" / "002_seed_policy_v1.sql"
)

HEADER = """\
-- Seeds the demo risk policy as policy_version_id = 1 (docs/05 section 7).
--
-- policy_json is the CANONICAL serialisation produced by
-- cce.audit.serialization.policy_to_json: per-asset min/max weights written
-- out in full rather than the min_weight_default shorthand used in
-- config/policy.yaml. An audit record must be readable without reloading the
-- configuration that produced it, and get_current_policy() reads this row.
--
-- Regenerate with:  python scripts/regenerate_policy_seed.py
"""


def main() -> int:
    policy = load_policy()
    policy_json = policy_to_json(policy)

    if policy_from_json(policy_json) != policy:
        print("ERROR: policy does not survive a serialisation round trip", file=sys.stderr)
        return 1

    sql = HEADER + f"""
INSERT INTO policy_versions (
    policy_version_id,
    created_at,
    created_by,
    created_by_role,
    source,
    policy_json,
    parent_version_id,
    change_summary,
    is_weakening,
    weakening_ack_by,
    weakening_reason
) VALUES (
    1,
    '2026-08-31T00:00:00Z',
    'system_seed',
    'SYSTEM',
    'SEED',
    '{policy_json.replace("'", "''")}',
    NULL,
    'Initial seed from config/policy.yaml',
    0,
    NULL,
    NULL
);
"""
    SEED.write_text(sql, encoding="utf-8")
    print(f"wrote {SEED.relative_to(Path.cwd())} ({len(policy_json)} chars of policy_json)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Regenerate 003_seed_demo_portfolio.sql from the demo weights.

The position values were hand-typed and drifted: ``total_value_paise`` was
1e12 paise — ₹1,000 Cr, ten times the ₹100 Cr every document and the UI
headline claim. Nothing caught it because no test asserted the demo's own
size, and 1,000 Cr is a plausible-looking number.

So the seed is DERIVED here instead: capital comes from
``DEFAULT_CAPITAL_PAISE``, positions are split with the same largest-remainder
method the portfolio builder uses, and the row is written out. Run::

    python scripts/regenerate_portfolio_seed.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cce.config import load_universe
from cce.contracts.portfolio import PAISE_PER_CRORE, PAISE_PER_RUPEE
from cce.portfolio import DEFAULT_CAPITAL_PAISE, allocate_paise

SEED = (
    Path(__file__).resolve().parent.parent
    / "cce" / "audit" / "migrations" / "003_seed_demo_portfolio.sql"
)

AS_OF = "2026-08-31"
STAMP = f"{AS_OF}T00:00:00Z"

#: The demo book. Weights only — every rupee figure below is derived.
WEIGHTS: dict[str, float] = {
    "NIFTY50": 0.28,
    "BANKNIFTY": 0.24,
    "IT": 0.12,
    "PHARMA": 0.08,
    "GOLD": 0.10,
    "GSEC": 0.12,
    "CASH": 0.06,
}
SEED_PRICE = 100.0


def build_positions(universe) -> list[dict]:
    """Positions summing EXACTLY to the capital.

    Largest-remainder, matching ``build_portfolio_state``: rounding each
    position independently leaves a residual of a few paise and the
    reconciliation assertion fails.
    """
    values = allocate_paise(DEFAULT_CAPITAL_PAISE, WEIGHTS)
    out = []
    for asset_id, weight in WEIGHTS.items():
        asset = universe.get(asset_id)
        value = values[asset_id]
        out.append({
            "asset_id": asset_id,
            "ticker": asset.ticker,
            "asset_class": asset.asset_class,
            "sector": asset.sector,
            "price": SEED_PRICE,
            "units": value / (SEED_PRICE * PAISE_PER_RUPEE),
            "value_paise": value,
            "weight": weight,
        })
    assert sum(p["value_paise"] for p in out) == DEFAULT_CAPITAL_PAISE
    return out


def main() -> int:
    universe = load_universe()
    missing = [a for a in WEIGHTS if a not in set(universe.asset_ids)]
    if missing:
        print(f"ERROR: not in the universe: {missing}", file=sys.stderr)
        return 1

    positions = build_positions(universe)
    cash = next(p["value_paise"] for p in positions if p["asset_id"] == "CASH")
    weights_json = json.dumps(WEIGHTS)
    positions_json = json.dumps(positions)

    sql = f"""\
-- Seeds the ₹100 Cr demo portfolio (docs/05 section 7).
--
-- DERIVED, not hand-typed. Regenerate with:
--     python scripts/regenerate_portfolio_seed.py
--
-- The values here were once entered by hand and drifted to 1e12 paise —
-- ₹1,000 Cr, ten times what every document and the dashboard headline claim.
-- Nothing caught it because no test asserted the demo's own size and
-- ₹1,000 Cr looks perfectly plausible. Capital now comes from
-- DEFAULT_CAPITAL_PAISE and positions are split with the largest-remainder
-- method, so they sum to it exactly.

INSERT INTO market_snapshots (snapshot_id, captured_at, as_of_date, provider, universe_hash, data_hash, row_count, asset_count, validation_status, validation_json, cache_path) VALUES (1, '{STAMP}', '{AS_OF}', 'CACHED', 'seed_uni', 'seed_data', 1000, {len(positions)}, 'VALID', '{{}}', NULL);

INSERT INTO portfolio_states (portfolio_state_id, portfolio_id, created_at, as_of_date, total_value_paise, cash_value_paise, positions_json, weights_json, origin, source_decision_id, snapshot_id) VALUES (1, 'DEMO_100CR', '{STAMP}', '{AS_OF}', {DEFAULT_CAPITAL_PAISE}, {cash}, '{positions_json}', '{weights_json}', 'SEED', NULL, 1);

INSERT INTO risk_snapshots (risk_snapshot_id, created_at, portfolio_state_id, snapshot_id, policy_version_id, expected_return_method, var_method, risk_state, breaches_json, degraded) VALUES (1, '{STAMP}', 1, 1, 1, 'HISTORICAL', 'HISTORICAL', 'GREEN', '[]', 0);

INSERT INTO decision_records (decision_id, event_uid, created_at, trigger_type, snapshot_id, policy_version_id, portfolio_state_before, risk_snapshot_before, control_status, circuit_breaker_active, human_action, portfolio_state_after) VALUES (1, '00000000-0000-0000-0000-000000000001', '{STAMP}', 'DATA_INTEGRITY', 1, 1, 1, 1, 'PASSED', 0, 'APPROVE', 1);

INSERT INTO candidate_allocations (candidate_id, decision_id, created_at, candidate_role, strategy, weights_json, solver_status, control_status, stress_status, eligible_for_approval) VALUES (1, 1, '{STAMP}', 'SAFE_CONSTRAINED', 'MAX_SHARPE', '{weights_json}', 'OPTIMAL', 'PASSED', 'PASSED', 1);

INSERT INTO safe_allocations (safe_allocation_id, portfolio_id, approved_at, decision_id, candidate_id, portfolio_state_id, weights_json, policy_version_id, approved_by, via_override) VALUES (1, 'DEMO_100CR', '{STAMP}', 1, 1, 1, '{weights_json}', 1, 'system_seed', 0);
"""
    SEED.write_text(sql, encoding="utf-8")
    print(
        f"wrote {SEED.name}: "
        f"Rs {DEFAULT_CAPITAL_PAISE / PAISE_PER_CRORE:,.1f} Cr across "
        f"{len(positions)} positions"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

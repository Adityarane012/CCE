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

INSERT INTO market_snapshots (snapshot_id, captured_at, as_of_date, provider, universe_hash, data_hash, row_count, asset_count, validation_status, validation_json, cache_path) VALUES (1, '2026-08-31T00:00:00Z', '2026-08-31', 'CACHED', 'seed_uni', 'seed_data', 1000, 7, 'VALID', '{}', NULL);

INSERT INTO portfolio_states (portfolio_state_id, portfolio_id, created_at, as_of_date, total_value_paise, cash_value_paise, positions_json, weights_json, origin, source_decision_id, snapshot_id) VALUES (1, 'DEMO_100CR', '2026-08-31T00:00:00Z', '2026-08-31', 100000000000, 6000000000, '[{"asset_id": "NIFTY50", "ticker": "NIFTY 50", "asset_class": "EQUITY", "sector": "BROAD_EQUITY", "price": 100.0, "units": 2800000.0, "value_paise": 28000000000, "weight": 0.28}, {"asset_id": "BANKNIFTY", "ticker": "NIFTY BANK", "asset_class": "EQUITY", "sector": "BANKING", "price": 100.0, "units": 2400000.0, "value_paise": 24000000000, "weight": 0.24}, {"asset_id": "IT", "ticker": "NIFTY IT", "asset_class": "EQUITY", "sector": "IT", "price": 100.0, "units": 1200000.0, "value_paise": 12000000000, "weight": 0.12}, {"asset_id": "PHARMA", "ticker": "NIFTY PHARMA", "asset_class": "EQUITY", "sector": "PHARMA", "price": 100.0, "units": 800000.0, "value_paise": 8000000000, "weight": 0.08}, {"asset_id": "GOLD", "ticker": "GOLDBEES", "asset_class": "COMMODITY", "sector": "GOLD", "price": 100.0, "units": 1000000.0, "value_paise": 10000000000, "weight": 0.1}, {"asset_id": "GSEC", "ticker": "GSEC10IETF", "asset_class": "FIXED_INCOME", "sector": "GSEC", "price": 100.0, "units": 1200000.0, "value_paise": 12000000000, "weight": 0.12}, {"asset_id": "CASH", "ticker": "CASH", "asset_class": "CASH", "sector": "CASH", "price": 100.0, "units": 600000.0, "value_paise": 6000000000, "weight": 0.06}]', '{"NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "PHARMA": 0.08, "GOLD": 0.1, "GSEC": 0.12, "CASH": 0.06}', 'SEED', NULL, 1);

INSERT INTO risk_snapshots (risk_snapshot_id, created_at, portfolio_state_id, snapshot_id, policy_version_id, expected_return_method, var_method, risk_state, breaches_json, degraded) VALUES (1, '2026-08-31T00:00:00Z', 1, 1, 1, 'HISTORICAL', 'HISTORICAL', 'GREEN', '[]', 0);

INSERT INTO decision_records (decision_id, event_uid, created_at, trigger_type, snapshot_id, policy_version_id, portfolio_state_before, risk_snapshot_before, control_status, circuit_breaker_active, human_action, portfolio_state_after) VALUES (1, '00000000-0000-0000-0000-000000000001', '2026-08-31T00:00:00Z', 'DATA_INTEGRITY', 1, 1, 1, 1, 'PASSED', 0, 'APPROVE', 1);

INSERT INTO candidate_allocations (candidate_id, decision_id, created_at, candidate_role, strategy, weights_json, solver_status, control_status, stress_status, eligible_for_approval) VALUES (1, 1, '2026-08-31T00:00:00Z', 'SAFE_CONSTRAINED', 'MAX_SHARPE', '{"NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "PHARMA": 0.08, "GOLD": 0.1, "GSEC": 0.12, "CASH": 0.06}', 'OPTIMAL', 'PASSED', 'PASSED', 1);

INSERT INTO safe_allocations (safe_allocation_id, portfolio_id, approved_at, decision_id, candidate_id, portfolio_state_id, weights_json, policy_version_id, approved_by, via_override) VALUES (1, 'DEMO_100CR', '2026-08-31T00:00:00Z', 1, 1, 1, '{"NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "PHARMA": 0.08, "GOLD": 0.1, "GSEC": 0.12, "CASH": 0.06}', 1, 'system_seed', 0);

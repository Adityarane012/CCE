-- Seeds the demo risk policy as policy_version_id = 1 (docs/05 section 7).
--
-- policy_json is the CANONICAL serialisation produced by
-- cce.audit.serialization.policy_to_json: per-asset min/max weights written
-- out in full rather than the min_weight_default shorthand used in
-- config/policy.yaml. An audit record must be readable without reloading the
-- configuration that produced it, and get_current_policy() reads this row.
--
-- Regenerate with:  python scripts/regenerate_policy_seed.py

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
    '{"constraints":{"asset_class_max":{"CASH":0.4,"COMMODITY":0.25,"EQUITY":0.75,"FIXED_INCOME":0.6},"include_txn_cost":true,"long_only":true,"max_cvar":null,"max_turnover":0.25,"max_volatility":null,"max_weights":{"BANKNIFTY":0.3,"CASH":0.4,"CORPBOND":0.3,"FMCG":0.3,"GOLD":0.3,"GSEC":0.3,"IT":0.3,"NIFTY50":0.3,"PHARMA":0.3},"min_cash_share":0.03,"min_liquid_share":0.15,"min_weights":{"BANKNIFTY":0.0,"CASH":0.0,"CORPBOND":0.0,"FMCG":0.0,"GOLD":0.0,"GSEC":0.0,"IT":0.0,"NIFTY50":0.0,"PHARMA":0.0},"sector_max":{"BANKING":0.35,"BROAD_EQUITY":0.35,"CASH":0.4,"CORP_DEBT":0.35,"FMCG":0.35,"GOLD":0.35,"GSEC":0.35,"IT":0.35,"PHARMA":0.35},"target_return":null},"label":"INIT26 demo policy","model":{"ewma_lambda":0.94,"ewma_seed_window":60,"min_return_observations":250,"monte_carlo_paths":10000,"random_seed":42,"risk_free_rate":0.065,"trading_days_per_year":252,"var_confidence":0.95},"stress_loss_limit":0.18,"thresholds":[{"amber_max":0.15,"amber_min":null,"comparator":"GT","control_code":"RISK_VOL_ANNUAL","green_max":0.12,"green_min":null,"is_hard":true,"label":"Annualised volatility","scope":"PORTFOLIO"},{"amber_max":0.08,"amber_min":null,"comparator":"GT","control_code":"RISK_CVAR_95","green_max":0.06,"green_min":null,"is_hard":true,"label":"95% Conditional VaR","scope":"PORTFOLIO"},{"amber_max":0.04,"amber_min":null,"comparator":"GT","control_code":"RISK_VAR_95","green_max":0.03,"green_min":null,"is_hard":false,"label":"95% Value at Risk","scope":"PORTFOLIO"},{"amber_max":0.12,"amber_min":null,"comparator":"GT","control_code":"RISK_DRAWDOWN_CURRENT","green_max":0.08,"green_min":null,"is_hard":false,"label":"Current drawdown","scope":"PORTFOLIO"},{"amber_max":0.4,"amber_min":null,"comparator":"GT","control_code":"CONC_ASSET_MAX","green_max":0.3,"green_min":null,"is_hard":true,"label":"Single-asset concentration","scope":"ASSET"},{"amber_max":0.35,"amber_min":null,"comparator":"GT","control_code":"CONC_SECTOR_MAX","green_max":0.25,"green_min":null,"is_hard":true,"label":"Sector concentration","scope":"SECTOR"},{"amber_max":0.4,"amber_min":null,"comparator":"GT","control_code":"RC_ASSET_MAX","green_max":0.3,"green_min":null,"is_hard":true,"label":"Asset risk contribution","scope":"ASSET"},{"amber_max":0.45,"amber_min":null,"comparator":"GT","control_code":"RC_SECTOR_MAX","green_max":0.35,"green_min":null,"is_hard":true,"label":"Sector risk contribution","scope":"SECTOR"},{"amber_max":null,"amber_min":0.1,"comparator":"LT","control_code":"LIQ_MIN_SHARE","green_max":null,"green_min":0.15,"is_hard":true,"label":"Minimum liquid assets","scope":"PORTFOLIO"},{"amber_max":null,"amber_min":0.03,"comparator":"LT","control_code":"LIQ_MIN_CASH","green_max":null,"green_min":0.05,"is_hard":true,"label":"Minimum cash","scope":"PORTFOLIO"},{"amber_max":0.25,"amber_min":null,"comparator":"GT","control_code":"TXN_TURNOVER_MAX","green_max":0.2,"green_min":null,"is_hard":true,"label":"Rebalance turnover","scope":"PORTFOLIO"},{"amber_max":0.003,"amber_min":null,"comparator":"GT","control_code":"TXN_COST_MAX","green_max":0.0015,"green_min":null,"is_hard":false,"label":"Transaction cost","scope":"PORTFOLIO"},{"amber_max":0.18,"amber_min":null,"comparator":"GT","control_code":"STRESS_LOSS_MAX","green_max":0.12,"green_min":null,"is_hard":true,"label":"Worst stress-scenario loss","scope":"PORTFOLIO"},{"amber_max":3,"amber_min":null,"comparator":"GT","control_code":"DATA_FRESHNESS","green_max":1,"green_min":null,"is_hard":true,"label":"Data staleness (trading days)","scope":"PORTFOLIO"},{"amber_max":null,"amber_min":0.95,"comparator":"LT","control_code":"DATA_COMPLETENESS","green_max":null,"green_min":0.98,"is_hard":true,"label":"Data completeness","scope":"PORTFOLIO"}],"version":1}',
    NULL,
    'Initial seed from config/policy.yaml',
    0,
    NULL,
    NULL
);

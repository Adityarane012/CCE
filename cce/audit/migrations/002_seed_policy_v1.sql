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
    '{"version": 1, "label": "INIT26 demo policy", "model": {"ewma_lambda": 0.94, "var_confidence": 0.95, "trading_days_per_year": 252, "risk_free_rate": 0.065, "min_return_observations": 250, "monte_carlo_paths": 10000, "random_seed": 42, "ewma_seed_window": 60}, "stress_loss_limit": 0.18, "thresholds": [{"code": "RISK_VOL_ANNUAL", "label": "Annualised volatility", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.12, "amber_max": 0.15, "is_hard": true}, {"code": "RISK_CVAR_95", "label": "95% Conditional VaR", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.06, "amber_max": 0.08, "is_hard": true}, {"code": "RISK_VAR_95", "label": "95% Value at Risk", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.03, "amber_max": 0.04, "is_hard": false}, {"code": "RISK_DRAWDOWN_CURRENT", "label": "Current drawdown", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.08, "amber_max": 0.12, "is_hard": false}, {"code": "CONC_ASSET_MAX", "label": "Single-asset concentration", "scope": "ASSET", "comparator": "GT", "green_max": 0.3, "amber_max": 0.4, "is_hard": true}, {"code": "CONC_SECTOR_MAX", "label": "Sector concentration", "scope": "SECTOR", "comparator": "GT", "green_max": 0.25, "amber_max": 0.35, "is_hard": true}, {"code": "RC_ASSET_MAX", "label": "Asset risk contribution", "scope": "ASSET", "comparator": "GT", "green_max": 0.3, "amber_max": 0.4, "is_hard": true}, {"code": "RC_SECTOR_MAX", "label": "Sector risk contribution", "scope": "SECTOR", "comparator": "GT", "green_max": 0.35, "amber_max": 0.45, "is_hard": true}, {"code": "LIQ_MIN_SHARE", "label": "Minimum liquid assets", "scope": "PORTFOLIO", "comparator": "LT", "green_min": 0.15, "amber_min": 0.1, "is_hard": true}, {"code": "LIQ_MIN_CASH", "label": "Minimum cash", "scope": "PORTFOLIO", "comparator": "LT", "green_min": 0.05, "amber_min": 0.03, "is_hard": true}, {"code": "TXN_TURNOVER_MAX", "label": "Rebalance turnover", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.2, "amber_max": 0.25, "is_hard": true}, {"code": "TXN_COST_MAX", "label": "Transaction cost", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.0015, "amber_max": 0.003, "is_hard": false}, {"code": "STRESS_LOSS_MAX", "label": "Worst stress-scenario loss", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 0.12, "amber_max": 0.18, "is_hard": true}, {"code": "DATA_FRESHNESS", "label": "Data staleness (trading days)", "scope": "PORTFOLIO", "comparator": "GT", "green_max": 1, "amber_max": 3, "is_hard": true}, {"code": "DATA_COMPLETENESS", "label": "Data completeness", "scope": "PORTFOLIO", "comparator": "LT", "green_min": 0.98, "amber_min": 0.95, "is_hard": true}], "constraints": {"long_only": true, "min_weight_default": 0.0, "max_weight_default": 0.3, "min_liquid_share": 0.15, "min_cash_share": 0.03, "max_turnover": 0.25, "include_txn_cost": true, "txn_cost_rate_default": 0.001, "sector_max": {"BROAD_EQUITY": 0.35, "BANKING": 0.35, "IT": 0.35, "PHARMA": 0.35, "FMCG": 0.35, "GOLD": 0.35, "GSEC": 0.35, "CORP_DEBT": 0.35, "CASH": 0.4}, "asset_class_max": {"EQUITY": 0.75, "FIXED_INCOME": 0.6, "COMMODITY": 0.25, "CASH": 0.4}}}',
    NULL,
    'Initial seed from config',
    0,
    NULL,
    NULL
);

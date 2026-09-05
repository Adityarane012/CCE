CREATE TABLE policy_versions (
    policy_version_id   INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,          -- UTC ISO-8601
    created_by          TEXT    NOT NULL,          -- user identity
    created_by_role     TEXT    NOT NULL,          -- e.g. RISK_MANAGER
    source              TEXT    NOT NULL           -- FILE | UI_EDIT | SEED
                        CHECK (source IN ('FILE','UI_EDIT','SEED')),
    policy_json         TEXT    NOT NULL,          -- full Policy object
    parent_version_id   INTEGER,
    change_summary      TEXT,                      -- human-readable diff
    is_weakening        INTEGER NOT NULL DEFAULT 0 -- 1 if a hard limit was loosened
                        CHECK (is_weakening IN (0,1)),
    weakening_ack_by    TEXT,                      -- who confirmed the warning
    weakening_reason    TEXT,
    FOREIGN KEY (parent_version_id) REFERENCES policy_versions(policy_version_id)
);

CREATE INDEX idx_policy_versions_created ON policy_versions(created_at DESC);

CREATE TABLE market_snapshots (
    snapshot_id         INTEGER PRIMARY KEY AUTOINCREMENT,
    captured_at         TEXT    NOT NULL,
    as_of_date          TEXT    NOT NULL,          -- trading date of latest observation
    provider            TEXT    NOT NULL           -- JUGAAD | CACHED | CACHED_FALLBACK
                        CHECK (provider IN ('JUGAAD','CACHED','CACHED_FALLBACK')),
    universe_hash       TEXT    NOT NULL,          -- hash of universe.yaml
    data_hash           TEXT    NOT NULL,          -- hash of the price panel
    row_count           INTEGER NOT NULL,
    asset_count         INTEGER NOT NULL,
    validation_status   TEXT    NOT NULL           -- VALID | DEGRADED | INVALID
                        CHECK (validation_status IN ('VALID','DEGRADED','INVALID')),
    validation_json     TEXT    NOT NULL,          -- ValidationReport findings
    cache_path          TEXT
);

CREATE INDEX idx_market_snapshots_asof ON market_snapshots(as_of_date DESC);
CREATE UNIQUE INDEX idx_market_snapshots_hash ON market_snapshots(data_hash, universe_hash);

CREATE TABLE portfolio_states (
    portfolio_state_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id        TEXT    NOT NULL DEFAULT 'DEMO_100CR',
    created_at          TEXT    NOT NULL,
    as_of_date          TEXT    NOT NULL,
    total_value_paise   INTEGER NOT NULL,          -- INR × 100
    cash_value_paise    INTEGER NOT NULL,
    positions_json      TEXT    NOT NULL,          -- [{asset_id, ticker, sector,
                                                   --   asset_class, price, units,
                                                   --   value_paise, weight}, ...]
    weights_json        TEXT    NOT NULL,          -- {asset_id: weight}
    origin              TEXT    NOT NULL           -- how this state came to exist
                        CHECK (origin IN ('SEED','SIMULATED_REBALANCE','MANUAL')),
    source_decision_id  INTEGER,                   -- the decision that produced it
    snapshot_id         INTEGER NOT NULL,
    FOREIGN KEY (source_decision_id) REFERENCES decision_records(decision_id),
    FOREIGN KEY (snapshot_id)        REFERENCES market_snapshots(snapshot_id)
);

CREATE INDEX idx_portfolio_states_created ON portfolio_states(portfolio_id, created_at DESC);

CREATE TABLE risk_snapshots (
    risk_snapshot_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at              TEXT    NOT NULL,
    portfolio_state_id      INTEGER NOT NULL,
    snapshot_id             INTEGER NOT NULL,
    policy_version_id       INTEGER NOT NULL,

    historical_volatility   REAL,                  -- annualised, decimal
    ewma_volatility         REAL,
    portfolio_volatility    REAL,
    expected_return         REAL,                  -- MODEL ESTIMATE
    expected_return_method  TEXT                   -- HISTORICAL | EWMA | BLACK_LITTERMAN
                            CHECK (expected_return_method IN
                                   ('HISTORICAL','EWMA','BLACK_LITTERMAN')),
    sharpe                  REAL,
    var_95                  REAL,                  -- loss as positive decimal
    cvar_95                 REAL,
    var_method              TEXT                   -- HISTORICAL | PARAMETRIC | MONTE_CARLO
                            CHECK (var_method IN ('HISTORICAL','PARAMETRIC','MONTE_CARLO')),
    current_drawdown        REAL,
    max_drawdown            REAL,
    liquidity_ratio         REAL,
    turnover_from_current   REAL,

    risk_contribution_json  TEXT,                  -- {asset_id: rc_share}
    sector_exposure_json    TEXT,                  -- {sector: weight}
    sector_risk_contrib_json TEXT,                 -- {sector: rc_share}
    concentration_json      TEXT,                  -- {max_asset, max_sector, ...}

    risk_state              TEXT    NOT NULL       -- GREEN | AMBER | RED
                            CHECK (risk_state IN ('GREEN','AMBER','RED')),
    breaches_json           TEXT    NOT NULL,      -- [Breach, ...] (may be [])
    degraded                INTEGER NOT NULL DEFAULT 0
                            CHECK (degraded IN (0,1)),   -- computed on partial data
    degraded_reason         TEXT,

    FOREIGN KEY (portfolio_state_id) REFERENCES portfolio_states(portfolio_state_id),
    FOREIGN KEY (snapshot_id)        REFERENCES market_snapshots(snapshot_id),
    FOREIGN KEY (policy_version_id)  REFERENCES policy_versions(policy_version_id)
);

CREATE INDEX idx_risk_snapshots_created ON risk_snapshots(created_at DESC);
CREATE INDEX idx_risk_snapshots_state   ON risk_snapshots(risk_state, created_at DESC);

CREATE TABLE decision_records (
    decision_id             INTEGER PRIMARY KEY AUTOINCREMENT,
    event_uid               TEXT    NOT NULL UNIQUE,   -- UUID4, stable across export
    created_at              TEXT    NOT NULL,

    trigger_type            TEXT    NOT NULL
                            CHECK (trigger_type IN
                                   ('USER_REQUEST','SCHEDULED','RISK_DETERIORATION',
                                    'STRESS_SCENARIO','DATA_INTEGRITY','MANUAL_REVIEW')),
    trigger_detail          TEXT,

    snapshot_id             INTEGER NOT NULL,
    policy_version_id       INTEGER NOT NULL,
    portfolio_state_before  INTEGER NOT NULL,
    risk_snapshot_before    INTEGER NOT NULL,

    optimizer_strategy      TEXT,                      -- MAX_SHARPE | MIN_VOL | ...
    expected_return_method  TEXT,
    solver_status           TEXT,                      -- OPTIMAL | INFEASIBLE | ERROR | ...

    control_status          TEXT    NOT NULL
                            CHECK (control_status IN
                                   ('PASSED','FAILED','NOT_VALIDATED')),
    circuit_breaker_active  INTEGER NOT NULL DEFAULT 0
                            CHECK (circuit_breaker_active IN (0,1)),
    breaker_trigger_category TEXT,                     -- RISK | CONSTRAINT | DATA |
                                                       -- MODEL | STRESS
    recommended_candidate_id INTEGER,                  -- -> candidate_allocations

    human_action            TEXT                       -- NULL until a human acts
                            CHECK (human_action IS NULL OR human_action IN
                                   ('APPROVE','REJECT','KEEP_CURRENT','OVERRIDE')),
    portfolio_state_after   INTEGER,                   -- NULL if nothing was adopted

    FOREIGN KEY (snapshot_id)            REFERENCES market_snapshots(snapshot_id),
    FOREIGN KEY (policy_version_id)      REFERENCES policy_versions(policy_version_id),
    FOREIGN KEY (portfolio_state_before) REFERENCES portfolio_states(portfolio_state_id),
    FOREIGN KEY (risk_snapshot_before)   REFERENCES risk_snapshots(risk_snapshot_id),
    FOREIGN KEY (portfolio_state_after)  REFERENCES portfolio_states(portfolio_state_id),
    FOREIGN KEY (recommended_candidate_id)
                                         REFERENCES candidate_allocations(candidate_id)
);

CREATE INDEX idx_decision_records_created ON decision_records(created_at DESC);
CREATE INDEX idx_decision_records_breaker ON decision_records(circuit_breaker_active,
                                                              created_at DESC);
CREATE INDEX idx_decision_records_action  ON decision_records(human_action);

CREATE TABLE candidate_allocations (
    candidate_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         INTEGER NOT NULL,
    created_at          TEXT    NOT NULL,

    candidate_role      TEXT    NOT NULL
                        CHECK (candidate_role IN
                               ('CURRENT','OPTIMAL_UNCONSTRAINED','SAFE_CONSTRAINED',
                                'RECOVERY_MAX_SHARPE','RECOVERY_MIN_RISK',
                                'RECOVERY_DEFENSIVE','ALTERNATIVE')),
    strategy            TEXT    NOT NULL,          -- MAX_SHARPE | MIN_VOL | TARGET_RETURN
                                                   -- | CVAR_MIN | HRP | BLACK_LITTERMAN
    weights_json        TEXT    NOT NULL,          -- {asset_id: weight}

    expected_return     REAL,                      -- MODEL ESTIMATE
    volatility          REAL,
    sharpe              REAL,
    var_95              REAL,
    cvar_95             REAL,
    turnover            REAL,
    transaction_cost_paise INTEGER,
    solver_status       TEXT    NOT NULL,

    control_status      TEXT    NOT NULL
                        CHECK (control_status IN ('PASSED','FAILED','NOT_VALIDATED')),
    stress_status       TEXT    NOT NULL
                        CHECK (stress_status IN ('PASSED','FAILED','NOT_RUN','ERROR')),
    eligible_for_approval INTEGER NOT NULL DEFAULT 0
                        CHECK (eligible_for_approval IN (0,1)),

    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
);

CREATE INDEX idx_candidates_decision ON candidate_allocations(decision_id, candidate_role);

CREATE TABLE control_findings (
    finding_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL,
    candidate_id    INTEGER,                       -- NULL = finding about current portfolio
    created_at      TEXT    NOT NULL,

    control_code    TEXT    NOT NULL,              -- e.g. CONC_SECTOR_MAX, RISK_CVAR_95
    control_label   TEXT    NOT NULL,              -- human-readable
    severity        TEXT    NOT NULL
                    CHECK (severity IN ('GREEN','AMBER','RED')),
    is_hard         INTEGER NOT NULL               -- hard controls trip the breaker
                    CHECK (is_hard IN (0,1)),
    observed_value  REAL,
    threshold_value REAL,
    comparator      TEXT,                          -- GT | GTE | LT | LTE
    scope           TEXT,                          -- asset_id / sector / PORTFOLIO
    message         TEXT    NOT NULL,

    FOREIGN KEY (decision_id)  REFERENCES decision_records(decision_id),
    FOREIGN KEY (candidate_id) REFERENCES candidate_allocations(candidate_id)
);

CREATE INDEX idx_findings_decision ON control_findings(decision_id, severity);
CREATE INDEX idx_findings_code     ON control_findings(control_code, created_at DESC);

CREATE TABLE stress_results (
    stress_result_id    INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         INTEGER NOT NULL,
    candidate_id        INTEGER,
    created_at          TEXT    NOT NULL,

    scenario_code       TEXT    NOT NULL,          -- BROAD_CRASH | BANKING_CRISIS | ...
    scenario_label      TEXT    NOT NULL,
    is_custom           INTEGER NOT NULL DEFAULT 0
                        CHECK (is_custom IN (0,1)),
    shocks_json         TEXT    NOT NULL,          -- {sector|asset_id: shock_decimal}

    portfolio_loss      REAL    NOT NULL,          -- positive decimal = loss
    loss_paise          INTEGER NOT NULL,
    contribution_json   TEXT,                      -- {asset_id: loss_contribution}
    post_shock_vol      REAL,
    post_shock_cvar     REAL,
    breaches_json       TEXT,                      -- policies breached post-shock

    passed              INTEGER NOT NULL
                        CHECK (passed IN (0,1)),
    loss_threshold      REAL    NOT NULL,          -- the limit applied

    FOREIGN KEY (decision_id)  REFERENCES decision_records(decision_id),
    FOREIGN KEY (candidate_id) REFERENCES candidate_allocations(candidate_id)
);

CREATE INDEX idx_stress_decision ON stress_results(decision_id, scenario_code);

CREATE TABLE explanations (
    explanation_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         INTEGER NOT NULL UNIQUE,
    created_at          TEXT    NOT NULL,

    structured_json     TEXT    NOT NULL,          -- SOURCE OF TRUTH
    template_text       TEXT    NOT NULL,          -- deterministic narrator output

    llm_used            INTEGER NOT NULL DEFAULT 0
                        CHECK (llm_used IN (0,1)),
    llm_model           TEXT,
    llm_text            TEXT,                      -- DISPLAY ONLY - never parsed back
    llm_error           TEXT,

    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
);

CREATE TABLE human_actions (
    action_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id         INTEGER NOT NULL,
    candidate_id        INTEGER,                   -- what was acted upon
    created_at          TEXT    NOT NULL,

    action              TEXT    NOT NULL
                        CHECK (action IN ('APPROVE','REJECT','KEEP_CURRENT','OVERRIDE')),
    user_identity       TEXT    NOT NULL,          -- simulated: 'demo_risk_manager'
    user_role           TEXT    NOT NULL,          -- RISK_MANAGER
    comment             TEXT,

    is_override         INTEGER NOT NULL DEFAULT 0
                        CHECK (is_override IN (0,1)),
    override_reason     TEXT,
    overridden_controls_json TEXT,                 -- [control_code, ...]
    confirmation_token  TEXT,                      -- proves the explicit-confirm step ran

    FOREIGN KEY (decision_id)  REFERENCES decision_records(decision_id),
    FOREIGN KEY (candidate_id) REFERENCES candidate_allocations(candidate_id)
);

CREATE INDEX idx_human_actions_decision ON human_actions(decision_id, created_at);

CREATE TABLE safe_allocations (
    safe_allocation_id  INTEGER PRIMARY KEY AUTOINCREMENT,
    portfolio_id        TEXT    NOT NULL DEFAULT 'DEMO_100CR',
    approved_at         TEXT    NOT NULL,
    decision_id         INTEGER NOT NULL,
    candidate_id        INTEGER NOT NULL,
    portfolio_state_id  INTEGER NOT NULL,
    weights_json        TEXT    NOT NULL,
    policy_version_id   INTEGER NOT NULL,          -- policy in force AT approval time
    approved_by         TEXT    NOT NULL,
    via_override        INTEGER NOT NULL DEFAULT 0
                        CHECK (via_override IN (0,1)),

    FOREIGN KEY (decision_id)        REFERENCES decision_records(decision_id),
    FOREIGN KEY (candidate_id)       REFERENCES candidate_allocations(candidate_id),
    FOREIGN KEY (portfolio_state_id) REFERENCES portfolio_states(portfolio_state_id),
    FOREIGN KEY (policy_version_id)  REFERENCES policy_versions(policy_version_id)
);

CREATE INDEX idx_safe_alloc_current ON safe_allocations(portfolio_id, approved_at DESC);

CREATE TABLE decision_events (
    event_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    decision_id     INTEGER NOT NULL,
    sequence_no     INTEGER NOT NULL,              -- ordering within the decision
    occurred_at     TEXT    NOT NULL,

    actor           TEXT    NOT NULL
                    CHECK (actor IN ('MACHINE','CONTROL','HUMAN')),
    event_code      TEXT    NOT NULL,              -- SHOCK_DETECTED, BREAKER_TRIPPED, ...
    summary         TEXT    NOT NULL,              -- one-line, display-ready
    detail_json     TEXT,

    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
);

CREATE UNIQUE INDEX idx_events_seq ON decision_events(decision_id, sequence_no);
CREATE INDEX idx_events_time       ON decision_events(occurred_at);

CREATE TABLE alerts (
    alert_id        INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at      TEXT    NOT NULL,
    decision_id     INTEGER,
    severity        TEXT    NOT NULL
                    CHECK (severity IN ('INFO','AMBER','RED')),
    category        TEXT    NOT NULL               -- RISK | CONSTRAINT | DATA |
                                                   -- MODEL | STRESS
    ,
    title           TEXT    NOT NULL,
    message         TEXT    NOT NULL,
    acknowledged_at TEXT,
    acknowledged_by TEXT,

    FOREIGN KEY (decision_id) REFERENCES decision_records(decision_id)
);

CREATE INDEX idx_alerts_open ON alerts(acknowledged_at, created_at DESC);

CREATE TABLE backtest_runs (
    run_id              INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT    NOT NULL,
    start_date          TEXT    NOT NULL,
    end_date            TEXT    NOT NULL,
    rebalance_frequency TEXT    NOT NULL
                        CHECK (rebalance_frequency IN ('MONTHLY','WEEKLY')),
    policy_version_id   INTEGER NOT NULL,
    snapshot_id         INTEGER NOT NULL,
    random_seed         INTEGER NOT NULL,
    config_json         TEXT    NOT NULL,
    FOREIGN KEY (policy_version_id) REFERENCES policy_versions(policy_version_id),
    FOREIGN KEY (snapshot_id)       REFERENCES market_snapshots(snapshot_id)
);

CREATE TABLE backtest_results (
    result_id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id              INTEGER NOT NULL,
    strategy            TEXT    NOT NULL
                        CHECK (strategy IN ('BUY_AND_HOLD','UNCONTROLLED_OPTIMIZER',
                                            'CCE_CONTROLLED')),

    cumulative_return   REAL,
    annualised_return   REAL,
    volatility          REAL,
    sharpe              REAL,
    max_drawdown        REAL,
    var_95              REAL,
    cvar_95             REAL,
    avg_turnover        REAL,
    total_txn_cost_paise INTEGER,
    policy_breach_count INTEGER,
    breaker_activations INTEGER,
    equity_curve_json   TEXT,                      -- [{date, value}, ...]

    FOREIGN KEY (run_id) REFERENCES backtest_runs(run_id)
);

CREATE UNIQUE INDEX idx_backtest_strategy ON backtest_results(run_id, strategy);

CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    checksum    TEXT NOT NULL
);

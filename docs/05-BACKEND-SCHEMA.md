# 05 — Backend Schema

**Engine:** SQLite 3 (file-based, transactional, zero-ops)
**File:** `./data/cce.db` (git-ignored; recreatable from migrations)
**Access:** exclusively through `cce/audit/repository.py`. No other module opens a connection.
**Derived from:** master spec §35, §44, §47.

---

## 1. Design rules

| Rule | Rationale |
|---|---|
| **Append-only for decision data.** No `UPDATE` or `DELETE` statement may exist in application code against `decision_records`, `decision_events`, `control_findings`, `stress_results`, `human_actions`, or `policy_versions`. | An audit trail that can be rewritten is not an audit trail. `[INV-6]` |
| **Every write is parameterised.** No string interpolation into SQL, ever. | `NFR-032` |
| **Weights and metric bundles are stored as JSON text**, validated against the contracts in `06-DATA-CONTRACTS.md` before insert. | The asset universe is configurable; a fixed-column schema would break when it changes. |
| **Every timestamp is UTC ISO-8601 with explicit offset**, stored as `TEXT`. | SQLite has no native datetime; ISO-8601 text sorts correctly and is unambiguous. |
| **Money is stored in paise (INR × 100) as `INTEGER`**, never as `REAL`. | Floating-point currency accumulates error across a ₹100 Cr portfolio. |
| **Rates, weights and ratios are stored as `REAL` in decimal form** (0.1568 = 15.68%), never as pre-formatted percentages. | One representation, formatted once at the UI edge. |
| **A failed write raises.** It is never swallowed and never reported as success. | `FR-125` |
| **The database is not the source of truth for live computation** — it is the record of what happened. Recomputation always starts from market data + config. | Keeps replay honest. |

### Referential integrity

`PRAGMA foreign_keys = ON;` MUST be executed on every connection — SQLite defaults it off.

### Connection setup

```sql
PRAGMA foreign_keys = ON;
PRAGMA journal_mode = WAL;      -- concurrent read during write
PRAGMA synchronous = NORMAL;    -- adequate durability for a prototype
```

---

## 2. Entity overview

```
policy_versions ──┐
                  │
market_snapshots ─┼──▶ decision_records ──┬──▶ control_findings
                  │         │             ├──▶ stress_results
portfolio_states ─┘         │             ├──▶ candidate_allocations
        ▲                   │             ├──▶ human_actions
        └───────────────────┘             └──▶ decision_events   (replay timeline)
                                          └──▶ explanations

safe_allocations   (pointer table: the Last Approved Safe Allocation)
alerts             (breaker + breach notifications)
backtest_runs ─────▶ backtest_results
```

---

## 3. DDL

### 3.1 `policy_versions` — versioned risk thresholds

Every threshold change is a new row. Nothing is edited in place. `[INV-8]`

```sql
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
```

> If `is_weakening = 1`, `weakening_ack_by` and `weakening_reason` MUST be non-null. Enforced in the repository, since SQLite conditional NOT NULL is awkward.

---

### 3.2 `market_snapshots` — provenance of the data behind a decision

```sql
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
```

`data_hash` is what makes a demo reproducible: two runs over the same snapshot must produce identical analysis.

---

### 3.3 `portfolio_states` — immutable portfolio snapshots

```sql
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
```

**Invariant checked on insert:** `abs(sum(weights) - 1.0) <= 1e-6`, and `sum(position values) + cash == total_value_paise`.

---

### 3.4 `risk_snapshots` — computed risk at a point in time

```sql
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
```

> `degraded = 1` means the snapshot was computed on incomplete or fallback data. Anything displayed from a degraded snapshot MUST be labelled (`NFR-043`).

---

### 3.5 `decision_records` — the spine

One row per material decision cycle. Everything else hangs off this.

```sql
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
```

> `human_action` and `portfolio_state_after` are the **only** columns permitted to transition from NULL to a value, and only once. This is the single, narrow exception to append-only, enforced in the repository with a guarded conditional update (`WHERE human_action IS NULL`) so a second write cannot succeed.

---

### 3.6 `candidate_allocations` — every proposal, accepted or not

Rejected candidates are first-class rows. The rejected optimal portfolio *is* the product story.

```sql
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
```

**Repository invariant:** `eligible_for_approval = 1` requires `control_status='PASSED'` **and** `stress_status='PASSED'`. Any other combination MUST be rejected at insert. `[INV-2]` `[INV-10]`

---

### 3.7 `control_findings` — one row per failed or warning control

```sql
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
```

`control_code` values are the canonical identifiers defined in `07-RISK-POLICY.md` §4.

---

### 3.8 `stress_results`

```sql
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
    -- added by 004_stress_result_status.sql
    status              TEXT    NOT NULL DEFAULT 'NOT_RUN'
                        CHECK (status IN ('PASSED','FAILED','NOT_RUN','ERROR')),
    -- added by 005_stress_error_reason.sql
    error_reason        TEXT,                      -- why there is no verdict

    FOREIGN KEY (decision_id)  REFERENCES decision_records(decision_id),
    FOREIGN KEY (candidate_id) REFERENCES candidate_allocations(candidate_id)
);

CREATE INDEX idx_stress_decision ON stress_results(decision_id, scenario_code);
```

---

### 3.9 `explanations`

```sql
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
```

> `structured_json` is authoritative. `llm_text` is decoration. No code path may read `llm_text` into any decision, metric, or state. `[INV-1]`

---

### 3.10 `human_actions`

```sql
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
```

**Repository invariant:** `is_override = 1` requires non-null `override_reason`, non-empty `overridden_controls_json` and a `confirmation_token`. `FR-118`

---

### 3.11 `safe_allocations` — the Last Approved Safe Allocation

A pointer history, not a mutable field. The current one is the most recent row.

```sql
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
```

```sql
-- The current Last Approved Safe Allocation
SELECT * FROM safe_allocations
WHERE portfolio_id = ?
ORDER BY approved_at DESC
LIMIT 1;
```

> `policy_version_id` records the policy that was in force when it was approved. This is what makes the name honest: it passed *those* controls, at *that* time. A later policy change does not retroactively make it safe or unsafe — it makes it *stale*, which the UI should indicate.

> `via_override = 1` marks an allocation adopted despite a breach. The UI MUST distinguish it from a cleanly-validated safe allocation.

---

### 3.12 `decision_events` — the Decision Replay timeline

```sql
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
```

Replay reads only this table plus its joins. It never recomputes. `FR-124`

---

### 3.13 `alerts`

```sql
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
```

Acknowledgement is the one permitted mutation here, and it never deletes the alert.

---

### 3.14 `backtest_runs` / `backtest_results`

```sql
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
```

`random_seed` is stored so a run is reproducible. `NFR-012`

---

## 4. JSON payload shapes

Validated in the repository before insert. Shapes mirror `06-DATA-CONTRACTS.md`.

### `weights_json`
```json
{ "NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "PHARMA": 0.08,
  "GOLD": 0.10, "GSEC": 0.12, "CASH": 0.06 }
```
Values sum to 1.0 ± 1e-6.

### `positions_json`
```json
[{ "asset_id": "BANKNIFTY", "ticker": "NIFTYBANK", "name": "Nifty Bank Index",
   "asset_class": "EQUITY", "sector": "BANKING",
   "price": 48250.15, "units": 4974.2,
   "value_paise": 24000000000, "weight": 0.24 }]
```

### `breaches_json`
```json
[{ "control_code": "RISK_CVAR_95", "severity": "RED", "is_hard": true,
   "observed": 0.094, "threshold": 0.08, "comparator": "GT",
   "scope": "PORTFOLIO",
   "message": "95% CVaR 9.4% exceeds the RED limit of 8.0%" }]
```

### `structured_json` (Explanation)

All nine FR-140 fields. Keys match the `Explanation` and `RiskChange` field
names exactly — `from_value`, not `from` — so the JSON and the contract cannot
drift apart under a rename. (`from` is a Python keyword and could never have
been the field name; a key that differs from its field is the translation
layer where mistakes hide.)

`control_result` carries the `ControlStatus` value (`PASSED` / `FAILED` /
`NOT_VALIDATED`), the same vocabulary as `decision_records.control_status`.
`delta` is written out even though it is derived, so a reader of the audit
record does not have to recompute anything to see the direction of a move.

```json
{
  "trigger": "Banking volatility increased sharply.",
  "risk_change": {
    "metric": "ewma_volatility", "from_value": 0.118, "to_value": 0.156,
    "delta": 0.038, "scope": "PORTFOLIO"
  },
  "main_contributors": [
    { "metric": "risk_contribution", "from_value": 0.27, "to_value": 0.41,
      "delta": 0.14, "scope": "BANKING" }
  ],
  "optimizer": "MAX_SHARPE",
  "candidate_summary": { "BANKNIFTY": 0.43 },
  "control_result": "FAILED",
  "reasons": [
    "Banking concentration 43% exceeds the 40% limit.",
    "95% CVaR 9.4% exceeds the 8% limit."
  ],
  "stress_summary": [
    "Banking crisis: loss 22.1% exceeds limit 18.0%."
  ],
  "action": "Generate defensive recovery allocations.",
  "expected_improvement": null
}
```

### `shocks_json`
```json
{ "BROAD_EQUITY": -0.12, "BANKING": -0.18, "IT": -0.08,
  "GOLD": 0.05, "GSEC": -0.04, "LIQUIDITY": -0.20 }
```

---

## 5. Migrations

Plain numbered SQL files, applied in order, tracked in a table. No ORM, no migration framework.

```
cce/audit/migrations/
├── 001_initial_schema.sql
├── 002_seed_policy_v1.sql
├── 003_seed_demo_portfolio.sql
├── 004_stress_result_status.sql
└── 005_stress_error_reason.sql
```

```sql
CREATE TABLE schema_migrations (
    version     INTEGER PRIMARY KEY,
    applied_at  TEXT NOT NULL,
    checksum    TEXT NOT NULL
);
```

Rules: migrations are forward-only and never edited after being applied; `cce/audit/database.py` runs pending migrations on startup, **each inside its own transaction**; the entire database MUST be recreatable by deleting the file and restarting (`NFR-015`).

**On transactions.** The connection is opened with `isolation_level=None` (autocommit) and every write goes through `cce.audit.database.transaction`. This is not stylistic. Python's `sqlite3` does not open an implicit transaction for DDL, so `CREATE TABLE` under the default isolation level commits immediately, and `executescript` issues an implicit `COMMIT` before it runs — either one silently breaks a migration out of its transaction and leaves a partial schema behind with no `schema_migrations` row. Scripts are therefore split into statements with `sqlite3.complete_statement` and executed inside an explicit `BEGIN IMMEDIATE` … `COMMIT`.

`005_stress_error_reason.sql` adds `stress_results.error_reason`. 004 made an ERROR distinguishable from a FAILED run; without a reason, an ERROR tells a risk manager that something went wrong and nothing about what — and the log line carrying the reason is not in front of them when they read the decision record. It matters most for the failure it was added alongside: a scenario whose shock keys match no asset or sector applies nothing and used to report a clean PASS, and `shock keys match no asset or sector: BANKING_` is the difference between finding that typo and not.

`004_stress_result_status.sql` adds `stress_results.status`, recording the full `StressStatus` rather than only the `passed` bit. Collapsing PASSED / FAILED / NOT_RUN / ERROR into one boolean keeps `INV-10` intact — nothing but PASSED ever reads as safe — but loses the difference between "the portfolio failed the scenario" and "the stress engine errored", which is exactly what the audit trail is consulted for afterwards.

---

## 6. Repository interface

The only sanctioned database surface (`cce/audit/repository.py`). Read models and write metadata live in `cce/audit/models.py`; the read SQL lives in `cce/audit/queries.py` and the repository delegates to it, so the surface stays single while the modules stay small.

```python
class AuditRepository:
    # --- writes (append-only) ---
    def record_policy_version(self, policy: Policy, meta: PolicyChangeMeta) -> int: ...
    def record_market_snapshot(self, snap: MarketSnapshotMeta) -> int: ...
    def record_portfolio_state(self, state: PortfolioState, origin: PortfolioOrigin,
                               snapshot_id: int,
                               source_decision_id: int | None = None) -> int: ...
    def record_risk_snapshot(self, snapshot: RiskSnapshot, portfolio_state_id: int,
                             snapshot_id: int, policy_version_id: int) -> int: ...
    def open_decision(self, ctx: DecisionContext) -> int: ...
    def record_candidate(self, decision_id: int, cand: Candidate,
                         created_at: datetime | None = None) -> int: ...
    def record_control_findings(self, decision_id: int, findings: Sequence[Breach],
                                candidate_id: int | None = None,
                                created_at: datetime | None = None) -> int: ...
    def record_stress_results(self, decision_id: int, results: Sequence[StressResult],
                              candidate_id: int | None = None,
                              created_at: datetime | None = None) -> int: ...
    def record_explanation(self, decision_id: int, expl: Explanation,
                           template_text: str, llm_text: str | None = None,
                           llm_model: str | None = None,
                           llm_error: str | None = None) -> int: ...
    def record_event(self, decision_id: int, event: DecisionEvent) -> int: ...
    def raise_alert(self, alert: Alert, decision_id: int | None = None) -> int: ...

    # --- the single guarded transition ---
    def close_decision_with_human_action(
        self, decision_id: int, action: HumanActionRecord,
        portfolio_state_after: int | None, candidate_id: int | None = None) -> int:
        """Fails if the decision already has a human action recorded."""

    def promote_safe_allocation(self, decision_id: int, candidate_id: int,
                                portfolio_state_id: int,
                                portfolio_id: str = "DEMO_100CR",
                                approved_at: datetime | None = None) -> int: ...

    # --- reads ---
    def get_last_safe_allocation(self, portfolio_id: str) -> SafeAllocation | None: ...
    def get_decision(self, decision_id: int) -> StoredDecision: ...
    def get_replay_timeline(self, decision_id: int) -> list[DecisionEvent]: ...
    def list_decisions(self, limit: int = 50, offset: int = 0) -> list[DecisionSummary]: ...
    def get_current_policy(self) -> Policy: ...
    def get_policy_version(self, policy_version_id: int) -> Policy: ...
```

There is deliberately **no** `update_decision`, `delete_decision`, or `execute_sql` method. If you find yourself wanting one, the design is wrong.

### Notes on the signatures

These differ from the sketch this section originally carried. Each difference is deliberate; the sketch predated the contracts.

| Signature | Why |
|---|---|
| `record_portfolio_state(..., snapshot_id)` · `record_risk_snapshot(..., portfolio_state_id, snapshot_id, policy_version_id)` | Those columns are `NOT NULL` foreign keys. A portfolio state is only meaningful against the market data that priced it, and a risk snapshot only against the policy it was judged under. |
| `cand: Candidate`, `findings: Sequence[Breach]` | The real contracts. There is no `CandidateRecord` or `ControlFinding` type — `Candidate` (`cce/contracts/control.py`) and `Breach` (`cce/contracts/risk.py`) already carry exactly these fields, and a parallel persistence type is a second source of truth. |
| `record_explanation(..., template_text)` | `explanations.template_text` is `NOT NULL`. The deterministic narration is the shipping default (FR-142), so it is required at write time, not optional. |
| `record_control_findings` / `record_stress_results` return `int` | The number of rows written. `None` cannot distinguish "wrote nothing because there was nothing" from "wrote nothing because it failed". |
| `raise_alert(alert, decision_id=None)` | `contracts.Alert` carries no decision id — the engines construct alerts without knowing the decision they will be filed under, because they perform no I/O. The link is supplied at the persistence edge. |
| `get_decision -> StoredDecision` | **Not** `DecisionRecord`. That contract embeds a full `PortfolioState`, which carries the `return_series` used to compute it; the series is not persisted, because it is derived from market data that is. Returning a `DecisionRecord` would mean inventing a return series to fill the field. The system does not invent — on failure it does less (Rule 2) — so the read model reports exactly what was stored. |
| `get_policy_version` added | Replay must read the policy version the decision recorded, not whichever is current, or a verdict is re-read against thresholds that were never applied to it (INV-8). |

### Enforced properties

- **`promote_safe_allocation` re-checks eligibility against the persisted candidate row**, not against what the caller claims. A candidate that the control engine failed or that stress validation did not pass can only be promoted through an override that is itself recorded, with a reason and the specific controls overridden (FR-118). `approved_by` and `via_override` are read from the decision's `human_actions` row, so a promotion cannot name an approver the audit trail does not have (INV-2, INV-6, INV-10).
- **`close_decision_with_human_action` writes two rows in one transaction**: the guarded `UPDATE` on `decision_records`, and the attribution row in `human_actions`. The update alone records only *what* was decided; INV-6 requires *who* and *why*.
- **`record_candidate` re-asserts the approval gate rather than reimplementing it.** `eligible_for_approval` comes from the `Candidate` property, which is defined once in `cce/contracts/control.py`. A second implementation is a bug waiting to diverge.

---

## 7. Seed data

`002_seed_policy_v1.sql` inserts the demo policy from `07-RISK-POLICY.md` §3 as `policy_version_id = 1`, `source = 'SEED'`.

`003_seed_demo_portfolio.sql` inserts the ₹100 Cr starting allocation as `origin = 'SEED'`, together with the initial `safe_allocations` row (EC-5.2).

Both are committed so a fresh clone reaches a working, healthy (GREEN) demo state with a single command.

**`policy_json` is the canonical serialisation** produced by `cce.audit.serialization.policy_to_json`, with per-asset `min_weights`/`max_weights` written out in full rather than the `min_weight_default` shorthand used in `config/policy.yaml`. The shorthand needs the universe to expand it, and an audit record must be readable without reloading the configuration that produced it. `get_current_policy()` reads this row back into a `Policy` equal to `load_policy()`, and a test asserts that.

Regenerate the seed rather than hand-editing its JSON:

```bash
python scripts/regenerate_policy_seed.py
```

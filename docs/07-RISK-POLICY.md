# 07 — Risk Policy

**Scope:** The GREEN/AMBER/RED framework, canonical control codes, demo thresholds, circuit-breaker triggers, and the policy configuration format.
**Owner module:** `cce/controls/policy.py` + `config/policy.yaml`
**Derived from:** master spec §15–§21, §26, §31.3, §46.

> **Every number in this document is a `[DEMO-CONFIG]` prototype setting.** They are chosen to make institutional control behaviour legible in a demo. They are **not** claims about universal institutional standards, and they are not regulatory values. The UI must present them as configurable policy, and the docs must never imply otherwise.

---

## 1. The three-state model

| State | Meaning | System behaviour |
|---|---|---|
| **GREEN** | Normal operating range | Normal monitoring · optimization allowed · standard approval path |
| **AMBER** | Approaching a limit, or deteriorating | Visual warning · risk explanation surfaced · optimization still allowed · heightened attention · **no automatic freeze** unless another hard condition trips |
| **RED** | Hard policy breach or critical system condition | Circuit breaker · unsafe candidate rejected · Last Approved Safe Allocation preserved · explicit human decision required · high-priority alert |

### Aggregation

The portfolio's overall risk state is the **most severe** state across all evaluated controls.

```python
overall = max((t.classify(v) for t, v in evaluated), key=lambda s: s.severity)
```

There is no averaging, no weighting, no "mostly green". One RED control makes the portfolio RED. This is deliberate: a control that can be outvoted is not a control.

### Hard vs soft controls

| | Hard control | Soft control |
|---|---|---|
| RED behaviour | **Trips the circuit breaker** | Raises an alert, does not trip |
| Approval | Blocks approval; requires Controlled Override | Approval permitted with warning |
| Example | CVaR limit, sector concentration cap | Drawdown level, turnover advisory |

Whether a control is hard is a **policy decision recorded in configuration**, not a property of the metric.

---

## 2. Canonical control codes

These strings are stable identifiers used in `Breach.control_code`, `control_findings.control_code`, tests, and the UI. Do not invent new ones ad hoc — add them here first.

| Code | Label | Scope | Metric | Hard |
|---|---|---|---|---|
| `RISK_VOL_ANNUAL` | Annualised volatility | PORTFOLIO | EWMA volatility (annualised) | ✅ |
| `RISK_VAR_95` | 95% Value at Risk | PORTFOLIO | 1-day historical VaR | ❌ |
| `RISK_CVAR_95` | 95% Conditional VaR | PORTFOLIO | 1-day historical CVaR | ✅ |
| `RISK_DRAWDOWN_CURRENT` | Current drawdown | PORTFOLIO | Current drawdown from peak | ❌ |
| `RISK_DRAWDOWN_MAX` | Maximum drawdown | PORTFOLIO | Max historical drawdown | ❌ |
| `CONC_ASSET_MAX` | Single-asset concentration | ASSET | Max single weight | ✅ |
| `CONC_SECTOR_MAX` | Sector concentration | SECTOR | Max sector weight | ✅ |
| `CONC_ASSET_CLASS_MAX` | Asset-class exposure | SECTOR | Max asset-class weight | ❌ |
| `RC_ASSET_MAX` | Asset risk contribution | ASSET | Max share of total risk | ✅ |
| `RC_SECTOR_MAX` | Sector risk contribution | SECTOR | Max sector share of total risk | ✅ |
| `LIQ_MIN_SHARE` | Minimum liquid assets | PORTFOLIO | Share in liquid instruments | ✅ |
| `LIQ_MIN_CASH` | Minimum cash | PORTFOLIO | Cash share | ✅ |
| `LIQ_DAYS_TO_LIQUIDATE` | Days to liquidate | ASSET | Est. liquidation days | ❌ |
| `TXN_TURNOVER_MAX` | Rebalance turnover | PORTFOLIO | Σ\|Δw\| / 2 | ✅ |
| `TXN_COST_MAX` | Transaction cost | PORTFOLIO | Cost as share of NAV | ❌ |
| `STRESS_LOSS_MAX` | Stress scenario loss | PORTFOLIO | Worst configured scenario loss | ✅ |
| `DATA_FRESHNESS` | Data staleness | PORTFOLIO | Trading days since last observation | ✅ |
| `DATA_COMPLETENESS` | Data completeness | PORTFOLIO | Share of expected observations present | ✅ |
| `MODEL_SOLVER` | Optimizer feasibility | PORTFOLIO | Solver status | ✅ |
| `MODEL_COVARIANCE` | Covariance validity | PORTFOLIO | PSD check outcome | ✅ |

---

## 3. Demo thresholds `[DEMO-CONFIG]`

### 3.1 From the master specification (§21)

These are the canonical demo values. Do not change them without changing the master spec too.

| Metric | GREEN | AMBER | RED |
|---|---|---|---|
| Annualised volatility | < 12% | 12–15% | > 15% |
| 95% CVaR | < 6% | 6–8% | > 8% |
| Single-asset concentration | < 30% | 30–40% | > 40% |
| Sector concentration | < 25% | 25–35% | > 35% |
| Minimum liquid assets | > 15% | 10–15% | < 10% |
| Turnover | < 20% | 20–25% | > 25% |

### 3.2 Proposed additional thresholds `[DEMO-CONFIG]`

These are **not** in the master spec — they are proposed defaults to make the additional controls operable. They are configurable and should be reviewed before the demo.

| Metric | GREEN | AMBER | RED | Note |
|---|---|---|---|---|
| Asset risk contribution | < 30% | 30–40% | > 40% | Catches "within weight cap, dominates risk" |
| Sector risk contribution | < 35% | 35–45% | > 45% | The banking-shock demo trips this |
| 95% VaR | < 3% | 3–4% | > 4% | Soft; CVaR is the authority |
| Current drawdown | < 8% | 8–12% | > 12% | Soft; monitoring metric |
| Minimum cash | > 5% | 3–5% | < 3% | Subset of the liquidity floor |
| Transaction cost | < 0.15% | 0.15–0.30% | > 0.30% | Of NAV, per rebalance |
| Worst stress-scenario loss | < 12% | 12–18% | > 18% | Hard: gates candidates |
| Data staleness | ≤ 1 day | 2–3 days | > 3 days | Trading days |
| Data completeness | > 98% | 95–98% | < 95% | Of expected observations |

> On drawdown specifically: the master spec is explicit that drawdown is **primarily a monitoring metric**, and that any trigger must be configurable rather than hard-coded as a universal financial rule. It is therefore soft by default.

### 3.3 Model parameters `[DEMO-CONFIG]`

| Parameter | Default | Note |
|---|---|---|
| EWMA decay λ | `0.94` | RiskMetrics convention for daily data; configurable |
| VaR/CVaR confidence | `0.95` | |
| Trading days per year | `252` | Annualisation factor |
| Risk-free rate | `0.065` | Reference rate for Sharpe; label as an assumption |
| Minimum return history | `250` observations | Below this, metrics are `degraded` |
| Monte Carlo paths | `10_000` | P2; reduce before blocking |
| Random seed | `42` | Reproducibility |

---

## 4. Policy configuration format

`config/policy.yaml` is the single source of thresholds. It is loaded into a `Policy` contract and versioned into `policy_versions` on every change.

```yaml
version: 1
label: "INIT26 demo policy"

model:
  ewma_lambda: 0.94
  var_confidence: 0.95
  trading_days_per_year: 252
  risk_free_rate: 0.065
  min_return_observations: 250
  monte_carlo_paths: 10000
  random_seed: 42

thresholds:
  - code: RISK_VOL_ANNUAL
    label: "Annualised volatility"
    scope: PORTFOLIO
    comparator: GT          # breach when the value EXCEEDS the band
    green_max: 0.12
    amber_max: 0.15
    is_hard: true

  - code: RISK_CVAR_95
    label: "95% Conditional VaR"
    scope: PORTFOLIO
    comparator: GT
    green_max: 0.06
    amber_max: 0.08
    is_hard: true

  - code: CONC_ASSET_MAX
    label: "Single-asset concentration"
    scope: ASSET
    comparator: GT
    green_max: 0.30
    amber_max: 0.40
    is_hard: true

  - code: CONC_SECTOR_MAX
    label: "Sector concentration"
    scope: SECTOR
    comparator: GT
    green_max: 0.25
    amber_max: 0.35
    is_hard: true

  - code: RC_SECTOR_MAX
    label: "Sector risk contribution"
    scope: SECTOR
    comparator: GT
    green_max: 0.35
    amber_max: 0.45
    is_hard: true

  - code: LIQ_MIN_SHARE
    label: "Minimum liquid assets"
    scope: PORTFOLIO
    comparator: LT          # breach when the value falls BELOW the band
    green_min: 0.15
    amber_min: 0.10
    is_hard: true

  - code: TXN_TURNOVER_MAX
    label: "Rebalance turnover"
    scope: PORTFOLIO
    comparator: GT
    green_max: 0.20
    amber_max: 0.25
    is_hard: true

  - code: STRESS_LOSS_MAX
    label: "Worst stress-scenario loss"
    scope: PORTFOLIO
    comparator: GT
    green_max: 0.12
    amber_max: 0.18
    is_hard: true

constraints:
  long_only: true
  min_weight_default: 0.00
  max_weight_default: 0.30
  min_cash_share: 0.03
  include_txn_cost: true
  txn_cost_rate_default: 0.0010     # 10 bps per unit of |weight change|
```

### Comparator semantics

| Comparator | Fields used | GREEN when | AMBER when | RED when |
|---|---|---|---|---|
| `GT` | `green_max`, `amber_max` | `v ≤ green_max` | `green_max < v ≤ amber_max` | `v > amber_max` |
| `LT` | `green_min`, `amber_min` | `v ≥ green_min` | `amber_min ≤ v < green_min` | `v < amber_min` |

Boundary values belong to the **less severe** band. `v == green_max` is GREEN. This must be tested explicitly — off-by-one at a threshold boundary is a classic and embarrassing bug in a risk system.

---

## 5. Editing policy at runtime

The Policy/Settings page lets a risk manager change thresholds. That capability carries obligations:

1. **Preview before apply.** `PolicyService.preview_change` returns which controls are affected and whether the change is a **weakening** of a hard limit.
2. **Weakening warning.** If a hard threshold is loosened substantially, show an explicit policy-weakening warning and require confirmation. `FR-084`
3. **Reason required.** A weakening change requires a free-text reason.
4. **Versioned, never edited.** Applying a change inserts a new `policy_versions` row. The previous version is never modified. `[INV-8]`
5. **Attribution.** Identity, role and timestamp recorded.
6. **Attached to decisions.** Every `decision_record` stores the `policy_version_id` in force, so replay shows which rules applied at the time.

### What counts as "weakening"

For a `GT` control: raising `green_max` or `amber_max`.
For an `LT` control: lowering `green_min` or `amber_min`.
Also weakening: flipping `is_hard` from `true` to `false`.

> **Substantially** is defined as a relative change of more than 10% of the current band, or any `is_hard` demotion. Below that, log the change without the modal warning. `[DEMO-CONFIG]`

---

## 6. Circuit-breaker triggers

The breaker trips on any **hard** control reaching RED, in five categories:

### 6.1 Risk breach
`RISK_VOL_ANNUAL` · `RISK_CVAR_95` · `RC_ASSET_MAX` · `RC_SECTOR_MAX` · configured drawdown conditions

### 6.2 Constraint breach
`CONC_ASSET_MAX` · `CONC_SECTOR_MAX` · `LIQ_MIN_SHARE` · `LIQ_MIN_CASH` · `TXN_TURNOVER_MAX`

### 6.3 Market / data-integrity breach
`DATA_FRESHNESS` · `DATA_COMPLETENESS` · abnormal values detected in validation

### 6.4 Model / optimizer failure
`MODEL_SOLVER` (infeasible, non-convergent, unstable) · `MODEL_COVARIANCE` (not PSD and unrepairable)

### 6.5 Stress breach
`STRESS_LOSS_MAX` — a candidate that passes every ordinary control but breaches the configured severe-loss limit is **still rejected**.

> §6.5 is the one worth explaining to judges: ordinary historical metrics systematically understate correlated shocks, so a candidate can look compliant and still be unacceptable. Stress is an independent gate, not a report.

### Trip behaviour

```
Reject candidate
  → preserve Last Approved Safe Allocation      (never overwritten by a failure)
  → emit RED alert
  → persist DecisionRecord with circuit_breaker_active = 1
  → generate up to 3 recovery candidates
  → validate each independently (controls + stress)
  → require an explicit human decision
```

---

## 7. Stress scenarios `[DEMO-CONFIG]`

`config/scenarios.yaml`. Shocks are instantaneous returns applied by sector or asset.

| Code | Label | Shocks |
|---|---|---|
| `BROAD_CRASH` | Broad market crash | BROAD_EQUITY −20%, BANKING −22%, IT −18%, PHARMA −12%, GOLD +6%, GSEC −2% |
| `BANKING_CRISIS` | Banking-sector crisis | BANKING −25%, BROAD_EQUITY −10%, IT −5%, GOLD +8%, GSEC −1%, LIQUIDITY −20% |
| `IT_CORRECTION` | IT-sector correction | IT −22%, BROAD_EQUITY −7%, BANKING −4%, GOLD +2% |
| `RATE_SHOCK` | Interest-rate shock | GSEC −8%, BANKING −12%, BROAD_EQUITY −9%, GOLD −3% |
| `LIQUIDITY_SHOCK` | Liquidity shock | LIQUIDITY −40%, BROAD_EQUITY −8%, BANKING −11%, GSEC −5% |
| `COMBINED_SEVERE` | Combined severe | BROAD_EQUITY −25%, BANKING −30%, IT −22%, PHARMA −15%, GOLD +5%, GSEC −6%, LIQUIDITY −35% |
| `HISTORICAL_SEVERE` | Historically-inspired severe event | Calibrated to a large drawdown episode in the loaded history; documented in the scenario file |

The demo scenario in `14-DEMO-SCRIPT.md` uses a custom shock (Banking −18%, Broad −12%, IT −8%, Gold +5%), which is deliberately **milder** than `BANKING_CRISIS` — it must be severe enough to trip RED but plausible enough not to look staged.

### Custom scenarios

Users may enter arbitrary per-sector or per-asset shocks in the Stress Lab. Custom scenarios are recorded with `is_custom = 1` and their full shock vector, so a replayed decision shows exactly what was applied.

---

## 8. What these thresholds are not

State this plainly in the UI and in any presentation:

- They are **not** Basel, SEBI, RBI, or any regulator's capital or risk limits.
- They are **not** calibrated to a real institution's risk appetite.
- They are chosen so that a demonstration portfolio moves between GREEN, AMBER and RED under plausible market conditions within a short demo.
- A real deployment would derive them from an institution's investment policy statement, regulatory capital requirements and board-approved risk appetite.

Saying this openly is a strength, not a weakness: it shows the difference between a *configurable control framework* and a *hard-coded rulebook* is understood — and the framework is what has actually been built.

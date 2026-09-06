# 03 — Technical Requirements Document (TRD)

**Scope:** Numbered functional and non-functional requirements, technology decisions, performance budgets, and traceability.
**Audience:** Implementers (human and AI). Every requirement here is testable.
**Derived from:** master spec §41–§48, §51, §56.

Requirement IDs are stable. Reference them in commits, tests and PRs (e.g. `test_fr_042_circuit_breaker_preserves_last_safe`).

---

## 1. Technology decisions

| Concern | Choice | Rationale | Alternative rejected |
|---|---|---|---|
| Language | **Python 3.11+** | Financial library ecosystem; team fluency | — |
| Numerics | **NumPy, Pandas, SciPy** | Standard, well-tested | — |
| Convex optimization | **CVXPY** | Declarative constraints; multiple solver backends | Hand-rolled SLSQP — harder to express constraints and to prove feasibility |
| Market data | **jugaad-data** | Indian market/RBI coverage | yfinance — weaker Indian instrument coverage |
| UI | **Streamlit + Plotly** | Fastest path to an interactive dashboard in a 24h build | React/Next.js — cost not justified at this scope |
| Persistence | **SQLite** | Zero-ops, file-based, transactional, sufficient for an audit log | Postgres — operational overhead with no benefit here |
| Testing | **pytest** | Standard | — |
| VCS | **Git + GitHub** | Standard | — |
| API layer | **None** | Streamlit calls the service layer in-process | FastAPI — add *only* if a genuine separation need emerges |
| LLM | **Optional, provider-agnostic** | Explanation only; never a dependency | Any LLM in the decision path — prohibited |

### Excluded from the workflow by decision

Codebase Memory MCP · Skill Security Scanner · TradingAgents as a dependency · large multi-agent frameworks · unnecessary MCP servers. The goal is a compact engineering workflow, not an oversized agent stack.

### Development tooling (approved)

Claude Code (primary implementation agent) · Claude-Mem (cross-session context) · Prompt Master (prompt compression) · Graphify (codebase relationship inspection, once real architecture exists) · Anthropic Security Guidance (security review). Tooling MUST remain subordinate to shipping.

---

## 2. Functional requirements

### 2.1 Data layer — FR-001…FR-019

| ID | P | Requirement |
|---|---|---|
| FR-001 | P0 | The system MUST expose a `MarketDataProvider` abstraction with at least `JugaadDataProvider` and `CachedDataProvider` implementations. |
| FR-002 | P0 | The active provider MUST be selectable by configuration without code changes. |
| FR-003 | P0 | `CachedDataProvider` MUST be the default so the demo runs with no network access. |
| FR-004 | P0 | Cached demo snapshots MUST be committed to the repository and produce byte-identical analysis across runs. |
| FR-005 | P0 | All providers MUST return an identical, documented data shape (date-indexed price panel + metadata). |
| FR-006 | P0 | Validation MUST detect missing observations, stale data, absent expected columns, price/return discontinuities, non-trading-day artefacts and suspicious values. |
| FR-007 | P0 | A validation failure MUST raise a data-integrity **control event**, not a silently-computed portfolio. |
| FR-008 | P0 | Missing returns MUST NOT be coerced to zero. |
| FR-009 | P1 | Live-retrieval failure MUST automatically fall back to cache, with the fallback visibly indicated in the UI. |
| FR-010 | P1 | The system MUST record which provider and which data snapshot produced each decision. |

### 2.2 Portfolio — FR-020…FR-029

| ID | P | Requirement |
|---|---|---|
| FR-020 | P0 | The system MUST represent total capital, per-asset positions, weights, cash, current prices, portfolio value and historical portfolio returns. |
| FR-021 | P0 | Default demo capital MUST be ₹100 Cr, configurable. |
| FR-022 | P0 | The asset universe MUST contain 8–12 instruments spanning at least equity, banking, IT, a defensive sector, gold and a fixed-income proxy. |
| FR-023 | P0 | Weights MUST sum to 1.0 within a documented numerical tolerance. |
| FR-024 | P0 | The universe MUST be defined in configuration, not hard-coded in engine modules. |
| FR-025 | P1 | Turnover between two allocations MUST be computable and displayable. |

### 2.3 Risk engine — FR-030…FR-049

| ID | P | Requirement |
|---|---|---|
| FR-030 | P0 | MUST compute annualised historical volatility. |
| FR-031 | P0 | MUST compute EWMA volatility with a configurable, documented decay factor. |
| FR-032 | P0 | MUST display historical and EWMA volatility side by side. |
| FR-033 | P0 | MUST compute portfolio volatility from weights and the covariance matrix. |
| FR-034 | P0 | MUST compute Sharpe ratio against a configurable risk-free rate. |
| FR-035 | P0 | MUST compute historical VaR at a configurable confidence level (default 95%). |
| FR-036 | P0 | MUST compute historical CVaR at the same confidence level. |
| FR-037 | P0 | MUST compute current, rolling and maximum drawdown. |
| FR-038 | P1 | MUST compute per-asset marginal and component risk contribution, and percentage of total risk. |
| FR-039 | P1 | MUST aggregate risk contribution to sector level. |
| FR-040 | P1 | MUST compute asset-level and sector-level concentration. |
| FR-041 | P1 | MUST compute a liquidity metric (minimum liquid share; days-to-liquidate where volume data is reliable). |
| FR-042 | P2 | SHOULD compute parametric VaR for comparison. |
| FR-043 | P2 | SHOULD compute Monte Carlo VaR (default 10,000 paths) when performance allows. |
| FR-044 | P0 | The covariance matrix MUST be checked for numerical validity before use, with a documented repair-or-reject path. |
| FR-045 | P0 | Every risk computation MUST be a pure function of its inputs — no hidden global state. |

### 2.4 Optimizer — FR-050…FR-069

| ID | P | Requirement |
|---|---|---|
| FR-050 | P0 | MUST implement constrained maximum-Sharpe optimization as the default strategy. |
| FR-051 | P0 | MUST enforce, at minimum: full investment (Σw=1), per-asset bounds, sector caps, liquidity floor, turnover cap. |
| FR-052 | P0 | MUST report solver status and MUST NOT return weights when the solver did not converge. |
| FR-053 | P0 | MUST include a transaction-cost consideration in the objective or as a reported penalty. |
| FR-054 | P0 | MUST produce an `OptimizationResult` including expected return, volatility, Sharpe, VaR, CVaR, turnover, transaction cost and solver status. |
| FR-055 | P0 | MUST be able to produce an **unconstrained/optimal** candidate for the Safe vs Optimal comparison, clearly labelled as not policy-validated. |
| FR-056 | P1 | MUST implement minimum-volatility optimization. |
| FR-057 | P1 | MUST implement target-return optimization. |
| FR-058 | P1 | MUST implement CVaR minimisation. |
| FR-059 | P1 | MUST implement Hierarchical Risk Parity. |
| FR-060 | P1 | MUST implement Black-Litterman posterior returns with user-entered views and confidence, feeding constrained optimization. |
| FR-061 | P1 | MUST support expected-return estimation via historical mean, EWMA, or BL posterior, selectable by the user. |
| FR-062 | P0 | Expected returns MUST be labelled **"Model Estimates"** wherever displayed. |
| FR-063 | P0 | The optimizer MUST NOT write to portfolio state, audit records, or control state. |

### 2.5 Control engine — FR-070…FR-099

| ID | P | Requirement |
|---|---|---|
| FR-070 | P0 | An independent control module MUST re-validate every candidate against all hard controls. |
| FR-071 | P0 | The control module MUST NOT import the optimizer package. |
| FR-072 | P0 | The control module MUST re-derive metrics from raw inputs rather than trusting `OptimizationResult` values. |
| FR-073 | P0 | Every configured policy MUST resolve to exactly one of GREEN / AMBER / RED. |
| FR-074 | P0 | Overall risk state MUST be the most severe individual policy state. |
| FR-075 | P0 | State transition logic MUST live in a single centralised module. |
| FR-076 | P0 | Validation MUST check weight bounds, sector limits, liquidity, minimum cash, volatility, CVaR, drawdown policy, turnover, transaction cost, stress loss and numerical feasibility. |
| FR-077 | P0 | A hard control failure MUST trip the circuit breaker. |
| FR-078 | P0 | A tripped breaker MUST preserve the Last Approved Safe Allocation unchanged. |
| FR-079 | P0 | A tripped breaker MUST emit an alert and persist a decision record. |
| FR-080 | P1 | A tripped breaker MUST generate up to three recovery candidates. |
| FR-081 | P1 | Each recovery candidate MUST be independently validated before being offered for approval. |
| FR-082 | P0 | `ControlResult` MUST enumerate every failed control with the observed value, the threshold and the severity. |
| FR-083 | P0 | Thresholds MUST be loaded from configuration, editable in the UI. |
| FR-084 | P0 | Substantially weakening a hard threshold MUST show a policy-weakening warning and require explicit confirmation. |
| FR-085 | P0 | Threshold changes MUST be versioned and written to the audit trail. |

### 2.6 Stress testing — FR-100…FR-114

| ID | P | Requirement |
|---|---|---|
| FR-100 | P0 | MUST ship at least the documented default scenarios: broad market crash, banking crisis, IT correction, rate shock, liquidity shock, combined severe, historically-inspired severe. |
| FR-101 | P0 | MUST apply scenario shocks and report portfolio loss, per-asset contribution, post-shock risk and resulting policy breaches. |
| FR-102 | P0 | A candidate that passes ordinary controls but breaches the configured stress-loss limit MUST still be rejected. |
| FR-103 | P0 | A candidate MUST NOT be reported as validated if mandatory stress testing did not complete. |
| FR-104 | P1 | MUST support user-defined custom scenarios with per-sector/asset shocks. |
| FR-105 | P2 | MAY provide Monte Carlo simulation; it MUST NOT become a dependency of the core loop. |

### 2.7 Decisions, approval and audit — FR-115…FR-139

| ID | P | Requirement |
|---|---|---|
| FR-115 | P0 | MUST offer Approve, Reject and Keep Current Allocation actions. |
| FR-116 | P0 | Approve MUST be unavailable for a candidate that failed hard controls or stress validation. |
| FR-117 | P0 | A RED-state allocation MUST NOT have a normal one-click approval path. |
| FR-118 | P0 | Controlled Override MUST capture explicit confirmation, a reason, affected controls, timestamp and user identity/role. |
| FR-119 | P0 | Approval MUST trigger a **simulated** rebalance and a portfolio state update. |
| FR-120 | P0 | The system MUST NOT connect to a brokerage or place real orders. |
| FR-121 | P0 | Every material decision MUST persist a complete `DecisionRecord` (fields per `06-DATA-CONTRACTS.md` §7). |
| FR-122 | P0 | The audit log MUST distinguish automated system action, control-engine decision and human action. |
| FR-123 | P0 | Audit records MUST be append-only; no update or delete path may exist in application code. |
| FR-124 | P1 | Decision Replay MUST reconstruct a chronological incident timeline purely from persisted records. |
| FR-125 | P0 | A failed audit write MUST surface visibly and MUST NOT be reported as success. |

### 2.8 Explanation and LLM — FR-140…FR-154

| ID | P | Requirement |
|---|---|---|
| FR-140 | P0 | The deterministic engine MUST produce a structured `Explanation` object containing trigger, risk change, main contributors, optimizer used, candidate summary, control result, reasons and action. |
| FR-141 | P0 | The structured explanation is the source of truth for all narrative output. |
| FR-142 | P0 | A deterministic template narrator MUST render readable prose with no LLM present. |
| FR-143 | P2 | An optional LLM MAY convert the structured explanation into natural language. |
| FR-144 | P0 | The LLM MUST NOT choose weights, alter thresholds, modify risk scores, approve allocations, override the breaker, modify audit records or replace deterministic calculations. |
| FR-145 | P0 | LLM output MUST be stored and rendered as display text only, never parsed back into decision state. |
| FR-146 | P0 | The system MUST function fully with no API key configured. |

### 2.9 Backtesting — FR-155…FR-169

| ID | P | Requirement |
|---|---|---|
| FR-155 | P1 | MUST compare buy-and-hold, uncontrolled optimizer and CCE-controlled strategies. |
| FR-156 | P1 | MUST report cumulative return, annualised return, volatility, Sharpe, max drawdown, VaR, CVaR, turnover, transaction costs, policy-breach count and circuit-breaker activations. |
| FR-157 | P1 | Default rebalance frequency MUST be monthly, with weekly optional. |
| FR-158 | P0 | Each rebalance decision MUST use only data strictly prior to the decision date, applied to the following period. |
| FR-159 | P0 | Look-ahead prevention MUST be covered by an explicit test. |

### 2.10 Dashboard — FR-170…FR-189

| ID | P | Requirement |
|---|---|---|
| FR-170 | P0 | MUST provide Executive Overview, Portfolio & Exposure, Risk Control Center and Optimizer pages. |
| FR-171 | P1 | MUST provide Stress Lab, Backtesting, Decision Replay and Policy/Settings pages. |
| FR-172 | P0 | The Executive Overview MUST show portfolio value, expected return, both volatilities, Sharpe, VaR, CVaR, liquidity, risk state, top exposures and the current recommended action. |
| FR-173 | P0 | The UI MUST show current portfolio, optimal candidate and safe candidate as three distinct things. |
| FR-174 | P0 | Rejected candidates MUST display the specific reasons for rejection. |
| FR-175 | P0 | UI modules MUST contain no financial computation and MUST import only the service layer. |
| FR-176 | P0 | Colour MUST NOT be the only channel conveying risk state; a text label is required alongside. |

---

## 3. Non-functional requirements

### 3.1 Performance budgets

| ID | Operation | Budget | Notes |
|---|---|---|---|
| NFR-001 | Cold app start to rendered Overview | ≤ 5 s | with cached data |
| NFR-002 | Full risk snapshot (12 assets, ~3y daily) | ≤ 1 s | |
| NFR-003 | Single constrained optimization | ≤ 3 s | CVXPY, default solver |
| NFR-004 | Independent validation of one candidate | ≤ 500 ms | |
| NFR-005 | One stress scenario | ≤ 500 ms | |
| NFR-006 | Full stress suite (7 scenarios) | ≤ 3 s | |
| NFR-007 | Breaker trip → 3 validated recovery candidates | ≤ 10 s | the demo's longest wait |
| NFR-008 | Backtest, 3 strategies, 3y monthly | ≤ 30 s | may show a progress indicator |
| NFR-009 | Monte Carlo, 10,000 paths | ≤ 5 s | P2; degrade path count rather than block |

Any operation exceeding its budget MUST show a progress indicator rather than appearing frozen.

### 3.2 Reliability

| ID | Requirement |
|---|---|
| NFR-010 | The demo MUST run end-to-end with no internet connection. |
| NFR-011 | The demo MUST run end-to-end with no LLM API key. |
| NFR-012 | Identical inputs MUST produce identical outputs; every stochastic routine takes an explicit seed. |
| NFR-013 | No exception may be silently swallowed. Every `except` either handles meaningfully or re-raises. |
| NFR-014 | No engine may terminate the process; failures return typed error results to the service layer. |
| NFR-015 | The SQLite file MUST be recreatable from scratch by running migrations. |

### 3.3 Maintainability

| ID | Requirement |
|---|---|
| NFR-020 | Modules stay small and single-purpose; a module exceeding ~300 lines is a signal to split. |
| NFR-021 | All cross-module communication uses the typed contracts in `cce/contracts/`, not bare dicts. |
| NFR-022 | Public functions carry type hints and a docstring stating units and conventions. |
| NFR-023 | Every magic number lives in configuration or a named constant. |
| NFR-024 | The layer-dependency table in `02-ARCHITECTURE.md` §2 is enforced; a violation blocks merge. |

### 3.4 Security

| ID | Requirement |
|---|---|
| NFR-030 | No hard-coded API keys or secrets. Configuration via `.env`, with `.env.example` committed and `.env` git-ignored. |
| NFR-031 | No `eval`, `exec`, `pickle.load` on untrusted input, or shell execution from user input. |
| NFR-032 | All SQL uses parameterised queries. |
| NFR-033 | Secrets MUST NOT be rendered in the Streamlit UI or written to logs. |
| NFR-034 | LLM output MUST NOT be executed, parsed as code, or used as a control instruction. |
| NFR-035 | File reads/writes are restricted to project-relative configured paths. |

Detail in `12-SECURITY.md`.

### 3.5 Usability

| ID | Requirement |
|---|---|
| NFR-040 | A risk manager unfamiliar with CCE must understand the current state from the Overview within ~10 seconds. |
| NFR-041 | Every displayed number carries a unit and a period basis (e.g. "annualised", "1-day 95%"). |
| NFR-042 | Estimated quantities are visually distinguished from measured ones. |
| NFR-043 | Any figure derived from a fallback or degraded path is labelled as such. |

---

## 4. Configuration surface

| Variable | Default | Purpose |
|---|---|---|
| `CCE_DATA_PROVIDER` | `cached` | `cached` or `jugaad` |
| `CCE_DB_PATH` | `./data/cce.db` | SQLite audit store |
| `CCE_POLICY_FILE` | `./config/policy.yaml` | Risk thresholds |
| `CCE_UNIVERSE_FILE` | `./config/universe.yaml` | Asset universe |
| `CCE_SCENARIOS_FILE` | `./config/scenarios.yaml` | Stress scenarios |
| `CCE_RANDOM_SEED` | `42` | Reproducibility |
| `CCE_LLM_ENABLED` | `false` | Master switch for the explanation LLM |
| `CCE_LLM_API_KEY` | *(unset)* | Never committed |
| `CCE_LOG_LEVEL` | `INFO` | |

Rule: if `CCE_LLM_ENABLED=true` but no key is present, the system logs a warning and uses the deterministic narrator. It does not error.

---

## 5. Traceability

| Rubric / spec area | Requirements |
|---|---|
| Optimization strategy | FR-050…FR-063 |
| Control & safeguard system | FR-070…FR-099, FR-100…FR-105 |
| Decision dashboard | FR-170…FR-189, FR-124 |
| Financial & Control Logic (35%) | FR-030…FR-049, FR-050…FR-063, FR-070…FR-105 |
| Technical Architecture (30%) | FR-001…FR-010, NFR-020…NFR-024, FR-063, FR-071 |
| UX & Clarity (20%) | FR-170…FR-189, FR-140…FR-142, NFR-040…NFR-043 |
| Innovation (15%) | FR-055, FR-070…FR-072, FR-078…FR-081, FR-038, FR-124 |

### Safety-invariant coverage

Each invariant in `10-RULES.md` §2 maps to requirements and to a test in `tests/test_invariants.py`:

| Invariant | Requirements |
|---|---|
| INV-1 LLM cannot modify financial decisions | FR-144, FR-145, NFR-034 |
| INV-2 Invalid optimizer output cannot be approved | FR-052, FR-070, FR-116 |
| INV-3 Hard control failure cannot be ignored | FR-077, FR-082 |
| INV-4 Optimizer failure preserves last approved allocation | FR-078 |
| INV-5 Missing data is not zero risk | FR-007, FR-008 |
| INV-6 Every approval/rejection is auditable | FR-121, FR-122 |
| INV-7 No look-ahead in backtests | FR-158, FR-159 |
| INV-8 Threshold changes are versioned and audited | FR-085 |
| INV-9 Current / optimal / safe are distinct | FR-173 |
| INV-10 Stress failure stays visible | FR-102, FR-103 |
| INV-11 Risk state computed in one place | FR-075 |
| INV-12 UI holds no financial logic | FR-175, NFR-024 |

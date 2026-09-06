# 04 — Workflow

**Scope:** The runtime closed loop (what the system does), and the development loop (how we build it).
**Derived from:** master spec §6, §26, §28–§34, §49, §57–§58.

---

# Part A — Runtime workflow

## A0. The loop in one line

```
Detect → Optimize → Validate → Stress-Test → Explain → Approve → Audit
```

Each step has a defined input, output, owning module and failure behaviour. No step may be skipped, and no step may be performed by the UI.

---

## A1. The twelve steps

### Step 1 — Ingest market data
**Owner:** `cce/data/providers.py` → concrete provider
**Out:** raw price panel + provider metadata

Retrieve historical/current market data via `jugaad-data` where supported. The demo MUST be able to fall back to cached historical data. **Live external data must never be able to break the core demonstration.**

**On failure:** fall back to cache, mark `data_source=CACHED_FALLBACK`, continue, and show the fallback in the UI.

---

### Step 2 — Validate data
**Owner:** `cce/data/validation.py`
**Out:** `ValidationReport` (valid / invalid + findings)

Before any calculation, detect: missing observations · stale data · absent expected columns · price/return discontinuities · non-trading-day artefacts · suspicious values.

**On failure:** a data-integrity failure is a **control event**, not a warning to ignore. Do not recompute risk. Preserve prior state and surface the problem. `[INV-5]`

---

### Step 3 — Build portfolio state
**Owner:** `cce/portfolio/state.py`
**Out:** `PortfolioState`

Represent total capital, per-asset positions, weights, cash/liquid assets, current prices, portfolio value and the historical portfolio return series. Default demo capital: **₹100 Cr**.

---

### Step 4 — Calculate risk
**Owner:** `cce/risk/engine.py`
**Out:** `RiskSnapshot`

Compute historical volatility · EWMA volatility · portfolio volatility · Sharpe · historical VaR · historical CVaR · parametric VaR · Monte Carlo VaR (where feasible) · maximum and rolling drawdown · concentration · sector exposure · risk contribution · liquidity metrics · turnover.

Every function here is pure: same inputs → same outputs, no I/O.

---

### Step 5 — Determine risk state
**Owner:** `cce/controls/state_machine.py`
**Out:** `RiskState` + `list[Breach]`

Each configured policy is classified GREEN (healthy) / AMBER (approaching threshold) / RED (hard breach or critical). The portfolio state is the **most severe** individual policy state.

This is the only place in the codebase where a risk state is computed. `[INV-11]`

---

### Step 6 — Trigger optimization
**Owner:** `cce/services/optimization_service.py`

Triggers: user request · scheduled/rebalance cadence · risk deterioration · a market or stress scenario.

The trigger is recorded — it becomes the first line of the explanation and the Decision Replay timeline.

---

### Step 7 — Generate candidate portfolios
**Owner:** `cce/optimizer/`
**Out:** `OptimizationResult` (one per requested strategy)

| Order | Strategy | Role |
|---|---|---|
| 1 | Maximum Sharpe / constrained MVO | **default** |
| 2 | Minimum volatility | defensive alternative |
| 3 | Target return | user-chosen return objective |
| 4 | CVaR minimisation | tail-risk-aware |
| 5 | HRP | expected-return-independent |
| 6 | Black-Litterman + constrained allocation | view-driven |

For the Safe vs Optimal view, an **unconstrained/optimal** candidate is also produced and explicitly labelled as *not policy-validated*.

**On failure:** solver non-convergence returns a failed result with status. It MUST NOT return weights. `[INV-2]`

---

### Step 8 — Validate independently
**Owner:** `cce/controls/validation.py` — **does not import the optimizer**
**Out:** `ControlResult`

Re-derive and check: weight bounds · sector limits · liquidity · minimum cash · volatility · CVaR · drawdown policy · turnover · transaction cost · stress loss · numerical feasibility.

The validator recomputes every metric from raw returns and weights. It never trusts a number the optimizer reported about itself.

**On failure:** trip the circuit breaker (Step 8b).

---

### Step 8b — Circuit breaker (only on hard failure)
**Owner:** `cce/controls/circuit_breaker.py`

```
Reject candidate
  → preserve Last Approved Safe Allocation   (never overwritten)
  → emit alert
  → persist DecisionRecord
  → generate up to 3 recovery candidates
  → validate each independently (+ stress)
  → require explicit human decision
```

Recovery candidates: **Max-Sharpe Recovery**, **Minimum-Risk Recovery**, **Defensive/Liquidity Recovery**. Each must pass hard controls on its own before it is offered. `[INV-4]`

---

### Step 9 — Stress test
**Owner:** `cce/stress/engine.py`
**Out:** `StressResult`

A candidate that passes ordinary constraints must still survive the configured scenarios. If it breaches the configured severe stress-loss limit, it is rejected **even though normal metrics passed** — because historical metrics systematically understate correlated shocks.

**On failure of the engine itself:** the candidate is `NOT_VALIDATED`, never `PASSED`. `[INV-10]`

---

### Step 10 — Explain
**Owner:** `cce/decisions/explanation.py` → `narrator.py` → optional `llm.py`
**Out:** `Explanation`

Structured, deterministic fields: trigger · changed risk · major contributors · proposed action · rejected constraints · stress results · expected improvement.

```
Deterministic Financial Engine
          ↓
Structured Explanation (source of truth)
          ↓
Deterministic template narrator   ─────► prose (always available)
          ↓ (optional)
        LLM                       ─────► richer prose (display only)
```

The LLM never re-enters the decision path. If it is absent or fails, the template narrator serves. `[INV-1]`

---

### Step 11 — Human decision
**Owner:** `cce/services/approval_service.py`

| Action | Precondition |
|---|---|
| Approve | candidate passed all hard controls **and** stress validation |
| Reject | always available |
| Keep Current Allocation | always available |
| Controlled Override | only via the override flow, with reason + confirmation |

A RED-state allocation has no normal one-click approval path. Approval performs a **simulated** rebalance and updates portfolio state; the approved allocation becomes the new Last Approved Safe Allocation.

---

### Step 12 — Record audit event
**Owner:** `cce/audit/repository.py`
**Out:** persisted `DecisionRecord`

Store the complete decision chain (fields in `06-DATA-CONTRACTS.md` §7 and `05-BACKEND-SCHEMA.md` §3). Records are append-only. A failed write surfaces visibly and is never reported as success. `[INV-6]`

---

## A2. Sequence — the happy path

```
User/Trigger      Service          Risk      Optimizer   Controls   Stress   Audit
    │                │               │           │           │        │        │
    ├─ optimize ────▶│               │           │           │        │        │
    │                ├─ snapshot ───▶│           │           │        │        │
    │                │◀── RiskSnapshot           │           │        │        │
    │                ├─ classify ────────────────────────────▶│       │        │
    │                │◀── RiskState=GREEN ───────────────────┤        │        │
    │                ├─ propose ────────────────▶│            │       │        │
    │                │◀── OptimizationResult ────┤            │       │        │
    │                ├─ validate (independent) ──────────────▶│       │        │
    │                │◀── ControlResult=PASSED ──────────────┤        │        │
    │                ├─ stress ──────────────────────────────────────▶│        │
    │                │◀── StressResult=PASSED ──────────────────────┤          │
    │                ├─ explain ──────────────────────────────────────────┐    │
    │◀── Recommendation + Explanation ◀───────────────────────────────────┘    │
    ├─ APPROVE ─────▶│                                                         │
    │                ├─ simulated rebalance, update state                      │
    │                ├─ persist DecisionRecord ───────────────────────────────▶│
    │◀── new PortfolioState + confirmation                                     │
```

## A3. Sequence — the breaker path (the demo story)

```
Shock applied
    │
    ├─▶ Risk recomputed:  EWMA vol 11.8% → 15.6%
    │                     Banking risk contribution 27% → 41%
    │                     CVaR crosses RED threshold
    │
    ├─▶ State machine: GREEN → RED
    │
    ├─▶ Optimizer proposes Max-Sharpe candidate (Banking 43%)
    │
    ├─▶ Independent validation: FAIL
    │       • Banking concentration 43% > 40%
    │       • CVaR 9.4% > 8%
    │       • Severe stress loss > limit
    │
    ├─▶ CIRCUIT BREAKER ACTIVE
    │       • candidate rejected
    │       • Last Approved Safe Allocation preserved
    │       • alert emitted
    │
    ├─▶ 3 recovery candidates generated and independently validated
    │
    ├─▶ Explanation produced (structured → prose)
    │
    ├─▶ Human approves Minimum-Risk Recovery
    │
    ├─▶ Simulated rebalance → new Last Approved Safe Allocation
    │
    └─▶ DecisionRecord persisted → visible in Decision Replay
```

---

## A4. Decision Replay timeline

Replay reconstructs the incident **only from persisted records** — no recomputation, no live state.

```
10:02  Market shock detected                      [MACHINE]
10:02  EWMA volatility increased                  [MACHINE]
10:02  Banking risk contribution increased        [MACHINE]
10:03  CVaR crossed RED threshold                 [CONTROL]
10:03  Circuit breaker activated                  [CONTROL]
10:04  Max-Sharpe candidate generated             [MACHINE]
10:04  Candidate failed concentration + CVaR      [CONTROL]
10:04  Candidate rejected                         [CONTROL]
10:05  Three recovery candidates generated        [MACHINE]
10:05  Stress validation completed                [CONTROL]
10:06  Risk Manager approved Min-Risk Recovery    [HUMAN]
10:06  Simulated rebalance applied                [MACHINE]
10:06  Audit event stored                         [MACHINE]
```

Each row is tagged `MACHINE` / `CONTROL` / `HUMAN` and rendered with a distinct visual treatment. The distinction is the point: it shows where automation ended and judgement began.

---

## A5. Backtest workflow (no look-ahead)

At every rebalance date `t`:

```
Data strictly BEFORE t
        ↓
Estimate expected returns and covariance
        ↓
Optimize
        ↓
Validate (controls + stress)
        ↓
Apply resulting weights to period [t, t+1)
        ↓
Record realised return, turnover, cost, breaches
```

No observation at or after `t` may influence the decision made at `t`. This is enforced by a test that shifts future returns and asserts the decision at `t` is unchanged. `[INV-7]`

Compared strategies: buy-and-hold · uncontrolled optimizer · CCE-controlled.
Reported: return, volatility, Sharpe, max drawdown, VaR, CVaR, turnover, transaction costs, **policy-breach count**, **circuit-breaker activations**.

The claim being tested is not "CCE made more money". It is: *did CCE improve the balance between return and risk while reducing policy breaches and drawdowns?*

---

# Part B — Development workflow

## B1. Build order

Do **not** start with the dashboard. The dashboard is a window onto a working engine; building it first produces a demo with nothing behind it.

| Phase | Deliverable | Done when |
|---|---|---|
| 1 | Data | A reproducible cached dataset loads and validates |
| 2 | Portfolio | Positions, weights, returns computed correctly |
| 3 | Risk | EWMA, volatility, VaR, CVaR, drawdown, risk contribution, all unit-tested |
| 4 | Optimizer | Constrained Max Sharpe returns a feasible allocation |
| 5 | Control | Policies, GREEN/AMBER/RED, independent validation |
| 6 | Circuit breaker | Rejection + Last Approved Safe Allocation preserved |
| 7 | Stress | Default scenarios gate candidates |
| 8 | Human approval | State transitions on Approve/Reject/Keep |
| 9 | Audit | Decision records persist and read back |
| 10 | Dashboard | The working engine becomes visible |
| 11 | Alternatives | HRP, Black-Litterman, other optimizers |
| 12 | Backtest | Controlled vs uncontrolled comparison |
| 13 | LLM | Only after everything deterministic is stable |
| 14 | Polish | Build the demo around the failure/recovery story |

## B2. Definition of done for a module

1. Contracts in `cce/contracts/` defined first.
2. Pure functions with type hints and unit-stating docstrings.
3. Unit tests, including at least one hand-computed expected value.
4. No layer-dependency violations (`02-ARCHITECTURE.md` §2).
5. Any threshold or constant moved to configuration.
6. Any relevant safety invariant covered by a test in `tests/test_invariants.py`.

## B3. Working with AI agents

- `CLAUDE.md` is loaded automatically each session — it is the constitution, not a suggestion.
- Reference documents explicitly in prompts: *"implement `cce/risk/ewma.py` per `08-FINANCIAL-METHODS.md` §3 and `06-DATA-CONTRACTS.md` §3"*.
- Ask for **one module at a time**. Multi-module generation is where layer violations enter.
- After any generated financial function, verify against a hand-computed case before moving on.
- If generated code makes the UI compute a metric, reject it. That is the most common and most damaging drift.
- When docs and generated code disagree, the docs win — or the doc is updated deliberately in the same commit.

## B4. Commit discipline

> Authoritative version: `CLAUDE.md` § GIT & COMMIT DISCIPLINE.

Commit at every completed, coherent unit of work — a module plus its tests, a fixed bug
plus its regression test, a finished build phase. Not at the end of a session, and not
after every file save.

```
type(scope): imperative subject, max ~70 chars

Why this change exists, and what it affects. Not a restatement of the
diff — git already has the diff.

Refs: FR-031, INV-4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

- **One logical change per commit.** Never mix a refactor with a behaviour change.
- **Reference `FR-`/`NFR-`/`INV-` IDs** so `git log --grep` and `git bisect` work when it matters.
- **Push after every 2–3 commits**, and before anything risky.
- **Tag known-good demo states**: `git tag -a demo-ok-1 -m "..."`. At 2am this is the
  difference between a demo and no demo.
- Never commit `.env`, real API keys, a populated `cce.db`, or `.venv/`.
- **Do** commit the cached demo snapshots — reproducibility depends on them.
- A commit that changes a threshold must also update `config/policy.yaml` and note the version bump.
- Never commit with a safety-invariant test failing.

### Phase commits

Each phase in the table above (§B1) ends in at least one commit. A phase that is not
committed is a phase you cannot roll back to.

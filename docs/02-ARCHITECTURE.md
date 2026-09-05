# 02 — Architecture

**Scope:** Logical layers, module map, dependency rules, control flow, state machine, fail-safe design.
**Derived from:** master spec §5, §41–§47, §58–§59.

---

## 1. Architectural thesis

CCE is a **closed-loop control system wrapped around an optimizer**, not an optimizer with some checks bolted on. The architecture exists to make one property structurally true rather than merely intended:

> The component that proposes an allocation cannot be the component that approves it.

Everything below serves that separation.

---

## 2. Layered view

```
┌──────────────────────────────────────────────────────────────┐
│  L5  PRESENTATION            ui/  (Streamlit + Plotly)        │
│      Renders results. Zero financial logic.                   │
└───────────────────────────┬──────────────────────────────────┘
                            │  calls only
┌───────────────────────────▼──────────────────────────────────┐
│  L4  APPLICATION / SERVICE   cce/services/                    │
│      Orchestrates the loop. Owns transactions & sequencing.   │
│      The ONLY layer the UI may import.                        │
└───────────────────────────┬──────────────────────────────────┘
                            │
      ┌─────────────┬───────┴───────┬──────────────┬────────────┐
      ▼             ▼               ▼              ▼            ▼
┌───────────┐ ┌───────────┐  ┌────────────┐ ┌──────────┐ ┌──────────┐
│ L3 RISK   │ │ L3 OPTIM  │  │ L3 CONTROL │ │ L3 STRESS│ │ L3 BACK  │
│ cce/risk  │ │cce/optim..│  │cce/controls│ │cce/stress│ │cce/back..│
│           │ │           │  │ INDEPENDENT│ │          │ │          │
└─────┬─────┘ └─────┬─────┘  └─────┬──────┘ └────┬─────┘ └────┬─────┘
      │             │              │             │            │
      └─────────────┴──────────────┴─────────────┴────────────┘
                            │  all read
┌───────────────────────────▼──────────────────────────────────┐
│  L2  DOMAIN MODEL            cce/portfolio/, cce/contracts/   │
│      PortfolioState, RiskSnapshot, OptimizationResult, ...    │
│      Pure data. No I/O. No dependencies on L3+.               │
└───────────────────────────┬──────────────────────────────────┘
                            │
┌───────────────────────────▼──────────────────────────────────┐
│  L1  DATA & PERSISTENCE      cce/data/, cce/audit/            │
│      MarketDataProvider abstraction · SQLite audit store      │
└──────────────────────────────────────────────────────────────┘
```

### Layer contract

| Layer | May import | MUST NOT import |
|---|---|---|
| L5 UI | L4 services, L2 contracts (for typing only) | L1, L3 — **any engine** |
| L4 Services | L1, L2, L3 | L5 |
| L3 Engines | L1 (data only), L2 | L4, L5, *and each other* except as noted in §4 |
| L2 Domain | stdlib, numpy/pandas | L1, L3, L4, L5 |
| L1 Data | stdlib, jugaad-data, sqlite3 | L2+ business logic |

Violations of this table are architectural bugs, not style preferences. See `10-RULES.md` §3.

---

## 3. Logical dataflow

```text
                    ┌─────────────────────────┐
                    │     Market Data Layer   │
                    │   NSE/RBI via jugaad    │
                    │     + cached fallback   │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │    Data Validation      │
                    │ freshness / missingness │
                    │ outliers / consistency  │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │     Portfolio State     │
                    │ positions / cash / NAV  │
                    │ weights / returns       │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │       Risk Engine       │
                    │ EWMA + historical vol   │
                    │ VaR / CVaR / drawdown   │
                    │ risk contribution       │
                    │ concentration/liquidity │
                    └────────────┬────────────┘
                                 ▼
                    ┌─────────────────────────┐
                    │   Control / Trigger     │
                    │  GREEN / AMBER / RED    │
                    │ breach classification   │
                    └───────┬─────────┬───────┘
                            │         │
                     NORMAL/WARN   CRITICAL
                            │         │
                            ▼         ▼
                   ┌────────────┐ ┌──────────────────┐
                   │ Optimizer  │ │ Circuit Breaker  │
                   │ MVO / HRP  │ │ preserve last    │
                   │ BL / CVaR  │ │ approved safe    │
                   └─────┬──────┘ └────────┬─────────┘
                         ▼                 │
                   ┌────────────┐          │
                   │ Constraint │◄─────────┘
                   │ Validation │
                   └─────┬──────┘
                         ▼
                   ┌────────────┐
                   │  Stress    │
                   │  Engine    │
                   └──┬──────┬──┘
                  PASS│      │FAIL
                      ▼      ▼
             ┌────────────┐ ┌──────────────┐
             │Explanation │ │ Reject +     │
             │ Generator  │ │ Last Safe    │
             └─────┬──────┘ └──────┬───────┘
                   └───────┬───────┘
                           ▼
                  ┌──────────────────┐
                  │  Human Approval  │
                  │ Approve/Reject/  │
                  │ Keep/Override    │
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │ Simulated Trade  │
                  │ Portfolio Update │
                  └────────┬─────────┘
                           ▼
                  ┌──────────────────┐
                  │ Audit / Replay   │
                  └──────────────────┘
```

---

## 4. Module map

```text
cce/
├── app.py                      # Streamlit entrypoint. Routing only.
├── CLAUDE.md                   # -> imports docs/CLAUDE.md
├── requirements.txt
├── .env.example
│
├── config/
│   ├── policy.yaml             # Risk thresholds  (see 07-RISK-POLICY.md)
│   ├── universe.yaml           # Asset universe definition
│   └── scenarios.yaml          # Default stress scenarios
│
├── data/
│   ├── raw/                    # Untouched provider output
│   ├── processed/              # Cleaned, aligned price/return panels
│   └── cache/                  # Deterministic demo snapshots (COMMITTED)
│
├── cce/
│   ├── contracts/              # L2 — dataclasses, enums, no logic
│   │   ├── enums.py            # RiskState, ControlStatus, HumanAction...
│   │   ├── portfolio.py        # PortfolioState, Position
│   │   ├── risk.py             # RiskSnapshot, Breach
│   │   ├── optimization.py     # OptimizationResult, Constraints
│   │   ├── control.py          # ControlResult, StressResult
│   │   └── decision.py         # DecisionRecord, Explanation
│   │
│   ├── data/                   # L1
│   │   ├── providers.py        # MarketDataProvider ABC
│   │   ├── jugaad_provider.py  # Live Indian market data
│   │   ├── cache.py            # CachedDataProvider (demo default)
│   │   └── validation.py       # Freshness, gaps, outliers, continuity
│   │
│   ├── portfolio/              # L2
│   │   ├── models.py
│   │   ├── state.py            # Build/update PortfolioState
│   │   └── calculations.py     # Weights, NAV, returns, turnover
│   │
│   ├── risk/                   # L3 — pure functions over returns/weights
│   │   ├── volatility.py       # Historical, annualisation
│   │   ├── ewma.py             # EWMA variance + covariance
│   │   ├── covariance.py       # Estimation + PSD repair
│   │   ├── var.py              # Historical / parametric / Monte Carlo
│   │   ├── cvar.py
│   │   ├── drawdown.py
│   │   ├── concentration.py
│   │   ├── risk_contribution.py
│   │   ├── liquidity.py
│   │   └── engine.py           # Assembles a RiskSnapshot
│   │
│   ├── optimizer/              # L3 — proposes only
│   │   ├── base.py             # Optimizer ABC, Constraints -> Result
│   │   ├── constraints.py      # Convex constraint construction
│   │   ├── mean_variance.py    # Max Sharpe (default)
│   │   ├── min_volatility.py
│   │   ├── target_return.py
│   │   ├── cvar_optimizer.py
│   │   ├── hrp.py
│   │   ├── black_litterman.py
│   │   └── expected_returns.py # Historical / EWMA / BL posterior
│   │
│   ├── controls/               # L3 — INDEPENDENT authority
│   │   ├── policy.py           # Load + version thresholds
│   │   ├── validation.py       # Re-check candidate against ALL controls
│   │   ├── state_machine.py    # GREEN/AMBER/RED transitions
│   │   ├── circuit_breaker.py  # Trip logic, safe-allocation preservation
│   │   └── recovery.py         # Generate + validate recovery candidates
│   │
│   ├── stress/                 # L3
│   │   ├── scenarios.py        # Default + custom scenario definitions
│   │   ├── engine.py           # Apply shock, recompute, gate
│   │   └── monte_carlo.py      # [P2]
│   │
│   ├── decisions/              # L3/L4 boundary
│   │   ├── explanation.py      # Structured Explanation objects
│   │   ├── narrator.py         # Deterministic template -> prose
│   │   ├── llm.py              # OPTIONAL: Explanation -> prose. Read-only.
│   │   └── replay.py           # Reconstruct timeline from audit records
│   │
│   ├── audit/                  # L1
│   │   ├── database.py         # SQLite connection, migrations
│   │   ├── repository.py       # Typed read/write of DecisionRecord
│   │   └── events.py           # Event emission helpers
│   │
│   ├── backtest/               # L3
│   │   ├── engine.py           # Walk-forward loop, no look-ahead
│   │   └── metrics.py          # Comparison metrics
│   │
│   └── services/               # L4 — the ONLY thing UI touches
│       ├── portfolio_service.py
│       ├── risk_service.py
│       ├── optimization_service.py   # Orchestrates propose->validate->stress
│       ├── approval_service.py       # Human actions, simulated rebalance
│       ├── stress_service.py
│       └── backtest_service.py
│
├── ui/                         # L5 — rendering only
│   ├── overview.py             ├── stress.py
│   ├── portfolio.py            ├── backtest.py
│   ├── risk.py                 ├── replay.py
│   ├── optimizer.py            └── settings.py
│   └── components/             # Reusable widgets, formatters, colour map
│
└── tests/
    ├── test_risk.py            ├── test_stress.py
    ├── test_optimizer.py       ├── test_backtest.py
    ├── test_controls.py        ├── test_invariants.py   # safety invariants
    └── fixtures/               # Deterministic synthetic + snapshot data
```

> The structure MAY be flattened during implementation if that improves speed **without collapsing the optimizer/controls separation**. That separation is not negotiable.

---

## 5. The independence rule, concretely

`cce/controls/validation.py` MUST NOT import anything from `cce/optimizer/`.

It receives a plain weight vector plus the domain contracts and re-derives every metric it needs from `cce/risk/`. It does not trust, read, or reuse any number the optimizer reported about its own output.

```python
# controls/validation.py  — correct shape
def validate(
    candidate_weights: np.ndarray,
    universe: Universe,
    returns: pd.DataFrame,
    current_weights: np.ndarray,
    policy: Policy,
) -> ControlResult:
    """Re-derive every metric independently. Never trust OptimizationResult."""
```

**Why this matters:** if the control layer read `OptimizationResult.cvar`, a bug or a numerically optimistic solver would propagate straight through the safety gate. Independent re-derivation means an optimizer bug produces a *rejection*, not an approval.

---

## 6. Control-engine state machine

```text
         ┌──────────────────────────────────────────┐
         │                 GREEN                    │
         │  normal monitoring, optimization allowed │
         └───────┬───────────────────────┬──────────┘
      soft breach│                       │hard breach
                 ▼                       ▼
         ┌────────────────┐      ┌─────────────────────────┐
         │     AMBER      │─────▶│          RED            │
         │ warn + explain │ hard │ circuit breaker ACTIVE  │
         │ optimize OK    │breach│ candidate rejection      │
         │ no auto-freeze │      │ last safe preserved      │
         └───────┬────────┘      │ human decision required  │
      recovery   │               └───────────┬─────────────┘
                 ▼                           │
              GREEN            validated recovery + approval
                                             │
                                             ▼
                                        GREEN / AMBER
                                (else: remain RED)
```

### Transition rules

| From | Trigger | To |
|---|---|---|
| GREEN | any soft threshold crossed | AMBER |
| GREEN | any hard threshold crossed | RED |
| AMBER | all metrics back inside green bands | GREEN |
| AMBER | any hard threshold crossed | RED |
| RED | recovery candidate passes hard controls **and** stress **and** is human-approved | GREEN or AMBER (per re-evaluated metrics) |
| RED | no approved recovery | RED (persist) |

**Centralisation rule:** all transition logic lives in `cce/controls/state_machine.py`. No UI file, service, or engine may compute a risk state locally. `[INV-11]`

---

## 7. Circuit breaker

### Trigger categories

| Category | Examples |
|---|---|
| **Risk breach** | volatility, VaR/CVaR, drawdown, risk contribution |
| **Constraint breach** | asset weight, sector cap, liquidity floor, turnover cap |
| **Market/data integrity** | stale data, missing critical observations, abnormal values |
| **Model/optimizer failure** | infeasible problem, invalid covariance, numerical failure, unstable output |
| **Stress breach** | scenario loss above the configured limit |

### Behaviour

```text
Candidate generated
        ↓
Hard validation (independent)
        ↓
      FAIL
        ↓
Reject candidate
        ↓
Preserve Last Approved Safe Allocation      ← never overwritten by a failure
        ↓
Emit alert + persist DecisionRecord
        ↓
Generate up to 3 recovery candidates
        ↓
Validate each independently (+ stress)
        ↓
Require explicit human decision
```

### Recovery candidates

| Candidate | Objective |
|---|---|
| **Max-Sharpe Recovery** | Best risk-adjusted return *within* all hard controls |
| **Minimum-Risk Recovery** | Minimise portfolio volatility subject to controls |
| **Defensive / Liquidity Recovery** | Maximise liquidity and defensive exposure |

Each MUST pass hard controls independently before being offered. A recovery candidate that fails validation is **not shown as an option** — it is shown as an attempted-and-rejected alternative, with reasons.

This converts the breaker from a "stop" into a decision-support mechanism.

---

## 8. Data layer design

```python
MarketDataProvider (ABC)
    ├── JugaadDataProvider    # live NSE/RBI retrieval
    └── CachedDataProvider    # committed snapshots — the demo default
```

Rules:

- The UI MUST NEVER import `jugaad_data` or any provider implementation directly.
- Provider selection is configuration, not code (`CCE_DATA_PROVIDER=cached|jugaad`).
- `CachedDataProvider` is the **default for the demo**. Live retrieval is an enhancement, never a dependency.
- Every provider returns the same validated shape; validation runs after *any* provider.
- A validation failure is a **control event** (`DataIntegrityBreach`), never a silently-substituted zero.

See `13-EDGE-CASES.md` §2 for the exact behaviour of each data failure.

---

## 9. Fail-safe design

| Failure | Behaviour | MUST NOT |
|---|---|---|
| **Optimizer fails / infeasible** | Reject candidate → preserve last approved allocation → show model alert | Fall back to equal weights or the previous *unvalidated* candidate |
| **Market data missing/stale** | Mark data state invalid → do not recompute metrics → preserve prior state | Treat missing returns as zero |
| **Covariance not PSD** | Attempt documented repair → if repair fails, reject the optimization run | Silently pass a broken matrix to the solver |
| **Stress engine fails** | Candidate is `NOT_VALIDATED`, never `PASSED` | Present it as fully validated |
| **Database write fails** | Fail visibly in the UI | Claim an audit record was stored |
| **LLM unavailable / errors** | Fall back to the deterministic template narrator | Block the decision loop |

Governing principle: **on failure, do less, not something different.**

---

## 10. Production evolution (out of scope)

Documented so the prototype is legible as a step toward a real system, not mistaken for one:

```text
Market Data Streams → Data Validation/Normalization → Portfolio & Position Service
  → Risk Service → Optimization Service → Independent Policy Control Service
  → Stress/Scenario Service → Approval Workflow → Execution Management
  → Audit / Reporting
```

Production additions would include authentication, RBAC/SSO, event streaming, distributed services, an enterprise database, broker/EMS integration, regulatory policy libraries, model governance and versioning, and monitoring. **None of these are required for the hackathon MVP**, and adding them would weaken it.

---

## 11. Key engineering rule

The Streamlit UI MUST NEVER contain financial decision logic.

```text
BAD                          GOOD
Button click                 UI
  → calculate risk             ↓
  → modify weights           Service layer
                               ↓
                             Risk / Optimizer / Control engines
                               ↓
                             Decision result
                               ↓
                             UI renders result
```

This keeps the system testable, modular, explainable, and convertible into an API later without rewriting the domain.

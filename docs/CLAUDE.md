# CLAUDE.md — Project Constitution

**Loaded every session.** This is the operating constitution for CCE. Follow it exactly; it overrides default behaviour.

---

## PROJECT

**CCE — Capital Control Engine**
INIT'26 FinTech Hackathon — Asset & Capital Management / Optimization Controls
₹100 crore institutional demo portfolio · Indian market data · Streamlit dashboard

## MISSION

Build an institutional capital-management prototype that optimizes risk-adjusted allocation while **independently** enforcing safety controls.

## CORE LOOP

```
Detect → Optimize → Validate → Stress-Test → Explain → Human Approval → Audit
```

## THE PRODUCT PRINCIPLE

> **Optimal ≠ Safe.** The highest-return mathematical allocation is not automatically the allocation an institution should accept. CCE separates optimality from safety, and shows both.

---

## THE THREE RULES

1. **The optimizer proposes. The control engine disposes.** Separate modules. `cce/controls/` MUST NOT import `cce/optimizer/`, and MUST re-derive every metric from raw returns rather than trusting `OptimizationResult`.
2. **On failure, do less — never something different.** Preserve the Last Approved Safe Allocation. Never invent an allocation, never relax a constraint to produce an answer.
3. **The LLM writes prose. It never writes decisions.**

---

## ARCHITECTURE — non-negotiable

```
ui/            → may import ONLY cce.services and cce.contracts
cce/services/  → orchestrates; the only layer the UI touches
cce/risk/      → pure functions; no I/O
cce/optimizer/ → proposes only; never writes state
cce/controls/  → INDEPENDENT authority; does NOT import optimizer
cce/stress/    → independent gate
cce/contracts/ → pure data; imports nothing from cce
cce/data/      → provider abstraction; cached is the default
cce/audit/     → append-only SQLite; the ONLY database access
```

**The Streamlit UI must never contain financial decision logic.**

```
BAD                        GOOD
Button click               UI → service layer → engines → result → UI renders
  → calculate risk
  → modify weights
```

---

## DATA

- Use `jugaad-data` for supported Indian market data.
- **`CachedDataProvider` is the default.** The demo must run with no network and no API key.
- Live retrieval failure falls back to cache, marked `CACHED_FALLBACK` and shown in the UI.
- Validation failure is a **control event**, not a warning to ignore.
- **Missing data is never zero-filled.** `None` means *not computed*; it renders as `—`, never `0`.

---

## CORE FINANCIAL METHODS (build these)

Mean-Variance Optimization · EWMA volatility · historical VaR · historical CVaR · risk contribution · concentration controls · liquidity constraints · transaction costs · turnover constraints · stress testing · basic backtesting.

## ALTERNATIVE METHODS (after the core works)

HRP · Black-Litterman · minimum volatility · target return · CVaR optimization · parametric VaR · Monte Carlo where feasible.

---

## SAFETY

- GREEN / AMBER / RED states; portfolio state is the **most severe** control state
- Circuit breaker on any hard RED
- Last Approved Safe Allocation preserved on every failure
- Independent constraint validation
- Human approval required before any (simulated) rebalance
- Full decision audit, append-only

### The twelve safety invariants

Each has a test in `tests/test_invariants.py`. Full text in `docs/10-RULES.md` §2.

1. The LLM cannot modify financial decisions
2. An invalid optimizer output cannot become an approved allocation
3. A hard control failure cannot be silently ignored
4. If optimization fails, retain the last approved allocation
5. Missing critical market data is not zero risk
6. Every approval and rejection is auditable
7. Backtesting must not use future information
8. Threshold changes are versioned and audited
9. Current, optimal and safe allocations stay distinct
10. A stress-test failure remains visible even if normal metrics pass
11. Risk state is computed in exactly one place
12. The UI contains no financial logic

---

## LLM

**Explanation-only.**

Allowed: summarise risk · explain a decision in natural language · describe scenario assumptions · turn structured metrics into a briefing.

Never: choose weights · alter thresholds · modify risk scores · approve allocations · override the circuit breaker · modify audit records · replace deterministic calculations.

```
Deterministic engine → structured Explanation → LLM → display text
                             ▲                              │
                             └──────── NO PATH BACK ────────┘
```

LLM output is stored and rendered as display text. It is never parsed back into decision state, never executed, never used as an instruction. The system works fully with no API key.

---

## DO NOT

- Build a retail stock-picking app
- Build an autonomous trading bot
- Use TradingAgents as a dependency
- Add unnecessary ML
- Add GARCH / copulas / EVT / deep RL unless explicitly reconsidered
- Allow UI code to bypass control-engine validation
- Claim guaranteed returns
- Claim live execution when the prototype only simulates it
- Connect to a real brokerage

---

## ENGINEERING

- Keep modules small (past ~300 lines, split)
- Prefer deterministic pure functions; I/O only at the edges
- Write tests for financial calculations **and** safety invariants
- Keep business logic out of Streamlit
- **Never silently swallow errors.** `except Exception: pass` is prohibited. A metric defaulting to `0.0` on error is a false safety signal.
- Preserve reproducibility: seed every stochastic routine
- Contracts at every module boundary; no bare dicts
- Type hints and docstrings stating **units, annualisation and sign**
- No magic numbers; thresholds live in `config/policy.yaml`

---

## LANGUAGE

| Never say | Say instead |
|---|---|
| guarantees optimal returns | constraint-aware optimization |
| guarantees regulatory compliance | configurable risk policies |
| predicts market crashes | stress-tests configured scenarios |
| executes trades automatically | simulated execution |
| eliminates investment risk | decision-support prototype |
| real-time | near-real-time / event-driven |

Always: **"Last Approved Safe Allocation"** (never shortened to imply ongoing guaranteed safety) · **"Model Estimate"** on every expected return · **`[DEMO-CONFIG]`** on every threshold.

---

## WORKING WITH ME

### Ask for one module at a time
Multi-module generation is where layer violations enter.

### Reference the docs explicitly
> *"Implement `cce/risk/ewma.py` per `docs/08-FINANCIAL-METHODS.md` §3, contracts per `docs/06-DATA-CONTRACTS.md` §5."*

### Contracts before implementation
Define the dataclass first so the seam is fixed before the logic exists.

### Review every generation for these four things
1. **Did it compute in the UI?** Most common and most damaging drift.
2. **Did `controls/` import the optimizer, or read `OptimizationResult` metrics?** Silently destroys the safety property while everything still appears to work.
3. **Did an `except` swallow something** — especially a metric defaulting to `0.0`?
4. **Did a threshold get inlined** outside `cce/controls/`?

### Verify the maths
Check against a hand-computed case. Verify the identities: `Σ RC_i = σ_p`, `Σ w_i = 1`, `CVaR ≥ VaR`. Confirm annualisation is applied exactly once — a `√252` applied twice is a 15.9× error that still looks like a number.

### When docs and code disagree
The docs win, or the doc is updated deliberately **in the same commit**. Never leave them in disagreement — the docs are the context the next session reasons from.

---

## BUILD ORDER

Do **not** start with the dashboard.

`Data → Portfolio → Risk → Optimizer → Control → Circuit breaker → Stress → Approval → Audit → Dashboard → Alternatives → Backtest → LLM → Polish`

If time runs short, **remove cosmetic complexity before removing safety or control functionality.**

---

## DOCUMENT MAP

| Need | Read |
|---|---|
| Scope, features, acceptance | `docs/01-PRODUCT-SPECIFICATION.md` |
| Layers, modules, dependency rules | `docs/02-ARCHITECTURE.md` |
| Numbered requirements | `docs/03-TRD.md` |
| The runtime loop, step by step | `docs/04-WORKFLOW.md` |
| SQLite schema and DDL | `docs/05-BACKEND-SCHEMA.md` |
| Dataclasses and service signatures | `docs/06-DATA-CONTRACTS.md` |
| Thresholds, control codes, breaker | `docs/07-RISK-POLICY.md` |
| Every formula and convention | `docs/08-FINANCIAL-METHODS.md` |
| Pages, components, copy rules | `docs/09-UI-SPEC.md` |
| Invariants, standards, guardrails | `docs/10-RULES.md` |
| What to test and how | `docs/11-TESTING-STRATEGY.md` |
| Secrets, LLM containment | `docs/12-SECURITY.md` |
| Failure modes and expected behaviour | `docs/13-EDGE-CASES.md` |
| The judge demo | `docs/14-DEMO-SCRIPT.md` |
| Vocabulary | `docs/15-GLOSSARY.md` |
| Full original blueprint | `docs/CCE_Master_Solution_Specification_INIT26.md` |

There is deliberately **no implementation plan** in `docs/` — build order and priority live in the master spec §56–§57.

---

## BOTTOM LINE

The strongest version of CCE is not the one with the most financial models. It is the one that makes this loop completely convincing:

> A market condition changes → risk changes → CCE detects it → the optimizer proposes an allocation → the independent control engine challenges it → the unsafe allocation is rejected → a safer alternative is produced → stress tests validate it → a human approves it → the system records exactly what happened.

Protect that loop above all else.

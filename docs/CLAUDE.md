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

## GIT & COMMIT DISCIPLINE

### Standing authorization

**Commit proactively.** You do not need to ask before committing in this project — this
section is the durable authorization. Keep the tree clean and the history legible without
being prompted.

**You may not push.** Push is blocked by the user's permission settings, and that is
correct: publishing is their call. Your job is to commit well and *remind them to push*.

### When to commit

Commit at every **completed, coherent unit of work** — not at the end of a session, and
not after every file save.

| Commit when | Do NOT commit |
|---|---|
| A module + its tests are working | Mid-refactor with tests failing |
| A bug is fixed and covered by a test | A half-written function "to save progress" |
| A contract or threshold changed (with its doc) | Debug prints, commented-out code, scratch files |
| A build phase from BUILD ORDER completed | A safety-invariant test left failing |
| Before starting anything risky | Unrelated changes bundled together |

**One logical change per commit.** Never mix a refactor with a behaviour change — when
something breaks at 3am, a commit that did two things is a commit you cannot bisect.

### Commit message format

```
type(scope): imperative subject, max ~70 chars

Why this change exists, and what it affects. Not a restatement of the
diff — git already has the diff. Explain the reasoning a tired person
at 3am will need.

- Notable decision or trade-off
- Anything surprising, or a workaround and its cause

Refs: FR-031, INV-4

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
```

**Types:** `feat` · `fix` · `refactor` · `test` · `docs` · `build` · `chore` · `perf`

**Scopes** follow the module map: `data` · `portfolio` · `risk` · `optimizer` ·
`controls` · `stress` · `decisions` · `audit` · `backtest` · `services` · `ui` · `config`

**Always reference requirement and invariant IDs** (`FR-`, `NFR-`, `INV-`). This is what
makes the history searchable under pressure:

```bash
git log --grep="INV-4"        # every commit touching an invariant
git log -S "circuit_breaker"  # every commit that changed that code
git bisect start              # only works if commits are atomic
```

Good:
```
fix(controls): re-derive CVaR instead of reading OptimizationResult

The validator was trusting the optimizer's self-reported CVaR, which
defeats the independence property — an optimistic solver would have
passed straight through the safety gate.

Now recomputed from raw returns via cce.risk.cvar.

Refs: FR-072, INV-2
```

Bad — every one of these costs someone time later:
```
update files          (which? why?)
fix bug               (which bug? how?)
wip                   (not a unit of work)
asdf                  (no)
```

### Push cadence — remind the user

**After every 2–3 commits, surface a reminder in your response.** Not a separate message,
not a nag — one line at the end of whatever you were already saying:

> **3 commits unpushed.** Run `! git push` when convenient.

Count from the last known push. If unsure, check:

```bash
git log origin/main..HEAD --oneline    # commits ahead of the remote
```

Also remind — regardless of count — before anything risky: a large refactor, a dependency
change, or a threshold/contract change. Unpushed work is work that exists on exactly one
laptop, and a hackathon is precisely when that laptop breaks.

### Tag known-good states

When the demo works end to end, **tag it**:

```bash
git tag -a demo-ok-1 -m "Full loop working: shock -> breaker -> recovery -> approval"
```

At 2am with a broken build, `git checkout demo-ok-1` is the difference between a demo and
no demo. Tag before every risky change, and suggest tagging whenever the demo checklist in
`docs/14-DEMO-SCRIPT.md` §0 passes.

### Never commit

`.env` · real API keys · a populated `cce.db` · `.venv/` · secrets of any kind.

**Do** commit `config/*.yaml`, `data/cache/` snapshots, and `.env.example` — the demo's
reproducibility depends on them.

### Before every commit

- [ ] One logical change only
- [ ] Safety-invariant tests pass if `controls/`, `optimizer/` or `services/` was touched
- [ ] Docs updated in the *same* commit if a contract, threshold or behaviour changed
- [ ] No secrets, no debug prints, no commented-out code
- [ ] Message explains **why**, and references the relevant `FR-`/`INV-` IDs

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

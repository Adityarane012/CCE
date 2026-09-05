# 10 — Rules

**Scope:** Non-negotiable safety invariants, architectural rules, coding standards, and guardrails for AI-assisted development.
**Status:** These are constraints, not preferences. A violation is a defect regardless of whether the code runs.
**Derived from:** master spec §46, §47, §50, §58.

---

## 1. The three rules that matter most

If everything else is forgotten:

1. **The optimizer proposes. The control engine disposes.** They are separate modules, and the control engine re-derives its own numbers.
2. **On failure, do less — never something different.** Preserve the Last Approved Safe Allocation. Never invent an allocation.
3. **The LLM writes prose. It never writes decisions.**

---

## 2. Safety invariants

Each has an ID, a rationale, and a test in `tests/test_invariants.py`. They are the system's definition of correct behaviour under stress.

### `[INV-1]` The LLM cannot modify financial decisions
An LLM may only convert a structured `Explanation` into prose. It MUST NOT choose weights, alter thresholds, modify risk scores, approve allocations, override the circuit breaker, modify audit records, or replace deterministic calculations. LLM output is stored and rendered as display text and is never parsed back into decision state.
**Test:** inject a malformed and an adversarial LLM response; assert every financial field of the resulting decision is byte-identical to the LLM-disabled run.

### `[INV-2]` An invalid optimizer output cannot become an approved allocation
Weights leave the optimizer only when `solver_status is OPTIMAL`. A candidate is approvable only when `control.passed` **and** stress passed. `ApprovalService` re-checks this server-side; a disabled button is convenience, not enforcement.
**Test:** attempt to approve a candidate with `INFEASIBLE` status, with `control_status=FAILED`, and with `stress_status=NOT_RUN`. All three must raise.

### `[INV-3]` A hard control failure cannot be silently ignored
Every hard control reaching RED trips the circuit breaker, produces a `Breach` with observed value and threshold, writes a `control_finding`, and raises an alert.
**Test:** construct a candidate breaching each hard control in turn; assert breaker active and a finding persisted for each.

### `[INV-4]` If optimization fails, retain the last approved allocation
Solver failure, unrepairable covariance, or validation failure → reject the candidate and preserve the Last Approved Safe Allocation unchanged. No equal-weight fallback. No adopting the previous unvalidated candidate.
**Test:** force a solver exception; assert `get_last_safe_allocation()` returns the identical row it did before.

### `[INV-5]` Missing critical market data cannot be interpreted as zero risk
Missing returns are never zero-filled. An `INVALID` validation report blocks risk computation and preserves prior state. `None` in a metric means *not computed* and renders as `—`.
**Test:** feed a panel with a gap; assert no metric is computed from zero-filled data and that the snapshot is `INVALID` or `degraded`.

### `[INV-6]` Every approval and rejection is auditable
Every material decision persists a complete `DecisionRecord` with trigger, portfolio before, risk before, candidates, control findings, stress results, explanation, human action and portfolio after. Records are append-only. A failed write surfaces visibly.
**Test:** run the full loop; assert every field is populated and readable; assert no `UPDATE`/`DELETE` against audit tables exists in application code.

### `[INV-7]` Backtesting must not use future information
Every rebalance decision at `t` uses only data strictly before `t`, applied to `[t, t+1)`.
**Test:** shift all returns at and after `t` by an arbitrary constant; assert every decision at `t` is bit-identical.

### `[INV-8]` User-configured thresholds are versioned and audited
Threshold changes insert a new `policy_versions` row with attribution. Weakening a hard limit requires a warning, explicit confirmation and a reason. Every decision stores the policy version in force.
**Test:** apply a weakening change without a reason and assert rejection; apply one correctly and assert a new version row with `is_weakening=1`.

### `[INV-9]` Current, optimal and safe are distinct
The UI presents three separate allocations. Under no state are they merged or is one silently substituted for another.
**Test:** render-model test asserting three distinct candidate roles are returned by `propose_safe_and_optimal` plus current state.

### `[INV-10]` A stress-test failure remains visible even if normal metrics pass
A candidate passing all ordinary controls but breaching `STRESS_LOSS_MAX` is rejected, and the stress failure is displayed.
**Test:** construct a candidate with all controls GREEN and a stress loss above limit; assert `eligible_for_approval` is false and the stress result is surfaced.

### `[INV-11]` Risk state is computed in exactly one place
All GREEN/AMBER/RED classification and transition logic lives in `cce/controls/state_machine.py`. No UI file, service or other engine computes a risk state.
**Test:** static check — no threshold comparison against policy values outside `cce/controls/`.

### `[INV-12]` The UI contains no financial logic
`ui/` imports only `cce.services` and `cce.contracts`.
**Test:** static import check over `ui/**/*.py`.

---

## 3. Architectural rules

### 3.1 Layer dependencies

| Layer | May import | MUST NOT import |
|---|---|---|
| `ui/` | `cce.services`, `cce.contracts` | any engine, any provider, `cce.audit` |
| `cce/services/` | contracts, data, engines, audit | `ui` |
| `cce/risk/`, `optimizer/`, `stress/`, `backtest/` | contracts, `cce.data` (read) | services, ui, `cce.audit` |
| `cce/controls/` | contracts, `cce.risk` | **`cce.optimizer`**, services, ui |
| `cce/contracts/` | stdlib, numpy, pandas | everything in `cce` |
| `cce/data/`, `cce/audit/` | contracts, stdlib, sqlite3, jugaad-data | engines, services, ui |

Enforced by a test that parses imports across the tree. A violation fails the build.

### 3.2 The independence rule
`cce/controls/validation.py` MUST NOT import `cce.optimizer`. It receives a weight vector and re-derives every metric from `cce/risk/`. It never trusts a number the optimizer reported about its own output.

*Why:* if the validator read `OptimizationResult.cvar`, an optimizer bug or an optimistic solver would propagate straight through the safety gate. Independent re-derivation turns an optimizer bug into a **rejection**, which is the safe direction to fail.

### 3.3 Single source of truth

| Concern | The one place |
|---|---|
| Risk-state classification | `cce/controls/state_machine.py` |
| Approval eligibility | `Candidate.eligible_for_approval` |
| Thresholds | `config/policy.yaml` → `Policy` |
| Asset universe | `config/universe.yaml` → `Universe` |
| Asset ordering for ndarrays | `Universe.asset_ids` |
| Number formatting | `ui/components/format.py` |
| Database access | `cce/audit/repository.py` |
| Explanation content | the structured `Explanation` object |

Duplicating any of these is how a system starts disagreeing with itself.

### 3.4 Determinism
Every stochastic routine takes an explicit seed. Same inputs → same outputs, always. This is what makes a demo repeatable and a bug reproducible.

---

## 4. Coding standards

### 4.1 Structure
- Modules stay small and single-purpose; past ~300 lines, split.
- Financial computations are **pure functions**: inputs → outputs, no I/O, no globals, no hidden state.
- I/O lives at the edges (`cce/data/`, `cce/audit/`), never inside a risk or optimizer function.
- Cross-module communication uses contracts, never bare dicts.

### 4.2 Typing and documentation
- Type hints on every public function.
- Docstrings state **units, annualisation state and sign convention**. `"""Returns annualised volatility as a decimal (0.156 = 15.6%)."""`
- No magic numbers. Every constant is named or configured.

### 4.3 Error handling
- **Never silently swallow an exception.** Every `except` either handles meaningfully or re-raises.
- `except Exception: pass` is prohibited. So is a bare `except:`.
- Engines never call `sys.exit` or terminate the process; they return typed error results.
- Log with context: what was being attempted, with which inputs, what will happen now.

```python
# WRONG — this is how a risk system lies to you
try:
    cvar = compute_cvar(returns)
except Exception:
    cvar = 0.0          # now the portfolio looks safe

# RIGHT
try:
    cvar = compute_cvar(returns)
except InsufficientDataError as e:
    logger.warning("CVaR not computed: %s. Snapshot marked degraded.", e)
    cvar = None         # renders as "—", never as safe
```

### 4.4 Naming
- `asset_id` everywhere for the stable asset key. Not `symbol`, `ticker`, `code` — `ticker` is a display field only.
- Metric names match `07-RISK-POLICY.md` control codes.
- Booleans read as assertions: `is_hard`, `passed`, `eligible_for_approval`.
- Never abbreviate a financial term into ambiguity: `cvar_95`, not `cv`.

### 4.5 Testing
- Every financial function has a unit test with at least one **hand-computed** expected value.
- Every safety invariant has a test in `tests/test_invariants.py`.
- Boundary values are tested explicitly (`v == green_max` classifies GREEN).
- Test fixtures are deterministic — synthetic series or committed snapshots, never live data.

---

## 5. Product rules

### 5.1 Never claim
Guaranteed optimal returns · guaranteed regulatory compliance · crash prediction · automatic trade execution · real-time institutional execution · elimination of investment risk.

### 5.2 Always say
Prototype · decision-support system · constraint-aware optimization · near-real-time / event-driven · configurable risk policies · simulated execution · demonstration of institutional control concepts.

### 5.3 Naming discipline
- **"Last Approved Safe Allocation"** — never shortened to anything implying ongoing guaranteed safety. It passed *those* controls at *that* time.
- **"Model Estimate"** on every expected-return figure.
- **`[DEMO-CONFIG]`** on every threshold in any presentation. They are prototype settings, not institutional standards.

### 5.4 Do not build
- A retail stock-picking app
- An autonomous trading bot
- TradingAgents as a dependency
- GARCH, copulas, EVT, deep RL, or unnecessary ML
- Any path that lets UI code bypass control-engine validation
- Live broker connectivity

---

## 6. Rules for AI-assisted development

`CLAUDE.md` is loaded automatically each session. These are the operational rules around it.

### 6.1 Prompting
- **One module at a time.** Multi-module generation is where layer violations enter.
- **Reference documents explicitly:** *"implement `cce/risk/ewma.py` per `08-FINANCIAL-METHODS.md` §3, contracts per `06-DATA-CONTRACTS.md` §5."*
- **Contracts first.** Define the dataclass before the implementation, so the seam is fixed before the logic is generated.
- **Ask for the test alongside the function**, including a hand-computed case.

### 6.2 Review — the four things to check every time

1. **Did it compute in the UI?** The most common and most damaging drift. Reject immediately.
2. **Did the control engine import the optimizer, or read `OptimizationResult` metrics?** This silently destroys the safety property while leaving everything apparently working.
3. **Did an `except` swallow something?** Particularly a metric defaulting to `0.0` or `False` — that converts an error into a false safety signal.
4. **Did a threshold get inlined?** Any literal comparison against a policy value outside `cce/controls/` is a bug.

### 6.3 Verification
- After any generated financial function, check it against a hand-computed case before building on it. Plausible-looking financial code is exactly the failure mode to expect.
- Verify identities that must hold: `Σ RC_i = σ_p`, `Σ w_i = 1`, `CVaR ≥ VaR`.
- Confirm annualisation is applied exactly once. A `√252` applied twice is a 15.9× error that still looks like a number.

### 6.4 When docs and code disagree
The docs win — or the doc is updated deliberately in the same commit. Never leave them in disagreement: in an AI-assisted build the docs are the context the next session reasons from, and a stale doc silently corrupts every subsequent decision.

### 6.5 Tooling
Approved: Claude Code · Claude-Mem · Prompt Master · Graphify (once real architecture exists) · Anthropic Security Guidance.
Excluded by decision: Codebase Memory MCP · Skill Security Scanner · TradingAgents · large multi-agent frameworks · unnecessary MCP servers.

The goal is a compact engineering workflow. Tooling that costs more time than it saves is a net loss on a 24-hour clock.

---

## 7. Git rules

> Full commit discipline — message format, push cadence, tagging — lives in
> `CLAUDE.md` § GIT & COMMIT DISCIPLINE, which is authoritative. Summary here.

- **Commit at every completed, coherent unit of work.** One logical change per commit.
  Never mix a refactor with a behaviour change — a commit that did two things cannot be
  bisected when something breaks late.
- **Message format:** `type(scope): imperative subject`, a body explaining *why*, and a
  `Refs: FR-031, INV-4` trailer. Types: `feat` `fix` `refactor` `test` `docs` `build`
  `chore` `perf`. Scopes follow the module map.
- **Reference requirement and invariant IDs.** This is what makes `git log --grep="INV-4"`
  and `git bisect` work under pressure.
- **Push after every 2–3 commits**, and always before anything risky. Unpushed work exists
  on exactly one laptop.
- **Tag known-good demo states** (`git tag -a demo-ok-1`). Tag before every risky change.
- Never commit `.env`, real API keys, a populated `cce.db`, or `.venv/`.
- **Do** commit `config/*.yaml`, `data/cache/` snapshots and `.env.example` — reproducibility depends on them.
- A commit changing a threshold also updates `config/policy.yaml` and notes the version bump.
- A commit changing a contract also updates `06-DATA-CONTRACTS.md`.
- Never commit with a safety-invariant test failing.

---

## 8. Pre-merge checklist

- [ ] No layer-dependency violation
- [ ] `cce/controls/` does not import `cce/optimizer/`
- [ ] No financial computation in `ui/`
- [ ] No swallowed exceptions; no metric defaulting to `0.0` on error
- [ ] No inlined thresholds outside `cce/controls/`
- [ ] Contracts used at every module boundary
- [ ] Type hints and unit-stating docstrings on public functions
- [ ] Unit test with a hand-computed value
- [ ] Affected safety invariants still pass
- [ ] Docs updated in the same commit if a contract, threshold or behaviour changed
- [ ] Deterministic: seeded, reproducible
- [ ] No secrets, no `eval`/`exec`, parameterised SQL only

# CCE Documentation

**Product:** CCE — Capital Control Engine
**Context:** INIT'26 FinTech Hackathon — Asset & Capital Management / Optimization Controls
**One-line:** An institutional capital-allocation prototype where the optimizer *proposes*, an independent control engine *validates*, stress tests *challenge*, a human *approves*, and every decision is *recorded*.

> **Core principle:** Optimal ≠ Safe. The optimizer is never the final authority.

---

## Build status — as-built, not aspirational

**All 15 phases are complete.** 571 tests pass, none skipped. `ruff` and `mypy`
are clean across 93 files. Six failure drills pass.

| Layer | Module | State |
|---|---|---|
| Data | `cce/data/` — provider abstraction, committed cache, validation | ✅ |
| Portfolio | `cce/portfolio/` — state, turnover, transaction costs | ✅ |
| Risk | `cce/risk/` — volatility, EWMA, VaR, CVaR, drawdown, risk contribution | ✅ |
| Optimizer | `cce/optimizer/` — max-Sharpe, min-vol, target-return, CVaR LP, HRP, Black-Litterman | ✅ |
| Controls | `cce/controls/` — independent validation, circuit breaker, recovery | ✅ |
| Stress | `cce/stress/` — 7 configured scenarios plus custom | ✅ |
| Audit | `cce/audit/` — append-only SQLite, the only database access | ✅ |
| Backtest | `cce/backtest/` — walk-forward, look-ahead prevention | ✅ |
| Services | `cce/services/` — the only layer the UI touches | ✅ |
| UI | `ui/` + `app.py` — 8 Streamlit pages | ✅ |
| LLM | `cce/decisions/` — explanation only, works with no API key | ✅ |

All twelve safety invariants have a real test in `tests/test_invariants.py`.
None is skipped and none passes vacuously: the two that once would have
(INV-7 needed `cce/backtest/`, INV-12 needed `ui/`) were deliberately left
**failing** until the component existed, because a green tick against
something never built is worse than a visible gap.

### Verify any of this yourself

```bash
.venv/Scripts/python.exe -m pytest                 # 571 passed, 0 skipped
.venv/Scripts/python.exe scripts/demo_drill.py     # 6 failure drills
.venv/Scripts/python.exe scripts/demo_figures.py   # every demo figure, re-derived
```

`demo_figures.py` is the authority for every number quoted in
[`14-DEMO-SCRIPT.md`](./14-DEMO-SCRIPT.md). If the script and the output
disagree, the script is wrong.

To run the dashboard: `.venv/Scripts/streamlit.exe run app.py`, or see
[`../DEPLOYMENT.md`](../DEPLOYMENT.md).

---

## How to use these docs

This folder is the **single source of truth** for CCE. Code follows docs. If code and docs disagree, one of them is a bug — fix the doc in the same commit that fixes the code. That rule was applied throughout: `IMPLEMENTATION-PLAN.md` §1b records the findings that changed a document rather than the code.

For AI-assisted ("vibe coding") sessions: `CLAUDE.md` is loaded automatically. Everything else is pulled in on demand — reference documents by filename in your prompt (e.g. *"implement per `07-RISK-POLICY.md` §3"*).

---

## Reading order

### Tier 0 — Why we are building this
| Doc | Purpose |
|---|---|
| [`readme_fintech.md`](./readme_fintech.md) | The original hackathon problem statement and evaluation rubric. Immutable input. |
| [`CCE_Master_Solution_Specification_INIT26.md`](./CCE_Master_Solution_Specification_INIT26.md) | The 62-section master blueprint. All other docs are derived from it and stay consistent with it. |

### Tier 1 — What we are building
| Doc | Purpose |
|---|---|
| [`01-PRODUCT-SPECIFICATION.md`](./01-PRODUCT-SPECIFICATION.md) | Vision, users, scope, feature set, non-goals, acceptance criteria. |
| [`03-TRD.md`](./03-TRD.md) | Numbered functional + non-functional requirements, tech stack, budgets, traceability matrix. |

### Tier 2 — How it is built
| Doc | Purpose |
|---|---|
| [`02-ARCHITECTURE.md`](./02-ARCHITECTURE.md) | Layers, module map, dependency rules, control-flow, state machine, fail-safe design. |
| [`04-WORKFLOW.md`](./04-WORKFLOW.md) | The 12-step runtime closed loop, plus the development/agent workflow. |
| [`06-DATA-CONTRACTS.md`](./06-DATA-CONTRACTS.md) | In-process object contracts and service-layer signatures. The seams between modules. |
| [`05-BACKEND-SCHEMA.md`](./05-BACKEND-SCHEMA.md) | SQLite DDL, indices, JSON payload shapes, persistence rules. |

### Tier 3 — The domain rules
| Doc | Purpose |
|---|---|
| [`07-RISK-POLICY.md`](./07-RISK-POLICY.md) | GREEN/AMBER/RED thresholds, hard vs soft controls, circuit-breaker triggers, policy file format. |
| [`08-FINANCIAL-METHODS.md`](./08-FINANCIAL-METHODS.md) | Every formula, convention, parameter default, and numerical-stability rule. |

### Tier 4 — Surface and quality
| Doc | Purpose |
|---|---|
| [`09-UI-SPEC.md`](./09-UI-SPEC.md) | Dashboard pages, components, states, copy rules, colour semantics. |
| [`10-RULES.md`](./10-RULES.md) | Engineering rules, coding standards, and hard guardrails for humans and AI agents. |
| [`11-TESTING-STRATEGY.md`](./11-TESTING-STRATEGY.md) | What must be tested, the safety-invariant test suite, definition of done. |
| [`12-SECURITY.md`](./12-SECURITY.md) | Secrets, input trust boundaries, LLM containment, dependency hygiene. |
| [`13-EDGE-CASES.md`](./13-EDGE-CASES.md) | Enumerated failure modes and the exact expected behaviour for each. |

### Tier 5 — Delivery
| Doc | Purpose |
|---|---|
| [`14-DEMO-SCRIPT.md`](./14-DEMO-SCRIPT.md) | The 9-stage judge demo, timed, with fallbacks. |
| [`15-GLOSSARY.md`](./15-GLOSSARY.md) | Financial and system vocabulary. Read this first if finance is not your background. |
| [`CLAUDE.md`](./CLAUDE.md) | Project constitution for Claude Code. Loaded every session. |

---

### Tier 6 — Execution
| Doc | Purpose |
|---|---|
| [`IMPLEMENTATION-PLAN.md`](./IMPLEMENTATION-PLAN.md) | The 15-phase one-shot build: a prompt per phase, hour budget, checkpoints, cut lines, and a matrix proving every edge case and invariant is assigned to a phase. |

> This folder originally excluded an implementation plan on the principle that it describes *the system*, not *the schedule*. The plan was added later and is the exception: it sequences the existing requirements and introduces none of its own. If it ever disagrees with a Tier 1–4 document, **the other document wins** and the plan is the thing to fix.

---

## Document conventions

- **MUST / MUST NOT / SHOULD / MAY** carry RFC-2119 weight. `MUST` items are non-negotiable and have a matching test.
- **`[DEMO-CONFIG]`** marks a value that is a configurable prototype setting, not a claim about real institutional standards.
- **`[P0] [P1] [P2]`** mark priority, matching master spec §56.
- **`[INV-n]`** references a safety invariant from `10-RULES.md` §2.
- **`[FR-n] [NFR-n]`** reference requirements in `03-TRD.md`.
- Currency is INR. `₹1 Cr = ₹10,000,000`. Default demo portfolio is `₹100 Cr`.

---

## Non-negotiable summary

If you read nothing else, read this:

1. The **optimizer** and the **control engine** are separate modules. The control engine MUST NOT import the optimizer.
2. The **LLM** may only turn structured facts into prose. It MUST NOT touch weights, metrics, thresholds, states, or approvals.
3. **UI contains no financial logic.** Streamlit calls a service layer; the service layer calls the engines.
4. On any failure — optimizer, data, stress, database — **preserve the Last Approved Safe Allocation**. Never invent one.
5. **Backtests MUST NOT see the future.** Every rebalance decision uses only data strictly prior to the decision date.
6. Nothing executes real trades. Approval leads to a **simulated** rebalance.

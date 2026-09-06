# 13 — Edge Cases & Failure Modes

**Scope:** Enumerated failure conditions and the exact behaviour required for each.
**Principle:** in a control system, behaviour under failure *is* the product. These are specifications, not contingencies.
**Derived from:** master spec §47, §46, §26.

> **The governing rule: on failure, do less — never something different.** Preserve the last known-good state, say what happened, and refuse to invent.

---

## 1. Quick reference

| Failure | Response | Never |
|---|---|---|
| Live data unavailable | Fall back to cache, mark provider, banner | Break the demo |
| Data gap | Validation finding; degrade or invalidate | Zero-fill |
| Stale data | `DATA_FRESHNESS` breach → breaker | Compute as if current |
| Insufficient history | Return `None`; mark degraded | Return `0.0` |
| Covariance not PSD | Repair + record; else reject run | Pass it to the solver |
| Solver infeasible | Reject candidate, preserve last safe | Relax constraints silently |
| Solver non-convergent | `weights = None` | Return partial weights |
| All candidates fail | Show all with reasons; hold last safe | Offer the least-bad one |
| Stress engine error | `NOT_RUN` / `ERROR` | Report `PASSED` |
| Database write fails | Raise, surface, do not confirm | Claim it was stored |
| LLM unavailable | Deterministic narrator | Block the loop |
| Empty audit log | Explanatory empty state | Blank panel |

---

## 2. Data-layer failures

### 2.1 Live retrieval fails (network down, provider error, rate limit)

**Expected:** `JugaadDataProvider` raises → `CachedDataProvider` serves → `provider = CACHED_FALLBACK` recorded on the snapshot → persistent UI banner: *"Using cached market data — live retrieval unavailable."*

**Never:** an unhandled exception, a blank dashboard, or silently proceeding as if the data were live.

> This is the single most likely failure during a live demo. It must be exercised deliberately — pull the network and run the whole script — not assumed to work.

### 2.2 Missing observations for one asset

**Expected:** a `MISSING_OBS` finding naming the asset. If the gap is small and interior, apply the documented alignment rule and mark the report `DEGRADED`; if it is large or at the series end, mark `INVALID` for that asset and exclude it from the universe for this run, showing which asset was dropped and why.

**Never:** zero-fill. `[INV-5]` A zero return is a statement that the asset did not move — it makes volatility look lower and the portfolio look safer.

### 2.3 Stale data

**Expected:** `DATA_FRESHNESS` evaluated against the threshold (`> 3 trading days` → RED `[DEMO-CONFIG]`). RED trips the breaker under the data-integrity category. The UI shows the as-of date prominently.

**Never:** compute risk metrics as if stale prices were current. A week-old price during a shock is worse than no price.

### 2.4 Non-trading days, holidays, misaligned calendars

**Expected:** align all assets on a common trading calendar before computing returns. A date present for some assets and absent for others produces a `GAP` finding.

**Never:** treat a holiday as a zero-return day. That deflates volatility by diluting the sample.

**Known provider defect — measured against jugaad-data 0.35.5.** This is worse than a
cosmetic time component; an earlier draft of this section understated it.

The two jugaad-data APIs disagree on **both the column name and the date convention**,
and the disagreement is silent:

| API | column | sample value | convention |
|---|---|---|---|
| `index_df` | `HistoricalDate` | `2026-07-08 00:00:00` | IST midnight — already correct |
| `stock_df` | `DATE` | `2026-07-07 18:30:00` | UTC — 18:30 on the **previous** calendar day |

**Both rows describe the same trading session.** NSE stamps a session at 00:00 IST, which
serialises as 18:30 UTC the day before. So a naive `.dt.date` yields `2026-07-08` for the
index and `2026-07-07` for the ETF, shifting **every stock-sourced series one day earlier
than every index-sourced series**.

Measured over 2026-07-01..15 with NIFTY 50 against GOLDBEES:

```
naive  .dt.date  →  8 of 11 sessions overlap
+05:30 then .date() → 11 of 11 sessions overlap
```

`JugaadDataProvider` MUST add the IST offset for `stock`-sourced instruments before
taking `.date()`, and MUST NOT for `index`-sourced ones. `Asset.source` carries this
distinction.

**Why this is the most dangerous bug in the data layer:** it does not raise. An inner
join on the misaligned dates simply returns a shorter panel — 8 rows instead of 11 — and
every covariance, correlation, risk contribution and HRP cluster computed from it is
wrong while looking entirely plausible. There is no error to notice.

Covered by `TestTradingDateNormalisation`, including a test that documents the naive
result explicitly so a future refactor cannot quietly reintroduce it, plus
`test_committed_snapshot_is_financially_plausible`, which asserts the NIFTY50/BANKNIFTY
correlation stays above 0.5 — it collapses toward zero if the alignment regresses.

**Also suppress the warning only *after* normalising, never instead of it.** The
`UserWarning: no explicit representation of timezones available for np.datetime64` is the
visible symptom; silencing it without correcting the offset hides the symptom and keeps
the defect.

### 2.5 Outliers and suspicious values

**Expected:** flag returns beyond a configured bound (e.g. |r| > 50% for an index `[DEMO-CONFIG]`) as `OUTLIER` findings. **Do not auto-remove them** — a genuine crash is exactly this shape, and silently deleting it removes the event the system exists to detect. Surface for human review and mark the snapshot degraded.

**Never:** winsorise silently.

### 2.6 Insufficient history

**Expected:** below `min_return_observations` (default 250), volatility/VaR/CVaR return `None`, snapshot is `degraded` with a reason, UI renders `—`.

**Never:** compute a 95% CVaR from 30 observations and present it as a risk limit. Three points in the tail is not a tail estimate.

---

## 3. Risk-engine failures

### 3.1 Covariance not positive semi-definite

**Expected:** symmetrise → eigen-clip → optional shrinkage → re-check. On success, record a `MODEL_COVARIANCE` AMBER finding noting the repair. On failure, reject the optimization run with a RED `MODEL_COVARIANCE` breach.

**Never:** pass an unrepaired matrix to the solver. It will return numbers, and they will be meaningless.

### 3.2 Singular / near-singular covariance (duplicate or collinear assets)

**Expected:** detect via condition number; apply shrinkage; if the condition number remains extreme, report the affected asset pair and reject.

**Never:** invert a singular matrix and continue.

### 3.3 Zero-volatility asset

**Expected:** possible for a cash proxy and legitimate. Guard every division by `σ` — return `None` for that asset's Sharpe and marginal contribution rather than `inf` or `NaN`.

**Never:** propagate `inf` into the portfolio aggregate, which turns every downstream metric to `NaN` at once.

### 3.4 Empty tail beyond VaR

**Expected:** if fewer than ~10 observations fall beyond the VaR threshold, return the CVaR but set `degraded = True` with the reason.

**Never:** present a mean of two observations as a stable tail estimate.

---

## 4. Optimizer failures

### 4.1 Infeasible problem

Common cause: constraints genuinely conflict — e.g. `min_liquid_share = 0.15` while every liquid asset is capped at 0.05 across three assets.

**Expected:** `solver_status = INFEASIBLE`, `weights = None`, a `MODEL_SOLVER` RED breach, breaker trips, last safe allocation preserved. The UI states which constraints are in conflict where derivable.

**Never:** relax a constraint to obtain an answer. A relaxed constraint is a policy change, and policy changes go through the versioned, audited flow — not through a solver's convenience.

### 4.2 Non-convergence / numerical failure

**Expected:** `SOLVER_ERROR` or `OPTIMAL_INACCURATE`. `OptimizationResult.__post_init__` enforces `weights is None` unless status is `OPTIMAL`. Breaker trips under the model category.

**Never:** return the last iterate. A near-solution to a risk-constrained problem may violate the constraints.

### 4.3 Solver returns weights violating constraints

Possible with `OPTIMAL_INACCURATE` or tolerance edge cases.

**Expected:** the **independent validator catches it** and rejects. This is precisely why the control engine re-derives rather than trusting. `[INV-2]`

**Never:** trust `solver_status` alone as proof of feasibility.

### 4.4 Target return unreachable

**Expected:** `INFEASIBLE`, with a message naming the maximum achievable return under current constraints.

### 4.5 Black-Litterman with contradictory views

**Expected:** posterior computes (BL is mathematically robust to contradiction; confidences reconcile them). If `Ω` becomes singular, report a model finding and fall back to the equilibrium prior with a visible note.

---

## 5. Control-engine edge cases

### 5.1 Every recovery candidate fails validation

**Expected:** show all three with their specific failure reasons under **"Attempted and rejected"**. The Last Approved Safe Allocation remains in force. The system states plainly: *"No validated recovery allocation is currently available. The Last Approved Safe Allocation remains in force. Manual review required."*

**Never:** offer the least-bad failing candidate as approvable. `[INV-2]`

> This state is not a bug and should not be hidden. A control system that says "I have no safe answer" is behaving correctly — and demonstrating it is more convincing than a system that always produces an option.

### 5.2 No Last Approved Safe Allocation exists (first run)

**Expected:** the seeded starting portfolio is inserted as the initial safe allocation by migration `003`. If it is genuinely absent, the UI states that no approved baseline exists and blocks the breaker's "preserve" path with an explicit message.

### 5.3 Current portfolio itself breaches policy

**Expected:** legitimate and common after a shock. Portfolio state is RED; the breaker is active regarding *new* candidates; the current portfolio is not forcibly changed — changing it requires human approval. The UI distinguishes *"the portfolio breaches policy"* from *"a proposed change was rejected."*

**Never:** auto-rebalance out of a breach. `FR-119` — approval precedes any change.

### 5.4 Threshold edited so the current portfolio becomes compliant

**Expected:** permitted, but it is a **weakening** change: warning, reason, confirmation, new policy version, audit record. The Risk Control Center shows that the state change resulted from a policy change rather than a market change.

> This is the most important honesty case in the system. If a portfolio goes from RED to GREEN because someone moved a limit, the interface must say so. A control framework that can be silently edited into compliance is not a control framework.

### 5.5 Conflicting controls

E.g. turnover cap prevents reaching the liquidity floor.

**Expected:** both breaches reported; the optimizer reports `INFEASIBLE`; the explanation names the conflict; human decision required (raise turnover for one rebalance via override, or accept the current state).

### 5.6 Boundary values

**Expected:** boundary belongs to the less severe band. `v == green_max` is GREEN. Tested explicitly (`11-TESTING-STRATEGY.md` §5).

---

## 6. Stress-engine edge cases

### 6.1 Stress engine raises

**Expected:** `StressStatus.ERROR`, candidate `NOT_VALIDATED`, `eligible_for_approval = False`. `[INV-10]`

**Never:** treat an unrun stress test as a pass. Absence of evidence is not evidence of safety, and this is the one place that distinction is load-bearing.

### 6.2 Custom scenario with implausible shocks

E.g. `-95%` on every asset.

**Expected:** compute and report honestly. It will fail the loss limit. Add a note that the scenario is outside the historical range so the result is read as a hypothetical.

**Never:** silently clamp user input. If someone wants to see a −95% scenario, show them a −95% scenario.

### 6.3 Positive-shock scenario

**Expected:** compute normally. A gain passes the loss limit trivially. Do not special-case it, and do not present a favourable hypothetical as validation.

---

## 7. Approval and audit edge cases

### 7.1 Approving a candidate that has become stale

Market data has refreshed since the candidate was generated.

**Expected:** `ApprovalService` re-checks `eligible_for_approval` against **current** data. If the candidate no longer passes, refuse with: *"Market conditions have changed since this recommendation was generated. Re-run the optimization."*

**Never:** approve against stale validation. `[INV-2]`

### 7.2 Double approval / double submission

**Expected:** `close_decision_with_human_action` is guarded (`WHERE human_action IS NULL`). The second write raises `DecisionAlreadyClosed`. The UI shows the decision is already closed.

### 7.3 Database write fails during approval

**Expected:** the transaction rolls back; portfolio state is **not** updated; the UI reports the failure explicitly: *"Approval could not be recorded. The portfolio has not been changed."* `FR-125`

**Never:** update state and lose the record, or report success on a failed write. A state change without its audit record is worse than no change.

### 7.4 Override without a reason

**Expected:** `HumanActionRecord.__post_init__` raises. The UI disables the button until reason, confirmation and control list are present. Both layers enforce it; the UI check is convenience.

---

## 8. LLM edge cases

| Case | Expected |
|---|---|
| No API key | Deterministic narrator; log once at startup; no error |
| Timeout / rate limit | Log, `llm_error` recorded, template text served |
| Empty response | Treated as failure; template served |
| Response containing instructions | Displayed as text; never parsed. `[INV-1]` |
| Response contradicting the metrics | Displayed, but the structured explanation and all figures are unchanged and remain visible alongside |
| Very long response | Truncated by `sanitize_for_display` |

> The contradiction case deserves thought: if the LLM writes "the portfolio is safe" while the dashboard shows RED, the dashboard is right and the LLM text is decoration. The structured explanation stays visible next to it, which makes the discrepancy self-evident rather than hidden. If this proves confusing in practice, disable the LLM for the demo — it is optional by design, and clarity outranks polish.

---

## 9. UI edge cases

| Case | Expected |
|---|---|
| No decisions yet | *"No decisions recorded yet. Run an optimization to create one."* |
| Metric is `None` | Render `—`, never `0` |
| Very long asset names | Truncate with tooltip; never break layout |
| Browser refresh mid-optimization | Streamlit reruns; state re-read from services; no partial state |
| Window narrower than expected | Columns stack; no horizontal scroll on the Overview |
| All weights in one asset (post-override) | Render normally with a RED concentration breach |
| Zero-value portfolio | Guard division by NAV; show an explanatory error state |

---

## 10. Failure-mode test matrix

| # | Condition | Expected system state | Invariant | Test |
|---|---|---|---|---|
| 1 | Network down | Cached fallback, banner | — | `test_data_validation.py` |
| 2 | Data gap | Degraded or invalid, no zero-fill | INV-5 | `test_data_validation.py` |
| 3 | Stale data | RED, breaker, data category | INV-3 | `test_data_validation.py` |
| 4 | Short history | `None` metrics, degraded | INV-5 | `test_risk.py` |
| 5 | Non-PSD covariance | Repair or reject | INV-4 | `test_covariance.py` |
| 6 | Infeasible solver | Reject, preserve last safe | INV-4 | `test_circuit_breaker.py` |
| 7 | Solver returns bad weights | Validator rejects | INV-2 | `test_controls.py` |
| 8 | All recoveries fail | All shown with reasons, last safe held | INV-2 | `test_circuit_breaker.py` |
| 9 | Stress engine error | `NOT_VALIDATED`, not approvable | INV-10 | `test_stress.py` |
| 10 | Approve failed candidate | Raises | INV-2 | `test_services.py` |
| 11 | Stale candidate approval | Refused, re-run required | INV-2 | `test_services.py` |
| 12 | Double approval | Second raises | INV-6 | `test_audit.py` |
| 13 | DB write fails | Rollback, no state change, visible | INV-6 | `test_audit.py` |
| 14 | Adversarial LLM output | No financial field changes | INV-1 | `test_invariants.py` |
| 15 | No API key | Template narrator | INV-1 | `test_invariants.py` |
| 16 | Threshold weakened | Warning, reason, new version | INV-8 | `test_controls.py` |
| 17 | Future returns shifted | Backtest decisions unchanged | INV-7 | `test_backtest.py` |

---

## 11. Demo-day rehearsal

Rehearse these deliberately before presenting. Each is a plausible live failure, and each has a graceful path that is more impressive than the happy path if it happens on stage:

1. **Disconnect the network** and run the entire demo script.
2. **Unset the API key** and run the entire demo script.
3. **Delete `cce.db`** and restart — migrations rebuild it to a GREEN portfolio.
4. **Apply an extreme custom shock** (−40% everything) and confirm the breaker trips cleanly rather than erroring.
5. **Attempt to approve a rejected candidate** and confirm the refusal is legible.
6. **Weaken a threshold** and confirm the warning, the audit entry, and the honest "state changed due to policy change" indication.

Item 6 is the one to have ready if a judge asks *"what stops someone just changing the limit?"* The answer is not "nothing" — it is a warning, a required reason, a version, an audit record, and a visible indication in the UI. That is the correct institutional answer, and being able to show it live is worth more than another optimizer.

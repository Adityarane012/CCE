# 09 — UI Specification

**Stack:** Streamlit + Plotly
**Location:** `ui/` — rendering only, zero financial logic
**Derived from:** master spec §38–§40, §58.

---

## 1. The governing constraint

```
BAD                              GOOD
Button click                     UI
  → calculate risk                 ↓
  → modify weights               Service layer
                                   ↓
                                 Risk / Optimizer / Control engines
                                   ↓
                                 Decision result
                                   ↓
                                 UI renders result
```

A `ui/` module may import from `cce.services` and `cce.contracts` (for typing). It may **not** import `cce.risk`, `cce.optimizer`, `cce.controls`, `cce.stress`, `cce.audit` or any data provider. `FR-175`

Practical test: if you deleted `ui/` entirely, every feature would still be reachable and testable through the service layer. If not, logic has leaked upward.

### Corollaries

- The Approve button's enabled state reads `candidate.eligible_for_approval`. It does not reimplement the condition.
- No percentage is computed in a UI file. Services return decimals; UI formats them.
- No threshold comparison happens in a UI file. `Breach` objects arrive pre-classified.
- Streamlit `session_state` holds *view state* (selected page, selected strategy, form drafts). It never holds portfolio, risk or control state — those are re-read from services.

---

## 2. Visual language

### 2.1 Risk-state palette

| State | Colour | Hex | Text label (always present) |
|---|---|---|---|
| GREEN | Green | `#1B873F` | `GREEN — Within policy` |
| AMBER | Amber | `#B7791F` | `AMBER — Approaching limit` |
| RED | Red | `#C53030` | `RED — Policy breach` |
| Neutral / not computed | Grey | `#6B7280` | `—` |

**Colour is never the only channel** (`FR-176`). Every state indicator carries a text label and, where space allows, a shape or icon. This is an accessibility requirement and also a projector requirement — demo-room colour reproduction is unreliable, and a judge who cannot distinguish your amber from your red cannot follow the story.

### 2.2 Data-quality markers

| Marker | Meaning | Rendering |
|---|---|---|
| **Model Estimate** | Expected returns, forward-looking figures | Italic + tooltip. Mandatory per `FR-062`. |
| **Degraded** | Computed on incomplete or fallback data | Amber dotted underline + tooltip naming the reason |
| **Cached fallback** | Live retrieval failed | Persistent banner: `Using cached market data — live retrieval unavailable` |
| **Not computed** | `None` from a service | Render `—`. **Never `0`.** |

The last row is a correctness requirement, not a style preference. Rendering an uncomputed risk metric as zero is the exact failure mode `[INV-5]` exists to prevent, arriving through the front door.

### 2.3 Number formatting

Formatting lives in one module: `ui/components/format.py`.

| Quantity | Format | Example |
|---|---|---|
| Currency | `₹X.X Cr` (≥ ₹1 Cr), `₹X.X L` (≥ ₹1 L), else `₹X,XXX` | `₹100.0 Cr` |
| Percentage | 1 decimal, always signed for changes | `15.6%`, `+3.8pp` |
| Ratio (Sharpe) | 2 decimals | `1.17` |
| Weight | 1 decimal | `24.0%` |
| Basis points | integer + `bps` | `10 bps` |
| Timestamp | `HH:MM:SS` in timeline, `YYYY-MM-DD HH:MM` elsewhere | |

Percentage-point changes use `pp`, not `%`. Volatility moving from 11.8% to 15.6% is `+3.8pp`, not `+3.8%` — the latter would mean 12.2%. In a risk dashboard this distinction is not pedantry.

---

## 3. Page map

| # | Page | Priority | Purpose |
|---|---|---|---|
| 1 | Executive Overview | P0 | The whole product in one screen |
| 2 | Portfolio & Exposure | P0 | Where the capital and the risk are |
| 3 | Risk Control Center | P0 | Every control vs its threshold |
| 4 | Optimizer | P0 | Propose, compare, act |
| 5 | Stress Lab | P1 | Scenario testing |
| 6 | Backtesting | P1 | Controlled vs uncontrolled |
| 7 | Decision Replay | P1 | The audit timeline |
| 8 | Policy / Settings | P1 | Thresholds and constraints |

Navigation: persistent sidebar. The current risk state chip is visible in the sidebar on **every** page — a risk manager should never have to navigate to discover the portfolio is RED.

---

## 4. Page 1 — Executive Overview (the hero view)

This is the judge-facing home page. It must communicate the entire product in seconds.

```
┌──────────────────────────────────────────────────────────────────┐
│  CCE — Capital Control Engine                                    │
│  ₹100 Cr Institutional Portfolio                                 │
│                                                                  │
│  ┌────────────────────────────────────────────────────────────┐  │
│  │  RISK STATE:  ● RED — Policy breach                        │  │
│  │  Circuit breaker ACTIVE since 10:03:12                     │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
│  Portfolio Value        ₹100.0 Cr                                │
│  Expected Return        13.2%   (Model Estimate)                 │
│  EWMA Volatility        15.6%   ▲ from 11.8%                     │
│  Historical Volatility  11.8%                                    │
│  95% CVaR                8.7%   ▲ limit 8.0%                     │
│  Liquidity                11%   ▼ limit 15%                      │
│  Sharpe                  0.94                                    │
│                                                                  │
│  BREACHES                                                        │
│  ● RED    CVaR                        8.7%  >  8.0%              │
│  ● RED    Liquidity                    11%  <   15%              │
│  ● AMBER  Banking risk contribution    41%  >   35%              │
│                                                                  │
│  RECOMMENDED ACTION                                              │
│  Circuit breaker active. Uncontrolled optimizer output rejected. │
│  Three validated recovery allocations are available.             │
│                                                                  │
│  [ View Safe vs Optimal ]  [ Open Recovery Options ]             │
│  [ Decision Replay ]                                             │
└──────────────────────────────────────────────────────────────────┘
```

### Rules
- Every breach row shows **observed vs threshold**, not just a colour.
- Arrows (▲▼) indicate direction of movement since the previous snapshot, not good/bad.
- The action block states what the system did and what the human can do next — it is never empty. In GREEN it reads e.g. *"No breaches. Optimization available."*
- The three buttons are the demo's spine. They stay in fixed positions so the presenter never hunts for them.

---

## 5. Page 2 — Portfolio & Exposure

**Components**
1. **Allocation donut** — weight by asset, sector-coloured.
2. **Sector exposure bars** — weight vs sector cap, cap drawn as a reference line.
3. **Weight vs risk contribution** — grouped horizontal bars, the two side by side per asset.
4. **Positions table** — asset · sector · price · units · value · weight · RC% · liquidity · status.
5. **Concentration summary** — largest asset, largest sector, largest risk contributor.

Component 3 is the one to get right. It renders the product's central insight visually: bars that should track each other, and visibly do not.

```
                 Weight   Risk Contribution
BANKNIFTY   ████████ 24%  ██████████████ 41%     ← the story
NIFTY50     ██████████ 28% ████████ 22%
IT          ████ 12%      █████ 14%
GOLD        ███ 10%       ██ 5%
GSEC        ████ 12%      █ 3%
```

---

## 6. Page 3 — Risk Control Center

A table of every configured control:

| Control | Observed | Threshold | State | Trend | Hard? |
|---|---|---|---|---|---|
| Annualised volatility | 15.6% | 15.0% | ● RED | ▲ | Hard |
| 95% CVaR | 8.7% | 8.0% | ● RED | ▲ | Hard |
| Single-asset concentration | 28% | 40% | ● GREEN | — | Hard |
| Sector concentration | 24% | 35% | ● GREEN | — | Hard |
| Sector risk contribution | 41% | 45% | ● AMBER | ▲ | Hard |
| Minimum liquid assets | 11% | 15% | ● RED | ▼ | Hard |
| Turnover | 0% | 25% | ● GREEN | — | Hard |

Plus:
- **Circuit-breaker status panel** — active/inactive, trigger category, activation time, what it preserved.
- **"What Changed?" panel** (see §10).
- **Breach history** — a compact strip showing state over the last N snapshots.

Sort order: RED first, then AMBER, then GREEN. A risk manager scanning this table should hit the problems before the reassurance.

---

## 7. Page 4 — Optimizer

### Inputs (left rail)
Strategy · expected-return method · risk profile preset · constraint overrides (with a clear "modified from policy" marker) · Black-Litterman view entry when BL is selected.

### Outputs — the three-column comparison

```
┌─────────────────┬──────────────────────┬─────────────────────┐
│    CURRENT      │  OPTIMAL             │  SAFE               │
│                 │  (unconstrained)     │  (risk-controlled)  │
├─────────────────┼──────────────────────┼─────────────────────┤
│ Exp. Return 12.1│ 14.8%  Model Est.    │ 13.2%  Model Est.   │
│ Sharpe      0.94│ 1.31                 │ 1.17                │
│ CVaR        8.7%│ 9.4%                 │ 7.3%                │
│ Banking      24%│ 43%                  │ 28%                 │
│ Turnover      — │ 61%                  │ 18%                 │
│ Txn cost      — │ ₹0.61 Cr             │ ₹0.18 Cr            │
├─────────────────┼──────────────────────┼─────────────────────┤
│ ● RED           │ ● REJECTED           │ ● APPROVAL REQUIRED │
│                 │                      │                     │
│                 │ Rejected because:    │ Passed all hard     │
│                 │ • Banking 43% > 40%  │ controls and stress │
│                 │ • CVaR 9.4% > 8.0%   │ validation.         │
│                 │ • Stress loss > 18%  │                     │
└─────────────────┴──────────────────────┴─────────────────────┘

              [ Approve Safe ]  [ Reject ]  [ Keep Current ]
```

### Rules
- Three columns are **always** three distinct things. Never collapse them. `[INV-9]`
- The rejected optimal column is **not hidden**. It is the argument.
- Rejection reasons are specific: control, observed, threshold. Never "constraints violated". `FR-174`
- `[ Approve ]` is enabled only when `candidate.eligible_for_approval` is true.
- Below: the recommended trade list — asset, current weight, target weight, Δ, estimated cost.

### Recovery options (breaker active)

Replaces the normal recommendation block when the breaker has tripped:

```
CIRCUIT BREAKER ACTIVE — three validated recovery allocations

┌──────────────────┬──────────────────┬──────────────────┐
│ Max-Sharpe       │ Minimum-Risk     │ Defensive /      │
│ Recovery         │ Recovery         │ Liquidity        │
│ Sharpe    1.09   │ Sharpe    0.88   │ Sharpe    0.79   │
│ CVaR      7.8%   │ CVaR      5.9%   │ CVaR      4.6%   │
│ Liquidity  16%   │ Liquidity  19%   │ Liquidity  31%   │
│ ● ELIGIBLE       │ ● ELIGIBLE       │ ● ELIGIBLE       │
│ [ Approve ]      │ [ Approve ]      │ [ Approve ]      │
└──────────────────┴──────────────────┴──────────────────┘

Last Approved Safe Allocation preserved (approved 09:41, policy v1)
```

A recovery candidate that failed its own validation appears in a separate **"Attempted and rejected"** section with its reasons. It is never silently dropped — the fact that CCE tried and rejected it is evidence the control layer is real.

### Controlled Override

Behind an expander labelled `Request Controlled Override`. Requires: an explicit confirmation checkbox, a free-text reason, and a rendered list of exactly which controls are being overridden. Only then does the override button enable. A RED allocation never gets a one-click approval. `FR-117`

---

## 8. Page 5 — Stress Lab

- Scenario selector — the seven defaults, multi-select.
- Custom scenario builder — per-sector shock sliders with numeric entry.
- Results per scenario: portfolio loss (₹ and %), waterfall of per-asset contribution, before/after allocation, post-shock risk metrics, resulting breaches, PASS/FAIL against `STRESS_LOSS_MAX`.
- Comparison view: the same scenario applied to Current / Optimal / Safe side by side.

The custom builder is the interactive moment in the demo. Sliders must be responsive and the recompute must feel immediate (`NFR-005`: 500 ms per scenario).

---

## 9. Page 6 — Backtesting

Controls: date range · rebalance frequency · strategies to include.

Outputs:
- **Equity curves**, three strategies overlaid.
- **Drawdown chart**, same three.
- **Metrics table**, one row per strategy.
- **Breach and breaker-activation counts** — given equal visual weight to return.

```
Strategy               Return  Vol   Sharpe  MaxDD  Breaches  Breaker
Buy-and-hold            11.2%  13.8%  0.81   -24.1%    18        —
Uncontrolled optimizer  14.6%  17.9%  0.82   -31.7%    27        —
CCE-controlled          13.1%  12.4%  0.94   -16.3%     4        7
```

A caption states the honest reading: *the controlled strategy gave up return relative to the uncontrolled optimizer while materially reducing drawdown and policy breaches.* Do not bury it, and do not dress a lower return as a win by omission.

Below the table: a `No look-ahead bias` note explaining the walk-forward construction. Judges evaluating financial logic will look for exactly this.

---

## 10. "What Changed?" component

Appears on the Overview and Risk Control Center whenever a previous snapshot exists.

```
WHAT CHANGED?

Portfolio volatility        11.8%  →  15.6%   (+3.8pp)
Primary driver              Banking volatility

Banking allocation            24%  →    24%   (unchanged)
Banking risk contribution     27%  →    41%   (+14pp)

Interpretation
Allocation did not materially change, but recent banking
volatility increased sharply, raising its contribution to
portfolio risk.
```

The interpretation line is generated by the deterministic narrator from the structured `Explanation` — not written in the UI, and not written by an LLM. If an LLM is enabled, its richer prose appears in a clearly-labelled separate block beneath.

---

## 11. Page 7 — Decision Replay

A vertical timeline, newest incident first, expandable per decision.

```
Decision #47 — 2026-09-05 10:02  ·  Circuit breaker activated  ·  policy v1

  10:02:04  ⚙  Market shock detected                        [MACHINE]
  10:02:05  ⚙  EWMA volatility 11.8% → 15.6%                [MACHINE]
  10:02:05  ⚙  Banking risk contribution 27% → 41%          [MACHINE]
  10:03:11  ⛔ CVaR 8.7% crossed RED threshold 8.0%          [CONTROL]
  10:03:12  ⛔ Circuit breaker activated                     [CONTROL]
  10:04:01  ⚙  Max-Sharpe candidate generated               [MACHINE]
  10:04:02  ⛔ Failed: concentration 43%>40%, CVaR 9.4%>8.0% [CONTROL]
  10:04:02  ⛔ Candidate rejected                            [CONTROL]
  10:05:10  ⚙  Three recovery candidates generated          [MACHINE]
  10:05:44  ⛔ Stress validation completed — all passed      [CONTROL]
  10:06:20  👤 Risk Manager approved Minimum-Risk Recovery   [HUMAN]
  10:06:21  ⚙  Simulated rebalance applied                  [MACHINE]
  10:06:21  ⚙  Audit event stored                           [MACHINE]
```

**Rules**
- Three actor types, three visual treatments. The `MACHINE` / `CONTROL` / `HUMAN` distinction is the entire point of the page.
- Rendered **only** from persisted `decision_events`. No recomputation. `FR-124`
- Each row expands to its stored detail JSON.
- A `Human Intervention: YES / NO` badge sits on the decision header.

---

## 12. Page 8 — Policy / Settings

- Threshold editor, grouped by control category, showing current values and defaults.
- Constraint editor — weight bounds, sector caps, liquidity floor, turnover cap, transaction-cost rates.
- Model parameters — EWMA λ, VaR confidence, risk-free rate, seed.
- Policy version history with diffs and attribution.

### The weakening flow (`FR-084`)

```
┌────────────────────────────────────────────────────────────┐
│  ⚠  POLICY WEAKENING WARNING                               │
│                                                            │
│  You are raising the 95% CVaR RED limit:                   │
│      8.0%  →  12.0%   (+50% relative)                      │
│                                                            │
│  This is a HARD control. Weakening it means allocations    │
│  that are currently rejected would become approvable.      │
│                                                            │
│  Currently breaching this control: 1 (the live portfolio)  │
│                                                            │
│  Reason for change (required)                              │
│  ┌──────────────────────────────────────────────────────┐  │
│  └──────────────────────────────────────────────────────┘  │
│                                                            │
│  ☐ I understand this weakens a hard risk control and       │
│    that this change will be recorded in the audit trail.   │
│                                                            │
│           [ Cancel ]        [ Apply Change ]               │
└────────────────────────────────────────────────────────────┘
```

`Apply Change` enables only when the reason is non-empty and the checkbox is ticked. The change writes a new policy version with `is_weakening = 1`. `[INV-8]`

---

## 13. Empty, loading and error states

Every page defines all three. A blank panel during a demo reads as a crash.

| State | Treatment |
|---|---|
| **Loading** | `st.spinner` with a specific message (`Running 7 stress scenarios…`), for anything over ~1 s (`NFR-041`) |
| **Empty** | Explain why and what to do: *"No decisions recorded yet. Run an optimization to create one."* |
| **Error** | State what failed, what the system did instead, and what is still safe: *"Optimization failed (solver infeasible). The Last Approved Safe Allocation is unchanged and remains in force."* |
| **Degraded** | Render the data with a persistent marker naming the degradation |

Errors never show a raw traceback in the UI. They log the traceback and display a stated consequence. A user must always be able to read what the system's state now is — that is what distinguishes a control system from a calculator that crashed.

---

## 14. Demo-readiness checklist

- [ ] Overview readable on a projector at 1280×720
- [ ] Risk state visible in the sidebar on every page
- [ ] The three hero buttons never move
- [ ] Every state indicator has a text label, not colour alone
- [ ] No page takes more than 3 s without a spinner
- [ ] Cached-fallback banner works when the network is off
- [ ] Every number carries a unit and a basis
- [ ] Expected returns are labelled "Model Estimate" everywhere
- [ ] Uncomputed metrics render `—`, never `0`
- [ ] The rejected optimal candidate is visible, with reasons
- [ ] Decision Replay renders with the LLM disabled

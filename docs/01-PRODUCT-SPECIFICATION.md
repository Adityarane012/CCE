# 01 — Product Specification

**Product:** CCE — Capital Control Engine
**Type:** Institutional capital-allocation and risk-control prototype
**Status:** Specification — authoritative for scope
**Derived from:** `CCE_Master_Solution_Specification_INIT26.md` §1–§4, §7, §25–§30, §38, §53–§55

---

## 1. Problem

Financial institutions allocate capital across asset classes under shifting volatility, liquidity requirements, concentration limits and transaction costs. Two failure modes exist, and most tools solve only one:

| Failure mode | Cause | Typical tool that fails here |
|---|---|---|
| **Stale allocation** | Static rules do not adapt when market conditions change | Fixed policy portfolios, spreadsheets |
| **Unsafe allocation** | A pure optimizer produces a statistically attractive portfolio that violates institutional policy | Naive mean-variance optimizers |

CCE addresses **both**. It continuously re-evaluates the portfolio *and* refuses to adopt an optimizer output that breaches policy.

### The question CCE answers

> How can an institution continuously seek better risk-adjusted capital allocation while ensuring that optimization never overrides predefined risk, liquidity, concentration, stress, or operational safety controls?

---

## 2. Product statement

> CCE is an institutional capital-control system that continuously monitors portfolio risk, generates constraint-aware allocation recommendations, rejects unsafe optimizer outputs, and provides an auditable human-in-the-loop decision process.

CCE treats portfolio management as a **closed-loop control problem**, not a one-time construction exercise:

```
Market Data → Portfolio State → Risk Engine → Detect → Optimize
    → Validate → Stress Test → Explain → Human Approval
    → Simulated Rebalance → Audit → (loop)
```

---

## 3. Users

### Primary

| User | Their job | What CCE gives them |
|---|---|---|
| **Risk Manager** | Enforce risk policy, sign off on exposure | Breach detection, circuit breaker, override workflow, audit trail |
| **Institutional Portfolio Manager** | Allocate capital for risk-adjusted return | Constrained optimizer, Safe vs Optimal comparison, recovery options |
| **Treasury / Capital Manager** | Maintain liquidity and capital efficiency | Liquidity controls, turnover and transaction-cost budgets |

### Secondary

Corporate treasury teams · family offices · asset-management risk operations.

### The demo persona

For the hackathon, authentication is simulated as a single user with role **`RISK_MANAGER`**. All human actions are attributed to this identity in the audit log.

---

## 4. Positioning

### CCE **is**

- A prototype institutional capital-allocation and risk-control engine.
- A decision-support system with an explicit human-in-the-loop gate.
- A demonstration of *optimization under independent policy control*.

### CCE **is not** — and MUST NOT be presented as

- A retail stock-picking application
- A trading bot or autonomous AI trader
- A brokerage or execution platform
- A guaranteed-return or regulatory-compliance product

### Language rules

| Never say | Say instead |
|---|---|
| "guarantees optimal returns" | "constraint-aware optimization" |
| "guarantees regulatory compliance" | "configurable risk policies" |
| "predicts market crashes" | "stress-tests configured adverse scenarios" |
| "executes trades automatically" | "simulated execution" |
| "eliminates investment risk" | "decision-support prototype" |
| "real-time" | "near-real-time / event-driven" |

---

## 5. Design philosophy

Six principles govern every design decision. When a trade-off appears, resolve it in favour of preserving the safety constraint.

**P1 — Optimization is subordinate to policy.**
The optimizer seeks the best allocation it can find. The control engine decides whether that allocation is acceptable.

**P2 — Safety is independent.**
The component that produces an allocation MUST NOT be the only component deciding whether it is safe. Therefore `Optimizer ≠ Control Engine`, enforced at the module-dependency level.

**P3 — Recent market conditions matter.**
EWMA volatility is the primary responsive estimator. Historical volatility stays visible for comparison, because showing both is what makes the responsiveness legible.

**P4 — Human oversight remains explicit.**
CCE automates analysis and recommendation. Simulated execution requires human approval. A RED-state allocation has no one-click approval path.

**P5 — Every important decision is explainable.**
A risk manager must be able to answer: *what changed, why did CCE react, what did the optimizer propose, what did the control engine accept or reject, and what did the human approve?*

**P6 — Failure degrades safely.**
If the optimizer fails, market data becomes invalid, or a candidate violates hard controls, CCE MUST NOT invent an allocation. It preserves the Last Approved Safe Allocation and surfaces the issue.

---

## 6. Portfolio model

| Property | Value |
|---|---|
| Default demo capital | **₹100 Cr** (₹1,000,000,000) `[DEMO-CONFIG]` |
| Asset universe size | 8–12 instruments/proxies |
| Currency | INR |
| Rebalance mode | Simulated only |

### Universe selection criteria

Instruments are chosen for meaningful Indian market representation, **available and reproducible historical data**, diversification, liquidity, and understandable behaviour.

Target categories:

- Broad Indian equity
- Banking
- IT
- A defensive sector (Pharma / FMCG)
- Gold
- Government securities / bond proxy
- Corporate debt proxy *(only where reliable data exists)*
- Cash / T-bill proxy

> **Rule:** Prefer an instrument with a reproducible series over pretending every asset class has equal data availability. If a category has no trustworthy series, drop the category and say so in the UI — do not synthesise one.

### Per-asset attributes

`asset_id · ticker · name · asset_class · sector · price · position_value · weight · historical_returns · liquidity_estimate · risk_contribution · min_weight · max_weight`

---

## 7. Feature set

### 7.1 [P0] Core control loop — must work

| # | Feature | Definition of working |
|---|---|---|
| F1 | Market data ingestion | Loads Indian market data via `jugaad-data`; falls back to cache without breaking the demo |
| F2 | Data validation | Detects missing/stale/outlier/discontinuous data and raises a **control event**, not a silent portfolio |
| F3 | Portfolio state | Positions, weights, cash, NAV, historical portfolio returns |
| F4 | Risk engine | Historical vol, EWMA vol, Sharpe, historical VaR, historical CVaR, drawdown |
| F5 | Risk state classification | Every policy resolves to GREEN / AMBER / RED |
| F6 | Constrained Max-Sharpe optimizer | Produces a feasible candidate honouring bounds, sector caps, liquidity, turnover |
| F7 | Independent constraint validation | A separate module re-checks the candidate against every hard control |
| F8 | Circuit breaker | Rejects unsafe candidates, preserves Last Approved Safe Allocation, raises an alert |
| F9 | Last Approved Safe Allocation | Persisted, displayed separately from the current portfolio |
| F10 | Safe vs Optimal | Both portfolios shown side by side with the reasons the optimal one was rejected |
| F11 | Stress scenarios | Default adverse scenarios applied to candidates as a gating check |
| F12 | Human approval | Approve / Reject / Keep Current, recorded with identity, role and timestamp |
| F13 | Audit log | Full decision chain persisted for every material decision |
| F14 | Dashboard | Executive Overview + Risk Control Center + Optimizer at minimum |

### 7.2 [P1] Differentiators

| # | Feature | Why it matters |
|---|---|---|
| F15 | **Risk contribution** | Detects hidden concentration: an asset within its weight cap that dominates portfolio risk |
| F16 | Liquidity controls | Minimum liquid allocation; days-to-liquidate where volume data supports it |
| F17 | Transaction costs | A rebalance is never free; cost enters the objective and the report |
| F18 | Turnover constraint | Prevents replacing most of a ₹100 Cr portfolio for a marginal expected-return gain |
| F19 | Alternative optimizers | Min-volatility, target-return, CVaR-minimisation, HRP, Black-Litterman |
| F20 | Recovery allocations | Up to 3 validated alternatives generated *when the breaker trips* |
| F21 | **Decision Replay** | Chronological timeline distinguishing machine action, control decision and human action |
| F22 | Backtesting | Buy-and-hold vs uncontrolled optimizer vs CCE-controlled, with no look-ahead |
| F23 | "What Changed?" | Explains risk *movement*, isolating allocation drift from volatility regime change |

### 7.3 [P2] Add only after stability

Parametric VaR · Monte Carlo VaR · ADV-based liquidity · custom scenario builder polish · LLM explanation layer · visualisation polish.

> **Trade-off rule:** If time runs out, remove cosmetic complexity before removing safety or control functionality.

---

## 8. Signature features in detail

> **Every number in this section is ILLUSTRATIVE**, written before the engine
> existed to show the SHAPE of each feature. None is a measured output.
>
> Measured results as of Phase 4, on the committed Aug 2023 – Aug 2026 data:
> the unconstrained optimum is PHARMA 30% / GOLD 30% / CORPBOND 27%, rejected
> on the cash floor (2% < 3%) and turnover (67.4% > 25%) — not on banking
> concentration. Banking reaches 58% *risk contribution* at a 43% weight, so
> the concentration story is real but needs a trigger to arise naturally.
>
> Per `10-RULES.md` §5.3, no illustrative figure here may be copied into the
> UI, the demo script or a slide.

### 8.1 Safe vs Optimal

The dashboard displays two portfolios simultaneously:

```
OPTIMAL                          SAFE
Expected Return: 14.8%           Expected Return: 13.2%
Sharpe:           1.31           Sharpe:           1.17
CVaR:             9.4%           CVaR:             7.3%
Banking:           43%           Banking:           28%
Status:       REJECTED           Status: APPROVAL REQUIRED
```

Accompanied by an explicit reason: *"The optimal portfolio was rejected because it exceeded the CVaR and banking concentration limits."*

This is the clearest single demonstration of why an institutional control layer must wrap an optimizer.

### 8.2 Circuit breaker + Last Approved Safe Allocation

On a hard failure the breaker: rejects the candidate → preserves the last approved allocation → alerts → generates recovery candidates → requires an explicit human decision. It MUST NOT silently replace the safe allocation.

**Naming discipline:** it is the *Last Approved Safe Allocation* — an allocation that passed hard controls and stress validation **at the time it was approved**. It is not a claim of future safety. Never shorten it in the UI to anything implying an ongoing guarantee.

### 8.3 Risk contribution

Weight answers *"how much capital is here?"* Risk contribution answers *"how much of our risk is caused by this?"* CCE reports both:

```
Banking allocation:         24%
Banking risk contribution:  43%
Status: AMBER
Reason: Risk concentration exceeds risk budget
```

### 8.4 "What Changed?"

```
Portfolio volatility:       11.8% → 15.6%
Primary driver:             Banking volatility
Banking allocation:         24%   → 24%
Banking risk contribution:  27%   → 41%

Interpretation: Allocation did not materially change, but recent
banking volatility increased sharply, raising its contribution to
portfolio risk.
```

### 8.5 Decision Replay

A chronological timeline of a single incident, visually distinguishing **machine action**, **control-engine decision** and **human action** — from shock detection through breaker activation, candidate rejection, recovery generation, approval and audit write.

---

## 9. Human decision model

| Action | Effect | Availability |
|---|---|---|
| **Approve** | Adopt the validated recommendation; simulated rebalance; becomes the new Last Approved Safe Allocation | Only for candidates that passed all hard controls **and** stress validation |
| **Reject** | Discard the recommendation; portfolio unchanged | Always |
| **Keep Current Allocation** | Explicitly retain the current approved state | Always |
| **Controlled Override** | Adopt despite a breach | Only via the override flow |

**Controlled Override** requires: explicit confirmation, a free-text reason, the list of controls being overridden, a timestamp, and user identity/role. All are persisted. A RED-state allocation MUST NOT have a normal one-click approval path.

---

## 10. Execution boundary

The MVP MUST NOT connect to a brokerage or place real orders.

```
Approval → Simulated Rebalance → Portfolio State Update
```

Production evolution (out of scope; sketched in `02-ARCHITECTURE.md` §10) would route the approved trade set to an execution-management layer.

---

## 11. Non-goals

Explicitly out of scope for this build:

- Real order execution or broker connectivity
- Real authentication, RBAC, SSO, multi-tenancy
- Intraday tick-level streaming
- GARCH, copulas, EVT, deep RL, or any ML beyond the documented estimators
- TradingAgents or any large multi-agent framework as a dependency
- React/Next.js frontend or a FastAPI service split, unless implementation need forces it
- Regulatory formula libraries (Basel, SEBI capital rules)
- An LLM with any authority over financial decisions

---

## 12. Acceptance criteria

CCE is **done** when a judge can watch this loop end-to-end without intervention:

> A market condition changes → risk changes → CCE detects it → the optimizer proposes an allocation → the independent control engine challenges it → the unsafe allocation is rejected → a safer alternative is produced → stress tests validate it → a human approves it → the system records exactly what happened.

Concretely, all of the following MUST hold:

- [ ] Portfolio of ₹100 Cr loads from cached data with zero network dependency
- [ ] Historical volatility, EWMA volatility, VaR, CVaR, Sharpe, drawdown and risk contribution all render
- [ ] A stress scenario flips at least one control from GREEN to RED
- [ ] The circuit breaker activates and blocks an unsafe optimizer output
- [ ] Optimal and Safe allocations are shown side by side with rejection reasons
- [ ] At least three recovery candidates are generated and independently validated
- [ ] A human approval visibly transitions state and is attributed in the audit log
- [ ] Decision Replay reconstructs the full incident timeline from persisted records
- [ ] Backtest compares controlled vs uncontrolled with breach and drawdown counts
- [ ] Every safety invariant in `10-RULES.md` §2 has a passing test
- [ ] The demo runs with no API key and no internet connection

---

## 13. Mapping to the hackathon rubric

| Rubric area | Weight | CCE's answer |
|---|---:|---|
| **Financial & Control Logic** | 35% | Constrained optimization, EWMA risk, VaR/CVaR, risk contribution, liquidity, concentration, transaction costs, stress testing, dynamic rebalancing, circuit breaker. *This is the strongest part of the submission.* |
| **Technical Architecture** | 30% | Modular Python engines, independent control layer, provider-abstracted cached data, SQLite audit state, deterministic calculations, testable components |
| **UX & Clarity** | 20% | GREEN/AMBER/RED semantics, Safe vs Optimal, Stress Lab, Decision Replay, actionable approval controls |
| **Innovation** | 15% | Optimization–control separation, safe-allocation fallback, independent validation, risk attribution, human-in-the-loop auditability |

The strongest version of CCE is **not** the one with the most financial models. It is the one that makes the detect → challenge → reject → recover → approve → record loop completely convincing.

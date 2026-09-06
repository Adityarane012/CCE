# 15 — Glossary

Financial and system vocabulary used across CCE. Read this first if finance is not your background — several of these terms mean something narrower here than in general usage.

---

## Portfolio and allocation

**Allocation / Weights** — the fraction of total capital in each asset. Sum to 1.0. `{"BANKNIFTY": 0.24, ...}` means 24% of the portfolio is in that instrument.

**Asset class** — broad category: equity, fixed income, commodity, cash.

**Sector** — finer grouping within equity: banking, IT, pharma, broad equity.

**NAV (Net Asset Value)** — total portfolio value. ₹100 Cr in the demo.

**Position** — a holding in a single asset: units, price, value, weight.

**Rebalance** — changing weights from current to target. In CCE always **simulated**; no real orders are placed.

**Turnover** — how much of the portfolio a rebalance trades: `Σ|w_new − w_current| / 2`. A 25% turnover means a quarter of the portfolio changed hands.

**Cr / Crore** — 10,000,000 (₹1 Cr = ₹1,00,00,000). **L / Lakh** — 100,000.

---

## Risk metrics

**Volatility (σ)** — standard deviation of returns; the standard measure of variability. Annualised by `× √252` unless stated otherwise.

**Historical volatility** — computed over a fixed window, weighting every observation equally. Slow to react to a regime change.

**EWMA volatility** — Exponentially Weighted Moving Average. Recent observations count more, controlled by the decay factor λ (default 0.94). **CCE's primary responsive estimator** — it moves within days of a volatility regime change, where a three-year historical window would dilute it away.

**Covariance matrix (Σ)** — how assets move together. The input that lets an optimizer distinguish diversification from duplication.

**PSD (positive semi-definite)** — a mathematical validity property Σ must satisfy. A non-PSD covariance implies negative portfolio variance, which is meaningless. Must be checked and repaired before optimization.

**Sharpe ratio** — return per unit of risk: `(E[R] − R_f) / σ`. Higher is better. The default optimization objective.

**Risk-free rate (R_f)** — the reference return assumed available without risk. Default 6.5% `[DEMO-CONFIG]`.

**VaR (Value at Risk)** — the loss threshold at a confidence level. "1-day 95% VaR of 3%" means on the worst 5% of days, losses were at least 3%. Says **where the tail begins**.

**CVaR (Conditional VaR / Expected Shortfall)** — the *average* loss given that VaR was breached. Says **how bad the tail is**. CCE's primary hard tail-risk control, because two portfolios can share a VaR and have very different tail severity.

**Drawdown** — decline from the running peak. **Maximum drawdown** is the worst such decline over the period. A monitoring metric in CCE, not a hard control by default.

**Risk contribution (RC)** — how much of total portfolio risk an asset causes, as distinct from how much capital it holds. `RC_i = w_i × MCR_i`, and `Σ RC_i = σ_p` exactly.

**MCR (Marginal Contribution to Risk)** — the sensitivity of portfolio volatility to a small increase in one asset's weight: `(Σw)_i / σ_p`.

**Concentration** — exposure clustered in one asset, sector or class. CCE controls it at four levels, including risk contribution — because weight caps alone are gameable by an optimizer.

**Liquidity** — how readily a position converts to cash without moving the price. Measured here as the share in liquid instruments, and where volume data allows, estimated days-to-liquidate.

**ADV (Average Daily Value traded)** — typical daily traded value; the input to days-to-liquidate. `None` when unavailable, which disables that control for the asset rather than fabricating a number.

**Days to liquidate** — `Position Value / (Participation Rate × ADV)`. An **estimate**, never a guarantee of execution.

---

## Optimization

**MVO (Mean-Variance Optimization)** — Markowitz's framework: trade expected return against variance. The classical basis for portfolio construction.

**Efficient frontier** — the set of portfolios with the best return for each level of risk.

**Constrained optimization** — optimization subject to real-world limits: weight bounds, sector caps, liquidity floors, turnover caps.

**Convex problem** — an optimization problem with a single global optimum, reliably solvable. CVXPY solves convex problems; the raw Sharpe objective is *not* convex, which is why CCE uses a transform or a frontier scan.

**Solver status** — the solver's verdict: `OPTIMAL`, `INFEASIBLE`, `UNBOUNDED`, `SOLVER_ERROR`. **Only `OPTIMAL` permits weights to leave the optimizer.**

**Infeasible** — no allocation satisfies all constraints simultaneously. Reported honestly; constraints are never silently relaxed to manufacture an answer.

**HRP (Hierarchical Risk Parity)** — clusters assets by correlation and allocates risk hierarchically. Needs **no expected-return estimate and no matrix inversion**, making it robust exactly where MVO is fragile.

**Black-Litterman** — blends market-equilibrium returns with investor views and their confidences into posterior expected returns, which then feed constrained optimization.

**Expected returns (μ)** — forecast asset returns. **The least reliable input in the system** — estimation error in means dominates error in covariances. Always labelled "Model Estimate".

**Transaction cost** — the cost of trading, modelled as a rate per unit of weight change. Ensures a rebalance is never treated as free.

---

## Control system

**Control engine** — the module that independently validates candidate allocations against policy. Structurally separate from the optimizer; does not import it.

**Candidate** — a proposed allocation plus the verdicts on it (control result, stress results).

**Hard control** — a control whose RED breach trips the circuit breaker and blocks approval. Example: CVaR limit.

**Soft control** — a control whose RED breach raises an alert but does not block. Example: current drawdown.

**GREEN / AMBER / RED** — healthy / approaching a limit / hard breach. Portfolio state is the **most severe** individual control state; there is no averaging.

**Breach** — a control evaluating to AMBER or RED, recorded with observed value, threshold, comparator and scope.

**Circuit breaker** — the safety mechanism that rejects unsafe candidates, preserves the Last Approved Safe Allocation, alerts, generates recovery options and demands a human decision.

**Last Approved Safe Allocation** — the most recently approved allocation that passed the configured hard controls and stress validation **at the time it was approved**. Deliberately *not* a claim of ongoing safety, and never abbreviated to imply one.

**Recovery allocation** — a validated alternative generated when the breaker trips: Max-Sharpe Recovery, Minimum-Risk Recovery, Defensive/Liquidity Recovery.

**Controlled Override** — the flow for adopting an allocation despite a breach. Requires explicit confirmation, a written reason, the list of overridden controls, and attribution. All recorded.

**Policy** — the versioned set of thresholds, constraints and model parameters. Editable at runtime, never edited in place.

**Policy weakening** — loosening a hard limit. Triggers a warning, requires a reason, and creates an audited new version.

**Safe vs Optimal** — CCE's signature view: the mathematically optimal allocation shown beside the risk-controlled one, with the reasons the optimal one was rejected.

---

## Stress and simulation

**Stress test** — applying a defined adverse shock and measuring the consequence. An **independent gate**: a candidate passing all ordinary controls can still be rejected on stress, because historical metrics systematically understate correlated shocks.

**Scenario** — a named shock vector by sector or asset, e.g. `BANKING_CRISIS`.

**Custom scenario** — user-defined shocks entered in the Stress Lab.

**Monte Carlo** — simulating many random return paths to estimate a distribution. Optional in CCE; never a dependency of the control loop.

---

## Backtesting

**Backtest** — replaying a strategy over history to see how it would have behaved.

**Walk-forward** — at each decision date, use only prior data, then apply the decision to the following period.

**Look-ahead bias** — accidentally using information unavailable at decision time. The single bug that would invalidate every backtest number, hence an explicit invariant and test. `[INV-7]`

**Rebalance frequency** — how often the strategy re-optimizes. Monthly by default.

**Buy-and-hold** — no rebalancing; the drift baseline.

**Uncontrolled optimizer** — adopts every optimizer recommendation with no control layer. The comparison that shows what the control layer costs and what it saves.

---

## System

**Contract** — a typed dataclass passed between modules (`PortfolioState`, `RiskSnapshot`, `OptimizationResult`, `ControlResult`, `DecisionRecord`). Bare dicts at module boundaries are prohibited.

**Service layer** — the orchestration layer (`cce/services/`) and the **only** thing the UI may call.

**Provider** — a market-data source behind the `MarketDataProvider` interface: `JugaadDataProvider` (live) or `CachedDataProvider` (demo default).

**Snapshot** — an immutable capture: `market_snapshots` (data), `risk_snapshots` (computed risk), `portfolio_states` (holdings).

**Decision Record** — the complete persisted chain for one decision cycle.

**Decision Replay** — the chronological reconstruction of an incident, built only from persisted records, distinguishing machine, control and human action.

**Audit log** — the append-only record of decisions. A record of what happened; not a tamper-evidence mechanism.

**Safety invariant** — a non-negotiable behavioural rule with an ID and a test. See `10-RULES.md` §2.

**Degraded** — computed on incomplete or fallback data. Must be visibly labelled wherever displayed.

**Deterministic** — same inputs always produce same outputs. Every stochastic routine is seeded.

**`[DEMO-CONFIG]`** — marks a configurable prototype value, not a claim about institutional or regulatory standards.

---

## Data sources

**jugaad-data** — the Python library used for Indian market and RBI data retrieval.

**NSE** — National Stock Exchange of India. **RBI** — Reserve Bank of India.

**G-Sec** — Government securities; the fixed-income proxy in the demo universe.

**Nifty 50 / Nifty Bank** — Indian equity benchmark indices used as broad-equity and banking proxies.

---

## Units and conventions

| Term | Convention in CCE |
|---|---|
| Rate / weight / ratio | Decimal. `0.1568` = 15.68%. Never stored pre-formatted. |
| Loss | Positive. `cvar_95 = 0.087` is an 8.7% expected tail loss. |
| Volatility / return | Annualised unless the name says otherwise. |
| VaR / CVaR | 1-day at 95% unless the name says otherwise. |
| Money (persisted) | Integer paise (INR × 100). Never floating-point currency. |
| Percentage point | `pp`. Volatility 11.8% → 15.6% is **+3.8pp**, not +3.8%. |
| Basis point | `bps`. 1 bp = 0.01% = 0.0001. |
| Trading days per year | 252. |
| `None` | Not computed. **Never** zero. Renders as `—`. |

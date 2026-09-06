# CCE — Capital Control Engine
## INIT'26 FinTech Hackathon — Master Solution Specification

**Status:** Master build blueprint  
**Product:** CCE (Capital Control Engine)  
**Positioning:** Prototype for financial institutions and institutional managers handling large pools of capital  
**Primary demo portfolio:** ₹100 crore  
**Primary interface:** Interactive risk-management dashboard  
**Core principle:** Optimize capital, enforce risk, explain every decision.

---

# 1. Executive Summary

CCE (Capital Control Engine) is an automated capital-management and portfolio-control prototype designed for financial institutions, institutional investment managers, treasury/risk teams, and other organizations managing large pools of capital.

The problem is not simply "which assets should we buy?" The central problem is:

> How can an institution continuously seek better risk-adjusted capital allocation while ensuring that optimization never overrides predefined risk, liquidity, concentration, stress, or operational safety controls?

CCE therefore treats portfolio optimization as a **closed-loop control problem** rather than as a one-time portfolio construction exercise.

The core operating loop is:

**Market Data → Portfolio State → Risk Engine → Detect → Optimize → Validate → Stress Test → Explain → Human Approval → Simulated Rebalance → Audit**

The optimizer is deliberately not the final authority. It generates candidate allocations. A separate control layer independently validates those allocations. Unsafe recommendations are rejected by a circuit breaker, while the most recently approved safe allocation is preserved.

This creates a central product distinction:

**Optimal ≠ Safe.**

CCE explicitly shows the mathematically optimal portfolio alongside the risk-controlled portfolio. If the mathematically optimal portfolio violates institutional policy, CCE rejects it and explains why.

The prototype uses deterministic financial mathematics for all decisions. An optional LLM layer is restricted to explanation, risk summarization, and scenario descriptions. The LLM cannot change weights, risk metrics, thresholds, control states, or approval decisions.

The solution directly addresses the hackathon's three required areas:
1. Optimization strategy.
2. Control and safeguard system.
3. Decision dashboard.

The problem statement specifically asks for optimization under real-world constraints, automated risk controls, and a dashboard that lets risk managers understand system decisions and run scenarios. CCE is designed around those requirements. 

---

# 2. Problem Definition

Financial institutions manage capital across multiple asset classes while facing:
- changing market conditions,
- liquidity requirements,
- concentration risk,
- market volatility,
- transaction costs,
- drawdowns,
- risk limits,
- and operational approval requirements.

Static allocation rules can become inappropriate when market conditions change. Conversely, a purely mathematical optimizer can produce an allocation that looks attractive statistically but violates an institution's actual risk policy.

CCE addresses both failure modes.

## 2.1 What CCE is solving

CCE answers four questions continuously:

### A. What is the current state of the portfolio?
- Where is capital allocated?
- Where is risk concentrated?
- How much liquidity exists?
- What are current volatility, VaR, CVaR, drawdown and risk contributions?

### B. Has the portfolio entered a dangerous state?
- Has a risk limit been breached?
- Is the portfolio approaching a limit?
- Has recent volatility increased sharply?
- Has a sector or asset become disproportionately responsible for risk?
- Has liquidity deteriorated?
- Has a market shock occurred?
- Is the optimizer or market data unreliable?

### C. What should the portfolio become?
Generate feasible candidate allocations that maximize risk-adjusted return while respecting constraints and transaction costs.

### D. Can that recommendation actually be accepted?
An independent control engine validates the candidate. Only validated recommendations can proceed to approval.

---

# 3. Product Vision

## 3.1 Product statement

> CCE is an institutional capital-control system that continuously monitors portfolio risk, generates constraint-aware allocation recommendations, rejects unsafe optimizer outputs, and provides an auditable human-in-the-loop decision process.

## 3.2 Target users

Primary:
- Financial institution risk managers
- Institutional portfolio managers
- Treasury/capital managers
- Investment managers responsible for large funds

Secondary:
- Corporate treasury teams
- Family offices or large private investment organizations
- Asset-management operations/risk teams

## 3.3 Positioning

CCE should NOT be presented as:
- a retail stock-picking application,
- a trading bot,
- an autonomous AI trader,
- a brokerage platform,
- or a guaranteed-return system.

It should be presented as:

**A prototype institutional capital allocation and risk-control engine.**

---

# 4. Core Design Philosophy

CCE follows six principles.

## Principle 1 — Optimization is subordinate to policy

The optimizer seeks the best allocation it can find.

The control engine decides whether that allocation is acceptable.

## Principle 2 — Safety is independent

The same component that produces an allocation should not be the only component deciding whether that allocation is safe.

Therefore:

**Optimizer ≠ Control Engine**

## Principle 3 — Recent market conditions matter

EWMA volatility is used as the primary responsive volatility estimator. Historical volatility remains visible for comparison.

## Principle 4 — Human oversight remains explicit

CCE automates analysis and recommendation, but simulated execution requires human approval.

## Principle 5 — Every important decision is explainable

A risk manager should be able to answer:

> What changed, why did CCE react, what did the optimizer propose, what did the control engine reject or accept, and what did the human approve?

## Principle 6 — Failure should degrade safely

If the optimizer fails, market data becomes invalid, or a candidate violates hard controls, CCE should not invent a new allocation.

It should preserve the last approved safe allocation and surface the issue.

---

# 5. High-Level Architecture

## 5.1 Logical architecture

```text
                    ┌─────────────────────────┐
                    │     Market Data Layer   │
                    │   NSE/RBI via data lib  │
                    │       jugaad-data       │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Data Validation      │
                    │ freshness / missingness │
                    │ outliers / consistency   │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Portfolio State       │
                    │ positions / cash / NAV  │
                    │ weights / trades        │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │       Risk Engine        │
                    │ EWMA volatility          │
                    │ historical volatility    │
                    │ VaR / CVaR               │
                    │ drawdown                 │
                    │ risk contribution       │
                    │ concentration            │
                    │ liquidity                │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    Control / Trigger     │
                    │ GREEN / AMBER / RED      │
                    │ breach classification    │
                    │ circuit breaker          │
                    └────────────┬────────────┘
                                 │
                       ┌─────────┴─────────┐
                       │                   │
                   NORMAL/WARN          CRITICAL
                       │                   │
                       ▼                   ▼
              ┌────────────────┐   ┌──────────────────┐
              │   Optimizer    │   │ Circuit Breaker  │
              │ MVO / HRP /    │   │ preserve last    │
              │ BL / CVaR      │   │ approved safe    │
              └───────┬────────┘   │ allocation        │
                      │            └─────────┬────────┘
                      ▼                      │
              ┌────────────────┐             │
              │ Constraint     │◄────────────┘
              │ Validation     │
              └───────┬────────┘
                      │
                      ▼
              ┌────────────────┐
              │ Stress Engine  │
              │ default/custom  │
              └───────┬────────┘
                      │
              ┌───────┴────────┐
              │                │
             PASS             FAIL
              │                │
              ▼                ▼
      ┌──────────────┐   ┌──────────────┐
      │ Explanation  │   │ Reject +     │
      │ Generator    │   │ Last Safe    │
      └──────┬───────┘   └──────┬───────┘
             │                  │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ Human Approval   │
             │ Approve / Reject │
             │ Keep Current     │
             │ Optional Override│
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ Simulated Trade  │
             │ / Portfolio State │
             └────────┬─────────┘
                      ▼
             ┌──────────────────┐
             │ Audit / Decision │
             │ Replay           │
             └──────────────────┘
```

---

# 6. Core Closed-Loop Workflow

## Step 1 — Ingest market data

Retrieve historical/current market information using `jugaad-data` where supported.

The system should be designed so the demo can fall back to cached historical data if live retrieval fails.

This is important because live external data must never be allowed to break the core demonstration.

## Step 2 — Validate data

Before calculations:
- detect missing observations,
- detect stale data,
- verify expected columns,
- verify price/return continuity,
- handle non-trading days,
- flag suspicious values.

A data-integrity failure should be treated as a control event rather than silently producing a portfolio.

## Step 3 — Build portfolio state

Represent:
- total capital,
- asset positions,
- asset weights,
- cash/liquid assets,
- current prices,
- current portfolio value,
- historical portfolio returns.

Default demo:
**₹100 crore**

## Step 4 — Calculate risk

Calculate:
- historical volatility,
- EWMA volatility,
- portfolio volatility,
- Sharpe ratio,
- historical VaR,
- historical CVaR,
- parametric VaR,
- Monte Carlo VaR where feasible,
- maximum/rolling drawdown,
- concentration,
- sector exposure,
- risk contribution,
- liquidity metrics,
- turnover.

## Step 5 — Determine risk state

Each policy is classified as:
- GREEN — healthy
- AMBER — approaching threshold
- RED — hard breach/critical

## Step 6 — Trigger optimization

Optimization can be:
- user-requested,
- scheduled/rebalance-triggered,
- triggered by risk deterioration,
- triggered by a market scenario.

## Step 7 — Generate candidate portfolios

Candidate optimizers:
1. Maximum Sharpe / constrained MVO — default
2. Minimum volatility
3. Target return
4. CVaR minimization
5. HRP
6. Black-Litterman + constrained allocation

## Step 8 — Validate independently

Check:
- weight bounds,
- sector limits,
- liquidity,
- minimum cash,
- volatility,
- CVaR,
- drawdown-related policy,
- turnover,
- transaction cost,
- stress loss,
- numerical feasibility.

## Step 9 — Stress test

A candidate that passes ordinary constraints must still survive configured stress scenarios.

## Step 10 — Explain

Generate structured reasons:
- trigger,
- changed risk,
- major contributors,
- proposed action,
- rejected constraints,
- stress results,
- expected improvement.

Optional LLM converts structured facts into natural-language explanation.

## Step 11 — Human decision

Dashboard:
- Approve
- Reject
- Keep Current Allocation

For critical cases:
- Request Override / controlled override flow

## Step 12 — Record audit event

Store the complete decision chain.

---

# 7. Portfolio Model

## 7.1 Demo capital

Default:
**₹100 crore**

This is large enough to make institutional liquidity and transaction constraints meaningful while remaining easy to visualize.

## 7.2 Asset universe

The final universe should contain approximately 8–12 instruments/proxies, selected for:
- meaningful Indian market representation,
- available historical data,
- diversification,
- liquidity,
- understandable behavior.

Potential categories:
- Broad Indian equity
- Banking
- IT
- Pharma/FMCG or another defensive sector
- Gold
- Government securities / bond proxy
- Corporate debt proxy where reliable data is available
- Cash/T-bill proxy

The implementation should prefer instruments with reproducible historical series over pretending that every asset class has identical data availability.

## 7.3 Portfolio representation

For each asset:

```text
Asset
Ticker / identifier
Asset class
Sector
Price
Position value
Portfolio weight
Historical returns
Liquidity estimate
Risk contribution
Minimum weight
Maximum weight
```

---

# 8. Risk Engine

The risk engine is one of CCE's most important components.

## 8.1 Historical volatility

Standard historical volatility provides the baseline comparison.

For return series r_t:

σ = standard deviation of returns × √annualization_factor

The dashboard should show both:
- Historical volatility
- EWMA volatility

This makes the value of responsive risk estimation visible.

---

# 9. EWMA Volatility

EWMA is the default responsive risk estimator.

For variance:

σ²_t = λ σ²_{t-1} + (1 − λ) r²_{t-1}

where:
- λ is the decay factor,
- recent observations receive greater influence.

The implementation should use a documented decay parameter and make it configurable.

Purpose:

If recent Indian market volatility increases sharply, EWMA should react faster than a long-window historical estimate.

Dashboard comparison:

```text
Historical Volatility: 11.4%
EWMA Volatility:       15.7%
Recent Risk Regime:    Elevated
```

This supports the narrative that CCE responds to current conditions rather than blindly relying on long-run averages.

---

# 10. Covariance Estimation

The optimizer requires an estimate of the covariance matrix.

Baseline:
- historical covariance,
- EWMA covariance as the responsive option.

The covariance matrix should be checked for numerical validity before optimization.

If necessary:
- regularize,
- repair numerical issues,
- reject unstable solutions.

The exact implementation should favor numerical stability over theoretical complexity.

---

# 11. Sharpe Ratio

Portfolio Sharpe ratio:

Sharpe = (E[R_p] − R_f) / σ_p

where:
- E[R_p] is expected portfolio return,
- R_f is the risk-free/reference rate,
- σ_p is portfolio volatility.

The default optimization objective is to maximize Sharpe subject to institutional constraints.

---

# 12. Value at Risk

## 12.1 Historical VaR

Primary MVP method.

Given historical portfolio returns, historical VaR at confidence level α is the loss percentile corresponding to the α tail.

Example:
At 95% confidence, the system identifies the threshold exceeded by the worst 5% of observations.

## 12.2 Parametric VaR

Secondary mandatory method where time permits.

Assumes a distributional form and derives VaR from portfolio mean and volatility.

Its purpose is comparison rather than unquestioned authority.

## 12.3 Monte Carlo VaR

Stretch/target capability.

Simulate portfolio return outcomes using estimated distributional parameters/covariance.

A configurable simulation count can be used, with approximately 10,000 simulations suitable for the demo if performance allows.

---

# 13. Conditional VaR

CVaR measures the expected loss in the tail beyond VaR.

For CCE, historical CVaR is the primary tail-risk metric.

Why CVaR matters:

VaR tells the risk manager approximately where the tail begins.

CVaR tells them how severe the tail is after that point.

This is particularly useful for evaluating candidate allocations under adverse conditions.

---

# 14. Risk Contribution

CCE should not only ask:

> How much capital is allocated to an asset?

It should also ask:

> How much portfolio risk is caused by that asset?

For a portfolio with covariance matrix Σ and weights w:

Portfolio variance:
σ²_p = wᵀΣw

Marginal contribution to risk:
MCR_i = (Σw)_i / σ_p

Component contribution can be represented as:

RC_i = w_i × MCR_i

Risk contribution percentage:

RC_i / Σ RC_j

This allows CCE to identify cases where an asset is within its allocation limit but dominates portfolio risk.

Example:

```text
Banking allocation: 24%
Banking risk contribution: 43%
Status: AMBER
Reason: Risk concentration exceeds risk budget
```

This is a major differentiator from basic allocation tools.

---

# 15. Concentration Controls

Controls should operate at multiple levels.

## Asset-level
Maximum allocation to a single instrument.

## Sector-level
Maximum allocation to a sector.

## Optional asset-class level
Maximum exposure to equity, fixed income, gold, etc.

## Risk-contribution level
Maximum contribution from an asset/sector.

This prevents the optimizer from exploiting a loophole where capital concentration is technically legal but risk concentration becomes excessive.

---

# 16. Liquidity Controls

Liquidity should be modeled progressively.

## Minimum requirement

Maintain a minimum liquid allocation.

## Intermediate control

Limit:
- position size,
- turnover,
- trade size.

## Stronger optional control

Where reliable volume data exists, estimate average daily traded value.

Approximate days-to-liquidate:

Days to Liquidate =
Position Value /
(Participation Rate × Average Daily Value Traded)

This should be treated as an estimate, not a guarantee of execution.

If reliable volume data is unavailable, CCE should fall back to the simpler liquidity controls rather than fabricate precision.

---

# 17. Transaction Costs

A rebalance should not be considered free.

Approximate transaction cost:

Cost = Σ c_i |w_i,new − w_i,current| × PortfolioValue

where c_i is an estimated transaction-cost rate.

The optimizer should penalize unnecessary turnover.

Conceptually:

Objective =
Risk-adjusted return
− transaction-cost penalty
− turnover penalty

The exact objective formulation should be selected during implementation based on numerical stability and interpretability.

---

# 18. Turnover Constraint

CCE should impose a maximum rebalance size.

Example:

Maximum Turnover = 25%

This prevents an optimizer from replacing most of a ₹100 crore portfolio simply because small expected-return differences make it mathematically attractive.

Turnover should be both:
- a constraint,
- and a displayed metric.

---

# 19. Drawdown Monitoring

CCE should track:
- current drawdown,
- rolling drawdown,
- maximum historical drawdown.

Drawdown is primarily a monitoring metric, but severe configured drawdown conditions may contribute to an AMBER/RED control state.

The exact trigger should be configurable rather than hard-coded as a universal financial rule.

---

# 20. Risk Policy Framework

CCE should use a three-state policy model.

## GREEN

Normal operating range.

Actions:
- normal monitoring,
- optimization allowed,
- standard approvals.

## AMBER

Approaching a risk limit or showing deterioration.

Actions:
- visual warning,
- risk explanation,
- optimization recommendation allowed,
- increased attention,
- no automatic hard freeze unless another hard condition is triggered.

## RED

Hard policy breach or critical system condition.

Actions:
- circuit breaker,
- unsafe candidate rejection,
- preserve last approved safe allocation,
- require explicit human decision,
- generate high-priority alert.

---

# 21. Example Demo Thresholds

These are prototype policy values, not claims of universal institutional standards.

Example:

| Metric | Green | Amber | Red |
|---|---:|---:|---:|
| Annualized volatility | <12% | 12–15% | >15% |
| 95% CVaR | <6% | 6–8% | >8% |
| Single asset concentration | <30% | 30–40% | >40% |
| Sector concentration | <25% | 25–35% | >35% |
| Minimum liquid assets | >15% | 10–15% | <10% |
| Turnover | <20% | 20–25% | >25% |

These values should be clearly labeled as configurable demonstration policy settings.

The dashboard should allow the risk manager to change thresholds.

If a user attempts to weaken a hard threshold substantially, CCE should display a policy-weakening warning and require explicit confirmation. The change should be recorded in the audit trail.

---

# 22. Optimization Engine

## 22.1 Default: Maximum Sharpe

The primary optimizer solves:

maximize:
(E[R_p] − R_f) / σ_p

subject to:
- Σw_i = 1
- w_min,i ≤ w_i ≤ w_max,i
- sector limits
- liquidity requirements
- turnover constraint
- transaction-cost consideration
- risk limits where directly formulable
- optional short-selling restrictions

The actual solver should use CVXPY where the selected formulation is convex/appropriate.

Where the direct Sharpe formulation creates numerical difficulty, the implementation can use a mathematically stable equivalent or a two-stage formulation.

---

# 23. Alternative Optimization Modes

CCE should support multiple strategies.

## 23.1 Minimum Volatility

Minimize:

wᵀΣw

subject to policy constraints.

Purpose:
Generate a defensive allocation.

## 23.2 Target Return

Minimize risk subject to:

E[R_p] ≥ target_return

Purpose:
Allow risk managers to choose an expected-return objective.

## 23.3 CVaR Minimization

Minimize tail risk while satisfying return/portfolio constraints.

Purpose:
Generate tail-risk-aware defensive portfolios.

## 23.4 HRP

Hierarchical Risk Parity should be implemented as an alternative allocation method.

Concept:
- measure asset similarity,
- cluster assets,
- allocate risk hierarchically,
- avoid excessive dependence on expected-return estimates.

CCE can compare HRP against MVO.

## 23.5 Black-Litterman

Black-Litterman should be implemented as an alternative expected-return framework.

The important concept is:
- start with equilibrium/reference returns,
- incorporate investor views,
- produce posterior expected returns,
- feed those returns into constrained optimization.

Views can be entered by the user.

Example:

```text
View:
IT will outperform broad equity by 2%.

Confidence:
60%
```

CCE should then show how the view affects the resulting allocation.

---

# 24. Expected Return Estimation

The system should support:

1. Historical mean
2. EWMA-based estimate
3. Black-Litterman posterior

The default should prioritize stability and explainability.

Expected returns are inherently uncertain. CCE should therefore avoid presenting them as facts.

The dashboard should label them as:
**Model Estimates**

---

# 25. Safe vs Optimal Allocation

This is a signature CCE feature.

The dashboard should display two portfolios.

## Mathematically Optimal

The allocation that best satisfies the chosen optimization objective.

## Risk-Controlled Safe Allocation

The best allocation that passes CCE's complete control framework.

Example:

```text
OPTIMAL
Expected Return: 14.8%
Sharpe: 1.31
CVaR: 9.4%
Banking: 43%
Status: REJECTED

SAFE
Expected Return: 13.2%
Sharpe: 1.17
CVaR: 7.3%
Banking: 28%
Status: APPROVAL REQUIRED
```

The system should explicitly explain:

> The optimal portfolio was rejected because it exceeded the CVaR and banking concentration limits.

This directly demonstrates why an institutional control layer is needed around optimization.

---

# 26. Circuit Breaker

The circuit breaker is a core safety mechanism.

## 26.1 Trigger categories

### Risk breach
- volatility,
- VaR/CVaR,
- drawdown,
- risk contribution.

### Constraint breach
- allocation,
- sector,
- liquidity,
- turnover.

### Market/data integrity breach
- stale data,
- missing critical observations,
- abnormal values.

### Model/optimizer failure
- infeasible optimization,
- invalid covariance,
- numerical failure,
- unstable output.

### Stress breach
- unacceptable scenario loss.

## 26.2 Circuit-breaker behavior

```text
Candidate generated
        ↓
Hard validation
        ↓
FAIL
        ↓
Reject candidate
        ↓
Preserve last approved allocation
        ↓
Generate alert
        ↓
Generate alternative recovery candidates
        ↓
Require human decision
```

The circuit breaker should never silently replace the last safe allocation with an unsafe optimizer output.

---

# 27. Last Approved Safe Allocation

Definition:

> The most recently approved allocation that successfully passed the configured hard controls and stress validation at the time of approval.

Important:
The system should call it **Last Approved Safe Allocation**, not imply that it is guaranteed to remain safe under future market conditions.

The current portfolio and last approved safe allocation should be shown separately.

---

# 28. Recovery Allocations

When a circuit breaker activates, CCE should generate up to three recovery alternatives:

1. **Maximum Sharpe Recovery**
2. **Minimum Risk Recovery**
3. **Maximum Liquidity / Defensive Recovery**

Each must independently pass hard controls before being offered for approval.

This transforms the circuit breaker from a simple "stop" mechanism into a decision-support mechanism.

---

# 29. Human Approval

The dashboard should provide:

### Approve
Accept the validated recommendation.

### Reject
Reject the recommendation.

### Keep Current Allocation
Do not adopt the recommendation and retain the current approved state.

### Controlled Override
For critical cases, an override can be requested with:
- explicit confirmation,
- reason/comment,
- affected controls,
- timestamp,
- user identity/role.

For the hackathon, authentication can be simulated as a "Risk Manager" user.

A hard RED allocation should not have a normal one-click approval path.

---

# 30. No Automatic Real Trade Execution

The MVP should not connect to a real brokerage or execute real market orders.

Instead:

**Approval → Simulated Rebalance → Portfolio State Update**

This keeps the project focused on capital management and control logic.

Production architecture can later connect the approved trade set to an execution-management or brokerage layer.

---

# 31. Stress Testing Engine

Stress testing answers:

> What happens if the market moves in an adverse but plausible way?

## 31.1 Default scenarios

Recommended scenarios:
1. Broad market crash
2. Banking-sector crisis
3. IT-sector correction
4. Interest-rate shock
5. Liquidity shock
6. Combined severe scenario
7. Historically inspired severe event

## 31.2 Custom scenarios

Users can specify shocks.

Example:

```text
Broad Equity:   -12%
Banking:        -18%
IT:              -8%
Gold:            +5%
Bond proxy:      -4%
Liquidity:       -20%
```

CCE calculates:
- portfolio loss,
- asset-level contribution,
- post-shock risk,
- policy breaches,
- candidate acceptability.

## 31.3 Stress-test decision rule

If a candidate passes ordinary controls but fails a configured severe stress-loss threshold, it can still be rejected.

This is critical because normal historical metrics can underestimate the effect of correlated shocks.

---

# 32. Monte Carlo Simulation

Monte Carlo should be implemented if stable and performant after the core engine works.

Potential uses:
- simulated return distributions,
- VaR/CVaR comparison,
- scenario visualization,
- portfolio uncertainty.

It should not be allowed to become a dependency for the basic control loop.

---

# 33. Backtesting

Backtesting is mandatory at a basic level.

The objective is not simply:

> Did CCE make more money?

The stronger question is:

> Did CCE improve the balance between return and risk while reducing policy breaches and drawdowns?

## 33.1 Strategies to compare

1. Buy-and-hold/current portfolio
2. Uncontrolled optimizer
3. CCE-controlled strategy

## 33.2 Metrics

- cumulative return,
- annualized return,
- volatility,
- Sharpe,
- maximum drawdown,
- VaR,
- CVaR,
- turnover,
- transaction costs,
- number of policy breaches,
- number of circuit-breaker activations.

## 33.3 Rebalancing

Default:
Monthly.

Optional:
Weekly.

## 33.4 Look-ahead prevention

At every rebalance date:

```text
Historical data available BEFORE date
          ↓
Estimate returns/risk
          ↓
Optimize
          ↓
Validate
          ↓
Apply to NEXT period
```

No future observations may be used when constructing the decision.

This should be explicitly documented because a backtest with look-ahead bias would undermine the credibility of the system.

---

# 34. Decision Replay

Decision Replay is another signature feature.

Instead of only showing a log table, show a chronological decision timeline.

Example:

```text
10:02  Market shock detected
   ↓
10:02  EWMA volatility increased
   ↓
10:02  Banking risk contribution increased
   ↓
10:03  CVaR crossed RED threshold
   ↓
10:03  Circuit breaker activated
   ↓
10:04  Max-Sharpe candidate generated
   ↓
10:04  Candidate failed concentration + CVaR checks
   ↓
10:04  Candidate rejected
   ↓
10:05  Three recovery candidates generated
   ↓
10:05  Stress validation completed
   ↓
10:06  Risk Manager approved Minimum-Risk Recovery
   ↓
10:06  Simulated rebalance applied
   ↓
10:06  Audit event stored
```

The timeline should clearly distinguish:
- automated system action,
- control-engine decision,
- human intervention.

---

# 35. Audit Log

Every material decision should store:

- event ID,
- timestamp,
- triggering event,
- market snapshot/reference,
- portfolio before,
- portfolio metrics before,
- risk state,
- violated policies,
- optimizer used,
- expected-return method,
- candidate allocation,
- constraint results,
- stress results,
- control-engine decision,
- recommended allocation,
- human action,
- user/role,
- override reason,
- resulting portfolio state.

This provides traceability and makes CCE demonstrably different from a black-box optimizer.

---

# 36. Explainability Layer

The deterministic engine should produce structured explanation objects.

Example:

```text
Trigger:
Banking volatility increased sharply.

Risk change:
EWMA portfolio volatility increased from 11.8% to 15.6%.

Main contributor:
Banking sector risk contribution increased from 27% to 41%.

Optimizer:
Maximum Sharpe.

Candidate:
Banking weight increased to 43%.

Control result:
REJECTED.

Reasons:
1. Banking concentration > 40%.
2. CVaR > 8%.
3. Severe stress loss > configured limit.

Action:
Generate defensive recovery allocations.
```

This structured explanation is the source of truth.

---

# 37. LLM Role

The LLM is optional and explanation-only.

Allowed:
- summarize risk,
- explain a decision in natural language,
- describe scenario assumptions,
- turn structured metrics into a risk-manager briefing.

Not allowed:
- choose weights,
- alter thresholds,
- modify risk scores,
- approve allocations,
- override circuit breakers,
- modify audit records,
- replace deterministic calculations.

Architecture:

```text
Deterministic Financial Engine
          ↓
Structured Explanation JSON
          ↓
Optional LLM
          ↓
Natural-language explanation
```

If no API key is available, CCE should still work using deterministic templates.

This guarantees that the demo does not depend on an external AI service.

---

# 38. Dashboard Design

Recommended pages:

## 38.1 Executive Overview

Show:
- portfolio value,
- expected return,
- volatility,
- Sharpe,
- VaR,
- CVaR,
- liquidity,
- risk state,
- top exposures,
- current action.

## 38.2 Portfolio & Exposure

Show:
- allocation,
- sector exposure,
- asset weights,
- risk contribution,
- concentration,
- liquidity.

## 38.3 Risk Control Center

Show:
- GREEN/AMBER/RED controls,
- current vs threshold,
- trend,
- breached policies,
- circuit-breaker state.

## 38.4 Optimizer

Inputs:
- strategy,
- expected-return method,
- risk profile,
- constraints.

Outputs:
- current,
- unconstrained/optimal,
- safe,
- recommended trades,
- expected metrics,
- transaction costs.

## 38.5 Stress Lab

Show:
- predefined scenarios,
- custom scenario builder,
- before/after allocation,
- portfolio loss,
- risk changes,
- control status.

## 38.6 Backtesting

Show:
- strategy comparison,
- returns,
- risk,
- drawdown,
- CVaR,
- breaches,
- turnover.

## 38.7 Decision Replay

Show:
- chronological events,
- machine actions,
- control decisions,
- human actions,
- audit record.

## 38.8 Policy / Settings

Show:
- risk thresholds,
- portfolio constraints,
- liquidity requirements,
- turnover,
- optimizer settings.

---

# 39. Executive Dashboard Hero View

The first screen should communicate the whole product in seconds.

Example:

```text
CCE — Capital Control Engine

₹100 Cr Institutional Portfolio

Risk State: RED

Portfolio Value       ₹100.0 Cr
Expected Return       13.2%
EWMA Volatility       15.6%
Historical Volatility 11.8%
95% CVaR              8.7%
Liquidity              11%
Sharpe                 0.94

BREACHES
● CVaR — RED
● Liquidity — RED
● Banking Risk Contribution — AMBER

RECOMMENDED ACTION
Circuit breaker active.
Uncontrolled optimizer rejected.

[View Safe vs Optimal]
[Open Recovery Options]
[Decision Replay]
```

This is the judge-facing home page.

---

# 40. "What Changed?" Feature

CCE should explain risk movement, not merely display it.

Example:

```text
WHAT CHANGED?

Portfolio volatility:
11.8% → 15.6%

Primary driver:
Banking volatility

Banking allocation:
24% → 24%

Banking risk contribution:
27% → 41%

Interpretation:
Allocation did not materially change, but recent
banking volatility increased sharply, causing its
contribution to portfolio risk to rise.
```

This is a powerful demonstration of why EWMA and risk contribution matter.

---

# 41. Data Layer

Primary data source selected:

**jugaad-data**

Use it for supported Indian market/RBI data retrieval.

Design the data layer behind an internal interface:

```python
MarketDataProvider
    ├── JugaadDataProvider
    └── CachedDataProvider
```

The cached provider is important for deterministic hackathon demos.

The UI should never directly depend on the data library.

---

# 42. Recommended Technology Stack

## Core

- Python
- Pandas
- NumPy
- SciPy
- CVXPY

## Data

- jugaad-data
- cached CSV/Parquet where useful

## UI

- Streamlit
- Plotly

## Persistence

- SQLite

## Testing

- pytest

## Version control

- Git
- GitHub

## Optional

- FastAPI only if a genuine separation/API need emerges
- LLM provider integration only after deterministic functionality works

For a 24-hour hackathon, Streamlit + modular Python is preferable to introducing React/FastAPI unless implementation needs force the change.

---

# 43. Proposed Repository Structure

```text
cce/
│
├── app.py
├── README.md
├── CLAUDE.md
├── requirements.txt
├── .env.example
│
├── data/
│   ├── raw/
│   ├── processed/
│   └── cache/
│
├── cce/
│   ├── data/
│   │   ├── providers.py
│   │   ├── jugaad_provider.py
│   │   ├── cache.py
│   │   └── validation.py
│   │
│   ├── portfolio/
│   │   ├── models.py
│   │   ├── state.py
│   │   └── calculations.py
│   │
│   ├── risk/
│   │   ├── volatility.py
│   │   ├── ewma.py
│   │   ├── var.py
│   │   ├── cvar.py
│   │   ├── drawdown.py
│   │   ├── concentration.py
│   │   ├── risk_contribution.py
│   │   └── liquidity.py
│   │
│   ├── optimizer/
│   │   ├── base.py
│   │   ├── mean_variance.py
│   │   ├── min_volatility.py
│   │   ├── target_return.py
│   │   ├── cvar_optimizer.py
│   │   ├── hrp.py
│   │   └── black_litterman.py
│   │
│   ├── controls/
│   │   ├── policy.py
│   │   ├── validation.py
│   │   ├── state_machine.py
│   │   └── circuit_breaker.py
│   │
│   ├── stress/
│   │   ├── scenarios.py
│   │   ├── engine.py
│   │   └── monte_carlo.py
│   │
│   ├── decisions/
│   │   ├── recommendation.py
│   │   ├── explanation.py
│   │   └── replay.py
│   │
│   ├── audit/
│   │   ├── database.py
│   │   └── events.py
│   │
│   └── backtest/
│       ├── engine.py
│       └── metrics.py
│
├── ui/
│   ├── overview.py
│   ├── portfolio.py
│   ├── risk.py
│   ├── optimizer.py
│   ├── stress.py
│   ├── backtest.py
│   ├── replay.py
│   └── settings.py
│
└── tests/
    ├── test_risk.py
    ├── test_optimizer.py
    ├── test_controls.py
    ├── test_stress.py
    └── test_backtest.py
```

The exact structure may be simplified during implementation if it improves speed without sacrificing separation of concerns.

---

# 44. Core Data Contracts

The modules should communicate using structured objects rather than arbitrary dictionaries wherever practical.

## PortfolioState

```text
portfolio_id
timestamp
total_value
cash_value
positions
weights
```

## RiskSnapshot

```text
timestamp
historical_volatility
ewma_volatility
sharpe
var_95
cvar_95
drawdown
risk_contribution
concentration
liquidity
risk_state
breaches
```

## OptimizationResult

```text
strategy
expected_return_method
weights
expected_return
volatility
sharpe
var
cvar
turnover
transaction_cost
solver_status
```

## ControlResult

```text
status
passed
failed_controls
warnings
hard_breaches
circuit_breaker_active
last_safe_allocation
```

## DecisionRecord

```text
event_id
timestamp
trigger
risk_snapshot
optimization_result
control_result
stress_result
recommendation
human_action
override_reason
portfolio_after
```

---

# 45. Control Engine State Machine

A useful state model:

```text
GREEN
  │
  ├── warning → AMBER
  │
  └── hard breach → RED

AMBER
  │
  ├── recovery → GREEN
  │
  └── hard breach → RED

RED
  │
  ├── validated recovery + approval → GREEN/AMBER
  │
  └── no approved recovery → remain RED
```

The exact state-transition logic should be centralized rather than scattered across UI code.

---

# 46. Safety Invariants

These should be treated as non-negotiable system rules.

1. The LLM cannot modify financial decisions.
2. An invalid optimizer output cannot become an approved allocation.
3. A hard control failure cannot be silently ignored.
4. If optimization fails, retain the last approved allocation.
5. Missing critical market data cannot be silently interpreted as zero risk.
6. Every approval/rejection should be auditable.
7. Backtesting must not use future information.
8. User-configured thresholds should be versioned/audited.
9. The dashboard should distinguish current portfolio, optimal candidate, and safe candidate.
10. A stress-tested failure must remain visible even if normal risk metrics pass.

---

# 47. Error Handling / Fail-Safe Design

Examples:

## Optimizer failure

```text
Optimization failed
→ reject candidate
→ preserve last approved allocation
→ show technical/model alert
```

## Missing market data

```text
Data validation failed
→ do not recalculate unsafe metrics
→ mark data state as invalid
→ preserve prior state
```

## Stress engine failure

A candidate should not be represented as fully validated if mandatory stress testing failed.

## Database failure

Core analysis should fail visibly rather than claiming that an audit record was successfully stored.

---

# 48. Security and Reliability

Use the official Anthropic Security Guidance plugin during development/review.

The project should avoid:
- hard-coded API keys,
- unsafe file access,
- arbitrary shell execution from user input,
- SQL injection,
- unsafe deserialization,
- exposing secrets in Streamlit,
- trusting LLM output as executable instructions.

However, security tooling must remain subordinate to the hackathon goal; do not add a large plugin ecosystem that slows development.

---

# 49. Claude Code Development Setup

Selected development tools:

## Claude Code
Primary implementation agent.

## Claude-Mem
Persistent context between Claude Code sessions.

## Prompt Master
Use for converting rough development instructions into precise, token-efficient Claude Code prompts.

## Graphifyy
Use once/as needed after meaningful architecture exists to inspect relationships in the codebase.

## Anthropic Security Guidance
Use for security-focused code review.

Explicitly excluded from the project workflow:
- Codebase Memory MCP
- Skill Security Scanner
- TradingAgents as a dependency
- large multi-agent frameworks
- unnecessary MCPs

The goal is a compact engineering workflow, not an oversized agent stack.

---

# 50. CLAUDE.md Project Constitution

Recommended initial project instructions:

```text
PROJECT:
CCE — Capital Control Engine
INIT'26 FinTech Hackathon

MISSION:
Build an institutional capital-management prototype that optimizes
risk-adjusted allocation while independently enforcing safety controls.

CORE LOOP:
Detect → Optimize → Validate → Stress-test → Explain → Human Approval

DATA:
Use jugaad-data for supported Indian market data.
Use cached data so the demo does not depend on live connectivity.

CORE FINANCIAL METHODS:
- Mean-Variance Optimization
- EWMA volatility
- Historical VaR
- Historical CVaR
- Risk contribution
- Concentration controls
- Liquidity constraints
- Transaction costs
- Turnover constraints
- Stress testing
- Basic backtesting

ALTERNATIVE METHODS TO BUILD:
- HRP
- Black-Litterman
- Minimum volatility
- Target return
- CVaR optimization
- Parametric VaR
- Monte Carlo where feasible

SAFETY:
- GREEN/AMBER/RED states
- Circuit breaker
- Last Approved Safe Allocation
- Independent constraint validation
- Human approval
- Full decision audit

LLM:
Explanation-only.
Never modify weights, risk metrics, thresholds, control states,
optimizer outputs, or approval decisions.

DO NOT:
- Build a retail stock-picking app.
- Build an autonomous trading bot.
- Use TradingAgents as a dependency.
- Add unnecessary ML.
- Add GARCH/copulas/EVT/deep RL unless explicitly reconsidered.
- Allow UI code to bypass control-engine validation.
- Claim guaranteed returns.
- Claim live execution if the prototype only simulates execution.

ENGINEERING:
- Keep modules small.
- Prefer deterministic functions.
- Write tests for financial calculations and safety invariants.
- Keep business logic out of Streamlit UI.
- Never silently swallow errors.
- Preserve reproducibility.
```

---

# 51. Testing Strategy

Testing should focus on financial correctness and safety, not just UI coverage.

## Unit tests

Test:
- return calculation,
- EWMA,
- covariance,
- Sharpe,
- VaR,
- CVaR,
- drawdown,
- risk contribution,
- turnover,
- transaction cost.

## Constraint tests

Given an allocation above the maximum asset weight:
Expected:
**FAIL**

Given allocation above sector limit:
Expected:
**FAIL**

Given liquidity below minimum:
Expected:
**FAIL**

## Circuit-breaker tests

Unsafe candidate:
Expected:
- rejected,
- circuit breaker active,
- last approved allocation preserved.

## LLM safety test

Malformed/exaggerated LLM explanation:
Expected:
- no change to financial decision.

## Backtest tests

Ensure:
- rebalance uses only prior data,
- no future returns leak into estimates.

---

# 52. Demo Scenario

The primary judge demonstration should follow a single coherent story.

## Stage 1 — Healthy portfolio

Display:
- ₹100 Cr
- balanced allocation
- GREEN status
- reasonable risk
- current/optimal/safe allocations.

## Stage 2 — Introduce banking-sector shock

The user opens Stress Lab and applies:

```text
Banking: -18%
Broad market: -12%
IT: -8%
Gold: +5%
```

Alternatively, a prepared market-data event can be loaded.

## Stage 3 — Risk changes

CCE recalculates.

EWMA responds quickly.

Banking risk contribution rises.

CVaR becomes RED.

## Stage 4 — Circuit breaker

CCE announces:

> Hard risk policy breach detected. New unsafe allocation blocked.

## Stage 5 — Show Optimal vs Safe

Uncontrolled Max-Sharpe candidate:

```text
Expected Sharpe: higher
Banking exposure: too high
CVaR: above policy
Stress loss: above policy
Status: REJECTED
```

Safe candidate:

```text
Lower theoretical Sharpe
Better risk compliance
Passes stress controls
Status: ELIGIBLE FOR APPROVAL
```

## Stage 6 — Recovery options

Show:
- Max-Sharpe Recovery
- Minimum-Risk Recovery
- Defensive/Liquidity Recovery

## Stage 7 — Human intervention

Risk manager selects:

**Approve**

or rejects/keeps current.

The interface should explicitly show:

**Human Intervention: YES**

## Stage 8 — Decision Replay

Open the timeline and show every machine and human step.

## Stage 9 — Backtest

Show that CCE's controlled approach reduces:
- breaches,
- extreme drawdowns,
- uncontrolled concentration,

while balancing return and risk.

This is the complete narrative judges should remember.

---

# 53. Judge-Facing Innovation

CCE's strongest innovation is not a new mathematical formula.

It is the combination of:

### 1. Optimization + independent control

The optimizer is not trusted blindly.

### 2. Safe vs Optimal

The system explicitly demonstrates why the theoretically optimal answer may be institutionally unacceptable.

### 3. Circuit breaker + Last Approved Safe Allocation

Unsafe outputs are blocked rather than propagated.

### 4. Risk contribution

CCE detects hidden concentration that allocation percentages alone can miss.

### 5. Stress-aware validation

A candidate must survive adverse scenarios.

### 6. Decision Replay

Every important machine and human decision is auditable.

### 7. Deterministic financial engine + optional LLM explanation

AI improves usability without controlling capital decisions.

---

# 54. Mapping to Hackathon Evaluation

## Financial & Control Logic — 35%

CCE addresses:
- constrained optimization,
- EWMA risk,
- VaR/CVaR,
- risk contribution,
- liquidity,
- concentration,
- transaction costs,
- stress testing,
- dynamic rebalancing,
- circuit breaker.

This should be the strongest part of the submission.

## Technical Architecture — 30%

Strengths:
- modular Python engines,
- independent control layer,
- cached market-data architecture,
- SQLite audit state,
- deterministic calculations,
- testable components,
- Streamlit interface.

## UX & Clarity — 20%

Strengths:
- GREEN/AMBER/RED states,
- safe vs optimal,
- risk dashboards,
- stress lab,
- decision replay,
- actionable approval controls.

## Innovation — 15%

Strengths:
- optimization-control separation,
- safe allocation fallback,
- independent validation,
- risk attribution,
- human-in-the-loop,
- auditability.

The official problem statement weights these four categories at 35%, 30%, 20%, and 15% respectively. 

---

# 55. What CCE Should NOT Overclaim

Avoid statements such as:
- "guarantees optimal returns,"
- "guarantees regulatory compliance,"
- "predicts market crashes,"
- "executes trades automatically,"
- "provides real-time institutional execution,"
- "eliminates investment risk."

Prefer:
- "prototype,"
- "decision-support system,"
- "constraint-aware optimization,"
- "near-real-time/event-driven architecture,"
- "configurable risk policies,"
- "simulated execution,"
- "demonstration of institutional control concepts."

---

# 56. Implementation Priority for the 24-Hour Hackathon

## P0 — Must work

1. Market data/cached data
2. Portfolio state
3. Historical returns
4. Historical volatility
5. EWMA volatility
6. Historical VaR
7. Historical CVaR
8. MVO / Max Sharpe
9. Hard constraints
10. GREEN/AMBER/RED
11. Circuit breaker
12. Last Approved Safe Allocation
13. Safe vs Optimal
14. Stress scenarios
15. Human approval buttons
16. Audit log
17. Core dashboard

## P1 — Strong differentiators

1. Risk contribution
2. Liquidity
3. Transaction costs
4. Turnover
5. Minimum-volatility optimizer
6. Target-return optimizer
7. CVaR optimizer
8. HRP
9. Black-Litterman
10. Basic backtesting
11. Decision Replay

## P2 — Add after stability

1. Parametric VaR
2. Monte Carlo
3. Advanced ADV-based liquidity
4. Custom scenario builder enhancements
5. Optional LLM integration
6. Advanced visualization polish

If time becomes constrained, remove cosmetic complexity before removing safety/control functionality.

---

# 57. Recommended Build Order

Do not start with the dashboard.

Build in this order:

### Phase 1 — Data
Get a reproducible dataset working.

### Phase 2 — Portfolio
Build positions, weights and returns.

### Phase 3 — Risk
Implement EWMA, volatility, VaR, CVaR, drawdown and risk contribution.

### Phase 4 — Optimizer
Implement constrained Max Sharpe.

### Phase 5 — Control
Implement policies, GREEN/AMBER/RED and validation.

### Phase 6 — Circuit breaker
Implement rejection + last approved allocation.

### Phase 7 — Stress
Implement default scenarios.

### Phase 8 — Human approval
Implement state transitions.

### Phase 9 — Audit
Persist decision records.

### Phase 10 — Dashboard
Expose the working engine.

### Phase 11 — Alternatives
HRP, Black-Litterman, other optimizers.

### Phase 12 — Backtest
Compare controlled vs uncontrolled strategies.

### Phase 13 — LLM
Only after deterministic functionality is stable.

### Phase 14 — Presentation polish
Build the judge demo around the failure/recovery story.

---

# 58. Key Engineering Rule

The Streamlit UI must never contain the actual financial decision logic.

Bad:

```text
Button click
→ calculate risk
→ modify weights
```

Better:

```text
UI
 ↓
Application/service layer
 ↓
Risk engine / optimizer / control engine
 ↓
Decision result
 ↓
UI renders result
```

This makes the system:
- testable,
- modular,
- explainable,
- easier to convert into APIs later.

---

# 59. Future Production Architecture

The hackathon prototype can later evolve into:

```text
Market Data Streams
        ↓
Data Validation / Normalization
        ↓
Portfolio & Position Service
        ↓
Risk Service
        ↓
Optimization Service
        ↓
Independent Policy Control Service
        ↓
Stress / Scenario Service
        ↓
Approval Workflow
        ↓
Execution Management
        ↓
Audit / Reporting
```

Potential production additions:
- authentication,
- RBAC,
- SSO,
- event streaming,
- distributed services,
- enterprise databases,
- broker/execution integrations,
- regulatory policy libraries,
- model governance,
- monitoring,
- model versioning.

These are not required for the hackathon MVP.

---

# 60. Final Product Definition

CCE is best understood as:

> **A closed-loop institutional capital-control system where optimization proposes, independent controls validate, stress testing challenges, humans approve, and the system records why every important decision occurred.**

The core differentiator can be summarized as:

**Detect → Optimize → Validate → Stress-Test → Explain → Approve → Audit**

And the most important product principle is:

> **The highest-return mathematical allocation is not automatically the allocation an institution should accept. CCE separates optimality from safety.**

---

# 61. Final Demo Checklist

Before submission, CCE should be able to demonstrate:

### Data
- [ ] Indian market data loads
- [ ] Cached fallback works
- [ ] Data validation works

### Portfolio
- [ ] ₹100 Cr portfolio
- [ ] Asset weights
- [ ] Sector exposure
- [ ] Cash/liquidity

### Risk
- [ ] Historical volatility
- [ ] EWMA volatility
- [ ] VaR
- [ ] CVaR
- [ ] Sharpe
- [ ] Drawdown
- [ ] Risk contribution

### Optimization
- [ ] Max Sharpe
- [ ] Constraints
- [ ] Transaction costs
- [ ] Turnover
- [ ] At least one alternative optimizer

### Controls
- [ ] GREEN/AMBER/RED
- [ ] Hard/soft thresholds
- [ ] Independent validation
- [ ] Circuit breaker
- [ ] Last Approved Safe Allocation

### Stress
- [ ] Default scenarios
- [ ] Candidate stress validation
- [ ] Custom scenario if stable

### Human control
- [ ] Approve
- [ ] Reject
- [ ] Keep Current Allocation
- [ ] Human intervention visibly recorded

### Audit
- [ ] Decision log
- [ ] Decision Replay
- [ ] Machine vs human actions

### Backtest
- [ ] Controlled vs uncontrolled
- [ ] Return
- [ ] Risk
- [ ] Drawdown
- [ ] Breaches
- [ ] Turnover
- [ ] No look-ahead bias

### AI
- [ ] Optional
- [ ] Explanation-only
- [ ] Deterministic fallback

---

# 62. Bottom Line

The strongest version of CCE is not the one with the largest number of financial models.

It is the one that makes the following loop extremely convincing:

**A market condition changes → risk changes → CCE detects it → optimizer proposes an allocation → the independent control engine challenges it → unsafe allocation is rejected → a safer alternative is produced → stress tests validate it → a human approves it → the system records exactly what happened.**

That is the story that turns CCE from a portfolio optimizer into a **Capital Control Engine**.
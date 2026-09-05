# 08 — Financial Methods

**Scope:** Every formula CCE implements, with conventions, defaults, numerical-stability rules and the reason each method was chosen.
**Audience:** Whoever writes `cce/risk/` and `cce/optimizer/` — including AI agents, who must not substitute a different formula because it looked equivalent.
**Derived from:** master spec §8–§25, §31–§33.

---

## 0. Global conventions

| Convention | Value | Note |
|---|---|---|
| Return type | **Simple returns** `r_t = P_t/P_{t-1} − 1` | Log returns MAY be used internally where additivity helps, but every reported figure is simple-return based. State which is used in the docstring. |
| Annualisation | `√252` for volatility, `×252` for mean return | `trading_days_per_year` is configurable |
| VaR / CVaR horizon | 1 day | Scale by `√h` only where explicitly labelled |
| Confidence | 95% | Configurable |
| Loss sign | **Positive** | `cvar_95 = 0.087` is an 8.7% expected tail loss |
| Weights | Sum to 1.0, long-only by default | `Σw = 1`, `w ≥ 0` |
| Missing data | Never zero-filled | An unresolvable gap invalidates the window `[INV-5]` |
| Determinism | Every stochastic routine takes an explicit seed | `NFR-012` |

> **Rule for implementers:** each function's docstring states its return convention, annualisation state and units. A function returning "volatility" without saying whether it is daily or annualised is not finished.

---

## 1. Returns

```
r_t = P_t / P_{t-1} − 1
```

Portfolio return from weights held over the period:

```
r_p,t = Σ_i w_i · r_i,t
```

**Implementation notes**
- Drop the first row after differencing; do not pad it.
- Align all assets on a common trading calendar **before** computing returns. Misaligned dates silently corrupt every covariance downstream.
- A date present for some assets and missing for others is a validation finding (`GAP`), not something to forward-fill without recording it.

---

## 2. Historical volatility

The baseline comparison estimator.

```
σ_daily  = stdev(r_t)                    # sample stdev, ddof=1
σ_annual = σ_daily × √252
```

**Purpose in CCE:** it is displayed alongside EWMA so the *difference* is visible. That difference is the evidence that CCE responds to current conditions rather than long-run averages.

```
Historical Volatility: 11.4%
EWMA Volatility:       15.7%
Recent Risk Regime:    Elevated
```

Use `ddof=1` (sample). Be consistent — mixing `ddof=0` and `ddof=1` across modules produces small, maddening discrepancies.

---

## 3. EWMA volatility — the primary responsive estimator

```
σ²_t = λ · σ²_{t−1} + (1 − λ) · r²_{t−1}
```

| Parameter | Default | Meaning |
|---|---|---|
| `λ` (decay) | `0.94` | Higher λ = smoother/slower; lower λ = more responsive |

**Initialisation:** seed `σ²_0` with the sample variance of the first `n` observations (default `n = 60`). Document the seed; do not start from zero, which produces a long meaningless warm-up.

**Zero-mean convention — verified in implementation.** The recursion squares the raw return `r`, not the deviation `(r − μ)`. This is the RiskMetrics convention and is standard for daily horizons, where the mean is negligible beside the volatility and estimating it adds more noise than it removes. Two consequences are visible in the UI and must not surprise anyone:

1. `historical_volatility` **demeans** (`np.std(ddof=1)`); EWMA does not. The two headline figures therefore use different mean conventions. For equities the discrepancy is ~0.25% of the estimate — immaterial.
2. **A constant non-zero return converges to `|r|`, not zero.** Our synthetic CASH proxy drifts at `risk_free_rate / 252` with zero variance, so it reports roughly **0.4% annualised EWMA volatility against 0.0% historical**. The estimator is behaving correctly — but do not describe cash as "zero volatility" while showing an EWMA figure beside it.

**Why EWMA is the default:** if recent Indian market volatility rises sharply, a long-window historical estimate dilutes the change across the whole window. EWMA weights recent observations more heavily and moves within days. That responsiveness is what lets the control engine detect a regime change while it still matters.

```python
def ewma_variance(returns: np.ndarray, lam: float = 0.94,
                  seed_window: int = 60) -> np.ndarray:
    """Return the EWMA variance series (daily, not annualised)."""
```

Annualise the same way as historical volatility: `σ_annual = √(σ²_daily) × √252`.

---

## 4. Covariance estimation

The optimizer needs `Σ`. Two estimators:

| Estimator | Use |
|---|---|
| **Historical sample covariance** | Baseline, stable |
| **EWMA covariance** | Responsive option, consistent with EWMA volatility |

EWMA covariance:

```
Σ_t = λ · Σ_{t−1} + (1 − λ) · r_{t−1} r_{t−1}ᵀ
```

### Numerical validity — mandatory before optimization

`Σ` must be symmetric and positive semi-definite. Sampling noise, short windows and near-collinear assets all break this.

```
1. Symmetrise:      Σ ← (Σ + Σᵀ) / 2
2. Eigen-decompose: Σ = V Λ Vᵀ
3. If min(λ_i) < 0:
     clip negatives to a small ε (e.g. 1e-10), reconstruct
     record a MODEL_COVARIANCE finding (AMBER)
4. Optionally shrink toward a diagonal target:
     Σ_shrunk = (1−δ)·Σ + δ·diag(Σ)
5. Re-check PSD. If it still fails:
     REJECT the optimization run. Do not pass a broken matrix to the solver.
```

**Rule (master spec §10):** favour numerical stability over theoretical sophistication. A repaired-and-recorded matrix beats an exotic estimator that intermittently fails.

An unrepairable covariance is a `MODEL_COVARIANCE` hard breach and trips the breaker. `[INV-4]`

---

## 5. Expected returns — "Model Estimates"

Three supported methods:

| Method | Formula | Character |
|---|---|---|
| **Historical mean** | `μ_i = mean(r_i) × 252` | Stable, noisy, backward-looking |
| **EWMA mean** | Exponentially-weighted mean, annualised | Responsive, noisier |
| **Black-Litterman posterior** | See §11 | Blends equilibrium with views |

**Default:** historical mean, for stability and explainability.

> **Mandatory display rule (`FR-062`):** expected returns are labelled **"Model Estimates"** everywhere they appear. They are the least reliable numbers in the system — mean estimation error dominates covariance estimation error in mean-variance optimization — and presenting them as facts would be the single most misleading thing CCE could do.

---

## 6. Sharpe ratio

```
Sharpe = (E[R_p] − R_f) / σ_p
```

- `E[R_p] = wᵀμ` (annualised)
- `σ_p = √(wᵀΣw)` (annualised)
- `R_f` default `6.5%`, configurable, always displayed as an assumption

---

## 7. Value at Risk

### 7.1 Historical VaR — primary method

```
VaR_α = −percentile(r_p, (1−α) × 100)
```

At 95%, this is the threshold exceeded by the worst 5% of observed portfolio returns. Negated so it is reported as a positive loss.

Non-parametric, makes no distributional assumption, and is directly explainable to a risk manager: *"on the worst 5% of days in our history, we lost at least this much."*

**Requirement:** at least `min_return_observations` (default 250) data points. Below that, return `None` and mark the snapshot `degraded`.

### 7.2 Parametric VaR — secondary, for comparison

```
VaR_α = −(μ_p + z_α · σ_p)          z_0.95 = −1.645
```

Assumes normality — which financial returns violate in exactly the tail this metric is about. Its role is **comparison, not authority**.

**Correction, measured against t(3) samples.** An earlier draft said the normal assumption "understates the tail", full stop. That is only true in the **far** tail. At 95% the normal fitted to a fat-tailed sample inherits that sample's inflated variance and typically **overstates** the loss — for t(3) the true 5% quantile sits near 1.36σ against the normal's 1.645σ. Fat tails only dominate further out.

| Confidence | t(3) sample | Which is larger |
|---|---|---|
| 95% | near tail | **parametric > historical** — normal overstates |
| 99% | far tail | **historical > parametric** — normal understates |

Both directions are asserted in `tests/test_risk.py` so the 99% result is not mistaken for a universal rule. The practical lesson is the one that justifies CVaR as the hard control: **where you measure changes the answer**, and a single threshold-location metric is not enough.

### 7.3 Monte Carlo VaR — stretch

```
1. Estimate μ, Σ from history
2. Cholesky-factor Σ (use the PSD-repaired matrix)
3. Simulate N correlated return paths (default N = 10,000, seeded)
4. Compute portfolio return per path
5. VaR = −percentile(simulated, 5)
```

**Constraint (master spec §32):** Monte Carlo MUST NOT become a dependency of the core control loop. If it is slow or unstable, reduce path count, then disable it. The loop keeps working.

---

## 8. Conditional VaR (Expected Shortfall) — the primary tail metric

```
CVaR_α = −mean( r_p | r_p ≤ −VaR_α )
```

The average loss **given** that the VaR threshold was breached.

| | Answers |
|---|---|
| VaR | *Where does the tail begin?* |
| CVaR | *How bad is it once we are in the tail?* |

CVaR is CCE's primary tail-risk control (`RISK_CVAR_95`, hard) because two candidate portfolios can share a VaR while having very different tail severity — and it is the tail that destroys capital.

**Implementation notes**
- Use the same historical window as VaR.
- If fewer than ~10 observations fall in the tail, the estimate is unstable: return the value but set `degraded = True` with a reason. Do not silently report a mean of three points as a risk limit.

---

## 9. Risk contribution — the hidden-concentration detector

Allocation answers *"how much capital is here?"* Risk contribution answers *"how much of our risk is caused by this?"* These diverge, and the divergence is where institutional risk actually hides.

```
Portfolio variance:              σ²_p = wᵀΣw
Marginal contribution to risk:   MCR_i = (Σw)_i / σ_p
Component contribution:          RC_i  = w_i × MCR_i
Percentage contribution:         PCR_i = RC_i / Σ_j RC_j
```

**Identity:** `Σ_i RC_i = σ_p` exactly. Assert this in tests — it is a free, powerful correctness check on the whole covariance/weight pipeline.

Sector aggregation: `RC_sector = Σ_{i ∈ sector} RC_i`.

**Why it earns its place:**

```
Banking allocation:        24%
Banking risk contribution: 43%
Status: AMBER
Reason: Risk concentration exceeds risk budget
```

The position is comfortably inside its 30% weight cap. It is nonetheless responsible for 43% of portfolio risk. A weight-only control framework cannot see this. `RC_SECTOR_MAX` can.

---

## 10. Concentration and liquidity

### 10.1 Concentration — four levels

| Level | Control | Catches |
|---|---|---|
| Asset weight | `CONC_ASSET_MAX` | Single-name over-exposure |
| Sector weight | `CONC_SECTOR_MAX` | Sector over-exposure |
| Asset-class weight | `CONC_ASSET_CLASS_MAX` | Equity/FI/commodity imbalance |
| **Risk contribution** | `RC_ASSET_MAX`, `RC_SECTOR_MAX` | Capital-legal, risk-illegal positions |

The fourth level exists specifically to close the loophole in the first three: an optimizer can satisfy every weight cap while concentrating risk. Weight limits alone are gameable by a sufficiently determined objective function.

### 10.2 Liquidity — progressive

**Level 1 — minimum liquid share** (always available)
```
liquid_share = Σ_{i : is_liquid} w_i        must be ≥ min_liquid_share
```

**Level 2 — size and turnover limits** — position size, turnover, trade size caps.

**Level 3 — days to liquidate** (only where reliable volume data exists)
```
Days to Liquidate = Position Value / (Participation Rate × Average Daily Value Traded)
```
Default participation rate: 20% `[DEMO-CONFIG]`.

> **Honesty rule (master spec §16):** this is an *estimate*, not a guarantee of execution. If reliable volume data is unavailable for an asset, `Asset.adv_paise` is `None` and the control is **disabled for that asset** — CCE falls back to Levels 1–2 rather than fabricating precision. Show "—", not a made-up number.

---

## 11. Optimization

### 11.1 Default — constrained maximum Sharpe

```
maximise    (wᵀμ − R_f) / √(wᵀΣw)

subject to  Σ w_i = 1
            w_min,i ≤ w_i ≤ w_max,i
            Σ_{i ∈ s} w_i ≤ sector_max_s      ∀ sectors s
            Σ_{i : liquid} w_i ≥ min_liquid_share
            Σ_i |w_i − w_current,i| / 2 ≤ max_turnover
            w ≥ 0                              (long-only)
```

**The numerical problem:** the Sharpe ratio is not concave in `w`, so this is not directly a convex program.

**Two stable resolutions — pick one and document it:**

*(a) Schur / homogenisation transform.* Substitute `y = w/κ`, `κ > 0`, and solve

```
minimise    yᵀΣy
subject to  (μ − R_f·1)ᵀ y = 1
            Σ y_i = κ,  κ > 0
            constraints scaled by κ
then        w = y / κ
```
Convex and exact — but every constraint must be scaled by `κ`, and forgetting one produces a subtly wrong answer.

*(b) Efficient-frontier scan.* Solve a sequence of constrained minimum-variance problems at target returns spanning the feasible range, compute the Sharpe of each, and select the maximum. Each sub-problem is a clean QP, all original constraints apply unchanged, and the frontier is a useful UI artefact in its own right.

> **Recommendation:** implement **(b)** first. It is robust, easy to verify, hard to get subtly wrong, and yields the efficient frontier as a by-product. Move to (a) only if the scan is too slow — which at 8–12 assets it will not be.

### 11.2 Transaction costs and turnover in the objective

```
Cost = Σ_i c_i · |w_new,i − w_current,i| · PortfolioValue

Objective = risk-adjusted return
          − transaction-cost penalty
          − turnover penalty
```

`|·|` is convex, so this stays solvable in CVXPY (`cp.abs`, `cp.norm1`).

**Turnover** is both a constraint and a displayed metric:
```
Turnover = Σ_i |w_new,i − w_current,i| / 2
```
The `/2` makes it "share of the portfolio traded" — a 100% turnover means every rupee moved once. State the convention wherever it is shown; the un-halved version is also common and the two differ by a factor of two, which is not a small confusion in a ₹100 Cr portfolio.

Default cap: 25% `[DEMO-CONFIG]`. Without it, an optimizer will happily replace most of the portfolio to chase a marginal expected-return difference that is well inside estimation error.

### 11.3 Minimum volatility

```
minimise wᵀΣw   subject to the same policy constraints
```
No expected-return input, so it sidesteps the least reliable estimate in the system. Natural basis for **Minimum-Risk Recovery**.

### 11.4 Target return

```
minimise wᵀΣw   subject to  wᵀμ ≥ target_return  + policy constraints
```
If infeasible, report `INFEASIBLE` and say which constraint conflicts with the target. Never quietly relax a constraint to produce an answer.

### 11.5 CVaR minimisation

Rockafellar–Uryasev linearisation over `T` historical scenarios:

```
minimise    ζ + (1/((1−α)T)) · Σ_t u_t

subject to  u_t ≥ −(r_tᵀ w) − ζ
            u_t ≥ 0
            + policy constraints
```
Linear program. Optimises the tail directly rather than through a variance proxy — the natural basis for a defensive candidate.

### 11.6 Hierarchical Risk Parity (HRP)

```
1. Correlation → distance:  d_ij = √(0.5 · (1 − ρ_ij))
2. Hierarchical clustering on d
3. Quasi-diagonalisation: reorder by the dendrogram
4. Recursive bisection: split each cluster, allocate inversely to cluster variance
```

Requires **no expected-return estimate and no matrix inversion**, which is exactly why it is worth having: it is robust where MVO is fragile. Comparing HRP against constrained MVO in the UI makes the fragility visible.

### 11.7 Black-Litterman

```
Equilibrium returns:  Π = δ · Σ · w_market
Views:                P (picking matrix), Q (view returns), Ω (view uncertainty)

Posterior:
μ_BL = [(τΣ)⁻¹ + PᵀΩ⁻¹P]⁻¹ · [(τΣ)⁻¹Π + PᵀΩ⁻¹Q]
```

| Parameter | Default | Meaning |
|---|---|---|
| `δ` | 2.5 | Risk-aversion |
| `τ` | 0.05 | Uncertainty in the equilibrium prior |
| `Ω` | `diag(P τΣ Pᵀ)` scaled by confidence | View uncertainty |

User-facing view entry:
```
View:       IT will outperform broad equity by 2%
Confidence: 60%
```
→ one row of `P` (+1 on IT, −1 on broad equity), `Q = 0.02`, `Ω` scaled by confidence.

`μ_BL` then feeds the **constrained** optimizer. The views change expected returns; they never bypass a control. The UI shows how a view shifted the allocation — which is the interesting part.

---

## 12. Drawdown

```
Running peak:      M_t = max(V_0..V_t)
Current drawdown:  DD_t = (M_t − V_t) / M_t
Maximum drawdown:  MDD = max(DD_t)
Rolling drawdown:  MDD over a trailing window (default 252 days)
```

Primarily a **monitoring** metric. Severe configured drawdown conditions may contribute to AMBER/RED, but the trigger is configurable and not hard-coded as a universal financial rule (master spec §19).

---

## 13. Stress testing

A scenario is a vector of instantaneous shocks by sector or asset:

```
Portfolio loss = Σ_i w_i · shock_i
Asset contribution to loss = w_i · shock_i
```

Post-shock, CCE recomputes: portfolio value, weights (they drift, since assets move differently), risk metrics under the shocked state, and which policies now breach.

**Decision rule (master spec §31.3):** a candidate that passes ordinary controls but breaches the configured severe stress-loss limit is **still rejected**.

The justification is not conservatism for its own sake: historical VaR and CVaR are estimated from a period that may contain no comparable correlated shock, so they systematically understate exactly the event stress testing is designed to probe. Stress is an independent gate.

---

## 14. Backtesting

### 14.1 Walk-forward loop

At each rebalance date `t`:

```
window = returns[:t]          # STRICTLY before t — this is the whole game
μ, Σ    = estimate(window)
w       = optimize(μ, Σ, constraints, w_prev)
result  = validate(w) + stress(w)
w_applied = w if result.passed else w_prev      # controlled strategy
realise over [t, t+1)
```

### 14.2 Look-ahead prevention `[INV-7]`

The one bug that would invalidate every backtest number: using data from `t` or later to make the decision at `t`.

Guards:
- All slicing is `returns.loc[:t_prev]` with an exclusive upper bound. Never `iloc` arithmetic — off-by-one there is invisible and fatal.
- The rebalance date's own return belongs to the *outcome* period, never the estimation window.
- Test: shift all future returns by an arbitrary constant and assert every decision at `t` is bit-identical. If a decision changes, there is leakage.

### 14.3 Strategies compared

| Strategy | Definition |
|---|---|
| **Buy-and-hold** | Initial weights, no rebalancing. Drift baseline. |
| **Uncontrolled optimizer** | Optimize and adopt every recommendation, no control layer. |
| **CCE-controlled** | Optimize → validate → stress → adopt only if it passes; else hold the last safe allocation. |

### 14.4 Metrics

Cumulative return · annualised return · volatility · Sharpe · max drawdown · VaR · CVaR · average turnover · total transaction costs · **policy-breach count** · **circuit-breaker activations**.

> The last two matter as much as the first. The question CCE answers is not *"did it make more money?"* but *"did it improve the return/risk balance while reducing policy breaches and drawdowns?"* If the controlled strategy earns slightly less with materially fewer breaches and a shallower maximum drawdown, that is a **successful** result — and saying so plainly is more credible than claiming outperformance on a single three-year sample.

---

## 15. Numerical hygiene checklist

Verify before trusting any output:

- [ ] `Σ` symmetric and PSD (after documented repair)
- [ ] `Σ_i w_i = 1` within `1e-6`
- [ ] `w ≥ 0` when long-only
- [ ] `Σ_i RC_i = σ_p` within `1e-8` (the free correctness check)
- [ ] `Σ_i PCR_i = 1` within `1e-8`
- [ ] `CVaR ≥ VaR` always — if not, the tail slice is wrong
- [ ] Annualisation applied exactly once (a `√252` applied twice is a 15.9× volatility error)
- [ ] No `NaN` anywhere in returns, weights or metrics
- [ ] Solver status is `OPTIMAL` before any weight leaves the optimizer
- [ ] Seeded RNG for every stochastic routine
- [ ] Boundary values classify to the less severe band (`v == green_max` is GREEN)

---

## 16. Method selection rationale

| Chosen | Over | Because |
|---|---|---|
| EWMA volatility | GARCH | One interpretable parameter, no fitting, no convergence failures mid-demo. GARCH is explicitly out of scope. |
| Historical VaR | Parametric-only | No normality assumption in exactly the tail that matters |
| CVaR as the hard limit | VaR | VaR says where the tail starts; CVaR says how bad it gets. Capital is destroyed by severity, not by threshold location. |
| Risk contribution | Weight limits alone | Weight caps are gameable; risk caps are not |
| Frontier scan for Max Sharpe | Direct non-convex solve | Robust, verifiable, yields the frontier free |
| Rockafellar–Uryasev CVaR LP | Heuristic tail optimisation | Exact, convex, standard |
| HRP alongside MVO | MVO alone | Shows robustness where expected-return estimates are unreliable |
| SciPy/CVXPY | Custom solvers | Well-tested; a hackathon is the wrong place to debug an optimiser |

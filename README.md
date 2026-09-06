# CCE — Capital Control Engine

> **Optimal ≠ Safe.** The highest-return mathematical allocation is not automatically the allocation an institution should accept.

An institutional capital-allocation prototype where the optimizer **proposes**, an independent control engine **validates**, stress tests **challenge**, a human **approves**, and every decision is **recorded**.

Built for the INIT'26 FinTech hackathon — *Asset & Capital Management / Optimization Controls*.

---

## The problem

Most portfolio tools solve one of two failure modes and ignore the other:

| Failure mode | Cause |
|---|---|
| **Stale allocation** | Static rules don't adapt when market conditions change |
| **Unsafe allocation** | A pure optimizer produces a statistically attractive portfolio that violates institutional policy |

CCE addresses both. It continuously re-evaluates the portfolio *and* refuses to adopt an optimizer output that breaches policy.

## The loop

```
Market Data → Portfolio State → Risk Engine → Detect → Optimize
    → Validate → Stress Test → Explain → Human Approval
    → Simulated Rebalance → Audit → (repeat)
```

The optimizer is deliberately **not** the final authority. It generates candidate allocations; a separate control layer independently re-derives every metric and decides whether the candidate is acceptable.

---

## What makes it different

**The control engine cannot import the optimizer.** This is enforced structurally by a test, not by convention:

```python
def test_controls_never_import_the_optimizer():   # INV-2, structural
```

The validator recomputes every metric from raw returns rather than reading the optimizer's self-reported numbers. If the optimizer has a bug or the solver is numerically optimistic, that becomes a **rejection**, not an approval — failing in the safe direction.

**Risk contribution, not just weight.** Allocation answers *"how much capital is here?"* Risk contribution answers *"how much of our risk is caused by this?"* These diverge, and the divergence is where institutional risk hides. Measured on real NSE data:

| Asset | Weight | Risk contribution |
|---|---:|---:|
| NIFTY50 | 28% | **35.5%** |
| BANKNIFTY | 24% | **33.6%** |
| GOLD | 10% | 7.0% |
| GSEC | 12% | **1.1%** |
| CASH | 6% | 0.0% |

Government securities are 12% of the capital and 1.1% of the risk; gold is 10%
and 7.0%. Both are doing what a diversifier should. Equity is not.

The gap gets wider the moment an optimizer is involved. Asked for the best
unconstrained risk-adjusted portfolio on this data, it proposes gold at **31% of
capital — and 62% of portfolio risk**, against a 40% hard limit. It is refused.
A weight-only control framework would have seen a 31% position and waved it
through.

**Safe vs Optimal, shown side by side.** The rejected optimal portfolio isn't hidden — it's the argument, displayed with the specific limits it broke (control, observed value, threshold), never a generic "constraints violated".

**Twelve safety invariants**, each with an ID and a test. Among them: the LLM cannot modify any financial decision; missing market data is never interpreted as zero risk; on optimizer failure the last approved safe allocation is preserved rather than replaced; backtests cannot see the future.

---

## Status

**All 15 phases complete.** 571 tests passing, none skipped. `ruff` and `mypy`
clean across 93 files. Six failure drills pass.

| Phase | Component | Status |
|---|---|---|
| 0 | Contracts, config, architecture guards | ✅ |
| 1 | Data layer, validation, committed cache | ✅ |
| 2 | Portfolio state, turnover, transaction costs | ✅ |
| 3 | Risk engine — volatility, EWMA, VaR, CVaR, drawdown, risk contribution | ✅ |
| 4 | Optimizer — constrained max-Sharpe, efficient frontier | ✅ |
| 5–7 | Control engine, circuit breaker, stress testing | ✅ |
| 8–9 | Audit store, services, approval workflow | ✅ |
| 10 | Streamlit dashboard — 8 pages | ✅ |
| 11 | Alternative optimizers — min-vol, target-return, CVaR LP, HRP, Black-Litterman | ✅ |
| 12 | Walk-forward backtest with look-ahead prevention | ✅ |
| 13–15 | LLM narration, "What Changed?", demo drill | ✅ |

All twelve safety invariants have a real test. None is skipped, and none passes
vacuously — the two that once did (INV-7 needed the backtest module, INV-12
needed the UI) were left **failing on purpose** until the component existed,
because a green tick against something that was never built is worse than a
visible gap.

### Does the control layer actually help?

Walk-forward, Sep 2024 – Aug 2026, monthly rebalance, identical data:

| Strategy | Return | Volatility | Max drawdown | Policy breaches |
|---|---:|---:|---:|---:|
| Buy and hold | 12.8% | 8.7% | 8.8% | 0 |
| Uncontrolled optimizer | **33.5%** | 11.3% | 6.5% | **37** |
| CCE-controlled | 23.5% | **7.3%** | **4.8%** | **0** |

The controlled strategy earned **ten points less**. In exchange: a third less
volatility, a shallower drawdown, and zero policy breaches against thirty-seven.
That is not outperformance — it is a different mandate, and stating it plainly
is more credible than claiming otherwise on a single three-year sample.

Every rebalance uses only data strictly *before* that date. The suite includes a
test that injects a one-day leak and fails if it goes undetected.

---

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/Adityarane012/CCE.git
cd CCE

python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Unix

.venv/Scripts/python.exe -m pytest -q            # 571 passed
.venv/Scripts/streamlit.exe run app.py           # dashboard on :8501
```

**It runs with no network and no API key.** A market-data snapshot is committed to `data/cache/`, which is what makes the demo reproducible and offline-capable.

### Verify it before you trust it

```bash
.venv/Scripts/python.exe scripts/demo_drill.py     # 6 failure drills
.venv/Scripts/python.exe scripts/demo_figures.py   # regenerate every quoted figure
```

`demo_drill.py` deliberately breaks the system six ways — no network, no API
key, deleted database, a −40% shock, an attempt to approve a rejected
allocation, and an attempt to weaken a threshold without a reason — and
asserts it degrades correctly each time rather than pretending to be healthy.

`demo_figures.py` re-derives every number quoted in the demo script from the
committed data. No figure is spoken aloud until that command has produced it.

### Try the risk engine

```python
from cce.config import load_universe, load_policy
from cce.data import load_market_data
from cce.risk import RiskInputs, compute_risk_snapshot

universe, policy = load_universe(), load_policy()
market, _ = load_market_data(universe)

# the committed demo book — ₹100 Cr
weights = {"NIFTY50": 0.28, "BANKNIFTY": 0.24, "IT": 0.12, "GSEC": 0.12,
           "GOLD": 0.10, "PHARMA": 0.08, "CASH": 0.06}

snapshot, cov = compute_risk_snapshot(RiskInputs(
    weights=weights, universe=universe, market_data=market,
    risk_free_rate=policy.risk_free_rate,
    total_value_paise=100_000_000_000,   # ₹100 Cr
))

print(f"EWMA volatility  {snapshot.ewma_volatility:.2%}")
print(f"95% CVaR         {snapshot.cvar_95:.2%}")
print(f"Banking risk     {snapshot.sector_risk_contribution['BANKING']:.1%}")
```

### Refresh the market data

```bash
.venv/Scripts/python.exe scripts/build_cache.py --years 3
```

Needs a network. Prints a `data_hash` — record it when you commit the snapshot.

---

## Architecture

```
ui/            → may import ONLY cce.services and cce.contracts
cce/services/  → orchestration; the only layer the UI touches
cce/risk/      → pure functions; no I/O
cce/optimizer/ → proposes only; never writes state
cce/controls/  → INDEPENDENT authority; does NOT import the optimizer
cce/stress/    → independent gate
cce/contracts/ → typed seams; imports nothing from cce
cce/data/      → provider abstraction; cached is the default
cce/audit/     → append-only SQLite
```

Layer rules are enforced by `tests/test_architecture.py`, which parses imports across the tree. A violation fails the build rather than being caught in review.

**The Streamlit UI contains no financial logic.** It calls a service layer; the service layer calls the engines. `tests/test_invariants.py` asserts that `ui/` imports nothing but `cce.services` and `cce.contracts` (INV-12) — that guard caught a real violation the first time the backtest page was written.

---

## Tech stack

Python 3.11 · NumPy · pandas · SciPy · CVXPY · [jugaad-data](https://github.com/jugaad-py/jugaad-data) (NSE/RBI market data) · SQLite · pytest · Streamlit + Plotly

Dependencies were installed per build phase rather than all at once, so a failed install never blocked an earlier phase. All are now pinned in `requirements.txt`; `anthropic` is optional and the system runs fully without an API key.

---

## Testing

```bash
.venv/Scripts/python.exe -m pytest -q                        # everything
.venv/Scripts/python.exe -m pytest tests/test_architecture.py -v   # layer guards
```

Every financial function has a test with a **hand-computed** expected value — comparing an implementation against itself proves nothing. The suite also asserts identities that must hold by construction:

- `Σ RCᵢ = σₚ` to 1e-12 — a free correctness check on the whole covariance and weight pipeline
- `CVaR ≥ VaR` across 20 seeds
- annualisation applied exactly once (a `√252` applied twice is a 15.9× error that still looks like a number)

A cross-check worth noting: `√(w'Σw)` from the covariance matrix and the standard deviation of the portfolio return series both give **10.35%** on the committed data — two entirely independent computational paths agreeing.

---

## What this is not

- Not a retail stock-picking app
- Not a trading bot or autonomous AI trader
- Not connected to any brokerage — approval triggers a **simulated** rebalance
- Not a guaranteed-return or regulatory-compliance product

**The risk thresholds are configurable demonstration values**, not Basel, SEBI or RBI limits, and not calibrated to any institution's risk appetite. They are chosen so a demo portfolio moves between GREEN, AMBER and RED under plausible conditions. What has been built is the configurable control *framework* — that distinction is the point.

Expected returns are labelled **"Model Estimate"** everywhere they appear. They are the least reliable numbers in the system.

---

## Documentation

CCE is specified by an 18-document set. Publishing all of it would make this repo harder to read, not easier, so the five that carry the argument are here and the rest stay local:

| Document | What it answers |
|---|---|
| [`01-PRODUCT-SPECIFICATION.md`](docs/01-PRODUCT-SPECIFICATION.md) | What CCE is, who it's for, what it deliberately is not |
| [`02-ARCHITECTURE.md`](docs/02-ARCHITECTURE.md) | The layers, the dependency rules, and how optimizer/control independence is enforced |
| [`07-RISK-POLICY.md`](docs/07-RISK-POLICY.md) | GREEN/AMBER/RED bands, the 20 control codes, circuit-breaker triggers |
| [`08-FINANCIAL-METHODS.md`](docs/08-FINANCIAL-METHODS.md) | Every formula, convention and numerical-stability rule |
| [`10-RULES.md`](docs/10-RULES.md) | The twelve safety invariants, each with an ID and a test |
| [`CLAUDE.md`](docs/CLAUDE.md) | The project constitution — the constraints this codebase operates under |

Kept local: the TRD (113 numbered requirements), workflow, data contracts, backend schema, UI spec, testing strategy, security, edge cases, demo script, glossary and the phase-by-phase implementation plan.

**Start with [`10-RULES.md`](docs/10-RULES.md) §2** if you only read one thing — the twelve invariants are the product's actual claims, and each one has a test.

---

## Licence

Hackathon prototype. Not licensed for production use or real capital allocation.

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
| NIFTY50 | 26% | **35.2%** |
| BANKNIFTY | 20% | 29.6% |
| GSEC | 12% | **1.2%** |
| CASH | 6% | 0.0% |

A position can sit comfortably inside its 30% weight cap while causing 43% of portfolio risk. A weight-only control framework cannot see that.

**Safe vs Optimal, shown side by side.** The rejected optimal portfolio isn't hidden — it's the argument, displayed with the specific limits it broke (control, observed value, threshold), never a generic "constraints violated".

**Twelve safety invariants**, each with an ID and a test. Among them: the LLM cannot modify any financial decision; missing market data is never interpreted as zero risk; on optimizer failure the last approved safe allocation is preserved rather than replaced; backtests cannot see the future.

---

## Status

**Phases 0–3 of 15 complete.** 232 tests passing.

| Phase | Component | Status |
|---|---|---|
| 0 | Contracts, config, architecture guards | ✅ |
| 1 | Data layer, validation, committed cache | ✅ |
| 2 | Portfolio state, turnover, transaction costs | ✅ |
| 3 | Risk engine — volatility, EWMA, VaR, CVaR, drawdown, risk contribution | ✅ |
| 4 | Optimizer (constrained max-Sharpe) | next |
| 5–7 | Control engine, circuit breaker, stress testing | planned |
| 8–9 | Audit store, services, approval workflow | planned |
| 10 | Streamlit dashboard | planned |
| 11–15 | Alternative optimizers, backtest, LLM narration, demo | planned |

This is an honest status, not a roadmap aspiration. The dashboard does not exist yet.

---

## Quick start

Requires Python 3.11+.

```bash
git clone https://github.com/Adityarane012/CCE.git
cd CCE

python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt   # Windows
.venv/bin/python -m pip install -r requirements.txt           # Unix

.venv/Scripts/python.exe -m pytest -q
```

**It runs with no network and no API key.** A market-data snapshot is committed to `data/cache/`, which is what makes the demo reproducible and offline-capable.

### Try the risk engine

```python
from cce.config import load_universe, load_policy
from cce.data import load_market_data
from cce.risk import RiskInputs, compute_risk_snapshot

universe, policy = load_universe(), load_policy()
market, _ = load_market_data(universe)

weights = {"NIFTY50": 0.26, "BANKNIFTY": 0.20, "IT": 0.10, "PHARMA": 0.08,
           "FMCG": 0.06, "GOLD": 0.10, "GSEC": 0.12, "CORPBOND": 0.02,
           "CASH": 0.06}

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

**The Streamlit UI will contain no financial logic.** It calls a service layer; the service layer calls the engines.

---

## Tech stack

Python 3.11 · NumPy · pandas · SciPy · CVXPY · [jugaad-data](https://github.com/jugaad-py/jugaad-data) (NSE/RBI market data) · SQLite · pytest · Streamlit + Plotly (planned)

Dependencies are installed per build phase rather than all at once, so a failed install never blocks an earlier phase. See `requirements.txt`.

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

A cross-check worth noting: `√(w'Σw)` from the covariance matrix and the standard deviation of the portfolio return series both give **9.71%** on the committed data — two entirely independent computational paths agreeing.

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

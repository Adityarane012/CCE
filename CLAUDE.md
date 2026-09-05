# CCE — Capital Control Engine

The full project constitution lives in `docs/CLAUDE.md` and is imported below.

@docs/CLAUDE.md

---

## Quick orientation

**What this is:** an institutional capital-allocation and risk-control prototype for the INIT'26 FinTech hackathon. ₹100 Cr demo portfolio, Indian market data, Streamlit dashboard.

**The product principle:** Optimal ≠ Safe. The optimizer proposes; an independent control engine disposes.

**Before writing any code, read:**
- `docs/README.md` — the documentation index and reading order
- `docs/10-RULES.md` §2 — the twelve safety invariants
- `docs/02-ARCHITECTURE.md` §2 — the layer-dependency table

**The three rules:**
1. `cce/controls/` MUST NOT import `cce/optimizer/`, and re-derives every metric itself.
2. On failure, do less — preserve the Last Approved Safe Allocation, never invent one.
3. The LLM writes prose, never decisions.

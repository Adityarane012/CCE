# 14 — Demo Script

**Audience:** Hackathon judges
**Duration target:** 7–8 minutes presentation + Q&A
**Derived from:** master spec §39, §52, §53, §61.

> **The one story:** a market condition changes → risk changes → CCE detects it → the optimizer proposes an allocation → the independent control engine challenges it → the unsafe allocation is rejected → a safer alternative is produced → stress tests validate it → a human approves it → the system records exactly what happened.
>
> Every second of the demo serves that arc. Anything that does not, gets cut.

---

## ✅ STATUS: every number here is measured, and regenerable

**Every figure below has been reproduced by a real run on the committed
data.** Regenerate them all with:

```bash
./.venv/Scripts/python.exe scripts/demo_figures.py
```

Per `10-RULES.md` §5.3, no number may be spoken aloud or put on a slide until
that command has produced it. If the script and the output disagree, **the
output wins and this script is corrected** — never the other way round. The
figures move whenever the cached panel is refreshed or a threshold changes, so
re-run it the morning of the demo.

### The narrative was rewritten, because the data would not support the old one

The original script's central image — an unconstrained optimum concentrating
**43% in banking** — is not what this data produces. Historical means over
Sep 2023 – Aug 2026 make PHARMA, GOLD and CORPBOND the highest-Sharpe assets.
The old script also quoted a volatility of 11.8%, a CVaR of 6.2% and a Sharpe
of 1.31; none of those are this portfolio's numbers.

Rather than adjust the numbers to fit the story, the story now follows the
numbers. **The banking narrative survives** — but as the consequence of a
stated human view rather than an unprompted result, which is a better demo
anyway: the trigger is something a judge watches a person do.

The two moments, both measured:

| | Optimizer proposes | Control engine says |
|---|---|---|
| **No view** | PHARMA 32% · GOLD 31% · CORPBOND 26% | **RED** — gold risk contribution **62.1%** vs a 40% hard limit; turnover 70.7% vs 25%; cash 0.9% vs a 3% floor |
| **"Banking will outperform by 4%"** | BANKING 30% · BROAD_EQUITY 30% · GOLD 20% | **RED** — worst stress loss **18.87%** vs the 18% limit; banking risk contribution **34.7%** vs 30% |

Both are rejected. Neither rejection was arranged.

### One thing to be honest about if asked

The demo portfolio is **GREEN at rest** — it is a well-diversified book and
no control is breaching. The drama comes from what the *optimizer* proposes,
not from the starting position. Do not imply the book is in trouble; the
product's claim is about what happens to a proposal, and that is exactly what
gets shown.

---

## 1. Stage 1 — Healthy portfolio (0:00–0:45)

**Screen:** Executive Overview

**Say:**
> "This is CCE — Capital Control Engine. A ₹100 crore institutional portfolio across Indian equity, banking, IT, pharma, gold and government securities.
>
> Right now every risk control is GREEN. Annualised volatility 10.4%, VaR 0.9%, CVaR 1.5%. Nothing is breaching."

*Measured. Allocation: broad equity 28% · banking 24% · IT 12% · G-sec 12% · gold 10% · pharma 8% · cash 6%.*

**One number worth pointing at before you move on:**
> "Banking is 24% of the money — and 34% of the risk. Broad equity is 28% of the money and 35% of the risk. Those are different questions, and most tools only answer the first one."

*Also measured. This is the allocation-vs-risk-contribution point, made without needing anything to go wrong yet.*

**Show:** the risk-state banner, the metric block, the empty breach list.

**Land this line:**
> "The point of this system isn't the optimizer. It's what sits *around* the optimizer. Let me show you why that matters."

*Do not tour the pages. Do not explain the architecture yet. Get to the shock.*

---

## 2. Stage 2 — Introduce the banking shock (0:45–1:30)

**Screen:** Stress Lab

**Do:** apply the prepared custom scenario.

```
Banking:       -18%
Broad equity:  -12%
IT:             -8%
Gold:           +5%
```

**Say:**
> "Suppose the banking sector drops 18% and the broad market 12% — a bad week, not an apocalypse. This book loses 8.1%, about ₹8 crore. It survives; the limit is 18%."

*Measured: 8.1% (₹8.1 Cr), status PASSED. Do not oversell it — the honest point is that the book is diversified enough to take this, and that the system says so with a number rather than a colour.*

**Then show the one that does not pass:**
> "Here's the combined severe scenario — everything at once. 18.3% loss, against an 18% limit. That one FAILS, and it stays visible even though every normal metric is green."

*Measured: Combined severe 18.3% (₹18.3 Cr), FAILED. This is INV-10 on screen — a stress failure is not masked by healthy day-to-day metrics.*

---

## 3. Stage 3 — Allocation is not risk (1:30–2:15)

**Screen:** Portfolio & Exposure

**Say:**
> "This is the chart I'd want you to remember.
>
> The blue bars are where the money is. The red bars are where the *risk* is. They are not the same shape.
>
> Banking is 24% of the allocation and 34% of the risk contribution. Broad equity, 28% and 35%. Gold is 10% of the book and 7% of the risk — it is doing what a diversifier is supposed to do.
>
> A tool that only watches allocation percentages cannot see this. Every control in CCE is evaluated on risk contribution as well as weight, which is why a portfolio can be inside every allocation cap and still be refused."

**Show:** the weight-vs-risk-contribution bar chart, third component down on **Portfolio & Exposure** (`docs/09-UI-SPEC.md` §5, component 3). This is the strongest single visual in the product — let it sit on screen for a beat.

*It is NOT on the Risk Control Center. An earlier draft of this script sent the presenter there, where they would have found a metrics table and no chart. The Risk Control Center is where the control STATES live; Portfolio & Exposure is where the exposure visuals live.*

*All measured. The earlier version of this script claimed a before/after volatility jump (11.8% → 15.6%) driven by the shock. That is not something this system does: the stress engine measures a scenario's loss, it does not re-estimate live risk from shocked returns. The claim was removed rather than staged — see `13-EDGE-CASES.md`. If a judge asks "what would move these numbers?", the honest answer is a new trading day, or the EWMA estimator reacting to a regime change, and you can show EWMA against historical volatility side by side.*

---

## 4. Stage 4 — Circuit breaker (2:15 — whenever it fires)

**Screen:** Overview, breaker banner

**Say:**
> "When a hard control goes RED, the circuit breaker fires.
>
> That means: no new allocation gets adopted, the Last Approved Safe Allocation is preserved, and a human has to decide. The system did not quietly rebalance ₹100 crore on its own.
>
> Note what it does *not* do. It doesn't relax the limit to find an answer, and it doesn't invent a fallback allocation. On failure it does less — never something different."

---

## 5. Stage 5 — Safe vs Optimal (2:15–4:00) — **the centrepiece**

**Screen:** Optimizer, three-column comparison

**Say:**
> "Now the interesting part. I asked the optimizer for the best risk-adjusted portfolio it can find, with no constraints at all.
>
> Here it is: pharma 32%, gold 31%, corporate debt 26%. On any standard optimizer, this is the answer you'd get.
>
> Our control engine rejected it. RED."

*(pause)*

> "And look at *why*, because the reasons are specific numbers, not 'constraints violated':
>
> Gold is 31% of the money but **62% of the portfolio risk** — against a 40% hard limit. Turnover to get there is **71%**, against 25%. Cash would fall to **0.9%**, under a 3% floor. And commodity exposure hits 30.5% against a 25% cap.
>
> Critically: the module that rejected it is not the module that produced it. The control engine doesn't import the optimizer, and doesn't trust a single number the optimizer reported about its own output. It recalculates everything from raw returns.
>
> That's deliberate. If the optimizer has a bug, or the solver is numerically optimistic, that bug becomes a **rejection**, not an approval. We fail in the safe direction.
>
> Next to it is the safe allocation — gold 25%, Nifty 20%, banking 19%, pharma 18%. It passes every hard control. That gap is the whole product."

**Show:** the rejection reason list with observed values and thresholds.

*All measured. Note the safe candidate is AMBER, not GREEN — gold risk contribution 36.9% against a 35% amber band, turnover 24.95%, worst stress loss 12.89%. It is approvable; it is not spotless, and the UI says so. Do not call it "green".*

---

## 6. Stage 6 — A human view, and what it costs (4:00–4:45)

**Screen:** Optimizer, Black-Litterman view panel

**Do:** enter the view — **banking outperforms by 4%, confidence 60%**.

**Say:**
> "Here's the case I actually want to show you. A portfolio manager has a view: banking will outperform by 4%. That's an ordinary, defensible opinion, and the system lets them state it — Black-Litterman blends it with the market-implied equilibrium.
>
> The optimizer takes the view seriously. Banking goes to 30%, broad equity to 30%.
>
> And the control engine refuses it. RED. Worst stress-scenario loss **18.87%** against an 18% limit, and banking risk contribution **34.7%** against 30%.
>
> The view changed what the optimizer *proposed*. It did not change what the controls *allow*. A user who believes banking will outperform can move the proposal — they cannot move the sector cap. That separation is the entire architecture in one interaction."

*Measured. This is the strongest 45 seconds in the demo: a human acts, the maths responds, and the safety layer holds. It also demonstrates Black-Litterman without a detour to explain it.*

---

## 6b. Stage 6b — Recovery options (4:45–5:15)

**Screen:** Optimizer, recovery panel

**Say:**
> "A circuit breaker that just says 'stop' isn't much use to a risk manager at 10am.
>
> So when it trips, CCE generates three recovery allocations — maximum Sharpe within the controls, minimum risk, and a defensive high-liquidity option. Each is independently validated and stress-tested before it's offered.
>
> One of them is approvable. The other two are not, and they're still on screen with their reasons: minimum-risk pushes Nifty to **52% of portfolio risk** against a 40% limit, and the defensive option hits 40.8%. Both refused.
>
> We don't hide the ones that didn't work. That the system tried and refused is the evidence the control layer is real."

*Measured. Worth knowing: until recently all three came back unapprovable, because the recovery path validated them without their stress results — so `STRESS_LOSS_MAX` was never evaluated and everything failed as NOT_VALIDATED. Fixed in `d0df031`; `tests/test_services.py::TestRecoveryCandidatesAreApprovable` now guards it. If you ever see all three refused, that regression is the first thing to check.*

---

## 7. Stage 7 — Human intervention (5:15–5:45)

**Screen:** approval controls

**Say:**
> "The human decides. Approve, reject, or keep the current allocation.
>
> And note there's no one-click approval available on a RED-state allocation. If a risk manager wants to override a hard control, that's a separate flow: an explicit confirmation, a written reason, and a list of exactly which controls are being overridden. All of it recorded."

**Do:** approve the **Maximum-Sharpe Recovery** — it is the one that passes.

*Do not try to approve minimum-risk: it is RED and the server will refuse, which is a good property to demonstrate deliberately but a bad one to discover mid-sentence.*

**Show:** the `Human Intervention: YES` badge, the state transition, the simulated rebalance.

**Say:**
> "Approval triggers a simulated rebalance. We don't connect to a broker — this is a capital-control prototype, not an execution platform, and we're not going to claim otherwise."

---

## 8. Stage 8 — Decision Replay (5:45–6:30)

**Screen:** Decision Replay

**Say:**
> "Everything that just happened is on a timeline, reconstructed entirely from stored records — nothing recomputed.
>
> Shock detected. Volatility moved. Risk contribution moved. CVaR crossed the limit. Breaker activated. Candidate generated. Candidate rejected, with the numbers. Three recoveries generated and validated. Human approved. Rebalance applied. Audit stored.
>
> Three colours: machine action, control-engine decision, human action. A risk manager or an auditor can reconstruct exactly what the system did, what it refused to do, and where a person stepped in."

---

## 9. Stage 9 — Backtest (6:30–7:15)

**Screen:** Backtesting

**Say:**
> "Finally — does the control layer actually help, or does it just cost return?
>
> Three strategies over the same period: buy-and-hold, an uncontrolled optimizer, and CCE-controlled.
>
> The uncontrolled optimizer earned the most — 33.5% over two years. CCE-controlled earned 23.5%. We gave up ten points of return. I'm not going to dress that up.
>
> Here's what it bought. Volatility 7.3% instead of 11.3%. Maximum drawdown 4.8% instead of 6.5%. And **zero policy breaches against thirty-seven**.
>
> Thirty-seven times, the uncontrolled optimizer proposed something that violated the risk policy — and a system without a control layer would have traded every one of them. That's not outperformance. That's a different mandate.
>
> I'm not going to stand here and claim our approach makes more money. It doesn't, on this sample. It makes a different trade — and for an institution with a mandated risk appetite, that trade is the entire point.
>
> And this is walk-forward with no look-ahead: every rebalance decision uses only data strictly before that date. We test for it explicitly — including a test that injects a one-day leak and fails if we don't catch it."

*All measured (Sep 2024 – Aug 2026, monthly). Buy-and-hold for reference: 12.8% return, 8.7% vol, 8.8% drawdown. Regenerate from the Backtesting page or `scripts/demo_figures.py`.*

*Note the controlled arm holds its previous allocation zero times on this sample — the constrained optimizer's proposals always pass validation, which is what it is for. The control layer's value shows up as 0 breaches against 37, not as refusals. If asked, say exactly that.*

*Being straight about the return gap is more persuasive than claiming outperformance. Judges evaluating financial logic at 35% weight will notice either way.*

---

## 10. Close (7:15–7:45)

> "So: CCE separates optimality from safety.
>
> The optimizer proposes. An independent control engine validates. Stress testing challenges. A human approves. And the system records exactly why every decision happened.
>
> The engine is fully deterministic. There's an optional LLM layer, but it only turns structured facts into readable prose — it cannot touch a weight, a threshold, a risk score, or an approval. The whole thing runs with no API key and no internet connection.
>
> That's the difference between a portfolio optimizer and a capital control engine."

---

## 11. Anticipated questions

**"What stops someone just changing the threshold?"**
> "Nothing stops them — a risk manager should be able to change policy. But it's not silent. Weakening a hard limit shows a warning, requires a written reason, creates a new versioned policy record, and is written to the audit trail. And every decision stores which policy version was in force, so replay shows the rules that applied at the time. If a portfolio goes from red to green because someone moved a limit, the interface says so."
>
> *(Then show it live. This answer is much stronger demonstrated than described.)*

**"Are these real institutional risk limits?"**
> "No, and we're explicit about that everywhere in the UI. They're configurable demonstration values chosen so the portfolio moves between states within a short demo. A real deployment would derive them from the institution's investment policy statement and board-approved risk appetite. What we've built is the configurable control framework — not a hard-coded rulebook."

**"Why EWMA rather than GARCH?"**
> "One interpretable parameter, no fitting, no convergence failures. For detecting a volatility regime change over days, EWMA gets most of the benefit at a fraction of the fragility. GARCH was a deliberate exclusion — not an oversight."

**"Why is CVaR the hard limit rather than VaR?"**
> "VaR tells you where the tail starts. CVaR tells you how bad it is once you're in it. Two portfolios can have identical VaR and very different tail severity — and capital is destroyed by severity, not by where the threshold sits. VaR is displayed for comparison; CVaR is what gates."

**"How do you know the control engine is genuinely independent?"**
> "It's structural, and there's a test for it. `cce/controls/` does not import `cce/optimizer/` — enforced by a static import test. And there's a test that hands the validator an `OptimizationResult` with deliberately falsified metrics and asserts the verdict is unchanged, because the validator recomputes everything from raw returns."

**"Does the LLM make any decisions?"**
> "No, and it structurally can't. The narration function returns a string that goes to the screen. There's no code path from that string back into a weight, a threshold, or an approval. We test it with adversarial responses — including ones that literally instruct the system to approve — and assert every financial field is byte-identical to the LLM-disabled run."

**"What happens if all three recovery options fail validation?"**
> "The system says so and holds the last approved safe allocation. It doesn't offer the least-bad option. A control system that says 'I have no safe answer for you' is behaving correctly — I can show you that state if you'd like."

**"Could this run on live data?"**
> "The data layer is behind a provider interface — there's a live `jugaad-data` provider alongside the cached one, and switching is configuration, not code. We demo on cached snapshots deliberately so the demo is reproducible and doesn't depend on connectivity. Production would add streaming, real auth, and an execution layer — none of which change the control architecture."

---

## 12. If something breaks

| Failure | Response |
|---|---|
| App crashes | Reset script, restart, resume from the last stage. Rehearse this. |
| Optimization hangs | *"That's the solver hitting its time limit — which is itself a model-failure trigger that would trip the breaker."* Then move to the pre-computed state. |
| Numbers look wrong | Do not improvise an explanation. *"Let me come back to that."* Continue the arc. |
| Network needed unexpectedly | Should be impossible — the demo is cached-only. If it happens, that is a bug to note, not to debug on stage. |
| Running long | Cut Stage 9 (backtest) first, then Stage 6b (recovery). **Never cut Stage 5 or Stage 6** — Safe vs Optimal is the product, and the Black-Litterman view is the strongest 45 seconds in the demo. |

---

## 13. Rubric coverage check

| Rubric area | Weight | Where it lands |
|---|---|---|
| Financial & Control Logic | 35% | Stages 2, 3, 4, 5, 6, 9 |
| Technical Architecture | 30% | Stage 5 (independence), Stage 8 (audit), Q&A |
| UX & Clarity | 20% | Stages 1, 3, 5, 8 |
| Innovation | 15% | Stage 5, Stage 6 (a human view meets an unmovable control), Stage 8 |

The heaviest-weighted category is covered by the stages that also carry the narrative. That is not a coincidence — the demo is built that way.

---

## 14. Final checklist

### Before you start
- [ ] `./.venv/Scripts/python.exe scripts/demo_drill.py` — all six failure drills pass
- [ ] `./.venv/Scripts/python.exe scripts/demo_figures.py` — every number in this script still matches
- [ ] `./.venv/Scripts/python.exe -m pytest` — green, nothing skipped

### Data
- [ ] Indian market data loads · cached fallback works · validation works

### Portfolio
- [ ] ₹100 Cr · asset weights · sector exposure · cash/liquidity

### Risk
- [ ] Historical vol · EWMA vol · VaR · CVaR · Sharpe · drawdown · risk contribution

### Optimization
- [ ] Max Sharpe · constraints honoured · transaction costs · turnover · one alternative optimizer

### Controls
- [ ] GREEN/AMBER/RED · hard vs soft · independent validation · circuit breaker · Last Approved Safe Allocation

### Stress
- [ ] Default scenarios · candidate stress validation · custom scenario

### Human control
- [ ] Approve · Reject · Keep Current · human intervention visibly recorded

### Audit
- [ ] Decision log · Decision Replay · machine vs control vs human distinction

### Backtest
- [ ] Controlled vs uncontrolled · return · risk · drawdown · breaches · turnover · no look-ahead

### AI
- [ ] Optional · explanation-only · deterministic fallback verified

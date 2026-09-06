# 06 — Data Contracts

**Scope:** The typed objects modules pass between each other, and the service-layer signatures the UI is allowed to call.
**Location:** `cce/contracts/` — pure data, no I/O, no business logic, no dependencies on L3+.
**Derived from:** master spec §44, §45.

> **Rule (`NFR-021`):** modules communicate through these objects, never through bare dicts. A dict crossing a module boundary is a bug — it makes the seam untypeable and lets fields drift silently.

---

## 1. Conventions

| Concern | Convention |
|---|---|
| Rates, weights, ratios | `float`, decimal form. `0.1568` means 15.68%. Never store pre-formatted percentages. |
| Money | `int` paise (INR × 100) in persistence; `float` rupees permitted inside computation, converted at the persistence edge. |
| Losses | Positive numbers. `cvar_95 = 0.087` means an expected tail loss of 8.7%. |
| Volatility / return | **Annualised** unless the field name says otherwise. |
| VaR / CVaR | **1-day at 95%** unless the field name says otherwise. |
| Timestamps | timezone-aware `datetime` in UTC. |
| Dates | `datetime.date` for trading dates. |
| Weight vectors | `dict[str, float]` keyed by `asset_id` at boundaries; `np.ndarray` ordered by `Universe.asset_ids` inside numerical code. Convert exactly once, at the edge. |
| Mutability | All contracts are `@dataclass(frozen=True)`. State changes create new objects. |
| Optionality | `None` means *not computed*. It never means *zero*. `[INV-5]` |

```python
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
import numpy as np
import pandas as pd
```

---

## 2. Enumerations — `cce/contracts/enums.py`

```python
class RiskState(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED   = "RED"

    @property
    def severity(self) -> int:
        return {"GREEN": 0, "AMBER": 1, "RED": 2}[self.value]


class ControlStatus(str, Enum):
    PASSED        = "PASSED"
    FAILED        = "FAILED"
    NOT_VALIDATED = "NOT_VALIDATED"   # validation could not complete


class StressStatus(str, Enum):
    PASSED  = "PASSED"
    FAILED  = "FAILED"
    NOT_RUN = "NOT_RUN"
    ERROR   = "ERROR"


class SolverStatus(str, Enum):
    OPTIMAL           = "OPTIMAL"
    OPTIMAL_INACCURATE = "OPTIMAL_INACCURATE"
    INFEASIBLE        = "INFEASIBLE"
    UNBOUNDED         = "UNBOUNDED"
    SOLVER_ERROR      = "SOLVER_ERROR"

    @property
    def usable(self) -> bool:
        """Only OPTIMAL yields weights that may leave the optimizer."""
        return self is SolverStatus.OPTIMAL


class Strategy(str, Enum):
    MAX_SHARPE      = "MAX_SHARPE"
    MIN_VOLATILITY  = "MIN_VOLATILITY"
    TARGET_RETURN   = "TARGET_RETURN"
    CVAR_MIN        = "CVAR_MIN"
    HRP             = "HRP"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"


class ExpectedReturnMethod(str, Enum):
    HISTORICAL      = "HISTORICAL"
    EWMA            = "EWMA"
    BLACK_LITTERMAN = "BLACK_LITTERMAN"


class VaRMethod(str, Enum):
    HISTORICAL  = "HISTORICAL"
    PARAMETRIC  = "PARAMETRIC"
    MONTE_CARLO = "MONTE_CARLO"


class CandidateRole(str, Enum):
    CURRENT              = "CURRENT"
    OPTIMAL_UNCONSTRAINED = "OPTIMAL_UNCONSTRAINED"   # for Safe vs Optimal
    SAFE_CONSTRAINED     = "SAFE_CONSTRAINED"
    RECOVERY_MAX_SHARPE  = "RECOVERY_MAX_SHARPE"
    RECOVERY_MIN_RISK    = "RECOVERY_MIN_RISK"
    RECOVERY_DEFENSIVE   = "RECOVERY_DEFENSIVE"
    ALTERNATIVE          = "ALTERNATIVE"


class HumanAction(str, Enum):
    APPROVE      = "APPROVE"
    REJECT       = "REJECT"
    KEEP_CURRENT = "KEEP_CURRENT"
    OVERRIDE     = "OVERRIDE"


class TriggerType(str, Enum):
    USER_REQUEST       = "USER_REQUEST"
    SCHEDULED          = "SCHEDULED"
    RISK_DETERIORATION = "RISK_DETERIORATION"
    STRESS_SCENARIO    = "STRESS_SCENARIO"
    DATA_INTEGRITY     = "DATA_INTEGRITY"
    MANUAL_REVIEW      = "MANUAL_REVIEW"


class BreakerCategory(str, Enum):
    RISK       = "RISK"
    CONSTRAINT = "CONSTRAINT"
    DATA       = "DATA"
    MODEL      = "MODEL"
    STRESS     = "STRESS"


class Actor(str, Enum):
    MACHINE = "MACHINE"   # system computation
    CONTROL = "CONTROL"   # control-engine judgement
    HUMAN   = "HUMAN"


class DataProvider(str, Enum):
    JUGAAD          = "JUGAAD"
    CACHED          = "CACHED"
    CACHED_FALLBACK = "CACHED_FALLBACK"


class ValidationStatus(str, Enum):
    VALID    = "VALID"
    DEGRADED = "DEGRADED"   # usable, but incomplete — must be labelled in UI
    INVALID  = "INVALID"    # must NOT be used for risk computation
```

---

## 3. Universe and market data — `cce/contracts/market.py`

```python
@dataclass(frozen=True)
class Asset:
    asset_id: str            # stable key, used in all weight dicts
    ticker: str
    name: str
    asset_class: str         # EQUITY | FIXED_INCOME | COMMODITY | CASH
    sector: str              # BANKING | IT | PHARMA | BROAD_EQUITY | GOLD | GSEC | CASH
    is_liquid: bool          # counts toward the liquidity floor
    min_weight: float
    max_weight: float
    txn_cost_rate: float     # per unit of |weight change|, decimal
    adv_paise: int | None    # average daily value traded; None => ADV liquidity disabled


@dataclass(frozen=True)
class Universe:
    assets: tuple[Asset, ...]

    @property
    def asset_ids(self) -> tuple[str, ...]:
        """Canonical ordering for every ndarray in the system."""
        return tuple(a.asset_id for a in self.assets)

    def to_vector(self, weights: dict[str, float]) -> np.ndarray: ...
    def to_dict(self, vector: np.ndarray) -> dict[str, float]: ...
    def sector_map(self) -> dict[str, list[str]]: ...


@dataclass(frozen=True)
class MarketData:
    prices: pd.DataFrame     # index=date, columns=asset_ids
    returns: pd.DataFrame    # simple returns, same shape, first row dropped
    as_of_date: date
    provider: DataProvider
    universe_hash: str
    data_hash: str           # reproducibility key


@dataclass(frozen=True)
class ValidationFinding:
    code: str                # MISSING_OBS | STALE_DATA | OUTLIER | GAP | SCHEMA
    asset_id: str | None
    severity: RiskState
    message: str
    detail: dict


@dataclass(frozen=True)
class ValidationReport:
    status: ValidationStatus
    findings: tuple[ValidationFinding, ...]
    checked_at: datetime

    @property
    def usable_for_risk(self) -> bool:
        return self.status is not ValidationStatus.INVALID
```

**Contract:** `MarketData.returns` never contains `NaN`. If a gap could not be resolved legitimately, the report is `INVALID` and no `MarketData` is produced. Filling with zero is prohibited. `[INV-5]`

---

## 4. Portfolio — `cce/contracts/portfolio.py`

```python
@dataclass(frozen=True)
class Position:
    asset_id: str
    ticker: str
    asset_class: str
    sector: str
    price: float
    units: float
    value_paise: int
    weight: float


@dataclass(frozen=True)
class PortfolioState:
    portfolio_id: str
    timestamp: datetime
    as_of_date: date
    total_value_paise: int
    cash_value_paise: int
    positions: tuple[Position, ...]
    weights: dict[str, float]              # asset_id -> weight, sums to 1.0
    return_series: pd.Series               # historical portfolio returns

    def __post_init__(self):
        assert abs(sum(self.weights.values()) - 1.0) < 1e-6, "weights must sum to 1"

    def sector_exposure(self) -> dict[str, float]: ...
    def liquid_share(self, universe: Universe) -> float: ...
```

---

## 5. Risk — `cce/contracts/risk.py`

```python
@dataclass(frozen=True)
class Breach:
    control_code: str        # canonical code from 07-RISK-POLICY.md §4
    control_label: str
    severity: RiskState
    is_hard: bool            # hard breaches trip the circuit breaker
    observed: float
    threshold: float
    comparator: str          # GT | GTE | LT | LTE
    scope: str               # asset_id | sector | "PORTFOLIO"
    message: str


@dataclass(frozen=True)
class RiskSnapshot:
    timestamp: datetime
    as_of_date: date

    historical_volatility: float | None
    ewma_volatility: float | None
    portfolio_volatility: float | None
    expected_return: float | None            # MODEL ESTIMATE
    expected_return_method: ExpectedReturnMethod | None
    sharpe: float | None

    var_95: float | None                     # positive = loss
    cvar_95: float | None
    var_method: VaRMethod

    current_drawdown: float | None
    max_drawdown: float | None
    liquidity_ratio: float | None
    turnover_from_current: float | None

    risk_contribution: dict[str, float]      # asset_id -> share of total risk
    sector_exposure: dict[str, float]
    sector_risk_contribution: dict[str, float]
    concentration: dict[str, float]          # max_asset_weight, max_sector_weight, ...

    risk_state: RiskState
    breaches: tuple[Breach, ...]

    degraded: bool = False
    degraded_reason: str | None = None

    @property
    def hard_breaches(self) -> tuple[Breach, ...]:
        return tuple(b for b in self.breaches if b.is_hard and b.severity is RiskState.RED)
```

`risk_contribution` values sum to 1.0. Every `None` means *not computed*, and the UI must render it as "—", never as 0.

---

## 6. Optimization and control — `cce/contracts/optimization.py`, `control.py`

```python
@dataclass(frozen=True)
class Constraints:
    """Everything the optimizer is told. The control engine re-derives its own."""
    min_weights: dict[str, float]
    max_weights: dict[str, float]
    sector_max: dict[str, float]
    asset_class_max: dict[str, float]
    min_liquid_share: float
    min_cash_share: float
    max_turnover: float
    max_volatility: float | None
    max_cvar: float | None
    target_return: float | None
    long_only: bool = True
    include_txn_cost: bool = True


@dataclass(frozen=True)
class OptimizationResult:
    strategy: Strategy
    expected_return_method: ExpectedReturnMethod
    solver_status: SolverStatus
    weights: dict[str, float] | None     # None unless solver_status.usable

    # Optimizer's own view of its output. ADVISORY ONLY.
    # The control engine MUST recompute these independently. [FR-072]
    expected_return: float | None
    volatility: float | None
    sharpe: float | None
    var_95: float | None
    cvar_95: float | None
    turnover: float | None
    transaction_cost_paise: int | None

    solve_time_ms: int
    diagnostics: dict                    # solver name, iterations, warnings

    def __post_init__(self):
        if self.weights is not None and not self.solver_status.usable:
            raise ValueError("weights must be None unless the solver returned OPTIMAL")


@dataclass(frozen=True)
class ControlResult:
    status: ControlStatus
    passed: bool
    findings: tuple[Breach, ...]         # every control evaluated that was not GREEN
    hard_breaches: tuple[Breach, ...]
    warnings: tuple[Breach, ...]         # AMBER-level
    circuit_breaker_active: bool
    breaker_category: BreakerCategory | None
    recomputed: RiskSnapshot             # the control engine's OWN metrics
    last_safe_allocation: "SafeAllocation | None"
    evaluated_at: datetime

    def __post_init__(self):
        if self.passed and self.hard_breaches:
            raise ValueError("cannot pass with hard breaches present")


@dataclass(frozen=True)
class StressResult:
    scenario_code: str
    scenario_label: str
    is_custom: bool
    shocks: dict[str, float]             # sector or asset_id -> shock (decimal)
    portfolio_loss: float                # positive = loss
    loss_paise: int
    contribution: dict[str, float]
    post_shock_volatility: float | None
    post_shock_cvar: float | None
    breaches: tuple[Breach, ...]
    loss_threshold: float
    status: StressStatus

    @property
    def passed(self) -> bool:
        return self.status is StressStatus.PASSED


@dataclass(frozen=True)
class Candidate:
    """A proposal plus the verdicts on it. The unit the UI renders."""
    role: CandidateRole
    optimization: OptimizationResult
    control: ControlResult | None
    stress: tuple[StressResult, ...]

    @property
    def stress_status(self) -> StressStatus:
        if not self.stress:
            return StressStatus.NOT_RUN
        if any(s.status is StressStatus.ERROR for s in self.stress):
            return StressStatus.ERROR
        return (StressStatus.PASSED
                if all(s.passed for s in self.stress) else StressStatus.FAILED)

    @property
    def eligible_for_approval(self) -> bool:
        """The single gate for the Approve button. [INV-2] [INV-10]"""
        return (self.control is not None
                and self.control.status is ControlStatus.PASSED
                and self.control.passed
                and self.stress_status is StressStatus.PASSED)
```

> `eligible_for_approval` is defined in exactly one place. The UI reads this property; it MUST NOT reimplement the condition. Any second implementation is a bug waiting to diverge.

---

## 7. Decisions, explanation, audit — `cce/contracts/decision.py`

```python
@dataclass(frozen=True)
class RiskChange:
    metric: str
    from_value: float
    to_value: float
    scope: str = "PORTFOLIO"


@dataclass(frozen=True)
class Explanation:
    """The deterministic source of truth for all narrative output. [FR-141]"""
    trigger: str
    risk_change: RiskChange | None
    main_contributors: tuple[RiskChange, ...]
    optimizer: Strategy | None
    candidate_summary: dict[str, float]
    control_result: str                  # ACCEPTED | REJECTED | NOT_VALIDATED
    reasons: tuple[str, ...]
    stress_summary: tuple[str, ...]
    action: str
    expected_improvement: str | None


@dataclass(frozen=True)
class NarratedExplanation:
    structured: Explanation              # authoritative
    template_text: str                   # deterministic, always present
    llm_text: str | None = None          # DISPLAY ONLY — never parsed back [INV-1]
    llm_model: str | None = None
    llm_error: str | None = None


@dataclass(frozen=True)
class HumanActionRecord:
    action: HumanAction
    user_identity: str
    user_role: str
    timestamp: datetime
    candidate_role: CandidateRole | None
    comment: str | None = None
    is_override: bool = False
    override_reason: str | None = None
    overridden_controls: tuple[str, ...] = ()
    confirmation_token: str | None = None

    def __post_init__(self):
        if self.is_override and not (self.override_reason
                                     and self.overridden_controls
                                     and self.confirmation_token):
            raise ValueError("override requires reason, controls and confirmation")


@dataclass(frozen=True)
class DecisionEvent:
    sequence_no: int
    occurred_at: datetime
    actor: Actor
    event_code: str
    summary: str
    detail: dict | None = None


@dataclass(frozen=True)
class SafeAllocation:
    safe_allocation_id: int
    approved_at: datetime
    weights: dict[str, float]
    decision_id: int
    policy_version_id: int               # the policy it passed, at that time
    approved_by: str
    via_override: bool = False


@dataclass(frozen=True)
class DecisionRecord:
    event_uid: str
    timestamp: datetime
    trigger: TriggerType
    trigger_detail: str | None

    portfolio_before: PortfolioState
    risk_before: RiskSnapshot

    candidates: tuple[Candidate, ...]
    recommended: CandidateRole | None

    control_status: ControlStatus
    circuit_breaker_active: bool
    breaker_category: BreakerCategory | None

    explanation: NarratedExplanation
    events: tuple[DecisionEvent, ...]

    human_action: HumanActionRecord | None = None
    portfolio_after: PortfolioState | None = None
```

---

## 8. Policy — `cce/contracts/policy.py`

```python
@dataclass(frozen=True)
class Threshold:
    control_code: str
    label: str
    green_max: float | None      # None on the side that is unbounded
    amber_max: float | None
    comparator: str              # GT: breach when value exceeds; LT: when below
    is_hard: bool                # hard => RED trips the circuit breaker
    scope: str                   # PORTFOLIO | ASSET | SECTOR

    def classify(self, value: float) -> RiskState: ...


@dataclass(frozen=True)
class Policy:
    version: int
    thresholds: tuple[Threshold, ...]
    risk_free_rate: float
    ewma_lambda: float
    var_confidence: float
    trading_days_per_year: int
    stress_loss_limit: float
    constraints: Constraints

    def threshold(self, control_code: str) -> Threshold: ...
```

---

## 9. Service layer — the only API the UI may call

`cce/services/` — L4. Every method returns contracts, never raw frames or dicts.

```python
class PortfolioService:
    def get_current_state(self) -> PortfolioState: ...
    def get_last_safe_allocation(self) -> SafeAllocation | None: ...
    def get_universe(self) -> Universe: ...


class RiskService:
    def get_snapshot(self, state: PortfolioState) -> RiskSnapshot: ...
    def what_changed(self, previous: RiskSnapshot,
                     current: RiskSnapshot) -> tuple[RiskChange, ...]: ...


class OptimizationService:
    def propose(self, strategy: Strategy,
                er_method: ExpectedReturnMethod,
                overrides: Constraints | None = None) -> Candidate:
        """Optimize -> independently validate -> stress test. One unit of work."""

    def propose_safe_and_optimal(self, strategy: Strategy
                                 ) -> tuple[Candidate, Candidate]:
        """(optimal_unconstrained, safe_constrained) for the signature view."""

    def generate_recovery_candidates(self) -> tuple[Candidate, ...]:
        """Up to 3, each independently validated. [FR-080] [FR-081]"""


class ApprovalService:
    def approve(self, decision_id: int, candidate: Candidate,
                actor: HumanActionRecord) -> PortfolioState: ...
    def reject(self, decision_id: int, actor: HumanActionRecord) -> None: ...
    def keep_current(self, decision_id: int, actor: HumanActionRecord) -> None: ...
    def override(self, decision_id: int, candidate: Candidate,
                 actor: HumanActionRecord) -> PortfolioState: ...


class StressService:
    def list_scenarios(self) -> tuple[Scenario, ...]: ...
    def run(self, weights: dict[str, float],
            scenario_codes: tuple[str, ...]) -> tuple[StressResult, ...]: ...
    def run_custom(self, weights: dict[str, float],
                   shocks: dict[str, float]) -> StressResult: ...


class BacktestService:
    def run(self, config: BacktestConfig) -> BacktestRun: ...
    def compare(self, run: BacktestRun) -> dict[str, StrategyMetrics]: ...
    def equity_curves(self, run: BacktestRun) -> dict[str, pd.Series]: ...
    def drawdowns(self, run: BacktestRun) -> dict[str, pd.Series]: ...
    def available_range(self) -> tuple[date, date]: ...


class ReplayService:
    def list_decisions(self, limit: int = 50) -> tuple[DecisionSummary, ...]: ...
    def get_timeline(self, decision_id: int) -> tuple[DecisionEvent, ...]: ...


class PolicyService:
    def get_current(self) -> Policy: ...
    def preview_change(self, changes: dict) -> PolicyChangePreview:
        """Returns is_weakening + affected controls, BEFORE applying. [FR-084]"""
    def apply_change(self, changes: dict,
                     actor: HumanActionRecord) -> Policy: ...
```

### As built (PHASE 9)

The signatures above are the design sketch. The implementation differs in
four ways, each deliberate:

| Difference | Why |
|---|---|
| Every service takes a `ServiceContext` | The universe, policy, market data and repository are resolved ONCE and shared. Loading them per service would let a cycle optimize against one price panel and validate against another — the two verdicts would not be about the same portfolio, and the independence property would be lost to a data race rather than to a design flaw. |
| Methods that need the book take `state: PortfolioState` | Passing it in keeps the services stateless and makes it explicit which snapshot a proposal was judged against. |
| `StressService.list_scenarios -> tuple[Scenario, ...]` | `ScenarioDefinition` was a duplicate of `Scenario` with its own loader over the same YAML. One contract now, in `cce/contracts/control.py`. |
| `OptimizationService.run_cycle` added | The prompt requires this layer to persist the `BreakerOutcome` the engines construct. `propose` stays pure so it can be called without writing; `run_cycle` is the one that records a decision. |

`ApprovalService.approve` also takes `state`, and `PolicyService.apply_change`
takes an optional `change_summary`.

**Ordering note.** `propose` runs optimize → **stress** → validate, not
optimize → validate → stress. `STRESS_LOSS_MAX` is a HARD control and the
control engine cannot evaluate it without the worst measured scenario loss;
validating first left it unevaluated, which correctly produced
`NOT_VALIDATED` for every candidate however healthy. The two steps remain one
indivisible unit — only their internal order differs from the prose.

---

### What the service layer guarantees

1. `OptimizationService.propose` **always** runs propose → validate → stress as one unit. There is no public path that optimizes without validating. This is why the UI cannot accidentally skip the control engine.
2. `ApprovalService.approve` re-checks `candidate.eligible_for_approval` server-side and raises if false. The UI disabling a button is a convenience, not the enforcement. `[INV-2]`
3. Every service method that changes state writes its audit record inside the same transaction as the change. `[INV-6]`

---

## 10. Contract change protocol

1. Update the dataclass in `cce/contracts/`.
2. Update this document in the same commit.
3. Update the persistence mapping in `05-BACKEND-SCHEMA.md` and add a migration if a stored shape changed.
4. Run the full test suite — contract drift usually surfaces first in `tests/test_invariants.py`.

A contract change that skips step 2 leaves the docs lying to the next session. That is the most expensive kind of bug in an AI-assisted build.


---

## 10. Backtest contracts

`cce/contracts/backtest.py`. **Both live in `contracts/`, not in
`cce/backtest/`**, because the UI constructs the config and renders the
metrics, and `ui/` may import only `cce.services` and `cce.contracts`
(INV-12). `tests/test_architecture.py` enforces that, and caught the
violation the first time the backtest page was written.

```python
@dataclass(frozen=True)
class BacktestConfig:
    start: date
    end: date
    rebalance: str = "MONTHLY"          # MONTHLY | WEEKLY
    initial_weights: dict[str, float] = field(default_factory=dict)
    er_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL
    min_window: int = 250               # skip a date with fewer priors
    random_seed: int = 42               # NFR-012, carried even while
                                        # nothing here is stochastic


@dataclass(frozen=True)
class StrategyMetrics:
    name: str
    cumulative_return: float | None
    annualised_return: float | None
    volatility: float | None
    sharpe: float | None
    max_drawdown: float | None
    var_95: float | None
    cvar_95: float | None
    avg_turnover: float | None
    total_txn_cost_paise: int
    policy_breach_count: int            # a PEER of return, not a diagnostic
    breaker_activations: int
    rebalances: int
    holds: int
```

Every performance field is `float | None`. Too few observations is a real
outcome and is reported as `—`, never as `0` (INV-5).

`BacktestRun` and `StrategyRun` stay in `cce/backtest/` — they hold pandas
objects and never cross into the UI, which receives finished series from
`equity_curves()` and `drawdowns()` instead.

**Drawdown is computed from RETURNS, not from the equity curve.**
`max_drawdown` builds its own cumulative series; handing it levels returns
`0.0` for every strategy without raising.

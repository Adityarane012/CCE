"""Risk engine — assembles a RiskSnapshot.

Spec: docs/04-WORKFLOW.md Step 4, docs/06-DATA-CONTRACTS.md section 5.

Every function reachable from here is PURE: same inputs, same outputs, no
I/O, no globals (FR-045).

**The snapshot returned here is UNCLASSIFIED.** ``risk_state`` is GREEN and
``breaches`` is empty regardless of the numbers, because classification is
the control engine's job and lives in exactly one place —
``cce.controls.state_machine`` (INV-11). Phase 5 takes this snapshot and
produces the classified one.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np

from ..contracts import (
    ExpectedReturnMethod, MarketData, RiskSnapshot, RiskState, Universe,
    VaRMethod,
)
from ..portfolio.calculations import (
    portfolio_returns, sector_exposure, turnover,
)
from .concentration import concentration_summary
from .covariance import CovarianceReport, estimate_covariance
from .cvar import cvar_with_diagnostics
from .drawdown import current_drawdown, max_drawdown
from .ewma import DEFAULT_LAMBDA, ewma_volatility
from .expected_returns import expected_returns
from .liquidity import liquidity_summary
from .risk_contribution import (
    risk_contribution_table, sector_risk_contributions,
)
from .var import MIN_OBSERVATIONS, historical_var
from .volatility import TRADING_DAYS, historical_volatility, portfolio_volatility

logger = logging.getLogger(__name__)

__all__ = ["RiskInputs", "compute_risk_snapshot", "sharpe_ratio"]


WEIGHT_TOLERANCE = 1e-6


@dataclass(frozen=True)
class RiskInputs:
    """Everything the engine needs. Grouped so callers cannot half-specify.

    Validates the weight vector on construction. Without this the engine
    happily measures a half-invested or over-invested book and returns
    plausible-looking numbers: weights summing to 0.5 produced a 6.9%
    volatility, and 1.5 produced 19.0%. Neither is wrong arithmetic — both
    are the wrong question, answered confidently.

    That is the exact failure mode the project forbids, and it is how a
    buggy optimizer output would get measured as safe. The engine is a pure
    function, but a pure function may still refuse nonsense.
    """

    weights: dict[str, float]
    universe: Universe
    market_data: MarketData
    risk_free_rate: float = 0.065
    ewma_lambda: float = DEFAULT_LAMBDA
    var_confidence: float = 0.95
    trading_days: int = TRADING_DAYS
    min_observations: int = MIN_OBSERVATIONS
    covariance_method: str = "historical"
    return_method: ExpectedReturnMethod = ExpectedReturnMethod.HISTORICAL
    current_weights: dict[str, float] | None = None
    total_value_paise: int = 0

    def __post_init__(self) -> None:
        _validate_weights(self.weights, self.universe, "weights")
        if self.current_weights is not None:
            _validate_weights(
                self.current_weights, self.universe, "current_weights"
            )


def _validate_weights(
    weights: dict[str, float], universe: Universe, label: str
) -> None:
    """Reject a weight vector that cannot describe a real portfolio."""
    if not weights:
        raise ValueError(f"{label} is empty")

    unknown = set(weights) - set(universe.asset_ids)
    if unknown:
        raise ValueError(
            f"{label} contain unknown asset_ids: {sorted(unknown)}"
        )

    negative = {a: w for a, w in weights.items() if w < 0}
    if negative:
        raise ValueError(
            f"{label} contain negative positions {negative}; CCE is "
            f"long-only and short exposure is not modelled"
        )

    total = sum(weights.values())
    if abs(total - 1.0) > WEIGHT_TOLERANCE:
        raise ValueError(
            f"{label} must sum to 1.0 within {WEIGHT_TOLERANCE}, got "
            f"{total!r}. Measuring a book that is not fully invested returns "
            f"a plausible number for the wrong question."
        )


def sharpe_ratio(
    expected_return: float | None,
    volatility: float | None,
    risk_free_rate: float,
) -> float | None:
    """``(E[R_p] - R_f) / sigma_p``, annualised inputs.

    Returns ``None`` when volatility is zero or either input is missing —
    an all-cash portfolio has an undefined Sharpe, not an infinite one
    (EC-3.3).
    """
    if expected_return is None or volatility is None or volatility <= 0.0:
        return None
    return float((expected_return - risk_free_rate) / volatility)


def compute_risk_snapshot(inputs: RiskInputs) -> tuple[RiskSnapshot, CovarianceReport]:
    """Compute every risk metric for an allocation.

    Returns the snapshot and the covariance report, because a repaired
    covariance must surface as a ``MODEL_COVARIANCE`` finding in Phase 5
    rather than being silently absorbed here.

    Raises :class:`~cce.exceptions.CovarianceError` if the covariance cannot
    be repaired — the safe direction to fail (INV-4).
    """
    md = inputs.market_data
    universe = inputs.universe
    weights = inputs.weights

    held = [a for a in universe.asset_ids if a in md.returns.columns]
    returns = md.returns[held]
    n_obs = len(returns)

    degraded_reasons: list[str] = []
    if n_obs < inputs.min_observations:
        degraded_reasons.append(
            f"only {n_obs} return observations; metrics requiring "
            f"{inputs.min_observations}+ are reported as not computed"
        )

    # ---- covariance (repaired or refused) --------------------------------
    cov, cov_report = estimate_covariance(
        returns, method=inputs.covariance_method, lam=inputs.ewma_lambda,
        annualise=True, trading_days=inputs.trading_days,
    )
    if cov_report.repaired:
        degraded_reasons.append(cov_report.message)

    w_vec = np.array([weights.get(a, 0.0) for a in held], dtype=float)

    # ---- volatility -------------------------------------------------------
    port_returns = portfolio_returns(weights, returns)
    hist_vol = historical_volatility(port_returns, trading_days=inputs.trading_days)
    ewma_vol = ewma_volatility(
        port_returns, lam=inputs.ewma_lambda, trading_days=inputs.trading_days
    )
    port_vol = portfolio_volatility(w_vec, cov)  # cov already annualised

    # ---- expected return and Sharpe (MODEL ESTIMATES) ---------------------
    mu = expected_returns(
        returns, method=inputs.return_method, lam=inputs.ewma_lambda,
        annualise=True, trading_days=inputs.trading_days,
    )
    exp_ret = float(w_vec @ mu)
    sharpe = sharpe_ratio(exp_ret, port_vol, inputs.risk_free_rate)

    # ---- tail -------------------------------------------------------------
    var_95 = historical_var(
        port_returns, inputs.var_confidence, min_observations=inputs.min_observations
    )
    cvar = cvar_with_diagnostics(
        port_returns, inputs.var_confidence, min_observations=inputs.min_observations
    )
    if cvar.degraded and cvar.reason:
        degraded_reasons.append(cvar.reason)

    # ---- attribution and exposure ----------------------------------------
    rc = risk_contribution_table(
        {a: weights.get(a, 0.0) for a in held}, cov, _restrict(universe, held)
    )
    sector_rc = sector_risk_contributions(
        {a: weights.get(a, 0.0) for a in held}, cov, _restrict(universe, held)
    )
    conc = concentration_summary(weights, universe)
    # total_value_paise only affects the ADV-based days-to-liquidate tier.
    # When it is unset, that tier is SKIPPED rather than computed against a
    # substituted value - a silent `or 1` would have measured liquidation
    # against one paise of portfolio (docs/08 section 10.2).
    liq = liquidity_summary(
        weights, universe,
        inputs.total_value_paise if inputs.total_value_paise > 0 else None,
    )
    conc["liquid_share"] = liq.liquid_share
    conc["cash_share"] = liq.cash_share

    turn = (
        turnover(weights, inputs.current_weights)
        if inputs.current_weights is not None else None
    )

    return (
        RiskSnapshot(
            timestamp=datetime.now(timezone.utc),
            as_of_date=md.as_of_date,
            historical_volatility=hist_vol,
            ewma_volatility=ewma_vol,
            portfolio_volatility=port_vol,
            expected_return=exp_ret,
            expected_return_method=inputs.return_method,
            sharpe=sharpe,
            var_95=var_95,
            cvar_95=cvar.value,
            var_method=VaRMethod.HISTORICAL,
            current_drawdown=current_drawdown(port_returns),
            max_drawdown=max_drawdown(port_returns),
            liquidity_ratio=liq.liquid_share,
            turnover_from_current=turn,
            risk_contribution=rc,
            sector_exposure=sector_exposure(weights, universe),
            sector_risk_contribution=sector_rc,
            concentration=conc,
            # UNCLASSIFIED - cce.controls.state_machine populates these (INV-11)
            risk_state=RiskState.GREEN,
            breaches=(),
            degraded=bool(degraded_reasons),
            degraded_reason="; ".join(degraded_reasons) or None,
        ),
        cov_report,
    )


def _restrict(universe: Universe, asset_ids: list[str]) -> Universe:
    """A universe view limited to the assets actually priced.

    Needed because covariance is built only from priced columns, and
    ``Universe.to_vector`` requires the two orderings to match exactly.
    """
    from ..contracts import Universe as U
    keep = [a for a in universe.assets if a.asset_id in set(asset_ids)]
    order = {aid: i for i, aid in enumerate(asset_ids)}
    keep.sort(key=lambda a: order[a.asset_id])
    return U(assets=tuple(keep))

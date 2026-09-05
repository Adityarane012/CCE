"""Risk engine (L3).

Pure functions over returns and weights. No I/O, no globals, no imports from
services, controls, optimizer or ui (docs/02-ARCHITECTURE.md section 2).

Conventions (docs/08-FINANCIAL-METHODS.md section 0):
- Volatility and return are ANNUALISED unless the name says otherwise
- VaR/CVaR are 1-day at 95% unless the name says otherwise
- Losses are POSITIVE
- ``None`` means NOT COMPUTED and never means zero (INV-5)
"""

from __future__ import annotations

from .concentration import (
    concentration_summary,
    effective_number_of_assets,
    herfindahl_index,
    max_asset_class_weight,
    max_asset_weight,
    max_sector_weight,
)
from .covariance import (
    CovarianceReport,
    condition_number,
    correlation_from_covariance,
    estimate_covariance,
    historical_covariance,
    is_psd,
    prepare_covariance,
)
from .cvar import CVaRResult, cvar_with_diagnostics, historical_cvar
from .drawdown import (
    current_drawdown,
    drawdown_series,
    equity_curve,
    max_drawdown,
    rolling_max_drawdown,
)
from .engine import RiskInputs, compute_risk_snapshot, sharpe_ratio
from .ewma import (
    DEFAULT_LAMBDA,
    ewma_covariance,
    ewma_variance_series,
    ewma_volatility,
)
from .expected_returns import ewma_mean, expected_returns, historical_mean
from .liquidity import (
    LiquidityProfile,
    cash_share,
    days_to_liquidate,
    liquid_share,
    liquidity_summary,
)
from .risk_contribution import (
    marginal_contributions,
    percentage_risk_contributions,
    risk_contribution_table,
    risk_contributions,
    sector_risk_contributions,
)
from .var import historical_var, monte_carlo_var, parametric_var
from .volatility import (
    TRADING_DAYS,
    annualisation_factor,
    historical_volatility,
    portfolio_volatility,
    rolling_volatility,
)

__all__ = [
    "DEFAULT_LAMBDA",
    "TRADING_DAYS",
    "CVaRResult",
    "CovarianceReport",
    "LiquidityProfile",
    "RiskInputs",
    "annualisation_factor",
    "cash_share",
    "compute_risk_snapshot",
    "concentration_summary",
    "condition_number",
    "correlation_from_covariance",
    "current_drawdown",
    "cvar_with_diagnostics",
    "days_to_liquidate",
    "drawdown_series",
    "effective_number_of_assets",
    "equity_curve",
    "estimate_covariance",
    "ewma_covariance",
    "ewma_mean",
    "ewma_variance_series",
    "ewma_volatility",
    "expected_returns",
    "herfindahl_index",
    "historical_covariance",
    "historical_cvar",
    "historical_mean",
    "historical_var",
    "historical_volatility",
    "is_psd",
    "liquid_share",
    "liquidity_summary",
    "marginal_contributions",
    "max_asset_class_weight",
    "max_asset_weight",
    "max_drawdown",
    "max_sector_weight",
    "monte_carlo_var",
    "parametric_var",
    "percentage_risk_contributions",
    "portfolio_volatility",
    "prepare_covariance",
    "risk_contribution_table",
    "risk_contributions",
    "rolling_max_drawdown",
    "rolling_volatility",
    "sector_risk_contributions",
    "sharpe_ratio",
]

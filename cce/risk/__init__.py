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
    concentration_summary, effective_number_of_assets, herfindahl_index,
    max_asset_class_weight, max_asset_weight, max_sector_weight,
)
from .covariance import (
    CovarianceReport, condition_number, correlation_from_covariance,
    estimate_covariance, historical_covariance, is_psd, prepare_covariance,
)
from .cvar import CVaRResult, cvar_with_diagnostics, historical_cvar
from .drawdown import (
    current_drawdown, drawdown_series, equity_curve, max_drawdown,
    rolling_max_drawdown,
)
from .engine import RiskInputs, compute_risk_snapshot, sharpe_ratio
from .ewma import (
    DEFAULT_LAMBDA, ewma_covariance, ewma_variance_series, ewma_volatility,
)
from .expected_returns import ewma_mean, expected_returns, historical_mean
from .liquidity import (
    LiquidityProfile, cash_share, days_to_liquidate, liquid_share,
    liquidity_summary,
)
from .risk_contribution import (
    marginal_contributions, percentage_risk_contributions,
    risk_contribution_table, risk_contributions, sector_risk_contributions,
)
from .var import historical_var, monte_carlo_var, parametric_var
from .volatility import (
    TRADING_DAYS, annualisation_factor, historical_volatility,
    portfolio_volatility, rolling_volatility,
)

__all__ = [
    "TRADING_DAYS", "DEFAULT_LAMBDA",
    "annualisation_factor", "historical_volatility", "portfolio_volatility",
    "rolling_volatility",
    "ewma_volatility", "ewma_variance_series", "ewma_covariance",
    "historical_covariance", "prepare_covariance", "estimate_covariance",
    "is_psd", "condition_number", "correlation_from_covariance",
    "CovarianceReport",
    "historical_var", "parametric_var", "monte_carlo_var",
    "historical_cvar", "cvar_with_diagnostics", "CVaRResult",
    "equity_curve", "drawdown_series", "current_drawdown", "max_drawdown",
    "rolling_max_drawdown",
    "marginal_contributions", "risk_contributions",
    "percentage_risk_contributions", "risk_contribution_table",
    "sector_risk_contributions",
    "max_asset_weight", "max_sector_weight", "max_asset_class_weight",
    "herfindahl_index", "effective_number_of_assets", "concentration_summary",
    "liquid_share", "cash_share", "days_to_liquidate", "liquidity_summary",
    "LiquidityProfile",
    "historical_mean", "ewma_mean", "expected_returns",
    "RiskInputs", "compute_risk_snapshot", "sharpe_ratio",
]

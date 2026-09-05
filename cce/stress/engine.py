"""Stress testing engine.

Spec: docs/07-RISK-POLICY.md section 7, docs/08-FINANCIAL-METHODS.md section 13.
"""

from __future__ import annotations

import logging

from ..contracts import (
    MarketData,
    Policy,
    StressResult,
    StressStatus,
    Universe,
)
from ..controls.validation import validate
from .scenarios import Scenario

logger = logging.getLogger(__name__)

__all__ = ["run_scenario"]


def run_scenario(
    weights: dict[str, float],
    scenario: Scenario,
    universe: Universe,
    md: MarketData,
    current_weights: dict[str, float],
    policy: Policy,
    total_value_paise: int,
) -> StressResult:
    """Apply a stress scenario to a portfolio and evaluate the result."""
    try:
        portfolio_return = 0.0
        contribution: dict[str, float] = {}

        # Resolve shocks per asset
        asset_shocks: dict[str, float] = {}
        for asset in universe.assets:
            shock = 0.0
            if asset.asset_id in scenario.shocks:
                shock = scenario.shocks[asset.asset_id]
            elif asset.sector in scenario.shocks:
                shock = scenario.shocks[asset.sector]
            asset_shocks[asset.asset_id] = shock

        for asset_id, w in weights.items():
            if asset_id not in asset_shocks:
                continue
            shock = asset_shocks[asset_id]
            ret = w * shock
            portfolio_return += ret
            if w > 0:
                contribution[asset_id] = -ret

        portfolio_loss = -portfolio_return
        loss_paise = round(total_value_paise * portfolio_loss)

        # Recompute drifted weights
        post_shock_weights: dict[str, float] = {}
        if portfolio_return > -1.0:
            for asset_id, w in weights.items():
                shock = asset_shocks.get(asset_id, 0.0)
                post_shock_weights[asset_id] = w * (1 + shock) / (1 + portfolio_return)
        else:
            # 100% loss
            post_shock_weights = {k: 0.0 for k in weights}

        # Apply LIQUIDITY pseudo-sector shock if present
        liquidity_shock = scenario.shocks.get("LIQUIDITY", 0.0)
        if liquidity_shock != 0.0:
            import dataclasses
            
            shocked_assets = []
            for a in universe.assets:
                if a.adv_paise is not None:
                    # Liquidity drops by the shock percentage
                    shocked_adv = round(a.adv_paise * (1 + liquidity_shock))
                    shocked_assets.append(dataclasses.replace(a, adv_paise=shocked_adv))
                else:
                    shocked_assets.append(a)
            universe = dataclasses.replace(universe, assets=tuple(shocked_assets))

        # Determine resulting breaches by running validation on post-shock weights
        control = validate(
            candidate_weights=post_shock_weights,
            universe=universe,
            market_data=md,
            current_weights=current_weights,
            policy=policy,
            total_value_paise=total_value_paise - loss_paise if total_value_paise > 0 else 0,
        )

        status = StressStatus.PASSED
        if portfolio_loss > policy.stress_loss_limit:
            status = StressStatus.FAILED

        return StressResult(
            scenario_code=scenario.code,
            scenario_label=scenario.label,
            is_custom=scenario.is_custom,
            shocks=scenario.shocks,
            portfolio_loss=portfolio_loss,
            loss_paise=loss_paise,
            contribution=contribution,
            post_shock_volatility=control.recomputed.portfolio_volatility,
            post_shock_cvar=control.recomputed.cvar_95,
            breaches=control.findings,
            loss_threshold=policy.stress_loss_limit,
            status=status,
        )
    except Exception as e:
        logger.exception("Stress engine failed on scenario %s: %s", scenario.code, e)
        return StressResult(
            scenario_code=scenario.code,
            scenario_label=scenario.label,
            is_custom=scenario.is_custom,
            shocks=scenario.shocks,
            portfolio_loss=0.0,
            loss_paise=0,
            contribution={},
            post_shock_volatility=None,
            post_shock_cvar=None,
            breaches=(),
            loss_threshold=policy.stress_loss_limit,
            status=StressStatus.ERROR,
        )

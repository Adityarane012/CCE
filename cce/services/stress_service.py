"""Stress scenario orchestration.

Spec: docs/06-DATA-CONTRACTS.md section 9, docs/07-RISK-POLICY.md section 7.
"""

from __future__ import annotations

from cce.contracts import Scenario, StressResult, StressStatus
from cce.stress import run_scenario

from .context import ServiceContext

__all__ = ["StressService"]


class StressService:
    """Runs configured and ad-hoc scenarios against a set of weights."""

    def __init__(self, ctx: ServiceContext) -> None:
        self._ctx = ctx
        self._scenarios: tuple[Scenario, ...] | None = None

    def list_scenarios(self) -> tuple[Scenario, ...]:
        """The configured scenarios, loaded once."""
        if self._scenarios is None:
            from cce.config import load_scenarios

            self._scenarios = load_scenarios()
        return self._scenarios

    def _run_one(
        self, weights: dict[str, float], scenario: Scenario, total_value_paise: int
    ) -> StressResult:
        return run_scenario(
            weights, scenario, self._ctx.universe, self._ctx.market_data,
            current_weights=weights, policy=self._ctx.policy,
            total_value_paise=total_value_paise,
        )

    def run(
        self,
        weights: dict[str, float],
        scenario_codes: tuple[str, ...] = (),
        total_value_paise: int = 0,
    ) -> tuple[StressResult, ...]:
        """Run the named scenarios, or all configured ones if none are named.

        A code that matches no configured scenario yields an ERROR result
        rather than being skipped. Skipping it would shorten the suite
        silently, and a shorter suite that passes looks exactly like a longer
        one that passes (INV-10).
        """
        available = {s.code: s for s in self.list_scenarios()}
        selected = scenario_codes or tuple(available)

        results: list[StressResult] = []
        for code in selected:
            scenario = available.get(code)
            if scenario is None:
                results.append(StressResult(
                    scenario_code=code, scenario_label=code, is_custom=False,
                    shocks={}, portfolio_loss=0.0, loss_paise=0, contribution={},
                    post_shock_volatility=None, post_shock_cvar=None, breaches=(),
                    loss_threshold=self._ctx.policy.stress_loss_limit,
                    status=StressStatus.ERROR,
                    error_reason=f"no scenario configured with code {code!r}",
                ))
                continue
            results.append(self._run_one(weights, scenario, total_value_paise))
        return tuple(results)

    def run_custom(
        self,
        weights: dict[str, float],
        shocks: dict[str, float],
        label: str = "Custom scenario",
        total_value_paise: int = 0,
    ) -> StressResult:
        """Run an ad-hoc scenario built in the UI.

        Unresolvable shock keys are caught by the engine and returned as
        ERROR — a custom scenario naming a sector that does not exist has
        tested nothing, whatever the loss figure says.
        """
        return self._run_one(
            weights, Scenario.custom(label, shocks), total_value_paise
        )

    def worst_loss(self, results: tuple[StressResult, ...]) -> float | None:
        """The worst MEASURED loss across a suite, or ``None``.

        ``None`` when no scenario produced a usable verdict. The control
        engine treats that as an unevaluated hard control rather than as a
        zero loss, so an unrun suite cannot read as a clean one (INV-5,
        INV-10).
        """
        measured = [r.portfolio_loss for r in results if r.loss_is_measured]
        return max(measured) if measured else None

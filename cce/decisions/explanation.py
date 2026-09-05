from collections.abc import Iterable

from cce.contracts.decision import Explanation
from cce.contracts.enums import ControlStatus, Strategy
from cce.contracts.risk import RiskChange


def build_explanation(
    trigger_desc: str,
    risk_change: RiskChange | None,
    main_contributors: Iterable[RiskChange],
    optimizer: Strategy | None,
    candidate_summary: dict[str, float],
    control_status: ControlStatus,
    reasons: Iterable[str],
    stress_summary: Iterable[str],
    action: str,
    expected_improvement: str | None = None
) -> Explanation:
    """Builds a structured Explanation object deterministically."""
    
    return Explanation(
        trigger=trigger_desc,
        risk_change=risk_change,
        main_contributors=tuple(main_contributors),
        optimizer=optimizer,
        candidate_summary=dict(candidate_summary),
        control_result=control_status.name,
        reasons=tuple(reasons),
        stress_summary=tuple(stress_summary),
        action=action,
        expected_improvement=expected_improvement
    )

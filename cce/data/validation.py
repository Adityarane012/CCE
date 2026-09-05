"""Market data validation.

Spec: docs/13-EDGE-CASES.md section 2, docs/03-TRD.md FR-006..FR-008.

A validation failure is a CONTROL EVENT, not a warning to ignore. Missing
data is never zero-filled: if a gap cannot be resolved legitimately, the
report is INVALID and no :class:`MarketData` is produced at all (INV-5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd

from ..clock import market_today
from ..contracts import (
    Policy,
    DataProvider,
    MarketData,
    RiskState,
    Universe,
    ValidationFinding,
    ValidationReport,
    ValidationStatus,
)
from ..exceptions import DataIntegrityError
from .providers import panel_hash, universe_hash

logger = logging.getLogger(__name__)

__all__ = [
    "panel_metrics","ValidationThresholds", "build_market_data", "validate_panel"]

# [DEMO-CONFIG] FALLBACKS ONLY, used when no Policy is supplied.
#
# These previously "mirrored" config/policy.yaml, which meant the same two
# bands existed in two places: editing policy.yaml moved the control the risk
# engine applies while this validator silently kept the old numbers. When a
# Policy is passed, DATA_FRESHNESS and DATA_COMPLETENESS are read FROM IT and
# these are not consulted.
MAX_STALE_TRADING_DAYS_GREEN = 1
MAX_STALE_TRADING_DAYS_AMBER = 3
MIN_COMPLETENESS_GREEN = 0.98
MIN_COMPLETENESS_AMBER = 0.95
OUTLIER_ABS_RETURN = 0.50      # |r| > 50% on an index is implausible
MIN_OBSERVATIONS = 250
MAX_INTERIOR_GAP = 3           # consecutive missing sessions still repairable


@dataclass(frozen=True)
class ValidationThresholds:
    """The bands this validator applies.

    Built from the Policy when one is available, so ``config/policy.yaml`` is
    the single source of truth for DATA_FRESHNESS and DATA_COMPLETENESS.
    """

    stale_green: float = MAX_STALE_TRADING_DAYS_GREEN
    stale_amber: float = MAX_STALE_TRADING_DAYS_AMBER
    completeness_green: float = MIN_COMPLETENESS_GREEN
    completeness_amber: float = MIN_COMPLETENESS_AMBER
    outlier: float = OUTLIER_ABS_RETURN
    min_observations: int = MIN_OBSERVATIONS

    @classmethod
    def from_policy(cls, policy: Policy | None) -> ValidationThresholds:
        """Read the data bands from the policy in force.

        A control the policy does not define keeps its fallback rather than
        vanishing: dropping a data-integrity check because a threshold is
        absent would be a silent weakening.
        """
        if policy is None:
            return cls()
        fresh = policy.threshold("DATA_FRESHNESS") if policy.has("DATA_FRESHNESS") else None
        comp = (
            policy.threshold("DATA_COMPLETENESS")
            if policy.has("DATA_COMPLETENESS") else None
        )
        return cls(
            stale_green=(
                fresh.green_max if fresh and fresh.green_max is not None
                else MAX_STALE_TRADING_DAYS_GREEN
            ),
            stale_amber=(
                fresh.amber_max if fresh and fresh.amber_max is not None
                else MAX_STALE_TRADING_DAYS_AMBER
            ),
            completeness_green=(
                comp.green_min if comp and comp.green_min is not None
                else MIN_COMPLETENESS_GREEN
            ),
            completeness_amber=(
                comp.amber_min if comp and comp.amber_min is not None
                else MIN_COMPLETENESS_AMBER
            ),
            min_observations=policy.model.min_return_observations,
        )


def _finding(code: str, asset: str | None, severity: RiskState,
             message: str, **detail) -> ValidationFinding:
    return ValidationFinding(
        code=code, asset_id=asset, severity=severity, message=message,
        detail=detail,
    )


def _worst(findings: list[ValidationFinding]) -> RiskState:
    if not findings:
        return RiskState.GREEN
    return max((f.severity for f in findings), key=lambda s: s.severity)



def panel_metrics(
    prices: pd.DataFrame, as_of: date | None = None
) -> tuple[float | None, float | None]:
    """Measure staleness and completeness. No thresholds, no judgement.

    Returns ``(stale_trading_days, completeness)``, either of which is
    ``None`` when it cannot be measured — never a zero standing in for
    "unknown" (INV-5).

    Extracted so the service layer can hand these numbers to the control
    engine. ``validate_panel`` only reports them inside a FINDING, and a
    finding is only raised when something is wrong; on clean data there was
    nothing to read, so DATA_FRESHNESS and DATA_COMPLETENESS came out
    unevaluated and every candidate was NOT_VALIDATED. The gate was stuck
    shut on healthy data.

    Comparing these against the policy bands stays in ``cce/controls/``
    (INV-11). This function measures; it does not classify.
    """
    if prices.empty:
        return None, None

    last = prices.index.max()
    if isinstance(last, datetime):
        last_date = last.date()
    elif isinstance(last, date):
        last_date = last
    else:
        last_date = pd.Timestamp(last).date()
    stale = float(np.busday_count(last_date, as_of or market_today()))

    total = prices.size
    completeness = (
        float(1.0 - int(prices.isna().sum().sum()) / total) if total else None
    )
    return stale, completeness

def validate_panel(
    prices: pd.DataFrame,
    universe: Universe,
    as_of: date | None = None,
    snapshot_mode: bool = False,
    policy: Policy | None = None,
) -> ValidationReport:
    """Run every check in docs/13-EDGE-CASES.md section 2.

    Parameters
    ----------
    snapshot_mode:
        Set when the panel is a DELIBERATELY frozen demo snapshot
        (``CachedDataProvider`` selected by configuration). Freshness is then
        reported as an informational ``DEMO_SNAPSHOT`` finding instead of a
        staleness breach.

        This is a narrow, explicit exemption, not a weakening of the control.
        A frozen snapshot is stale *by construction* — that is the point of
        committing it — so measuring it against today's date says nothing
        about data integrity. Every other check still runs unchanged.

        It does NOT apply to ``CACHED_FALLBACK``: there the caller asked for
        live data and silently got old data, which is exactly the condition
        ``DATA_FRESHNESS`` exists to catch.

    Returns a report. It does not raise — the caller decides whether an
    INVALID report is fatal, because a data-integrity failure is a control
    event that must be recorded, not an exception to swallow.
    """
    as_of = as_of or market_today()
    limits = ValidationThresholds.from_policy(policy)
    findings: list[ValidationFinding] = []

    # -- EC-2.x schema: columns present and recognised -----------------------
    if prices.empty:
        findings.append(_finding(
            "SCHEMA", None, RiskState.RED, "price panel is empty"))
        return ValidationReport(
            status=ValidationStatus.INVALID, findings=tuple(findings),
            checked_at=datetime.now(timezone.utc),
        )

    known = set(universe.asset_ids)
    unknown = [c for c in prices.columns if c not in known]
    if unknown:
        findings.append(_finding(
            "SCHEMA", None, RiskState.RED,
            f"panel contains columns not in the universe: {unknown}",
            columns=unknown,
        ))

    missing_assets = [a for a in universe.asset_ids if a not in prices.columns]
    if missing_assets:
        # Excluded upstream and reported; the portfolio is built from what
        # actually has data (docs/01 section 6).
        findings.append(_finding(
            "SCHEMA", None, RiskState.AMBER,
            f"universe assets absent from the panel: {missing_assets}",
            assets=missing_assets,
        ))

    # -- EC-2.3 staleness ----------------------------------------------------
    last = prices.index.max()
    # datetime is checked BEFORE date, and the order is the whole point:
    # pandas Timestamp subclasses datetime, which subclasses date, so an
    # isinstance(last, date) test matches a Timestamp and passes it through
    # untouched. np.busday_count then refuses the datetime64[us] operand and
    # the staleness check raises instead of producing a number — taking out
    # DATA_FRESHNESS, a hard control, for every DatetimeIndex-backed panel.
    if isinstance(last, datetime):
        last_date = last.date()
    elif isinstance(last, date):
        last_date = last
    else:
        last_date = pd.Timestamp(last).date()
    stale_days = int(np.busday_count(last_date, as_of))
    if snapshot_mode:
        # Frozen by construction. Recorded so the UI can show the as-of date
        # prominently (docs/09-UI-SPEC.md section 2.2), never hidden.
        if stale_days > limits.stale_green:
            findings.append(_finding(
                "DEMO_SNAPSHOT", None, RiskState.AMBER,
                f"using a frozen demo snapshot as of {last_date} "
                f"({stale_days} trading day(s) ago). Deliberate: the committed "
                f"cache is what lets the demo run without a network.",
                stale_trading_days=stale_days, last_date=str(last_date),
            ))
    else:
        if stale_days > limits.stale_amber:
            sev = RiskState.RED
        elif stale_days > limits.stale_green:
            sev = RiskState.AMBER
        else:
            sev = RiskState.GREEN
        if sev is not RiskState.GREEN:
            findings.append(_finding(
                "STALE_DATA", None, sev,
                f"latest observation is {stale_days} trading day(s) old "
                f"(as of {last_date})",
                stale_trading_days=stale_days, last_date=str(last_date),
            ))

    # -- EC-2.6 sufficient history ------------------------------------------
    if len(prices) < limits.min_observations:
        findings.append(_finding(
            "MISSING_OBS", None, RiskState.AMBER,
            f"only {len(prices)} observations; metrics needing "
            f"{limits.min_observations}+ will be reported as "
            f"not computed rather than as zero",
            observations=len(prices),
        ))

    # -- EC-2.2 per-asset gaps ----------------------------------------------
    for col in prices.columns:
        s = prices[col]
        n_missing = int(s.isna().sum())
        if not n_missing:
            continue
        completeness = 1.0 - n_missing / len(s)
        run = _longest_nan_run(s)
        trailing = bool(s.iloc[-1:].isna().any())

        if trailing or run > MAX_INTERIOR_GAP or completeness < limits.completeness_amber:
            sev = RiskState.RED
            note = (
                "trailing gap" if trailing
                else f"gap run of {run} sessions"
            )
        else:
            sev = RiskState.AMBER
            note = f"interior gap run of {run} session(s)"
        findings.append(_finding(
            "GAP", col, sev,
            f"{col}: {n_missing} missing observation(s), {note}; "
            f"completeness {completeness:.1%}. Not zero-filled.",
            missing=n_missing, completeness=completeness, longest_run=run,
            trailing=trailing,
        ))

    # -- EC-2.5 outliers: FLAGGED, never removed -----------------------------
    rets = prices.pct_change().iloc[1:]
    for col in rets.columns:
        extreme = rets[col].abs() > limits.outlier
        if extreme.any():
            worst = float(rets[col].abs().max())
            findings.append(_finding(
                "OUTLIER", col, RiskState.AMBER,
                f"{col}: {int(extreme.sum())} return(s) beyond "
                f"+/-{limits.outlier:.0%} (max {worst:.1%}). "
                f"Flagged for review, NOT removed - a genuine crash looks "
                f"exactly like this.",
                count=int(extreme.sum()), max_abs_return=worst,
            ))

    # -- non-positive prices -------------------------------------------------
    for col in prices.columns:
        if (prices[col].dropna() <= 0).any():
            findings.append(_finding(
                "SCHEMA", col, RiskState.RED,
                f"{col}: non-positive price present; returns are undefined",
            ))

    worst_state = _worst(findings)
    status = {
        RiskState.GREEN: ValidationStatus.VALID,
        RiskState.AMBER: ValidationStatus.DEGRADED,
        RiskState.RED: ValidationStatus.INVALID,
    }[worst_state]

    return ValidationReport(
        status=status, findings=tuple(findings),
        checked_at=datetime.now(timezone.utc),
    )


def _longest_nan_run(s: pd.Series) -> int:
    """Longest consecutive run of missing values."""
    isna = s.isna().values
    best = run = 0
    for v in isna:
        run = run + 1 if v else 0
        best = max(best, run)
    return best


def build_market_data(
    prices: pd.DataFrame,
    universe: Universe,
    provider: DataProvider,
    report: ValidationReport | None = None,
    as_of: date | None = None,
) -> MarketData:
    """Validate, then build :class:`MarketData`.

    Raises :class:`DataIntegrityError` when the report is INVALID. There is
    deliberately no path that produces MarketData from unusable data
    (INV-5) — the caller must handle the failure as a control event.
    """
    report = report or validate_panel(prices, universe, as_of=as_of)
    if not report.usable_for_risk:
        reasons = "; ".join(f.message for f in report.findings
                            if f.severity is RiskState.RED)
        raise DataIntegrityError(
            f"market data failed validation and MUST NOT be used for risk "
            f"computation: {reasons}"
        )

    clean = prices.dropna(axis=0, how="any")
    if len(clean) < 2:
        raise DataIntegrityError(
            "fewer than two complete sessions after alignment; cannot "
            "compute returns"
        )

    returns = clean.pct_change().iloc[1:]
    if returns.isna().any().any():
        raise DataIntegrityError(
            "returns contain NaN after cleaning; refusing to zero-fill (INV-5)"
        )

    last = clean.index.max()
    as_of_date = last if isinstance(last, date) else pd.Timestamp(last).date()

    return MarketData(
        prices=clean,
        returns=returns,
        as_of_date=as_of_date,
        provider=provider,
        universe_hash=universe_hash(universe),
        data_hash=panel_hash(clean),
    )

"""Market data validation.

Spec: docs/13-EDGE-CASES.md section 2, docs/03-TRD.md FR-006..FR-008.

A validation failure is a CONTROL EVENT, not a warning to ignore. Missing
data is never zero-filled: if a gap cannot be resolved legitimately, the
report is INVALID and no :class:`MarketData` is produced at all (INV-5).
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from ..contracts import (
    DataProvider, MarketData, RiskState, Universe, ValidationFinding,
    ValidationReport, ValidationStatus,
)
from ..exceptions import DataIntegrityError
from .providers import panel_hash, universe_hash

logger = logging.getLogger(__name__)

__all__ = ["validate_panel", "build_market_data", "ValidationThresholds"]

# [DEMO-CONFIG] mirrors config/policy.yaml DATA_* thresholds.
MAX_STALE_TRADING_DAYS_GREEN = 1
MAX_STALE_TRADING_DAYS_AMBER = 3
MIN_COMPLETENESS_GREEN = 0.98
MIN_COMPLETENESS_AMBER = 0.95
OUTLIER_ABS_RETURN = 0.50      # |r| > 50% on an index is implausible
MIN_OBSERVATIONS = 250
MAX_INTERIOR_GAP = 3           # consecutive missing sessions still repairable


class ValidationThresholds:
    """Grouped for readability; values mirror config/policy.yaml."""

    stale_green = MAX_STALE_TRADING_DAYS_GREEN
    stale_amber = MAX_STALE_TRADING_DAYS_AMBER
    completeness_green = MIN_COMPLETENESS_GREEN
    completeness_amber = MIN_COMPLETENESS_AMBER
    outlier = OUTLIER_ABS_RETURN
    min_observations = MIN_OBSERVATIONS


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


def validate_panel(
    prices: pd.DataFrame,
    universe: Universe,
    as_of: date | None = None,
    snapshot_mode: bool = False,
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
    as_of = as_of or date.today()
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
    last_date = last if isinstance(last, date) else pd.Timestamp(last).date()
    stale_days = int(np.busday_count(last_date, as_of))
    if snapshot_mode:
        # Frozen by construction. Recorded so the UI can show the as-of date
        # prominently (docs/09-UI-SPEC.md section 2.2), never hidden.
        if stale_days > ValidationThresholds.stale_green:
            findings.append(_finding(
                "DEMO_SNAPSHOT", None, RiskState.AMBER,
                f"using a frozen demo snapshot as of {last_date} "
                f"({stale_days} trading day(s) ago). Deliberate: the committed "
                f"cache is what lets the demo run without a network.",
                stale_trading_days=stale_days, last_date=str(last_date),
            ))
    else:
        if stale_days > ValidationThresholds.stale_amber:
            sev = RiskState.RED
        elif stale_days > ValidationThresholds.stale_green:
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
    if len(prices) < ValidationThresholds.min_observations:
        findings.append(_finding(
            "MISSING_OBS", None, RiskState.AMBER,
            f"only {len(prices)} observations; metrics needing "
            f"{ValidationThresholds.min_observations}+ will be reported as "
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

        if trailing or run > MAX_INTERIOR_GAP or completeness < ValidationThresholds.completeness_amber:
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
        extreme = rets[col].abs() > ValidationThresholds.outlier
        if extreme.any():
            worst = float(rets[col].abs().max())
            findings.append(_finding(
                "OUTLIER", col, RiskState.AMBER,
                f"{col}: {int(extreme.sum())} return(s) beyond "
                f"+/-{ValidationThresholds.outlier:.0%} (max {worst:.1%}). "
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

    worst = _worst(findings)
    status = {
        RiskState.GREEN: ValidationStatus.VALID,
        RiskState.AMBER: ValidationStatus.DEGRADED,
        RiskState.RED: ValidationStatus.INVALID,
    }[worst]

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

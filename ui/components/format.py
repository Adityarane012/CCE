"""Every number the UI renders is formatted here.

Spec: docs/09-UI-SPEC.md section 2.3.

One module, because a percentage formatted two ways in two places is how a
dashboard starts contradicting itself on a projector.

Two rules that are correctness, not style:

- ``None`` renders as an em dash. NEVER ``0``. A metric that was not computed
  is not a metric that came out zero, and rendering it as zero is the exact
  failure INV-5 exists to prevent, arriving through the front door.
- Changes in percentage points use ``pp``, not ``%``. Volatility moving from
  11.8% to 15.6% is ``+3.8pp``; ``+3.8%`` would mean 12.2%.
"""

from __future__ import annotations

from datetime import datetime

__all__ = [
    "DASH",
    "MODEL_ESTIMATE",
    "arrow",
    "bps",
    "crore",
    "delta_pp",
    "money",
    "pct",
    "ratio",
    "time_only",
    "timestamp",
    "weight",
]

#: What "not computed" looks like. Never "0", never "N/A", never blank.
DASH = "—"

#: Mandatory beside every forward-looking return (FR-062). Expected returns are
#: the least reliable numbers in the system and showing one bare is the most
#: misleading thing this UI can do.
MODEL_ESTIMATE = "Model Estimate"

PAISE_PER_CRORE = 10_000_000 * 100
PAISE_PER_LAKH = 100_000 * 100
PAISE_PER_RUPEE = 100


def money(paise: int | None) -> str:
    """Currency, scaled to the unit a reader actually uses.

    ``Rs 100.0 Cr`` above a crore, ``Rs 4.2 L`` above a lakh, rupees below.
    """
    if paise is None:
        return DASH
    if abs(paise) >= PAISE_PER_CRORE:
        return f"₹{paise / PAISE_PER_CRORE:,.1f} Cr"
    if abs(paise) >= PAISE_PER_LAKH:
        return f"₹{paise / PAISE_PER_LAKH:,.1f} L"
    return f"₹{paise / PAISE_PER_RUPEE:,.0f}"


def crore(paise: int | None) -> str:
    """Always in crore, for columns that must line up."""
    return DASH if paise is None else f"₹{paise / PAISE_PER_CRORE:,.1f} Cr"


def pct(value: float | None, places: int = 1) -> str:
    """A rate or share as a percentage. ``0.156`` -> ``15.6%``."""
    return DASH if value is None else f"{value * 100:.{places}f}%"


def weight(value: float | None) -> str:
    """A portfolio weight. One decimal, like every other share."""
    return pct(value, 1)


def delta_pp(before: float | None, after: float | None) -> str:
    """A move between two rates, in PERCENTAGE POINTS.

    Signed always, so the direction is readable without comparing to the
    neighbouring cell.
    """
    if before is None or after is None:
        return DASH
    return f"{(after - before) * 100:+.1f}pp"


def ratio(value: float | None) -> str:
    """Sharpe and friends. Two decimals — the third is noise."""
    return DASH if value is None else f"{value:.2f}"


def bps(value: float | None) -> str:
    """Basis points, as an integer. ``0.0010`` -> ``10 bps``."""
    return DASH if value is None else f"{value * 10_000:.0f} bps"


def arrow(before: float | None, after: float | None) -> str:
    """Direction of travel. Neutral about whether it is good news.

    A rising liquidity ratio and a rising CVaR both get the up arrow; which
    one is bad is the control's job to say, not the arrow's.
    """
    if before is None or after is None or before == after:
        return ""
    return "▲" if after > before else "▼"


def timestamp(value: datetime | None) -> str:
    return DASH if value is None else value.strftime("%Y-%m-%d %H:%M")


def time_only(value: datetime | None) -> str:
    """Second precision, for the replay timeline."""
    return DASH if value is None else value.strftime("%H:%M:%S")

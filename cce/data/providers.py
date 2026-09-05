"""Market data provider abstraction.

Spec: docs/02-ARCHITECTURE.md section 8.

The UI MUST NEVER import a provider implementation or ``jugaad_data``
directly. Provider selection is configuration, not code.

Date normalisation lives here because it is the single most dangerous step in
the whole data layer. See :func:`to_trading_date`.
"""

from __future__ import annotations

import hashlib
import logging
from abc import ABC, abstractmethod
from datetime import date, timedelta

import pandas as pd

from ..contracts import Universe

logger = logging.getLogger(__name__)

__all__ = [
    "IST_OFFSET",
    "MarketDataProvider",
    "align_calendar",
    "panel_hash",
    "to_trading_date",
    "universe_hash",
]

# jugaad-data returns stock_df timestamps in UTC. Indian markets close at
# 15:30 IST, and NSE stamps the session at 00:00 IST, which serialises as
# 18:30 UTC on the PREVIOUS calendar day.
IST_OFFSET = timedelta(hours=5, minutes=30)


def to_trading_date(series: pd.Series, source: str) -> pd.Series:
    """Normalise a jugaad-data timestamp column to the real trading date.

    The two jugaad-data APIs disagree, and the disagreement is silent:

    ==========  ====================  ==========================  ============
    API         column                sample value                convention
    ==========  ====================  ==========================  ============
    ``index_df``  ``HistoricalDate``  ``2026-07-08 00:00:00``     IST midnight
    ``stock_df``  ``DATE``            ``2026-07-07 18:30:00``     UTC
    ==========  ====================  ==========================  ============

    Both rows above describe **the same trading session**. Taking ``.dt.date``
    naively yields ``2026-07-08`` for the index and ``2026-07-07`` for the
    ETF — shifting every stock-sourced series one day earlier than every
    index-sourced series.

    Verified against jugaad-data 0.35.5 over 2026-07-01..15: a naive
    conversion overlapped on only 8 of 11 sessions, while adding the IST
    offset overlapped on 11 of 11.

    This does not raise. An inner join on the misaligned dates simply returns
    a shorter panel, and every covariance, correlation and risk contribution
    computed from it is wrong while looking entirely plausible — which is why
    it is corrected at the provider boundary and covered by a test.
    """
    ts = pd.to_datetime(series)
    if source == "stock":
        ts = ts + IST_OFFSET
    return ts.dt.date


def align_calendar(
    frames: dict[str, pd.Series], max_loss: float = 0.02
) -> tuple[pd.DataFrame, dict[str, float]]:
    """Align per-asset close series on a common trading calendar.

    Returns the aligned panel and the fraction of rows each asset lost to the
    intersection. A large loss means the instrument does not really trade on
    the same calendar and should be reconsidered rather than silently carried.

    An inner join is used deliberately: forward-filling across a session an
    instrument genuinely did not trade would invent a zero return, which
    deflates volatility (INV-5).
    """
    if not frames:
        raise ValueError("no series to align")

    common: set[date] | None = None
    for s in frames.values():
        idx = set(s.index)
        common = idx if common is None else (common & idx)
    ordered = sorted(common or set())

    panel = pd.DataFrame(
        {aid: s.reindex(ordered) for aid, s in frames.items()},
        index=pd.Index(ordered, name="date"),
    )
    loss = {
        aid: 1.0 - (len(ordered) / len(s)) if len(s) else 1.0
        for aid, s in frames.items()
    }
    for aid, frac in loss.items():
        if frac > max_loss:
            logger.warning(
                "%s lost %.1f%% of its rows to calendar alignment "
                "(%d of %d sessions kept)",
                aid, frac * 100, len(ordered), len(frames[aid]),
            )
    return panel, loss


def panel_hash(prices: pd.DataFrame) -> str:
    """Stable content hash of a price panel — the reproducibility key.

    Two runs over the same snapshot must produce identical analysis
    (NFR-012), so this covers values, columns and index.
    """
    h = hashlib.sha256()
    h.update(",".join(map(str, prices.columns)).encode())
    h.update(",".join(map(str, prices.index)).encode())
    h.update(prices.round(6).to_csv().encode())
    return h.hexdigest()[:16]


def universe_hash(universe: Universe) -> str:
    """Hash of the universe definition, so a snapshot is tied to its universe."""
    h = hashlib.sha256()
    for a in universe.assets:
        h.update(
            f"{a.asset_id}|{a.ticker}|{a.sector}|{a.asset_class}|"
            f"{a.is_liquid}|{a.source}".encode()
        )
    return h.hexdigest()[:16]


class MarketDataProvider(ABC):
    """Every provider returns the same shape: a date-indexed close panel
    whose columns are ``asset_id`` values, already calendar-aligned and
    date-normalised.

    Validation runs after ANY provider — a provider is never trusted to have
    produced clean data.
    """

    name: str = "abstract"

    @abstractmethod
    def fetch_prices(
        self, universe: Universe, start: date, end: date
    ) -> pd.DataFrame:
        """Return a date-indexed DataFrame of close prices."""

    def __repr__(self) -> str:
        return f"{type(self).__name__}(name={self.name!r})"

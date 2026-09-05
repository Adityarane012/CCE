"""Market data layer (L1).

Provider abstraction plus validation. The UI never imports anything from
here — it goes through the service layer (docs/02-ARCHITECTURE.md section 2).

``load_market_data`` is the single entry point: it selects a provider from
configuration, falls back to cache when live retrieval fails, and validates
whatever came back. A provider is never trusted to have produced clean data.
"""

from __future__ import annotations

import logging
from datetime import date, timedelta
from pathlib import Path

from ..clock import market_today
from ..config import PROJECT_ROOT, get_settings
from ..contracts import DataProvider, MarketData, Universe, ValidationReport
from ..exceptions import DataIntegrityError
from .cache import CACHE_FILENAME, CachedDataProvider, write_cache
from .jugaad_provider import InstrumentUnavailable, JugaadDataProvider
from .providers import (
    IST_OFFSET,
    MarketDataProvider,
    align_calendar,
    panel_hash,
    to_trading_date,
    universe_hash,
)
from .validation import build_market_data, validate_panel

logger = logging.getLogger(__name__)

__all__ = [
    "CACHE_FILENAME",
    "DEFAULT_CACHE_DIR",
    "IST_OFFSET",
    "CachedDataProvider",
    "InstrumentUnavailable",
    "JugaadDataProvider",
    "MarketDataProvider",
    "align_calendar",
    "build_market_data",
    "load_market_data",
    "panel_hash",
    "to_trading_date",
    "universe_hash",
    "validate_panel",
    "write_cache",
]

DEFAULT_CACHE_DIR = PROJECT_ROOT / "data" / "cache"


def load_market_data(
    universe: Universe,
    start: date | None = None,
    end: date | None = None,
    provider: MarketDataProvider | None = None,
    cache_dir: Path | None = None,
) -> tuple[MarketData, ValidationReport]:
    """Load and validate market data, falling back to cache on live failure.

    Returns both the data and its report, because a DEGRADED report must
    still be surfaced in the UI (NFR-043) — the caller cannot be allowed to
    forget that the numbers came from a degraded source.

    Raises :class:`DataIntegrityError` if the data is unusable. That is a
    control event, and the caller records it rather than silently continuing.
    """
    settings = get_settings()
    cache_dir = cache_dir or DEFAULT_CACHE_DIR
    end = end or market_today()
    start = start or (end - timedelta(days=365 * 3))

    used = DataProvider.CACHED
    if provider is None:
        if settings.data_provider is DataProvider.JUGAAD:
            try:
                prices = JugaadDataProvider(
                    risk_free_rate=0.065
                ).fetch_prices(universe, start, end)
                used = DataProvider.JUGAAD
            except Exception as exc:
                # EC-2.1 - live failure must NEVER break the demo.
                logger.warning(
                    "live retrieval failed (%s: %s); falling back to cache",
                    type(exc).__name__, exc,
                )
                prices = CachedDataProvider(cache_dir).fetch_prices(
                    universe, start, end
                )
                used = DataProvider.CACHED_FALLBACK
        else:
            prices = CachedDataProvider(cache_dir).fetch_prices(
                universe, start, end
            )
    else:
        prices = provider.fetch_prices(universe, start, end)
        used = (
            DataProvider.JUGAAD if provider.name == "jugaad"
            else DataProvider.CACHED
        )

    # A deliberately frozen snapshot is stale by construction. CACHED_FALLBACK
    # is NOT exempt: there the caller wanted live data and silently got old
    # data, which is precisely what DATA_FRESHNESS exists to catch.
    report = validate_panel(
        prices, universe, as_of=end,
        snapshot_mode=(used is DataProvider.CACHED),
    )
    if not report.usable_for_risk:
        raise DataIntegrityError(
            "market data failed validation: "
            + "; ".join(f.message for f in report.findings)
        )
    return build_market_data(prices, universe, used, report=report), report

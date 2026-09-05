"""Cached market data — the demo default.

Spec: docs/02-ARCHITECTURE.md section 8, FR-003, FR-004, NFR-010.

The cached provider is what makes the demo reproducible and network-free.
Live retrieval is an enhancement; this is the shipping path.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import pandas as pd

from ..contracts import Universe
from ..exceptions import DataIntegrityError
from .providers import MarketDataProvider

logger = logging.getLogger(__name__)

__all__ = ["CachedDataProvider", "write_cache", "CACHE_FILENAME"]

CACHE_FILENAME = "prices.parquet"


def _cache_path(cache_dir: Path) -> Path:
    return cache_dir / CACHE_FILENAME


def write_cache(prices: pd.DataFrame, cache_dir: Path) -> Path:
    """Persist a price panel as parquet.

    Parquet, not pickle: loading a pickle executes arbitrary code, and this
    file is committed to the repository (NFR-031).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = _cache_path(cache_dir)
    out = prices.copy()
    out.index = pd.to_datetime(pd.Index(out.index))
    out.to_parquet(path, engine="pyarrow", index=True)
    logger.info("wrote %d rows x %d assets to %s", len(out), out.shape[1], path)
    return path


class CachedDataProvider(MarketDataProvider):
    """Reads a committed parquet snapshot.

    Works with no network and no credentials, which is what lets the demo run
    on a disconnected laptop.
    """

    name = "cached"

    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = Path(cache_dir)

    @property
    def path(self) -> Path:
        return _cache_path(self.cache_dir)

    def available(self) -> bool:
        return self.path.exists()

    def fetch_prices(
        self, universe: Universe, start: date, end: date
    ) -> pd.DataFrame:
        if not self.available():
            raise DataIntegrityError(
                f"no cached snapshot at {self.path}. Build one with "
                f"`python scripts/build_cache.py` while a network is available."
            )
        df = pd.read_parquet(self.path, engine="pyarrow")
        df.index = pd.Index([pd.Timestamp(i).date() for i in df.index], name="date")

        keep = [a.asset_id for a in universe.assets if a.asset_id in df.columns]
        missing = [aid for aid in universe.asset_ids if aid not in df.columns]
        if missing:
            logger.warning(
                "cached snapshot lacks %s; those assets are excluded", missing
            )
        if not keep:
            raise DataIntegrityError(
                "cached snapshot shares no assets with the configured universe"
            )

        mask = (pd.Index(df.index) >= start) & (pd.Index(df.index) <= end)
        return df.loc[mask, keep]

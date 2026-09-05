"""Live Indian market data via jugaad-data.

Spec: docs/02-ARCHITECTURE.md section 8, docs/13-EDGE-CASES.md section 2.

Verified against jugaad-data 0.35.5. Three instrument kinds are dispatched
differently, and they do NOT share a date convention — see
:func:`cce.data.providers.to_trading_date`.

Live retrieval is an enhancement, never a dependency. The demo default is
:class:`~cce.data.cache.CachedDataProvider`.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date

import pandas as pd

from ..contracts import Universe
from ..exceptions import DataIntegrityError
from .providers import MarketDataProvider, align_calendar, to_trading_date

logger = logging.getLogger(__name__)

__all__ = ["JugaadDataProvider", "InstrumentUnavailable"]


class InstrumentUnavailable(DataIntegrityError):
    """An instrument returned no usable series and must be excluded.

    Excluding it and saying so is correct. Fabricating a series is not
    (docs/01-PRODUCT-SPECIFICATION.md section 6).
    """


class JugaadDataProvider(MarketDataProvider):
    """Fetches NSE index and equity/ETF series.

    Parameters
    ----------
    risk_free_rate:
        Annual rate used to synthesise the CASH proxy. A real money-market
        ETF (LIQUIDBEES) is available and was deliberately NOT used: its
        price series is flat near Rs 1000 because its yield is distributed,
        so price returns would report cash as earning ~0% rather than the
        risk-free rate. A labelled synthetic series is more honest than a
        real series that misrepresents the instrument.
    strict:
        When True, an unavailable instrument raises instead of being dropped.
    """

    name = "jugaad"

    def __init__(self, risk_free_rate: float = 0.065,
                 trading_days: int = 252, strict: bool = False) -> None:
        self.risk_free_rate = risk_free_rate
        self.trading_days = trading_days
        self.strict = strict
        self.excluded: dict[str, str] = {}

    # ---------------------------------------------------------------- fetch

    def _fetch_index(self, ticker: str, start: date, end: date) -> pd.Series:
        from jugaad_data.nse import index_df

        df = index_df(symbol=ticker, from_date=start, to_date=end)
        if df is None or df.empty:
            raise InstrumentUnavailable(f"{ticker}: index_df returned no rows")
        idx = to_trading_date(df["HistoricalDate"], source="index")
        return pd.Series(df["CLOSE"].astype(float).values, index=idx.values)

    def _fetch_stock(self, ticker: str, start: date, end: date) -> pd.Series:
        from jugaad_data.nse import stock_df

        df = stock_df(symbol=ticker, from_date=start, to_date=end, series="EQ")
        if df is None or df.empty:
            raise InstrumentUnavailable(f"{ticker}: stock_df returned no rows")
        idx = to_trading_date(df["DATE"], source="stock")
        return pd.Series(df["CLOSE"].astype(float).values, index=idx.values)

    def _synthesise_cash(self, index: list[date]) -> pd.Series:
        """A cash proxy compounding at the configured risk-free rate.

        Deterministic, zero volatility, clearly labelled synthetic.
        """
        daily = self.risk_free_rate / self.trading_days
        values = [100.0 * (1.0 + daily) ** i for i in range(len(index))]
        return pd.Series(values, index=index)

    # --------------------------------------------------------------- public

    def fetch_prices(
        self, universe: Universe, start: date, end: date
    ) -> pd.DataFrame:
        """Fetch every instrument, normalise dates, align on a common calendar.

        An instrument with no usable series is EXCLUDED and recorded in
        :attr:`excluded`, not silently replaced.
        """
        self.excluded = {}
        series: dict[str, pd.Series] = {}
        synthetic: list[str] = []

        # jugaad-data emits a np.datetime64 timezone UserWarning on every
        # call. Suppressed only AFTER to_trading_date has done the real work,
        # never instead of it.
        with warnings.catch_warnings():
            warnings.filterwarnings(
                "ignore", message=".*timezones.*", category=UserWarning
            )
            for asset in universe.assets:
                if asset.source == "synthetic":
                    synthetic.append(asset.asset_id)
                    continue
                try:
                    if asset.source == "index":
                        s = self._fetch_index(asset.ticker, start, end)
                    else:
                        s = self._fetch_stock(asset.ticker, start, end)
                except InstrumentUnavailable:
                    raise
                except Exception as exc:  # provider/network/schema failure
                    msg = f"{type(exc).__name__}: {exc}"
                    if self.strict:
                        raise InstrumentUnavailable(
                            f"{asset.asset_id} ({asset.ticker}): {msg}"
                        ) from exc
                    logger.warning(
                        "excluding %s (%s): %s", asset.asset_id, asset.ticker, msg
                    )
                    self.excluded[asset.asset_id] = msg
                    continue

                if s.empty:
                    self.excluded[asset.asset_id] = "empty series"
                    continue
                series[asset.asset_id] = s.sort_index()

        if not series:
            raise DataIntegrityError(
                "no instrument returned a usable series; refusing to build a "
                "portfolio from nothing"
            )

        panel, loss = align_calendar(series)

        for aid in synthetic:
            panel[aid] = self._synthesise_cash(list(panel.index)).values

        # preserve universe ordering for the columns we actually have
        cols = [a.asset_id for a in universe.assets if a.asset_id in panel.columns]
        panel = panel[cols]

        if self.excluded:
            logger.warning(
                "excluded %d instrument(s): %s",
                len(self.excluded), ", ".join(sorted(self.excluded)),
            )
        return panel

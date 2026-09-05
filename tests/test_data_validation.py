"""Data layer and validation tests.

Spec: docs/13-EDGE-CASES.md section 2, docs/11-TESTING-STRATEGY.md section 10.

No test here touches the network. The cached snapshot is committed, which is
also what lets the demo run disconnected (NFR-010).
"""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pandas as pd
import pytest

from cce.contracts import DataProvider, RiskState, ValidationStatus
from cce.data import (
    DEFAULT_CACHE_DIR,
    IST_OFFSET,
    CachedDataProvider,
    align_calendar,
    build_market_data,
    panel_hash,
    to_trading_date,
    universe_hash,
    validate_panel,
    write_cache,
)
from cce.exceptions import DataIntegrityError

AS_OF = date(2026, 8, 31)


def _busday_offset(d: date, days: int) -> date:
    """Shift by trading days. Staleness is measured in sessions, not
    calendar days, and conflating the two produced a false test failure."""
    return np.busday_offset(np.datetime64(d, "D"), days, roll="backward").astype(date)


def _panel(n: int = 300, cols=("NIFTY50", "BANKNIFTY", "GOLD"),
           end: date = AS_OF, seed: int = 42) -> pd.DataFrame:
    idx = [d.date() for d in pd.bdate_range(end=pd.Timestamp(end), periods=n)]
    rng = np.random.default_rng(seed)
    data = 100.0 * np.exp(np.cumsum(rng.normal(0, 0.008, (n, len(cols))), axis=0))
    return pd.DataFrame(data, index=pd.Index(idx, name="date"), columns=list(cols))


# =========================================================================
# EC-2.4b  The date convention. The most dangerous bug in the data layer.
# =========================================================================

class TestTradingDateNormalisation:
    """jugaad-data's two APIs disagree on the date convention, silently.

    ``index_df`` stamps IST midnight; ``stock_df`` stamps UTC, which is 18:30
    on the PREVIOUS calendar day. A naive ``.dt.date`` shifts every
    stock-sourced series one day earlier than every index-sourced one.

    Verified against 0.35.5 over 2026-07-01..15: naive conversion overlapped
    on 8 of 11 sessions; with the offset, 11 of 11.
    """

    def test_stock_timestamps_shift_forward_to_the_real_session(self) -> None:
        # 2026-07-07 18:30 UTC IS the 2026-07-08 IST session
        s = pd.Series([pd.Timestamp("2026-07-07 18:30:00")])
        assert to_trading_date(s, source="stock").iloc[0] == date(2026, 7, 8)

    def test_index_timestamps_are_already_correct(self) -> None:
        s = pd.Series([pd.Timestamp("2026-07-08 00:00:00")])
        assert to_trading_date(s, source="index").iloc[0] == date(2026, 7, 8)

    def test_both_sources_agree_after_normalisation(self) -> None:
        """The whole point: an index and an ETF from the same session must
        land on the same date."""
        idx = pd.Series([pd.Timestamp("2026-07-08 00:00:00")])
        stk = pd.Series([pd.Timestamp("2026-07-07 18:30:00")])
        assert (to_trading_date(idx, "index").iloc[0]
                == to_trading_date(stk, "stock").iloc[0])

    def test_naive_conversion_would_have_misaligned(self) -> None:
        """Documents the bug this guards against.

        It does NOT raise - an inner join on misaligned dates just returns a
        shorter panel, and every covariance computed from it is wrong while
        looking entirely plausible.
        """
        stk = pd.Series([pd.Timestamp("2026-07-07 18:30:00")])
        naive = pd.to_datetime(stk).dt.date.iloc[0]
        correct = to_trading_date(stk, "stock").iloc[0]
        assert naive == date(2026, 7, 7)
        assert correct == date(2026, 7, 8)
        assert (correct - naive) == timedelta(days=1)

    def test_ist_offset_is_five_thirty(self) -> None:
        assert timedelta(hours=5, minutes=30) == IST_OFFSET


# =========================================================================
# EC-2.4  Calendar alignment
# =========================================================================

class TestCalendarAlignment:
    def test_inner_join_keeps_only_common_sessions(self) -> None:
        a = pd.Series([1.0, 2.0, 3.0],
                      index=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)])
        b = pd.Series([9.0, 8.0],
                      index=[date(2026, 7, 2), date(2026, 7, 3)])
        panel, loss = align_calendar({"A": a, "B": b})
        assert list(panel.index) == [date(2026, 7, 2), date(2026, 7, 3)]
        assert loss["A"] == pytest.approx(1 / 3)
        assert loss["B"] == pytest.approx(0.0)

    def test_alignment_never_forward_fills(self) -> None:
        """Forward-filling a session an instrument did not trade would invent
        a zero return, which deflates volatility (INV-5)."""
        a = pd.Series([1.0, 2.0, 3.0],
                      index=[date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)])
        b = pd.Series([9.0], index=[date(2026, 7, 3)])
        panel, _ = align_calendar({"A": a, "B": b})
        assert len(panel) == 1
        assert not panel.isna().any().any()


# =========================================================================
# EC-2.2 / INV-5  Missing data is never zero
# =========================================================================

class TestMissingData:
    def test_gap_is_reported_and_never_zero_filled(self) -> None:
        p = _panel()
        p.iloc[150, 1] = np.nan
        report = validate_panel(p, _universe(), as_of=AS_OF)
        codes = {f.code for f in report.findings}
        assert "GAP" in codes
        gap = next(f for f in report.findings if f.code == "GAP")
        assert "Not zero-filled" in gap.message

    def test_trailing_gap_is_fatal(self) -> None:
        """A hole at the end of a series is not repairable - it means the
        instrument stopped reporting."""
        p = _panel()
        p.iloc[-1, 1] = np.nan
        report = validate_panel(p, _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.INVALID

    def test_long_interior_gap_is_fatal(self) -> None:
        p = _panel()
        p.iloc[100:110, 1] = np.nan
        report = validate_panel(p, _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.INVALID

    def test_short_interior_gap_degrades_but_survives(self) -> None:
        p = _panel()
        p.iloc[150, 1] = np.nan
        report = validate_panel(p, _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.DEGRADED
        assert report.usable_for_risk is True

    def test_invalid_report_blocks_market_data(self) -> None:
        """INV-5. There is no path from unusable data to a MarketData."""
        p = _panel()
        p.iloc[-1, 1] = np.nan
        with pytest.raises(DataIntegrityError, match="MUST NOT be used"):
            build_market_data(p, _universe(), DataProvider.CACHED, as_of=AS_OF)

    def test_returns_never_contain_nan(self) -> None:
        md = build_market_data(_panel(), _universe(), DataProvider.CACHED,
                               as_of=AS_OF)
        assert not md.returns.isna().any().any()


# =========================================================================
# EC-2.3  Staleness
# =========================================================================

class TestStaleness:
    def test_fresh_data_is_valid(self) -> None:
        report = validate_panel(_panel(end=AS_OF), _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.VALID

    def test_moderately_stale_data_is_amber(self) -> None:
        """Staleness is counted in TRADING days, not calendar days - three
        calendar days back from a Monday is only one trading day."""
        end = _busday_offset(AS_OF, -3)
        report = validate_panel(_panel(end=end), _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.DEGRADED
        stale = next(f for f in report.findings if f.code == "STALE_DATA")
        assert stale.severity is RiskState.AMBER
        assert stale.detail["stale_trading_days"] == 3

    def test_very_stale_data_is_invalid(self) -> None:
        """A week-old price during a shock is worse than no price."""
        report = validate_panel(_panel(end=_busday_offset(AS_OF, -10)),
                                _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.INVALID
        stale = next(f for f in report.findings if f.code == "STALE_DATA")
        assert stale.severity is RiskState.RED

    def test_one_trading_day_old_is_still_green(self) -> None:
        """Boundary: the green band is 'at most one trading day old'."""
        report = validate_panel(_panel(end=_busday_offset(AS_OF, -1)),
                                _universe(), as_of=AS_OF)
        assert report.status is ValidationStatus.VALID


# =========================================================================
# EC-2.5  Outliers are flagged, never removed
# =========================================================================

def test_outliers_are_flagged_but_not_removed() -> None:
    """A genuine crash looks exactly like an outlier. Silently deleting it
    removes the event the system exists to detect."""
    p = _panel()
    p.iloc[200, 0] = p.iloc[199, 0] * 0.35   # -65% in one session
    report = validate_panel(p, _universe(), as_of=AS_OF)
    outlier = next(f for f in report.findings if f.code == "OUTLIER")
    assert outlier.severity is RiskState.AMBER
    assert "NOT removed" in outlier.message
    # still usable, and the extreme value is still present
    assert report.usable_for_risk
    md = build_market_data(p, _universe(), DataProvider.CACHED, as_of=AS_OF)
    assert md.returns.iloc[:, 0].min() < -0.5


# =========================================================================
# EC-2.6  Insufficient history
# =========================================================================

def test_short_history_degrades_rather_than_silently_passing() -> None:
    report = validate_panel(_panel(n=100), _universe(), as_of=AS_OF)
    assert report.status is ValidationStatus.DEGRADED
    assert any(f.code == "MISSING_OBS" for f in report.findings)


def test_non_positive_price_is_fatal() -> None:
    p = _panel()
    p.iloc[50, 0] = 0.0
    report = validate_panel(p, _universe(), as_of=AS_OF)
    assert report.status is ValidationStatus.INVALID


# =========================================================================
# Reproducibility (NFR-012)
# =========================================================================

class TestReproducibility:
    def test_panel_hash_is_stable(self) -> None:
        assert panel_hash(_panel()) == panel_hash(_panel())

    def test_panel_hash_changes_with_content(self) -> None:
        p, q = _panel(), _panel()
        q.iloc[0, 0] += 1.0
        assert panel_hash(p) != panel_hash(q)

    def test_universe_hash_is_stable(self) -> None:
        assert universe_hash(_universe()) == universe_hash(_universe())


# =========================================================================
# EC-2.1  Cached provider — the demo path
# =========================================================================

class TestCachedProvider:
    def test_committed_snapshot_loads_offline(self) -> None:
        """NFR-010. No network, no credentials."""
        from cce.config import load_universe
        u = load_universe()
        p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
            u, date(2000, 1, 1), date(2030, 1, 1)
        )
        assert not p.empty
        assert len(p) >= 250, "committed cache must exceed the metric minimum"
        assert list(p.columns) == list(u.asset_ids)

    def test_committed_snapshot_is_financially_plausible(self) -> None:
        """Guards against a corrupt or misaligned rebuild.

        If the date normalisation regressed, correlations would collapse
        toward zero because the series would be off by one session.
        """
        from cce.config import load_universe
        u = load_universe()
        p = CachedDataProvider(DEFAULT_CACHE_DIR).fetch_prices(
            u, date(2000, 1, 1), date(2030, 1, 1)
        )
        md = build_market_data(p, u, DataProvider.CACHED, as_of=AS_OF)
        r = md.returns
        ann = r.std() * np.sqrt(252)

        assert 0.05 < ann["NIFTY50"] < 0.35, "broad equity vol implausible"
        assert ann["BANKNIFTY"] > ann["GSEC"], "banking must be riskier than G-Sec"
        assert ann["CASH"] < 0.005, "cash proxy must be near zero volatility"
        # Indian equity and banking move together; if the calendar regressed
        # this collapses toward zero.
        assert r["NIFTY50"].corr(r["BANKNIFTY"]) > 0.5

    def test_missing_cache_raises_with_a_useful_message(self, tmp_path) -> None:
        from cce.config import load_universe
        with pytest.raises(DataIntegrityError, match="build_cache"):
            CachedDataProvider(tmp_path).fetch_prices(
                load_universe(), date(2020, 1, 1), date(2030, 1, 1)
            )

    def test_roundtrip_through_parquet_preserves_values(self, tmp_path) -> None:
        from cce.config import load_universe
        p = _panel()
        write_cache(p, tmp_path)
        back = CachedDataProvider(tmp_path).fetch_prices(
            load_universe(), date(2000, 1, 1), date(2030, 1, 1)
        )
        # only universe columns survive; compare the ones present
        common = [c for c in p.columns if c in back.columns]
        assert common
        pd.testing.assert_frame_equal(
            p[common], back[common], check_freq=False, atol=1e-9
        )


# -------------------------------------------------------------- helpers

def _universe():
    """A universe covering the synthetic panel's columns."""
    from cce.contracts import Asset, Universe
    spec = [
        ("NIFTY50", "BROAD_EQUITY", "EQUITY", True),
        ("BANKNIFTY", "BANKING", "EQUITY", True),
        ("GOLD", "GOLD", "COMMODITY", True),
    ]
    return Universe(assets=tuple(
        Asset(asset_id=a, ticker=a, name=a, asset_class=c, sector=s,
              is_liquid=liquid, min_weight=0.0, max_weight=0.4, txn_cost_rate=0.001)
        for a, s, c, liquid in spec
    ))


class TestSnapshotMode:
    """A frozen demo snapshot is stale by construction.

    snapshot_mode is a narrow, explicit exemption for a deliberately
    committed cache - NOT a weakening of DATA_FRESHNESS.
    """

    def test_frozen_snapshot_is_informational_not_a_breach(self) -> None:
        report = validate_panel(_panel(end=_busday_offset(AS_OF, -10)),
                                _universe(), as_of=AS_OF, snapshot_mode=True)
        assert report.usable_for_risk
        note = next(f for f in report.findings if f.code == "DEMO_SNAPSHOT")
        assert note.severity is RiskState.AMBER
        assert not any(f.code == "STALE_DATA" for f in report.findings)

    def test_same_panel_without_snapshot_mode_is_invalid(self) -> None:
        """The control still bites when the data is not a declared snapshot."""
        report = validate_panel(_panel(end=_busday_offset(AS_OF, -10)),
                                _universe(), as_of=AS_OF, snapshot_mode=False)
        assert report.status is ValidationStatus.INVALID

    def test_snapshot_mode_does_not_disable_other_checks(self) -> None:
        """Only freshness is exempted. Everything else still runs."""
        p = _panel(end=_busday_offset(AS_OF, -10))
        p.iloc[-1, 1] = np.nan          # trailing gap: still fatal
        report = validate_panel(p, _universe(), as_of=AS_OF, snapshot_mode=True)
        assert report.status is ValidationStatus.INVALID

    def test_cached_fallback_is_not_exempt(self) -> None:
        """EC-2.1. Wanting live data and silently getting old data is exactly
        what DATA_FRESHNESS exists to catch."""
        # load_market_data passes snapshot_mode only for CACHED, never for
        # CACHED_FALLBACK - asserted structurally here.
        import inspect

        from cce.data import load_market_data
        src = inspect.getsource(load_market_data)
        assert "snapshot_mode=(used is DataProvider.CACHED)" in src


# ---------------------------------------------------------------------------
# load_market_data — the demo's data entry point (EC-2.1)
# ---------------------------------------------------------------------------

class TestLoadMarketData:
    """The orchestration that decides which provider was used, and says so.

    This path was 43% covered while carrying the one behaviour the demo
    depends on: the system must run with no network and no API key, and when
    live retrieval fails it must fall back to cache and SAY it fell back.
    """

    def _stub(self, name: str, panel: pd.DataFrame | None = None, boom: bool = False):
        """A provider that either returns a panel or raises."""
        class _P:
            def __init__(self) -> None:
                self.name = name

            def fetch_prices(self, universe, start, end):
                if boom:
                    raise RuntimeError("network is down")
                return panel

        return _P()

    def _panel(self, universe, n: int = 400) -> pd.DataFrame:
        ids = [a.asset_id for a in universe.assets]
        rng = np.random.default_rng(11)
        idx = pd.bdate_range(end=pd.Timestamp(date(2026, 8, 31)), periods=n)
        steps = rng.normal(0.0004, 0.008, (n, len(ids)))
        return pd.DataFrame(100.0 * np.exp(np.cumsum(steps, axis=0)),
                            columns=ids, index=idx)

    def test_an_explicit_provider_is_used_as_given(self, universe):
        from cce.data import load_market_data

        panel = self._panel(universe)
        md, report = load_market_data(
            universe, end=date(2026, 8, 31),
            provider=self._stub("cached", panel),
        )
        assert md.provider is DataProvider.CACHED
        assert report.usable_for_risk
        assert not md.returns.empty

    def test_a_live_provider_is_labelled_jugaad(self, universe):
        from cce.data import load_market_data

        md, _ = load_market_data(
            universe, end=date(2026, 8, 31),
            provider=self._stub("jugaad", self._panel(universe)),
        )
        assert md.provider is DataProvider.JUGAAD

    def test_live_failure_falls_back_to_cache_and_says_so(
        self, universe, monkeypatch, tmp_path
    ):
        """EC-2.1: a live failure must never break the demo, and must never
        pretend the data came from where it did not.

        CACHED_FALLBACK is a distinct value from CACHED precisely so the UI can
        show that the caller asked for live data and silently got old data.
        """
        import cce.data as data_pkg
        from cce.data import load_market_data

        panel = self._panel(universe)

        class _Boom:
            def __init__(self, *a, **kw) -> None:
                pass

            def fetch_prices(self, *a, **kw):
                raise RuntimeError("network is down")

        class _Cache:
            def __init__(self, *a, **kw) -> None:
                pass

            def fetch_prices(self, *a, **kw):
                return panel

        monkeypatch.setenv("CCE_DATA_PROVIDER", "jugaad")
        monkeypatch.setattr(data_pkg, "JugaadDataProvider", _Boom)
        monkeypatch.setattr(data_pkg, "CachedDataProvider", _Cache)

        md, report = load_market_data(universe, end=date(2026, 8, 31))

        assert md.provider is DataProvider.CACHED_FALLBACK, (
            "a fallback must not be reported as a normal cached read"
        )
        assert report.usable_for_risk

    def test_a_fallback_is_not_exempt_from_the_freshness_check(
        self, universe, monkeypatch
    ):
        """A deliberately frozen snapshot is stale by construction and is
        exempt. A fallback is not: there the caller wanted live data and got
        old data, which is exactly what DATA_FRESHNESS exists to catch."""
        import cce.data as data_pkg
        from cce.data import load_market_data

        stale = self._panel(universe)
        stale.index = pd.bdate_range(
            end=pd.Timestamp(date(2026, 6, 1)), periods=len(stale)
        )

        class _Boom:
            def __init__(self, *a, **kw) -> None:
                pass

            def fetch_prices(self, *a, **kw):
                raise RuntimeError("down")

        class _Cache:
            def __init__(self, *a, **kw) -> None:
                pass

            def fetch_prices(self, *a, **kw):
                return stale

        monkeypatch.setenv("CCE_DATA_PROVIDER", "jugaad")
        monkeypatch.setattr(data_pkg, "JugaadDataProvider", _Boom)
        monkeypatch.setattr(data_pkg, "CachedDataProvider", _Cache)

        try:
            _, report = load_market_data(universe, end=date(2026, 8, 31))
        except DataIntegrityError:
            return  # blocked outright is a valid, and stricter, outcome
        codes = {f.code for f in report.findings}
        assert "STALE" in codes or any(
            "stale" in f.message.lower() for f in report.findings
        ), "a fallback that returned months-old data must be flagged"

    def test_unusable_data_raises_rather_than_returning_something(self, universe):
        """A data-integrity failure is a control event, not a warning to
        ignore. It must not return a half-usable panel (INV-5)."""
        from cce.data import load_market_data

        empty = pd.DataFrame()
        with pytest.raises(DataIntegrityError):
            load_market_data(
                universe, end=date(2026, 8, 31),
                provider=self._stub("cached", empty),
            )

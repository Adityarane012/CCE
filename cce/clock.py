"""Time, in the two forms this system needs.

Two clocks, because they answer different questions and confusing them is how
a date bug gets into a hard control:

- :func:`utc_now` — when the machine did something. Audit timestamps, report
  ``checked_at``, breaker evaluation time. Always timezone-aware UTC.
- :func:`market_today` — what "today" means to the NSE. Data-freshness and
  staleness checks compare a trading date against this, never against the
  machine's local date.

``date.today()`` is deliberately not used anywhere in ``cce/``. It reads the
host's local calendar, so the same panel is fresh on a laptop in Mumbai and a
day stale on a CI runner in UTC. ``DATA_FRESHNESS`` is a HARD control whose
green band is one trading day (docs/07-RISK-POLICY.md §2) — a one-day shift is
the difference between GREEN and AMBER on a control that can trip the circuit
breaker.

That failure mode is not hypothetical here. The same off-by-one already
appeared once in this codebase, in the jugaad-data panels: ``index_df`` stamps
IST midnight and ``stock_df`` stamps UTC, so a naive ``.dt.date`` matched on
only 8 of 11 sessions and silently corrupted every covariance
(docs/13-EDGE-CASES.md §2.4b).

IST is a fixed +05:30 offset and has never observed daylight saving, so it is
expressed directly rather than through ``zoneinfo``. That keeps the demo
independent of whether a tz database is installed — a Windows box without
``tzdata`` would otherwise raise at import.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

__all__ = ["IST", "market_today", "utc_now"]

#: Indian Standard Time. Fixed +05:30, no daylight saving, ever.
IST = timezone(timedelta(hours=5, minutes=30), name="IST")


def utc_now() -> datetime:
    """The current instant, timezone-aware, in UTC.

    Used for anything recording *when the system acted*: audit rows, report
    timestamps, breaker evaluation time.
    """
    return datetime.now(UTC)


def market_today() -> date:
    """Today's civil date in the market's own timezone (IST).

    The reference date for freshness and staleness. This is a calendar date,
    not a trading date: it does not know about weekends or NSE holidays, and
    callers that need trading-day arithmetic do that separately against the
    observed session index.
    """
    return datetime.now(IST).date()
